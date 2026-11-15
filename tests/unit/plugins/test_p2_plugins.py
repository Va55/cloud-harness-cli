"""Tests for the CloudFront, Lambda, VPC, and Org plugins — moto-mocked."""

import pytest

try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

pytestmark = pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")

import boto3  # noqa: E402

from harness_plugins.aws_lambda.plugin import LambdaPlugin  # noqa: E402
from harness_plugins.cloudfront.plugin import CloudFrontPlugin  # noqa: E402
from harness_plugins.org.plugin import OrgPlugin  # noqa: E402
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


class TestCloudFront:
    def test_list_empty(self, session):
        plugin = CloudFrontPlugin()
        assert list(plugin.list_distributions(session)) == []

    def test_create_and_list(self, session):
        client = session.get_client("cloudfront", "us-east-1")
        resp = client.create_distribution(
            DistributionConfig={
                "CallerReference": "test-ref",
                "Comment": "test",
                "Enabled": True,
                "Origins": {"Quantity": 1, "Items": [{
                    "Id": "origin-1",
                    "DomainName": "example.com",
                    "CustomOriginConfig": {
                        "HTTPPort": 80, "HTTPSPort": 443,
                        "OriginProtocolPolicy": "http-only",
                    },
                }]},
                "DefaultCacheBehavior": {
                    "TargetOriginId": "origin-1",
                    "ViewerProtocolPolicy": "allow-all",
                    "MinTTL": 0, "MaxTTL": 10000, "DefaultTTL": 500,
                    "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}},
                },
            },
        )
        dist_id = resp["Distribution"]["Id"]
        plugin = CloudFrontPlugin()
        dists = list(plugin.list_distributions(session))
        assert len(dists) == 1
        assert dists[0]["resource_id"] == dist_id
        assert dists[0]["enabled"] is True

    def test_get_resource(self, session):
        client = session.get_client("cloudfront", "us-east-1")
        resp = client.create_distribution(
            DistributionConfig={
                "CallerReference": "test-ref2",
                "Comment": "t", "Enabled": True,
                "Origins": {"Quantity": 1, "Items": [{
                    "Id": "o1", "DomainName": "example.org",
                    "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443,
                                            "OriginProtocolPolicy": "http-only"},
                }]},
                "DefaultCacheBehavior": {
                    "TargetOriginId": "o1", "ViewerProtocolPolicy": "allow-all",
                    "MinTTL": 0, "MaxTTL": 1000, "DefaultTTL": 100,
                    "ForwardedValues": {"QueryString": False, "Cookies": {"Forward": "none"}},
                },
            },
        )
        dist_id = resp["Distribution"]["Id"]
        plugin = CloudFrontPlugin()
        dist = plugin.get_resource(session, dist_id)
        assert dist is not None
        assert dist["resource_id"] == dist_id
        assert plugin.get_resource(session, "ENOEXIST") is None

    def test_global_service_flag(self):
        assert CloudFrontPlugin.CAPABILITIES.is_global_service is True

    def test_unknown_safe_op(self, session):
        plugin = CloudFrontPlugin()
        with pytest.raises(NotImplementedError):
            plugin.safe_op(session, "delete", "E123")


class TestLambda:
    def _make_role(self, session):
        """Moto requires an assumable role for Lambda."""
        import json as _json
        iam = session.get_client("iam", "us-east-1")
        try:
            role = iam.create_role(
                RoleName="lambda-role",
                AssumeRolePolicyDocument=_json.dumps({
                    "Version": "2012-10-17",
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }],
                }),
            )
            return role["Role"]["Arn"]
        except Exception:
            return iam.get_role(RoleName="lambda-role")["Role"]["Arn"]

    def _make_function(self, session, name="test-fn", runtime="python3.12"):
        client = session.get_client("lambda", "us-east-1")
        role_arn = self._make_role(session)
        client.create_function(
            FunctionName=name,
            Runtime=runtime,
            Role=role_arn,
            Handler="index.handler",
            Code={"ZipFile": b"def handler(event, context): return {'ok': True}"},
        )

    def test_list_functions(self, session):
        self._make_function(session, "fn-1")
        self._make_function(session, "fn-2", runtime="nodejs20.x")
        plugin = LambdaPlugin()
        fns = list(plugin.list_functions(session, "us-east-1"))
        assert len(fns) == 2
        names = {f["resource_id"] for f in fns}
        assert names == {"fn-1", "fn-2"}

    def test_runtime_filter(self, session):
        self._make_function(session, "py-fn")
        self._make_function(session, "js-fn", runtime="nodejs20.x")
        plugin = LambdaPlugin()
        py_fns = list(plugin.list_functions(session, "us-east-1",
                                            runtime="python3.12"))
        assert [f["resource_id"] for f in py_fns] == ["py-fn"]

    def test_get_function(self, session):
        self._make_function(session, "get-fn")
        plugin = LambdaPlugin()
        fn = plugin.get_resource(session, "get-fn", "us-east-1")
        assert fn["resource_id"] == "get-fn"
        assert fn["runtime"] == "python3.12"
        assert plugin.get_resource(session, "missing", "us-east-1") is None

    def test_invoke(self, session):
        """Moto's Lambda invoke executes the code via Docker.

        Skip when Docker is unusable: module missing OR the daemon
        unreachable (docker installed but daemon down → moto returns
        'Handled' errors instead of executing — a skip, not a failure).
        """
        try:
            import docker
        except ImportError:
            pytest.skip("moto Lambda invoke requires docker")
        try:
            docker.from_env().ping()
        except Exception:
            pytest.skip("docker daemon not reachable — moto cannot "
                        "execute Lambda functions")
        self._make_function(session, "invoke-fn")
        plugin = LambdaPlugin()
        result = plugin.invoke(session, "invoke-fn", "us-east-1")
        assert result["status_code"] == 200
        assert result["error_type"] is None

    def test_regional_service_flag(self):
        assert LambdaPlugin.CAPABILITIES.is_global_service is False


class TestVPC:
    def _make_vpc(self, session, cidr="10.0.0.0/16"):
        client = session.get_client("ec2", "us-east-1")
        return client.create_vpc(CidrBlock=cidr)["Vpc"]["VpcId"]

    def test_list_vpcs(self, session):
        vpc_id = self._make_vpc(session)
        plugin = VPCPlugin()
        vpcs = list(plugin.list_vpcs(session, "us-east-1"))
        assert any(v["resource_id"] == vpc_id for v in vpcs)

    def test_get_vpc(self, session):
        vpc_id = self._make_vpc(session)
        plugin = VPCPlugin()
        vpc = plugin.get_resource(session, vpc_id, "us-east-1")
        assert vpc["resource_id"] == vpc_id

    def test_list_subnets_with_vpc_filter(self, session):
        vpc_id = self._make_vpc(session)
        client = session.get_client("ec2", "us-east-1")
        client.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
        plugin = VPCPlugin()
        subnets = list(plugin.list_subnets(session, "us-east-1", vpc_id=vpc_id))
        assert len(subnets) == 1
        assert subnets[0]["vpc_id"] == vpc_id

    def test_type_dispatch(self, session):
        """Inventory collector passes type= filters."""
        vpc_id = self._make_vpc(session)
        client = session.get_client("ec2", "us-east-1")
        client.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
        plugin = VPCPlugin()
        vpcs = list(plugin.list_resources(session, "us-east-1", type="vpcs"))
        subnets = list(plugin.list_resources(session, "us-east-1", type="subnets"))
        assert len(vpcs) >= 1
        assert len(subnets) >= 1

    def test_readonly(self, session):
        plugin = VPCPlugin()
        with pytest.raises(NotImplementedError, match="read-only"):
            plugin.safe_op(session, "delete", "vpc-1")


class TestOrg:
    def test_list_accounts(self, session):
        client = session.get_client("organizations", "us-east-1")
        client.create_organization(FeatureSet="ALL")
        client.create_account(AccountName="prod", Email="prod@example.com")
        plugin = OrgPlugin()
        accounts = list(plugin.list_accounts(session))
        names = [a["name"] for a in accounts]
        assert "prod" in names
        assert all(a["status"] == "ACTIVE" for a in accounts)

    def test_list_ous(self, session):
        client = session.get_client("organizations", "us-east-1")
        client.create_organization(FeatureSet="ALL")
        root_id = client.list_roots()["Roots"][0]["Id"]
        ou = client.create_organizational_unit(
            ParentId=root_id, Name="production")["OrganizationalUnit"]
        plugin = OrgPlugin()
        ous = list(plugin.list_ous(session))
        assert any(o["resource_id"] == ou["Id"] and o["name"] == "production"
                   for o in ous)

    def test_nested_ous_walked(self, session):
        client = session.get_client("organizations", "us-east-1")
        client.create_organization(FeatureSet="ALL")
        root_id = client.list_roots()["Roots"][0]["Id"]
        prod = client.create_organizational_unit(
            ParentId=root_id, Name="prod")["OrganizationalUnit"]
        client.create_organizational_unit(ParentId=prod["Id"], Name="eu")
        plugin = OrgPlugin()
        ous = list(plugin.list_ous(session))
        paths = [o.get("path") for o in ous if o.get("path")]
        assert any("prod/eu" in p for p in paths), f"paths: {paths}"

    def test_global_service_flag(self):
        assert OrgPlugin.CAPABILITIES.is_global_service is True
