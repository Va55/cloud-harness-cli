#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Bootstrap the read-only IAM user for a production rollout (Stage 0).

This is the script the business owner (or their admin) runs ONCE per
business, as described in docs/production-rollout-plan.md §6:

  1. creates an IAM user  <name>  (default: harness-readonly)
  2. attaches the read-only policy from the plan's Appendix B
     (or AWS-managed ReadOnlyAccess with --managed)
  3. creates one access key
  4. writes the SECRET to a 0600 file (never stdout) and prints the
     profile snippet to paste into ~/.aws/credentials

Run with ADMIN credentials of the target account. Creates a READ-ONLY
identity — by design it cannot mutate anything.

Usage:
    python3 scripts/bootstrap-readonly-user.py [--profile P] \\
        [--user-name harness-readonly] [--managed | custom policy default]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3

CUSTOM_READONLY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "HarnessReadonly",
        "Effect": "Allow",
        "Action": [
            "ec2:Describe*", "iam:List*", "iam:Get*", "s3:List*",
            "s3:GetBucket*", "backup:List*", "lambda:List*",
            "cloudfront:List*", "guardduty:List*", "guardduty:Get*",
            "cloudtrail:LookupEvents", "ce:GetCostAndUsage",
            "organizations:Describe*", "account:ListRegions",
        ],
        "Resource": "*",
    }],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None, help="AWS profile with ADMIN access")
    ap.add_argument("--user-name", default="harness-readonly")
    ap.add_argument("--managed", action="store_true",
                    help="attach AWS-managed ReadOnlyAccess instead of the custom policy")
    args = ap.parse_args()

    session = boto3.Session(profile_name=args.profile)
    sts = session.client("sts", region_name="eu-north-1")
    account = sts.get_caller_identity()["Account"]
    iam = session.client("iam")
    print(f"target account: {account} "
          f"(user: {sts.get_caller_identity()['Arn']})")

    # 1. user
    try:
        iam.get_user(UserName=args.user_name)
        print(f"user exists: {args.user_name}")
    except iam.exceptions.NoSuchEntityException:
        iam.create_user(UserName=args.user_name)
        print(f"user created: {args.user_name}")

    # 2. policy
    if args.managed:
        iam.attach_user_policy(
            UserName=args.user_name,
            PolicyArn="arn:aws:iam::aws:policy/ReadOnlyAccess")
        print("attached: AWS-managed ReadOnlyAccess")
    else:
        policy_name = "HarnessReadOnly"
        arn = None
        for p in iam.list_policies(Scope="Local")["Policies"]:
            if p["PolicyName"] == policy_name:
                arn = p["Arn"]
                break
        if arn is None:
            arn = iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(CUSTOM_READONLY),
                Description="Harness read-only access (rollout plan Appendix B)")["Policy"]["Arn"]
            print(f"policy created: {policy_name}")
        else:
            print(f"policy exists: {policy_name}")
        iam.attach_user_policy(UserName=args.user_name, PolicyArn=arn)
        print(f"policy attached to {args.user_name}")

    # 3. access key (reuse if one is already active)
    keys = [k for k in iam.list_access_keys(UserName=args.user_name)["AccessKeyMetadata"]
            if k["Status"] == "Active"]
    if keys:
        key_id = keys[0]["AccessKeyId"]
        print(f"active key already exists: {key_id} — not creating another")
        print("\nDone. The profile snippet (secret is in the file from its "
              "creation time):")
    else:
        key = iam.create_access_key(UserName=args.user_name)["AccessKey"]
        key_id = key["AccessKeyId"]
        secret = key["SecretAccessKey"]

        # 4. secret → 0600 file, never stdout (the harness convention)
        secret_dir = Path.home() / ".cache" / "aws-harness" / "credentials"
        secret_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(secret_dir, 0o700)
        secret_path = secret_dir / f"{key_id}.secret"
        fd = os.open(str(secret_path),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secret)
        os.chmod(secret_path, 0o600)
        print(f"access key created: {key_id}")
        print(f"secret written to: {secret_path} (0600 — never displayed)")

        print("\nAdd this profile to ~/.aws/credentials:")
        print("    [<profile-name>]")
        print(f"    aws_access_key_id = {key_id}")
        print("    aws_secret_access_key = <contents of the secret file>")

    print("""
Done. Next (the operator side):
    1. Fill ~/.aws/credentials with the profile above
    2. In ~/.config/aws-harness/config.yaml add the business with
       read_only: true  ← the production safety lock
    3. Verify:  harness --profile <profile> whoami
    4. Pre-brief the business's monitoring on the harness-* CloudTrail
       session pattern (rollout plan §4)
""")


if __name__ == "__main__":
    sys.exit(main())
