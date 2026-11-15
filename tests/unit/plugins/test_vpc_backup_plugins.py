"""Tests for the VPC extension and the AWS Backup plugin (Phase 22).

VPC + backup vaults/plans: moto-mocked (real API shapes).
Backup jobs/recovery-points/start-backup: moto does not implement
these backends, so mocked client responses assert OUR parsing logic.
"""

from unittest.mock import MagicMock

import pytest

try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

pytestmark = pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")

import boto3  # noqa: E402

from harness_plugins.backup.plugin import BackupPlugin  # noqa: E402
from harness_plugins.vpc.plugin import VPCPlugin  # noqa: E402


class FakeSession:
    def __init__(self):
        self._session = boto3.Session(region_name="us-east-1")

    def get_client(self, service, region=None):
        return self._session.client(service, region_name=region or "us-east-1")


@pytest.fixture
def session():
    with mock_aws():
        yield FakeSession()


# ─── VPC extension ──────────────────────────────────────────────

class TestVPCInternetGateways:
    def test_list_igws(self, session):
        client = session.get_client("ec2")
        client.create_internet_gateway(TagSpecifications=[{
            "ResourceType": "internet-gateway",
            "Tags": [{"Key": "Name", "Value": "igw-main"}],
        }])
        rows = list(VPCPlugin().list_internet_gateways(session))
        assert len(rows) == 1
        assert rows[0]["name"] == "igw-main"
        assert rows[0]["attached_vpcs"] == []


class TestVPCNatGateways:
    def test_list_nat_gateways(self, session):
        client = session.get_client("ec2")
        vpc = client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
        subnet = client.create_subnet(
            VpcId=vpc["VpcId"], CidrBlock="10.0.1.0/24")["Subnet"]
        allocation = client.allocate_address(Domain="vpc")
        client.create_nat_gateway(
            SubnetId=subnet["SubnetId"],
            AllocationId=allocation["AllocationId"],
        )["NatGateway"]
        rows = list(VPCPlugin().list_nat_gateways(session))
        assert len(rows) == 1
        assert rows[0]["vpc_id"] == vpc["VpcId"]
        assert rows[0]["state"] == "available"


class TestVPCNacls:
    def test_list_nacls_default_exists(self, session):
        client = session.get_client("ec2")
        vpc = client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
        rows = list(VPCPlugin().list_nacls(session, vpc_id=vpc["VpcId"]))
        assert len(rows) == 1
        assert rows[0]["default"] is True
        # Default NACL: 2 inbound + 2 outbound entries (allow-all +
        # deny-all each) per moto's model
        assert rows[0]["rules_in"] >= 1
        assert rows[0]["rules_out"] >= 1


class TestVPCEndpoints:
    def test_list_endpoints(self, session):
        client = session.get_client("ec2")
        vpc = client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
        client.create_vpc_endpoint(
            VpcId=vpc["VpcId"],
            ServiceName="com.amazonaws.us-east-1.s3",
            VpcEndpointType="Gateway",
        )
        rows = list(VPCPlugin().list_endpoints(session, vpc_id=vpc["VpcId"]))
        assert len(rows) == 1
        assert rows[0]["service"] == "s3"
        assert rows[0]["type"] == "Gateway"


class TestVPCFlowLogsAndAudit:
    def test_audit_flags_vpc_without_flow_logs_and_public_subnet(self, session):
        client = session.get_client("ec2")
        vpc = client.create_vpc(CidrBlock="10.0.0.0/16",
                                InstanceTenancy="default")["Vpc"]
        subnet = client.create_subnet(VpcId=vpc["VpcId"],
                                      CidrBlock="10.0.1.0/24")["Subnet"]
        client.modify_subnet_attribute(
            SubnetId=subnet["SubnetId"],
            MapPublicIpOnLaunch={"Value": True})

        audit = VPCPlugin().audit(session)
        types = {f["type"] for f in audit["findings"]}
        assert "vpc_without_flow_logs" in types
        assert "public_subnet" in types
        assert audit["compliant"] is False

    def test_describe_vpc(self, session):
        client = session.get_client("ec2")
        vpc = client.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
        subnet = client.create_subnet(VpcId=vpc["VpcId"],
                                      CidrBlock="10.0.1.0/24")["Subnet"]
        client.modify_subnet_attribute(
            SubnetId=subnet["SubnetId"],
            MapPublicIpOnLaunch={"Value": True})
        row = VPCPlugin().describe_vpc(session, vpc["VpcId"])
        assert row is not None
        assert row["subnet_count"] == 1
        assert row["public_subnets"] == 1
        assert row["flow_logs"] == 0
        assert row["internet_gateways"] == []

    def test_describe_missing_vpc(self, session):
        assert VPCPlugin().describe_vpc(session, "vpc-nonexistent") is None


# ─── AWS Backup (moto-supported: vaults, plans) ────────────────

class TestBackupVaults:
    def test_list_vaults_empty_then_created(self, session):
        plugin = BackupPlugin()
        assert list(plugin.list_vaults(session)) == []

        client = session.get_client("backup")
        client.create_backup_vault(BackupVaultName="prod-vault")
        rows = list(plugin.list_vaults(session))
        assert len(rows) == 1
        assert rows[0]["resource_id"] == "prod-vault"
        assert rows[0]["recovery_points"] == 0
        assert rows[0]["locked"] is False

    def test_get_resource_vault(self, session):
        client = session.get_client("backup")
        client.create_backup_vault(BackupVaultName="prod-vault")
        row = BackupPlugin().get_resource(session, "prod-vault")
        assert row["resource_id"] == "prod-vault"
        assert BackupPlugin().get_resource(session, "nope") is None


class TestBackupPlans:
    def test_list_plans(self, session):
        client = session.get_client("backup")
        client.create_backup_plan(BackupPlan={
            "BackupPlanName": "daily-all",
            "Rules": [{"RuleName": "daily",
                       "TargetBackupVaultName": "prod-vault",
                       "ScheduleExpression": "cron(0 5 * * ? *)"}],
        })
        client.create_backup_vault(BackupVaultName="prod-vault")
        rows = list(BackupPlugin().list_plans(session))
        assert len(rows) == 1
        assert rows[0]["name"] == "daily-all"


# ─── AWS Backup (moto-unsupported: mocked client shapes) ────────

class TestBackupJobsParsing:
    def test_list_jobs_filters_state(self):
        plugin = BackupPlugin()
        session = MagicMock()
        client = MagicMock()
        session.get_client.return_value = client
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "BackupJobs": [
                {"JobId": "j1", "ResourceArn": "arn:aws:ec2:us-east-1:1:instance/i-1",
                 "State": "COMPLETED", "CreationDate": "2026-11-01",
                 "CompletionDate": "2026-11-01", "StatusMessage": ""},
                {"JobId": "j2", "ResourceArn": "arn:aws:ec2:us-east-1:1:instance/i-2",
                 "State": "FAILED", "CreationDate": "2026-11-02",
                 "CompletionDate": "", "StatusMessage": "role denied"},
            ]}]
        client.get_paginator.return_value = paginator

        all_jobs = list(plugin.list_jobs(session, "us-east-1"))
        assert len(all_jobs) == 2
        failed = list(plugin.list_jobs(session, "us-east-1", state="failed"))
        assert len(failed) == 1
        assert failed[0]["state"] == "FAILED"
        assert "role denied" in failed[0]["message"]

    def test_audit_flags_failed_jobs_and_empty_vaults(self):
        plugin = BackupPlugin()
        session = MagicMock()
        client = MagicMock()

        jobs_paginator = MagicMock()
        jobs_paginator.paginate.return_value = [{
            "BackupJobs": [
                {"JobId": "j2", "ResourceArn": "arn:aws:rds:us-east-1:1:db:prod",
                 "State": "FAILED", "StatusMessage": "vault not found"},
                {"JobId": "j1", "ResourceArn": "arn:...", "State": "COMPLETED"},
            ]}]

        vaults_paginator = MagicMock()
        vaults_paginator.paginate.return_value = [{
            "BackupVaultList": [
                {"BackupVaultName": "empty-vault", "Locked": False,
                 "NumberOfRecoveryPoints": 0},
            ]}]

        client.get_paginator.side_effect = lambda name: {
            "list_backup_jobs": jobs_paginator,
            "list_backup_vaults": vaults_paginator,
        }[name]
        session.get_client.return_value = client

        audit = plugin.audit(session, "us-east-1")
        types = {f["type"] for f in audit["findings"]}
        assert "backup_job_failed" in types
        assert "empty_vault" in types
        assert audit["compliant"] is False


class TestBackupStartBackup:
    def test_start_backup_requires_vault_and_role(self):
        plugin = BackupPlugin()
        with pytest.raises(ValueError, match="vault"):
            plugin.start_backup(MagicMock(), "arn:aws:ec2:...")
        with pytest.raises(ValueError, match="iam-role"):
            plugin.start_backup(MagicMock(), "arn:aws:ec2:...",
                                vault_name="v")

    def test_start_backup_calls_api(self):
        plugin = BackupPlugin()
        session = MagicMock()
        client = MagicMock()
        session.get_client.return_value = client
        client.start_backup_job.return_value = {"BackupJobId": "JOB123"}
        result = plugin.start_backup(
            session, "arn:aws:ec2:...", vault_name="v",
            iam_role_arn="arn:aws:iam::1:role/backup")
        assert result["job_id"] == "JOB123"
        kwargs = client.start_backup_job.call_args.kwargs
        assert kwargs["BackupVaultName"] == "v"
        assert kwargs["IamRoleArn"] == "arn:aws:iam::1:role/backup"

    def test_safe_op_dispatch(self):
        plugin = BackupPlugin()
        session = MagicMock()
        session.get_client.return_value.start_backup_job.return_value = \
            {"BackupJobId": "J"}
        result = plugin.safe_op(session, "start-backup", "arn:aws:ec2:...",
                                vault_name="v",
                                iam_role_arn="role", region="us-east-1")
        assert result["job_id"] == "J"
        with pytest.raises(NotImplementedError):
            plugin.safe_op(session, "restore", "arn:aws:ec2:...")

    def test_dry_run_simulate_makes_no_calls(self):
        plugin = BackupPlugin()
        result = plugin.dry_run_simulate(MagicMock(), "start-backup",
                                         resource_id="arn:x",
                                         vault_name="v")
        assert result["status"] == "would_execute"
        assert "No API call" in result["message"]


# ─── CLI surface ────────────────────────────────────────────────

class TestCLIRegistration:
    def test_backup_and_vpc_commands_registered(self):
        from typer.testing import CliRunner

        from harness_cli.main import app
        runner = CliRunner()

        result = runner.invoke(app, ["backup", "--help"])
        assert result.exit_code == 0
        for cmd in ("list-vaults", "list-plans", "list-recovery-points",
                    "list-jobs", "audit", "start-backup"):
            assert cmd in result.output

        result = runner.invoke(app, ["vpc", "--help"])
        assert result.exit_code == 0
        for cmd in ("describe", "internet-gateways", "nat-gateways",
                    "nacls", "endpoints", "flow-logs", "audit"):
            assert cmd in result.output

    def test_backup_in_ask_catalog(self):
        from harness_cli.ask import _build_catalog
        catalog = _build_catalog()
        assert "backup" in catalog
        assert "list-vaults" in catalog["backup"]


class TestDescribeVpcFilters:
    """Live-found (pass 4): DescribeFlowLogs has no 'vpc-id' filter —
    real AWS rejects it; moto is lenient (why tests missed it). The
    filter must be 'resource-id'."""

    def test_flow_logs_filter_is_resource_id(self):
        plugin = VPCPlugin()
        session = MagicMock()
        client = MagicMock()
        session.get_client.return_value = client
        client.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-1", "CidrBlock": "10.0.0.0/16",
                      "IsDefault": False, "Tags": []}]}
        client.describe_subnets.return_value = {"Subnets": []}
        client.describe_internet_gateways.return_value = {
            "InternetGateways": []}
        client.describe_flow_logs.return_value = {"FlowLogs": []}

        row = plugin.describe_vpc(session, "vpc-1", "eu-north-1")
        assert row is not None
        fl_call = client.describe_flow_logs.call_args.kwargs
        assert fl_call["Filters"] == [{"Name": "resource-id",
                                       "Values": ["vpc-1"]}], \
            "must use the real DescribeFlowLogs filter name"

    def test_describe_missing_vpc_returns_none(self):
        plugin = VPCPlugin()
        session = MagicMock()
        client = MagicMock()
        session.get_client.return_value = client
        client.exceptions.ClientError = Exception
        client.describe_vpcs.side_effect = Exception("not found")
        assert plugin.describe_vpc(session, "vpc-x", "eu-north-1") is None
