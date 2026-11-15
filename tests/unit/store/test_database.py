"""Tests for the store Python API (harness_store.database)."""

import pytest

from harness_store import database


@pytest.fixture
def db(tmp_path):
    conn = database.connect(tmp_path / "test.db")
    database.migrate(conn)
    yield conn
    conn.close()


class TestConnect:
    def test_connect_creates_parent_dirs(self, tmp_path):
        conn = database.connect(tmp_path / "a" / "b" / "c" / "test.db")
        assert (tmp_path / "a" / "b" / "c" / "test.db").exists()
        conn.close()

    def test_wal_mode(self, db):
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def test_foreign_keys_on(self, db):
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_row_factory_named(self, db):
        row = db.execute("SELECT 'x' AS val").fetchone()
        assert row["val"] == "x"


class TestMigrations:
    def test_migrate_returns_count(self, tmp_path):
        conn = database.connect(tmp_path / "test.db")
        applied = database.migrate(conn)
        assert applied == 4  # v001..v004
        conn.close()

    def test_migrate_idempotent(self, db):
        assert database.migrate(db) == 4  # re-apply must succeed
        assert database.schema_version(db) >= 1


class TestAccounts:
    def test_upsert_and_list(self, db):
        database.upsert_account(db, "111111111111", name="prod",
                                ou_path="prod", discovery_source="organizations")
        accounts = database.list_accounts(db)
        assert len(accounts) == 1
        assert accounts[0]["id"] == "111111111111"
        assert accounts[0]["name"] == "prod"
        assert accounts[0]["ou_path"] == "prod"

    def test_upsert_updates_existing(self, db):
        database.upsert_account(db, "111111111111", name="prod")
        database.upsert_account(db, "111111111111", name="production")
        accounts = database.list_accounts(db)
        assert len(accounts) == 1
        assert accounts[0]["name"] == "production"

    def test_suspended_filtered_by_default(self, db):
        database.upsert_account(db, "111111111111", name="active", status="ACTIVE")
        database.upsert_account(db, "222222222222", name="dead", status="SUSPENDED")
        active = database.list_accounts(db)
        assert [a["id"] for a in active] == ["111111111111"]
        all_accounts = database.list_accounts(db, include_suspended=True)
        assert len(all_accounts) == 2

    def test_regions_enabled_roundtrip(self, db):
        database.upsert_account(db, "111111111111", regions_enabled=["us-east-1", "eu-west-1"])
        accounts = database.list_accounts(db)
        assert accounts[0]["regions_enabled"] == ["us-east-1", "eu-west-1"]

    def test_get_account(self, db):
        database.upsert_account(db, "111111111111", name="prod")
        assert database.get_account(db, "111111111111")["name"] == "prod"
        assert database.get_account(db, "999999999999") is None


class TestInventory:
    def test_snapshot_and_resources(self, db):
        database.upsert_account(db, "111111111111", name="prod")
        snap = database.create_snapshot(db, "111111111111", "us-east-1", "ec2")
        count = database.insert_resources(
            db, snap, "111111111111", "us-east-1", "ec2", [
                {"resource_id": "i-001", "arn": "arn:aws:ec2:...", "state": "running",
                 "tags": {"Name": "web"}, "raw": {"InstanceId": "i-001"}},
                {"resource_id": "i-002", "state": "stopped"},
            ]
        )
        assert count == 2
        rows = db.execute("SELECT resource_id FROM resources WHERE snapshot_id=?",
                          (snap,)).fetchall()
        assert {r["resource_id"] for r in rows} == {"i-001", "i-002"}

    def test_summarize_counts(self, db):
        database.upsert_account(db, "111111111111", name="prod")
        snap = database.create_snapshot(db, "111111111111", "us-east-1", "ec2")
        database.insert_resources(db, snap, "111111111111", "us-east-1", "ec2",
                                  [{"resource_id": f"i-{n}"} for n in range(3)])
        snap2 = database.create_snapshot(db, "111111111111", "us-east-1", "s3")
        database.insert_resources(db, snap2, "111111111111", "us-east-1", "s3",
                                  [{"resource_id": "bucket-1"}])
        summary = database.summarize(db)
        by_service = {s["service"]: s["count"] for s in summary}
        assert by_service["ec2"] == 3
        assert by_service["s3"] == 1

    def test_summarize_uses_latest_snapshot(self, db):
        """Older snapshots must not pollute the summary."""
        database.upsert_account(db, "111111111111", name="prod")
        snap_old = database.create_snapshot(db, "111111111111", "us-east-1", "ec2")
        database.insert_resources(db, snap_old, "111111111111", "us-east-1", "ec2",
                                  [{"resource_id": "i-old"}])
        snap_new = database.create_snapshot(db, "111111111111", "us-east-1", "ec2")
        database.insert_resources(db, snap_new, "111111111111", "us-east-1", "ec2",
                                  [{"resource_id": "i-new1"}, {"resource_id": "i-new2"}])
        summary = database.summarize(db)
        assert summary[0]["count"] == 2  # Only the latest snapshot


class TestAudit:
    def test_record_and_query(self, db):
        database.record_audit_event(
            db, principal="arn:aws:iam::111111111111:user/alice",
            source_identity="user:alice", account_id="111111111111",
            service="ec2", action="stop-instances",
            resource_id="i-001", region="us-east-1", success=True,
        )
        events = database.query_audit_trail(db, account_id="111111111111")
        assert len(events) == 1
        assert events[0]["action"] == "stop-instances"
        assert events[0]["source_identity"] == "user:alice"
        assert events[0]["success"] == 1

    def test_query_filters(self, db):
        for acct in ["111111111111", "222222222222"]:
            database.record_audit_event(
                db, principal="p", source_identity="user:alice",
                account_id=acct, service="ec2", action="list",
            )
        assert len(database.query_audit_trail(db, account_id="111111111111")) == 1
        assert len(database.query_audit_trail(db, user="alice")) == 2
        assert len(database.query_audit_trail(db, service="s3")) == 0

    def test_failed_event_stored(self, db):
        database.record_audit_event(
            db, principal="p", source_identity="user:bob",
            account_id="111111111111", service="iam", action="delete-user",
            success=False, error_message="DeleteConflict",
        )
        events = database.query_audit_trail(db)
        assert events[0]["success"] == 0
        assert events[0]["error_message"] == "DeleteConflict"


def test_store_file_and_dir_are_owner_only(tmp_path, monkeypatch):
    """The store holds account IDs + the audit trail: dir 0700, file 0600.

    Skipped where POSIX modes do not apply (Windows ACLs).
    """
    import os
    import stat
    import sys

    import pytest

    from harness_store.database import connect

    if sys.platform.startswith("win"):  # pragma: no cover
        pytest.skip("POSIX permission bits not applicable")

    db = tmp_path / "sub" / "store.db"
    conn = connect(db)
    conn.close()

    d_mode = stat.S_IMODE(os.stat(db.parent).st_mode)
    f_mode = stat.S_IMODE(os.stat(db).st_mode)
    assert d_mode & 0o077 == 0, f"dir too open: {oct(d_mode)}"
    assert f_mode & 0o077 == 0, f"file too open: {oct(f_mode)}"


def test_harden_permissions_never_raises(tmp_path):
    """A filesystem refusing chmod must not break the harness."""
    from harness_store.database import _harden_permissions

    # a path that does not exist for is_dir=True must be a silent no-op
    _harden_permissions(tmp_path / "nope", 0o700, is_dir=True)
    _harden_permissions(tmp_path / "nope", 0o600, is_dir=False)
