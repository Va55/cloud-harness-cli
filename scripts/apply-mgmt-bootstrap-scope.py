#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Scope the management-account bootstrap user down to a bootstrap-only policy.

Why: `harness-mgmt` (management account 222222222222) currently carries
AdministratorAccess + AdministratorAccess-Amplify + AccountManagementFromVercel.
The harness itself never uses it — at runtime the entry user
(111111111111:user/harness) assumes role `HarnessAccess`. This user exists
only to maintain those roles, so it gets IAM-management rights and nothing
else.

What it does (idempotent, dry-run by default):

  1. create / update customer-managed policy `HarnessMgmtBootstrap`
     from infra/policies/harness-bootstrap-user.json
  2. attach `HarnessMgmtBootstrap` to user `harness-mgmt`
  3. pre-flight: simulate every action the bootstrap workflows need,
     using ONLY that policy (iam:SimulatePrincipalPolicy with an explicit
     PolicySourceArn) — refuse to detach admin if anything is denied
  4. only then detach AdministratorAccess, AdministratorAccess-Amplify,
     AccountManagementFromVercel
  5. end-to-end self-test: create/update/delete a throwaway role

Every run writes a state snapshot to infra/policies/backup/.

Restore (console, management account — root or an admin identity):
    aws iam attach-user-policy --user-name harness-mgmt \
        --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

Usage:
    python3 scripts/apply-mgmt-bootstrap-scope.py                # dry run
    python3 scripts/apply-mgmt-bootstrap-scope.py --yes          # apply
    python3 scripts/apply-mgmt-bootstrap-scope.py --yes --self-test
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

PROFILE = "sandbox-mgmt"
ACCOUNT = "222222222222"
USER = "harness-mgmt"
POLICY_NAME = "HarnessMgmtBootstrap"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/{POLICY_NAME}"

DROP_MANAGED = [
    "AdministratorAccess",
    "AdministratorAccess-Amplify",
    "AccountManagementFromVercel",
]

# What the bootstrap workflows (apply-least-privilege.py, role creation for a
# new account, key hygiene) actually call. Simulated before admin is removed.
REQUIRED = [
    "sts:GetCallerIdentity",
    "iam:CreateRole",
    "iam:DeleteRole",
    "iam:GetRole",
    "iam:UpdateAssumeRolePolicy",
    "iam:TagRole",
    "iam:PutRolePolicy",
    "iam:GetRolePolicy",
    "iam:DeleteRolePolicy",
    "iam:ListRolePolicies",
    "iam:ListAttachedRolePolicies",
    "iam:ListUsers",
    "iam:GetUser",
    "iam:ListUserPolicies",
    "iam:GetUserPolicy",
    "iam:ListAttachedUserPolicies",
    "iam:ListAccessKeys",
    "iam:GetAccessKeyLastUsed",
    "iam:ListMFADevices",
    "iam:ListGroupsForUser",
    "iam:ListRoles",
    "iam:GetPolicy",
    "iam:GetPolicyVersion",
    "iam:ListPolicies",
    "iam:SimulatePrincipalPolicy",
]


def load_policy() -> dict:
    return json.loads((POLICY_DIR / "harness-bootstrap-user.json").read_text())


def snapshot(iam) -> dict:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    state = {
        "captured_at": stamp,
        "account": ACCOUNT,
        "user": USER,
        "attached": [p["PolicyName"] for p in
                     iam.list_attached_user_policies(UserName=USER)["AttachedPolicies"]],
        "inline": {n: iam.get_user_policy(UserName=USER, PolicyName=n)["PolicyDocument"]
                   for n in iam.list_user_policies(UserName=USER)["PolicyNames"]},
        "groups": [g["GroupName"] for g in
                   iam.list_groups_for_user(UserName=USER)["Groups"]],
    }
    path = BACKUP_DIR / f"{stamp}-mgmt-user.json"
    path.write_text(json.dumps(state, indent=2, default=str))
    return {"path": str(path), **state}


def ensure_policy(iam, doc: dict, dry_run: bool, log) -> None:
    """Create the customer-managed policy, or add a new default version."""
    try:
        cur = iam.get_policy(PolicyArn=POLICY_ARN)["Policy"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        log(f"create customer-managed policy {POLICY_NAME}")
        if not dry_run:
            iam.create_policy(PolicyName=POLICY_NAME, PolicyDocument=json.dumps(doc),
                              Description="Bootstrap-only IAM for the cloud-harness CLI "
                                          "(creates/maintains HarnessAccess roles)")
        return

    default = iam.get_policy_version(
        PolicyArn=POLICY_ARN, VersionId=cur["DefaultVersionId"])["PolicyVersion"]["Document"]
    if json.loads(json.dumps(default)) == doc:
        log(f"policy {POLICY_NAME} already current ({cur['DefaultVersionId']})")
        return
    log(f"publish new default version of {POLICY_NAME}")
    if not dry_run:
        iam.create_policy_version(PolicyArn=POLICY_ARN, PolicyDocument=json.dumps(doc),
                                  SetAsDefault=True)
        # IAM keeps 5 versions; drop the oldest non-default ones.
        versions = iam.list_policy_versions(PolicyArn=POLICY_ARN)["Versions"]
        for v in sorted(versions, key=lambda v: v["CreateDate"]):
            if v["IsDefaultVersion"]:
                continue
            keep = [x for x in versions if not x["IsDefaultVersion"]]
            if len(keep) <= 4:
                break
            iam.delete_policy_version(PolicyArn=POLICY_ARN, VersionId=v["VersionId"])


def simulate(iam, doc, log) -> bool:
    """Prove the scoped policy alone covers the bootstrap workflows.

    SimulateCustomPolicy evaluates only the policy documents passed in, so
    the still-attached AdministratorAccess cannot mask a gap.
    """
    resp = iam.simulate_custom_policy(
        PolicyInputList=[json.dumps(doc)],
        ActionNames=REQUIRED,
        ResourceArns=["*"],
    )
    denied = [r["EvalActionName"] for r in resp["EvaluationResults"]
              if r["EvalDecision"] != "allowed"]
    if denied:
        log(f"SIMULATION FAILED — policy is missing: {denied}")
        return False
    log(f"simulation passed: all {len(REQUIRED)} bootstrap actions allowed "
        f"by {POLICY_NAME} alone")
    return True


def self_test(iam, log) -> bool:
    role = "HarnessBootstrapSelfTest"
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"}]}
    doc = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Action": "sts:GetCallerIdentity", "Resource": "*"}]}
    ok = True
    steps = [
        ("create role", lambda: iam.create_role(RoleName=role,
                                                AssumeRolePolicyDocument=json.dumps(trust)),
         "DeleteConflict"),
        ("put inline policy", lambda: iam.put_role_policy(RoleName=role, PolicyName="Probe",
                                                          PolicyDocument=json.dumps(doc)), None),
        ("read inline policy", lambda: iam.get_role_policy(RoleName=role, PolicyName="Probe"), None),
        ("update trust policy", lambda: iam.update_assume_role_policy(
            RoleName=role, PolicyDocument=json.dumps(trust)), None),
    ]
    for label, fn, ignore in steps:
        try:
            fn()
            log(f"  self-test {label}: ok")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if ignore and code == ignore:
                log(f"  self-test {label}: ok (role already existed)")
                continue
            log(f"  self-test {label}: FAILED {code}")
            ok = False
    try:
        iam.delete_role_policy(RoleName=role, PolicyName="Probe")
        iam.delete_role(RoleName=role)
        log(f"  self-test cleanup: role {role} deleted")
    except ClientError as e:
        log(f"  self-test cleanup: {e.response['Error']['Code']}")
        ok = False
    return ok


def main() -> int:
    global USER, POLICY_ARN
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="apply (default: dry run)")
    ap.add_argument("--self-test", action="store_true",
                    help="after detaching admin, create+delete a throwaway role")
    ap.add_argument("--profile", default=PROFILE)
    ap.add_argument("--user", default=USER)
    args = ap.parse_args()
    dry_run = not args.yes

    USER = args.user
    iam = boto3.Session(profile_name=args.profile).client("iam")
    acct = boto3.Session(profile_name=args.profile).client("sts").get_caller_identity()["Account"]
    POLICY_ARN = f"arn:aws:iam::{acct}:policy/{POLICY_NAME}"

    def log(msg):
        print(("[dry-run] " if dry_run else "[apply]  ") + msg)

    snap = snapshot(iam)
    print(f"state snapshot -> {snap['path']}")
    print(f"current attached: {snap['attached']}")

    doc = load_policy()
    ensure_policy(iam, doc, dry_run, log)

    attached = {p["PolicyName"] for p in
                iam.list_attached_user_policies(UserName=USER)["AttachedPolicies"]}
    if POLICY_NAME in attached:
        log(f"{POLICY_NAME} already attached to {USER}")
    else:
        log(f"attach {POLICY_NAME} to {USER}")
        if not dry_run:
            iam.attach_user_policy(UserName=USER, PolicyArn=POLICY_ARN)

    if dry_run:
        # Simulation needs the policy attached; dry run just reports the gate.
        log(f"would then simulate {len(REQUIRED)} actions against {POLICY_NAME} only")
        log(f"would detach (only if simulation passes): "
            f"{[n for n in DROP_MANAGED if n in attached] or 'nothing (already detached)'}")
        print("\n1 change set pending (re-run with --yes).")
        return 0

    if not simulate(iam, doc, log):
        print("\nABORT: admin policies NOT detached.", file=sys.stderr)
        return 2

    dropped = []
    for name in DROP_MANAGED:
        if name not in attached:
            log(f"detach {name}: already absent")
            continue
        log(f"detach managed policy {name}")
        iam.detach_user_policy(UserName=USER,
                               PolicyArn=f"arn:aws:iam::aws:policy/{name}")
        dropped.append(name)

    remaining = [p["PolicyName"] for p in
                 iam.list_attached_user_policies(UserName=USER)["AttachedPolicies"]]
    print(f"\nattached now: {remaining}")
    print(f"detached: {dropped or 'nothing'}")

    if args.self_test:
        print("\n--- end-to-end self-test ---")
        if not self_test(iam, log):
            print("WARNING: self-test failed — see restore command in this script's docstring",
                  file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
