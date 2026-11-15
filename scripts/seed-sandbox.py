#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Seed the AWS sandbox with test resources (Phase 25, scripted).

Sandbox-only: creates billable-but-tiny resources so the harness's
mutation paths have something real to work on. NOT for production
businesses (use scripts/bootstrap-readonly-user.py there instead).

Seeds (per account/region, default profile+region from args):
  - one t3.micro instance, tagged 'harness-test', left STOPPED
  - one AWS Backup vault 'harness-test-vault'
  - one GuardDuty detector (30-day free trial)

Teardown: --teardown removes everything this script created
(the instance incl. its volume, the vault, the detector).
Cost while seeded: ~$0.01/day (the stopped instance's 8GB EBS volume).

Usage:
    python3 scripts/seed-sandbox.py [--profile P] [--region R]
    python3 scripts/seed-sandbox.py --teardown [--profile P] [--region R]
"""

import argparse
import sys

import boto3

INSTANCE_TAG = "harness-test"
VAULT_NAME = "harness-test-vault"
NAME_TAG = [{"Key": "Name", "Value": INSTANCE_TAG}]


def find_test_instance(ec2):
    resp = ec2.describe_instances(
        Filters=[{"Name": "tag:Name", "Values": [INSTANCE_TAG]}])
    for r in resp.get("Reservations", []):
        for i in r.get("Instances", []):
            if i["State"]["Name"] not in ("terminated",):
                return i
    return None


def seed(profile, region):
    session = boto3.Session(profile_name=profile)
    ec2 = session.client("ec2", region_name=region)

    inst = find_test_instance(ec2)
    if inst:
        print(f"instance already exists: {inst['InstanceId']} "
              f"({inst['State']['Name']}) — skipping")
    else:
        images = ec2.describe_images(
            Owners=["amazon"],
            Filters=[{"Name": "name", "Values": ["al2023-ami-2023.*-x86_64"]},
                     {"Name": "state", "Values": ["available"]}])["Images"]
        images.sort(key=lambda i: i["CreationDate"], reverse=True)
        resp = ec2.run_instances(
            ImageId=images[0]["ImageId"], InstanceType="t3.micro",
            MaxCount=1, MinCount=1,
            TagSpecifications=[{"ResourceType": "instance", "Tags": NAME_TAG}])
        inst_id = resp["Instances"][0]["InstanceId"]
        print(f"instance created: {inst_id} — waiting for running…")
        ec2.get_waiter("instance_running").wait(InstanceIds=[inst_id])
        ec2.stop_instances(InstanceIds=[inst_id])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[inst_id])
        print(f"instance stopped: {inst_id}")

    backup = session.client("backup", region_name=region)
    try:
        backup.create_backup_vault(BackupVaultName=VAULT_NAME)
        print(f"backup vault created: {VAULT_NAME}")
    except backup.exceptions.AlreadyExistsException:
        print(f"backup vault exists: {VAULT_NAME} — skipping")

    gd = session.client("guardduty", region_name=region)
    detectors = gd.list_detectors()["DetectorIds"]
    if detectors:
        print(f"guardduty detector exists: {detectors[0][:16]}… — skipping")
    else:
        det = gd.create_detector(Enable=True,
                                  FindingPublishingFrequency="SIX_HOURS")
        print(f"guardduty detector created: {det['DetectorId'][:16]}…")

    print("\nSeeded. Verify with:")
    print(f"  harness ec2 list-instances --region {region} --profile {profile}"
          if profile else f"  harness ec2 list-instances --region {region}")
    print(f"  harness backup list-vaults --region {region}")


def teardown(profile, region):
    session = boto3.Session(profile_name=profile)
    ec2 = session.client("ec2", region_name=region)

    inst = find_test_instance(ec2)
    if inst:
        ec2.terminate_instances(InstanceIds=[inst["InstanceId"]])
        print(f"instance terminating: {inst['InstanceId']}")
        print("  (its volume is deleted automatically — DeleteOnTermination)")
    else:
        print("no test instance found")

    backup = session.client("backup", region_name=region)
    try:
        vaults = [v["BackupVaultName"]
                  for v in backup.list_backup_vaults()["BackupVaultList"]]
        if VAULT_NAME in vaults:
            backup.delete_backup_vault(BackupVaultName=VAULT_NAME)
            print(f"backup vault deleted: {VAULT_NAME}")
    except Exception as e:
        print(f"backup vault: {e}")

    gd = session.client("guardduty", region_name=region)
    detectors = gd.list_detectors()["DetectorIds"]
    for d in detectors:
        gd.delete_detector(DetectorId=d)
        print(f"guardduty detector deleted: {d[:16]}…")
    if not detectors:
        print("no guardduty detectors found")
    print("\nTeardown complete — the sandbox is now empty again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None, help="AWS profile (default: default chain)")
    ap.add_argument("--region", default="eu-north-1", help="region (default: eu-north-1)")
    ap.add_argument("--teardown", action="store_true", help="remove everything this script created")
    args = ap.parse_args()

    if args.teardown:
        teardown(args.profile, args.region)
    else:
        seed(args.profile, args.region)


if __name__ == "__main__":
    sys.exit(main())
