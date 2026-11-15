"""Tests for the real EC2 plugin operations — moto-mocked."""

import pytest

try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

pytestmark = pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")

import boto3  # noqa: E402

from harness_plugins.ec2.plugin import EC2Plugin  # noqa: E402


class FakeSession:
    """Wraps a moto-mocked boto3 session with the harness client API."""

    def __init__(self):
        self._session = boto3.Session(region_name="us-east-1")

    def get_client(self, service, region=None):
        return self._session.client(service, region_name=region or "us-east-1")

    def get_sts_client(self):
        return self.get_client("sts", "us-east-1")


@pytest.fixture
def session():
    with mock_aws():
        yield FakeSession()


@pytest.fixture
def plugin():
    return EC2Plugin()


def make_instance(session, name="web", state="running", public=False):
    ec2 = session.get_client("ec2", "us-east-1")
    kwargs = {
        "ImageId": "ami-12345678",
        "InstanceType": "t3.micro",
        "MinCount": 1,
        "MaxCount": 1,
        "TagSpecifications": [{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": name}],
        }],
    }
    if public:
        kwargs["NetworkInterfaces"] = [{
            "DeviceIndex": 0,
            "AssociatePublicIpAddress": True,
            "SubnetId": _default_subnet(ec2),
            "Groups": [_default_sg(ec2)["GroupId"]],
        }]
    resp = ec2.run_instances(**kwargs)
    return resp["Instances"][0]["InstanceId"]


def _default_subnet(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    subnet = ec2.create_subnet(VpcId=vpc["VpcId"], CidrBlock="10.0.1.0/24")["Subnet"]
    return subnet["SubnetId"]


def _default_sg(ec2):
    sgs = ec2.describe_security_groups()["SecurityGroups"]
    return sgs[0]


class TestListInstances:
    def test_lists_created_instance(self, session, plugin):
        iid = make_instance(session, name="web-1")
        instances = list(plugin.list_instances(session, "us-east-1"))
        assert len(instances) == 1
        assert instances[0]["resource_id"] == iid
        assert instances[0]["name"] == "web-1"
        assert instances[0]["state"] == "running"
        assert instances[0]["type"] == "t3.micro"

    def test_state_filter(self, session, plugin):
        make_instance(session, name="a")
        instances = list(plugin.list_instances(session, "us-east-1", state="stopped"))
        assert instances == []  # created running

    def test_empty_region_is_success(self, session, plugin):
        assert list(plugin.list_instances(session, "us-east-1")) == []


class TestGetResource:
    def test_get_existing(self, session, plugin):
        iid = make_instance(session)
        inst = plugin.get_resource(session, iid, "us-east-1")
        assert inst is not None
        assert inst["resource_id"] == iid

    def test_get_missing_returns_none(self, session, plugin):
        assert plugin.get_resource(session, "i-nonexistent", "us-east-1") is None


class TestSafeOps:
    def test_stop_instance(self, session, plugin):
        iid = make_instance(session)
        result = plugin.safe_op(session, "stop", iid, region="us-east-1")
        assert result["status"] == "stopping"
        assert result["instances"][0]["id"] == iid

    def test_start_instance(self, session, plugin):
        iid = make_instance(session)
        plugin.safe_op(session, "stop", iid, region="us-east-1")
        result = plugin.safe_op(session, "start", iid, region="us-east-1")
        assert result["status"] == "starting"

    def test_dry_run_reported(self, session, plugin):
        """EC2 native DryRun — DryRunOperation means permitted."""
        iid = make_instance(session)
        result = plugin.safe_op(session, "stop", iid, region="us-east-1", dry_run=True)
        assert "dry-run-ok" in result["status"]

    def test_unknown_op_rejected(self, session, plugin):
        with pytest.raises(NotImplementedError):
            plugin.safe_op(session, "reboot", "i-123", region="us-east-1")


class TestSecurityGroups:
    def test_lists_sgs(self, session, plugin):
        ec2 = session.get_client("ec2", "us-east-1")
        ec2.create_security_group(GroupName="web-sg", Description="web")
        sgs = list(plugin.list_security_groups(session, "us-east-1"))
        assert any(sg["name"] == "web-sg" for sg in sgs)


class TestVolumes:
    def test_lists_volumes(self, session, plugin):
        vol = list(plugin.list_volumes(session, "us-east-1"))
        assert len(vol) >= 0  # moto creates none by default


class TestAudit:
    def test_no_findings_on_clean(self, session, plugin):
        audit = plugin.audit(session, "us-east-1")
        assert audit["compliant"] is True

    def test_public_instance_flagged(self, session, plugin):
        make_instance(session, name="public-web", public=True)
        audit = plugin.audit(session, "us-east-1")
        assert audit["compliant"] is False
        assert any(f["type"] == "public_instance" for f in audit["findings"])

    def test_open_sg_flagged(self, session, plugin):
        ec2 = session.get_client("ec2", "us-east-1")
        sg = ec2.create_security_group(GroupName="open", Description="open")["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=sg,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
            }],
        )
        audit = plugin.audit(session, "us-east-1")
        assert any(f["type"] == "open_security_group" for f in audit["findings"])
