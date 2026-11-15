"""Regression: plugin row contract + raw-payload display (pass 3).

Found LIVE against AWS: `inventory collect --services iam` died with
KeyError 'resource_id' — the IAM plugin yielded raw boto3 dicts,
violating the normalized-row contract every other plugin follows.
Also: 'raw' payloads (kept for inventory/JSON) must never pollute
table output.
"""

from datetime import datetime, timezone

import pytest

try:
    from moto import mock_aws
    HAS_MOTO = True
except ImportError:
    HAS_MOTO = False

import boto3  # noqa: E402

from harness_plugins.iam.plugin import IAMPlugin  # noqa: E402
from harness_primitives.output import PartialResult, format_output  # noqa: E402


class FakeSession:
    def __init__(self):
        self._session = boto3.Session(region_name="us-east-1")

    def get_client(self, service, region=None):
        return self._session.client(service, region_name=region or "us-east-1")


@pytest.mark.skipif(not HAS_MOTO, reason="moto not installed")
class TestIAMRowContract:
    """list_resources output must carry resource_id (inventory contract)."""

    def test_list_users_rows_have_resource_id(self):
        with mock_aws():
            session = FakeSession()
            session.get_client("iam").create_user(UserName="alice")
            rows = list(IAMPlugin().list_users(session))
        assert len(rows) == 1
        row = rows[0]
        assert row["resource_id"] == "alice"
        assert row["name"] == "alice"
        assert row["arn"].endswith(":user/alice")
        assert "raw" in row  # inventory keeps the full payload

    def test_list_roles_rows_have_resource_id(self):
        with mock_aws():
            session = FakeSession()
            session.get_client("iam").create_role(
                RoleName="r1",
                AssumeRolePolicyDocument='{"Version":"2012-10-17",'
                                         '"Statement":[]}')
            rows = list(IAMPlugin().list_roles(session))
        assert rows[0]["resource_id"] == "r1"

    def test_list_policies_rows_have_resource_id(self):
        with mock_aws():
            session = FakeSession()
            session.get_client("iam").create_policy(
                PolicyName="p1",
                PolicyDocument='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"*"}]}')
            rows = list(IAMPlugin().list_policies(session))
        assert rows[0]["resource_id"] == "p1"

    def test_inventory_collect_iam_succeeds(self, tmp_path):
        """The original failure: inventory collect with iam users."""
        from harness_store import database

        with mock_aws():
            session = FakeSession()
            session.get_client("iam").create_user(UserName="alice")

            conn = database.connect(tmp_path / "inv.db")
            database.migrate(conn)

            # _store_snapshot must not raise on iam rows
            rows = list(IAMPlugin().list_users(session))
            assert rows  # precondition

        # Verify the store roundtrip shape directly (account FK first)
        database.upsert_account(conn, account_id="111")
        snapshot_id = database.create_snapshot(conn, "111", "_global", "iam")
        database.insert_resources(conn, snapshot_id, "111", "_global",
                                  "iam", rows)
        rows_stored = conn.execute(
            "SELECT resource_id FROM resources WHERE service = 'iam'"
        ).fetchall()
        assert any("alice" in r["resource_id"] for r in rows_stored)


class TestRawHiddenInTables:
    def test_table_skips_raw_key_dict(self):
        r = PartialResult()
        r.success["acct"] = {"resource_id": "alice", "name": "alice",
                             "raw": {"giant": "payload" * 50}}
        out = format_output(r, "table")
        assert "alice" in out
        assert "giant" not in out        # raw never shown in tables

    def test_table_skips_raw_column_in_list_of_dicts(self):
        r = PartialResult()
        r.success["acct"] = [
            {"resource_id": "alice", "name": "alice",
             "raw": {"giant": "payload" * 50}},
            {"resource_id": "bob", "name": "bob",
             "raw": {"giant": "payload" * 50}},
        ]
        out = format_output(r, "table")
        assert "alice" in out and "bob" in out
        assert "raw" not in out          # no garbage column
        assert "giant" not in out

    def test_json_keeps_raw(self):
        """JSON consumers (inventory export, future MCP) get full data."""
        import json
        r = PartialResult()
        r.success["acct"] = {"resource_id": "alice",
                             "raw": {"full": "payload"}}
        data = json.loads(format_output(r, "json"))
        assert data["success"]["acct"]["raw"] == {"full": "payload"}

    def test_datetime_row_survives_json(self):
        r = PartialResult()
        r.success["acct"] = [{"resource_id": "x",
                             "created": datetime(2026, 1, 1,
                                                 tzinfo=timezone.utc)}]
        import json
        data = json.loads(format_output(r, "json"))
        assert data["success"]["acct"][0]["created"] == \
            "2026-01-01T00:00:00+00:00"
