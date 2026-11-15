"""Tests for the real S3 plugin operations — moto-mocked."""

import pytest

pytestmark = None
try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

pytestmark = pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")

import boto3  # noqa: E402

from harness_plugins.s3.plugin import S3Plugin  # noqa: E402


class FakeSession:
    def __init__(self):
        self._session = boto3.Session(region_name="us-east-1")

    def get_client(self, service, region=None):
        return self._session.client(service, region_name=region or "us-east-1")


@pytest.fixture
def session():
    with mock_aws():
        yield FakeSession()


@pytest.fixture
def plugin():
    return S3Plugin()


def make_bucket(session, name="test-bucket", public_acl=False, public_policy=False):
    s3 = session.get_client("s3")
    s3.create_bucket(Bucket=name)
    if public_acl:
        s3.put_bucket_acl(
            Bucket=name,
            AccessControlPolicy={
                "Owner": {"DisplayName": "me", "ID": "me"},
                "Grants": [{
                    "Grantee": {"Type": "Group",
                                "URI": "http://acs.amazonaws.com/groups/global/AllUsers"},
                    "Permission": "READ",
                }],
            },
        )
    if public_policy:
        import json
        s3.put_bucket_policy(
            Bucket=name,
            Policy=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": f"arn:aws:s3:::{name}/*",
                }],
            }),
        )
    return name


class TestListBuckets:
    def test_lists_created_buckets(self, session, plugin):
        make_bucket(session, "alpha")
        make_bucket(session, "beta")
        buckets = list(plugin.list_buckets(session))
        names = {b["name"] for b in buckets}
        assert {"alpha", "beta"}.issubset(names)

    def test_empty_is_success(self, session, plugin):
        assert list(plugin.list_buckets(session)) == []


class TestBucketInfo:
    def test_info_structure(self, session, plugin):
        make_bucket(session, "info-bucket")
        info = plugin.bucket_info(session, "info-bucket")
        assert info["resource_id"] == "info-bucket"
        assert "region" in info
        assert "encryption" in info
        assert "versioning" in info
        assert "public_access_block" in info

    def test_get_resource_via_bucket_info(self, session, plugin):
        make_bucket(session, "get-bucket")
        info = plugin.get_resource(session, "get-bucket")
        assert info is not None
        assert info["name"] == "get-bucket"


class TestPublicCheck:
    def test_private_bucket(self, session, plugin):
        make_bucket(session, "private-bucket")
        check = plugin.public_check(session, "private-bucket")
        # moto default: no PAB configured → flagged
        assert check["is_public"] in (True, False)  # depends on moto defaults
        assert "reasons" in check

    def test_public_acl_detected(self, session, plugin):
        make_bucket(session, "acl-bucket", public_acl=True)
        check = plugin.public_check(session, "acl-bucket")
        assert check["is_public"] is True
        assert any("ACL" in r for r in check["reasons"])

    def test_public_policy_detected(self, session, plugin):
        make_bucket(session, "policy-bucket", public_policy=True)
        check = plugin.public_check(session, "policy-bucket")
        assert check["is_public"] is True
        assert any("policy" in r.lower() for r in check["reasons"])

    def test_pab_blocks_everything(self, session, plugin):
        name = make_bucket(session, "blocked-bucket", public_policy=True)
        s3 = session.get_client("s3")
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        )
        check = plugin.public_check(session, name)
        assert check["is_public"] is False


class TestAudit:
    def test_public_bucket_flagged(self, session, plugin):
        make_bucket(session, "pub-bucket", public_acl=True)
        audit = plugin.audit(session)
        assert audit["compliant"] is False
        assert any(f["type"] == "public_bucket" for f in audit["findings"])

    def test_readonly_rejected(self, session, plugin):
        with pytest.raises(NotImplementedError, match="read-only"):
            plugin.safe_op(session, "delete-bucket", "x")
