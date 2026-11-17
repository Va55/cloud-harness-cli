#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Create / tighten the harness `HarnessAccess` role in ONE account.

Idempotent, dry-run by default. This is the "new account" step from
docs/harness-needed_aws-roles.md §6 (cross-account pattern):

  1. role `HarnessAccess`, trust pinned to the ENTRY user
     (arn:aws:iam::<entry>:user/harness) + ExternalId condition
  2. inline `HarnessReadOnly`  (infra/policies/harness-read-policy.json)
  3. inline `HarnessOrgsRead`  (infra/policies/harness-orgs-read.json)
     — only for the management account, or wherever org view is wanted

Run it with a profile that has role-creation rights *in the target
account*. For the member/management pair that is the `sandbox-mgmt`
profile (scoped to HarnessMgmtBootstrap since 2026-11-17).

Usage:
    python3 scripts/create-harness-role.py --profile sandbox-mgmt --dry-run
    python3 scripts/create-harness-role.py --profile sandbox-mgmt --yes
    python3 scripts/create-harness-role.py --profile some-admin --orgs-read --yes
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "infra" / "policies"

ROLE = "HarnessAccess"
ENTRY_ACCOUNT = "111111111111"
ENTRY_USER = "harness"
EXTERNAL_ID = "harness-example"

INLINE = [("HarnessReadOnly", "harness-read-policy.json")]
ORGS_INLINE = ("HarnessOrgsRead", "harness-orgs-read.json")


def load(name: str) -> dict:
    return json.loads((POLICY_DIR / name).read_text())


def trust_doc(entry_account: str, entry_user: str, external_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "TrustHarnessEntryUserOnly",
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{entry_account}:user/{entry_user}"},
            "Action": ["sts:AssumeRole", "sts:TagSession", "sts:SetSourceIdentity"],
            "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
        }],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="profile with IAM admin in TARGET account")
    ap.add_argument("--role", default=ROLE)
    ap.add_argument("--entry-account", default=ENTRY_ACCOUNT)
    ap.add_argument("--entry-user", default=ENTRY_USER)
    ap.add_argument("--external-id", default=EXTERNAL_ID)
    ap.add_argument("--orgs-read", action="store_true",
                    help="also attach HarnessOrgsRead (management account only)")
    ap.add_argument("--yes", action="store_true", help="apply (default: dry run)")
    args = ap.parse_args()
    dry_run = not args.yes

    def log(msg: str) -> None:
        print(("[dry-run] " if dry_run else "[apply]  ") + msg)

    session = boto3.Session(profile_name=args.profile)
    iam = session.client("iam")
    who = session.client("sts").get_caller_identity()
    account = who["Account"]
    print(f"target account {account} as {who['Arn'].rsplit('/', 1)[-1]}")

    trust = trust_doc(args.entry_account, args.entry_user, args.external_id)
    policies = list(INLINE) + ([ORGS_INLINE] if args.orgs_read else [])
    changed = []

    # ── role + trust ────────────────────────────────────────────
    try:
        current = iam.get_role(RoleName=args.role)["Role"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        log(f"create role {args.role} (trust: user {args.entry_user}@"
            f"{args.entry_account}, ExternalId {args.external_id})")
        if not dry_run:
            iam.create_role(
                RoleName=args.role,
                AssumeRolePolicyDocument=json.dumps(trust),
                Description="Cloud Harness CLI — read-only access "
                            "(see docs/harness-needed_aws-roles.md)",
                MaxSessionDuration=3600,
                Tags=[{"Key": "managed-by", "Value": "cloud-harness-cli"}],
            )
        changed.append("role:created")
    else:
        if json.loads(json.dumps(current["AssumeRolePolicyDocument"])) != trust:
            log(f"tighten trust policy on {args.role} -> entry user "
                f"{args.entry_user}@{args.entry_account} + ExternalId")
            if not dry_run:
                iam.update_assume_role_policy(RoleName=args.role,
                                              PolicyDocument=json.dumps(trust))
            changed.append("trust:tightened")
        else:
            log(f"role {args.role} exists, trust policy already correct")

    # ── inline policies ─────────────────────────────────────────
    for pol_name, fname in policies:
        doc = load(fname)
        try:
            same = json.loads(json.dumps(
                iam.get_role_policy(RoleName=args.role, PolicyName=pol_name)["PolicyDocument"]
            )) == doc
        except ClientError:
            same = False
        if same:
            log(f"  inline policy {pol_name} already correct")
            continue
        log(f"  put inline policy {pol_name} on {args.role}")
        if not dry_run:
            iam.put_role_policy(RoleName=args.role, PolicyName=pol_name,
                                PolicyDocument=json.dumps(doc))
        changed.append(f"inline:{pol_name}")

    print(f"\n{len(changed)} change(s) "
          f"{'pending (re-run with --yes)' if dry_run else 'applied'}.")
    if not dry_run and changed:
        print(f"\nNow add to ~/.config/cloud-harness/config.yaml:\n"
              f"  - id: '{account}'\n    name: <short-name>\n"
              f"    role_arn: arn:aws:iam::{account}:role/{args.role}\n"
              f"    read_only: true\n"
              f"then: harness account list   # persist discovery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
