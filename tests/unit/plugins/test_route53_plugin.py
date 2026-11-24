"""Route 53 plugin: read-only DNS inventory.

Covers the row contract (every row carries resource_id), the private/public
flag, record filtering, zone lookup by name as well as ID, and health
checks. Route 53 is a global service, so no region fan-out.
"""

import boto3
import pytest

try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:  # pragma: no cover
    HAS_MOTO = False

from harness_plugins.route53.plugin import Route53Plugin


class FakeSession:
    def __init__(self):
        self._session = boto3.Session(region_name="us-east-1")

    def get_client(self, service, region=None):
        return self._session.client(service, region_name=region or "us-east-1")


@pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
class TestRoute53Plugin:
    def _seed(self, client):
        public = client.create_hosted_zone(
            Name="example.com", CallerReference="ref-public",
            HostedZoneConfig={"Comment": "public zone"})
        private = client.create_hosted_zone(
            Name="internal.example.com", CallerReference="ref-private",
            VPC={"VPCRegion": "us-east-1", "VPCId": "vpc-12345678"},
            HostedZoneConfig={"Comment": "private zone", "PrivateZone": True})
        client.change_resource_record_sets(
            HostedZoneId=public["HostedZone"]["Id"].replace("/hostedzone/", ""),
            ChangeBatch={"Changes": [
                {"Action": "UPSERT", "ResourceRecordSet": {
                    "Name": "www.example.com", "Type": "A", "TTL": 300,
                    "ResourceRecords": [{"Value": "203.0.113.10"}]}},
                {"Action": "UPSERT", "ResourceRecordSet": {
                    "Name": "example.com", "Type": "MX", "TTL": 3600,
                    "ResourceRecords": [{"Value": "10 mail.example.com"}]}},
            ]})
        client.create_health_check(CallerReference="hc-1", HealthCheckConfig={
            "Type": "HTTPS", "FullyQualifiedDomainName": "example.com",
            "ResourcePath": "/health"})
        return public, private

    def test_zones_carry_row_contract_and_private_flag(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            self._seed(client)
            rows = list(Route53Plugin().list_hosted_zones(FakeSession()))

            assert len(rows) == 2
            for row in rows:
                assert row["resource_id"], "row contract: resource_id required"
                assert row["name"], "row contract: name required"
                assert isinstance(row["private"], bool)
            by_name = {r["name"]: r for r in rows}
            assert by_name["internal.example.com"]["private"] is True
            assert by_name["example.com"]["private"] is False
            assert by_name["example.com"]["comment"] == "public zone"
            # IDs are normalised (no /hostedzone/ prefix)
            assert not any(r["resource_id"].startswith("/hostedzone/") for r in rows)

    def test_private_only_filter(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            self._seed(client)
            rows = list(Route53Plugin().list_hosted_zones(FakeSession(), private_only=True))
            assert [r["name"] for r in rows] == ["internal.example.com"]

    def test_records_by_zone_name_and_type_filter(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            self._seed(client)
            plugin = Route53Plugin()

            all_rows = list(plugin.list_record_sets(FakeSession(), "example.com"))
            types = {r["type"] for r in all_rows}
            assert {"A", "MX"} <= types
            for row in all_rows:
                assert row["resource_id"]

            mx_only = list(plugin.list_record_sets(FakeSession(), "example.com",
                                                  record_type="MX"))
            assert [r["type"] for r in mx_only] == ["MX"]
            assert "mail.example.com" in mx_only[0]["values"]

    def test_unknown_zone_is_a_harness_error(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            self._seed(client)
            with pytest.raises(Exception) as excinfo:
                list(Route53Plugin().list_record_sets(FakeSession(), "nope.example"))
            assert "hosted zone not found" in str(excinfo.value)

    def test_health_checks(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            self._seed(client)
            rows = list(Route53Plugin().list_health_checks(FakeSession()))
            assert len(rows) == 1
            assert rows[0]["resource_id"]
            assert rows[0]["type"] == "HTTPS"
            assert rows[0]["target"] == "example.com"

    def test_get_resource_by_id(self):
        with mock_aws():
            client = FakeSession().get_client("route53", "us-east-1")
            public, _ = self._seed(client)
            zone_id = public["HostedZone"]["Id"].replace("/hostedzone/", "")
            row = Route53Plugin().get_resource(FakeSession(), zone_id)
            assert row is not None and row["name"] == "example.com"
