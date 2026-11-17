#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Apply least-privilege IAM to the two harness accounts.

What it does (idempotent, dry-run by default):

  member  (entry) account, IAM user  harness
    1. attach inline  HarnessReadOnly    (infra/policies/harness-read-policy.json)
    2. attach inline  HarnessAssumeMgmt  (infra/policies/harness-entry-assume.json)
    3. detach        AdministratorAccess, *-Amplify, *-AWSElasticBeanstalk,
                     AccountManagementFromVercel
  management account, IAM role HarnessAccess
    4. put inline     HarnessReadOnly    (infra/policies/harness-read-policy.json)
    5. put inline     HarnessOrgsRead    (infra/policies/harness-orgs-read.json)
    6. tighten the trust policy to the single entry user
                     (infra/policies/harness-role-trust.json)

Before touching anything it dumps the current IAM state to
infra/policies/backup/<timestamp>.json so the change is reversible.

Usage:
    python3 scripts/apply-least-privilege.py                 # dry run
    python3 scripts/apply-least-privilege.py --yes           # apply
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "infra" / "policies"
BACKUP_DIR = POLICY_DIR / "backup"

ENTRY_PROFILE = "sandbox"
MGMT_PROFILE = "sandbox-mgmt"

ENTRY_USER = "harness"
MGMT_ROLE = "HarnessAccess"

# Managed policies that grant far more than the harness needs.
DROP_MANAGED = [
    "AdministratorAccess",
    "AdministratorAccess-Amplify",
    "AdministratorAccess-AWSElasticBeanstalk",
    "AccountManagementFromVercel",
]


def load(name):
    return json.loads((POLICY_DIR / name).read_text())


def _try(fn, default, skip):
    """Read IAM config if allowed, else record the denial.

    After the first apply the entry user is read-only for resources but
    not for IAM configuration, so a re-run only snapshots what it may
    see. The mgmt profile still yields a full snapshot.
    """
    try:
        return fn()
    except ClientError as e:
        skip.append(e.response["Error"]["Code"])
        return default


def dump_state(session, account_id):
    """Capture everything we are about to change (best effort)."""
    iam = session.client("iam")
    skipped = []
    state = {"account": account_id, "users": {}, "roles": {}}
    for u in _try(lambda: iam.list_users()["Users"], [], skipped):
        name = u["UserName"]
        state["users"][name] = {
            "attached": _try(
                lambda n=name: [p["PolicyArn"] for p in
                                iam.list_attached_user_policies(UserName=n)["AttachedPolicies"]],
                None, skipped),
            "inline": _try(
                lambda n=name: {p: iam.get_user_policy(UserName=n, PolicyName=p)["PolicyDocument"]
                                for p in iam.list_user_policies(UserName=n)["PolicyNames"]},
                None, skipped),
        }
    # role trust policies arrive with ListRoles; inline docs need GetRolePolicy
    for r in _try(lambda: iam.list_roles()["Roles"], [], skipped):
        name = r["RoleName"]
        if name.startswith("AWSServiceRoleFor") or name.startswith("aws-service-role"):
            continue
        state["roles"][name] = {
            "trust": r["AssumeRolePolicyDocument"],
            "inline": _try(
                lambda n=name: {p: iam.get_role_policy(RoleName=n, PolicyName=p)["PolicyDocument"]
                                for p in iam.list_role_policies(RoleName=n)["PolicyNames"]},
                None, skipped),
        }
    if skipped:
        state["skipped_reads"] = sorted(set(skipped))
    return state


def apply_entry(session, dry_run, log):
    iam = session.client("iam")
    changed = []

    def current(name):
        try:
            return iam.get_user_policy(UserName=ENTRY_USER, PolicyName=name)["PolicyDocument"]
        except ClientError:
            return None

    for pol_name, fname in (("HarnessReadOnly", "harness-read-policy.json"),
                            ("HarnessAssumeMgmt", "harness-entry-assume.json")):
        doc = load(fname)
        cur = current(pol_name)
        if cur == doc:
            log(f"  inline policy {pol_name} already correct")
            continue
        if cur is None:
            log(f"  {pol_name}: unverifiable from this identity "
                f"(no iam:GetUserPolicy) — re-put (idempotent)")
        else:
            log(f"  put inline policy {pol_name} on user {ENTRY_USER}")
        if not dry_run:
            iam.put_user_policy(UserName=ENTRY_USER, PolicyName=pol_name,
                                PolicyDocument=json.dumps(doc))
        changed.append(f"inline:{pol_name}")

    attached = {p["PolicyName"] for p in
                iam.list_attached_user_policies(UserName=ENTRY_USER)["AttachedPolicies"]}
    for name in DROP_MANAGED:
        if name not in attached:
            log(f"  detach {name}: already absent")
            continue
        arn = f"arn:aws:iam::aws:policy/{name}"
        log(f"  detach managed policy {name} from user {ENTRY_USER}")
        if not dry_run:
            iam.detach_user_policy(UserName=ENTRY_USER, PolicyArn=arn)
        changed.append(f"detached:{name}")
    return changed


def apply_mgmt_role(session, dry_run, log):
    iam = session.client("iam")
    changed = []

    for pol_name, fname in (("HarnessReadOnly", "harness-read-policy.json"),
                            ("HarnessOrgsRead", "harness-orgs-read.json")):
        doc = load(fname)
        try:
            same = json.loads(json.dumps(
                iam.get_role_policy(RoleName=MGMT_ROLE, PolicyName=pol_name)["PolicyDocument"])) == doc
        except ClientError:
            same = False
        if same:
            log(f"  inline policy {pol_name} already correct")
            continue
        log(f"  put inline policy {pol_name} on role {MGMT_ROLE}")
        if not dry_run:
            iam.put_role_policy(RoleName=MGMT_ROLE, PolicyName=pol_name,
                                PolicyDocument=json.dumps(doc))
        changed.append(f"role-inline:{pol_name}")

    trust = load("harness-role-trust.json")
    current = iam.get_role(RoleName=MGMT_ROLE)["Role"]["AssumeRolePolicyDocument"]
    if current != trust:
        log(f"  tighten trust policy on role {MGMT_ROLE} "
            f"-> single entry user {ENTRY_USER}")
        if not dry_run:
            iam.update_assume_role_policy(RoleName=MGMT_ROLE,
                                          PolicyDocument=json.dumps(trust))
        changed.append("trust:tightened")
    else:
        log("  trust policy already tightened")
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true",
                    help="actually apply (default is a dry run)")
    ap.add_argument("--entry-profile", default=ENTRY_PROFILE)
    ap.add_argument("--mgmt-profile", default=MGMT_PROFILE)
    args = ap.parse_args()
    dry_run = not args.yes

    def log(msg):
        print(("[dry-run] " if dry_run else "[apply]  ") + msg)

    entry = boto3.Session(profile_name=args.entry_profile)
    mgmt = boto3.Session(profile_name=args.mgmt_profile)
    entry_id = entry.client("sts").get_caller_identity()["Account"]
    mgmt_id = mgmt.client("sts").get_caller_identity()["Account"]

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"{stamp}.json"
    state = {"captured_at": stamp,
             "accounts": {entry_id: dump_state(entry, entry_id),
                          mgmt_id: dump_state(mgmt, mgmt_id)}}
    backup.write_text(json.dumps(state, indent=2, default=str))
    print(f"state snapshot -> {backup}")

    print(f"\n=== member {entry_id}: user {ENTRY_USER} ===")
    a = apply_entry(entry, dry_run, log)
    print(f"\n=== management {mgmt_id}: role {MGMT_ROLE} ===")
    b = apply_mgmt_role(mgmt, dry_run, log)

    print(f"\n{len(a) + len(b)} change(s) "
          f"{'pending (re-run with --yes)' if dry_run else 'applied'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
