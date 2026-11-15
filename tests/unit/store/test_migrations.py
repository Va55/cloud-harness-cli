"""Tests for SQLite store migrations.

Verifies:
- Migrations are idempotent (running twice doesn't fail)
- All tables created with correct structure
- WAL mode enabled
- Foreign keys enforced
"""

import sqlite3
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "harness_store" / "schemas"

EXPECTED_TABLES = {
    "accounts", "inventory_snapshots", "resources",
    "resource_diffs", "audit_events", "metadata",
}


@pytest.fixture
def db(tmp_path):
    """Fresh DB with metadata table + all migrations applied."""
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)
    """)
    conn.commit()
    yield conn
    conn.close()


def apply_migrations(conn):
    for schema in sorted(SCHEMA_DIR.glob("v*.sql")):
        sql = schema.read_text()
        conn.executescript(sql)  # Raises on error — no masking
        conn.commit()


class TestMigrations:
    def test_all_schema_files_exist(self):
        expected = ["v001_accounts.sql", "v002_inventory.sql",
                    "v003_audit.sql", "v004_diffs.sql"]
        actual = sorted(f.name for f in SCHEMA_DIR.glob("v*.sql"))
        assert actual == expected

    def test_migrations_apply_cleanly(self, db):
        apply_migrations(db)

    def test_migrations_idempotent(self, db):
        """Running migrations twice must not fail."""
        apply_migrations(db)
        apply_migrations(db)  # Must not raise

    def test_all_tables_created(self, db):
        apply_migrations(db)
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert EXPECTED_TABLES.issubset(tables)

    def test_wal_mode(self, db):
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_metadata_schema_version(self, db):
        apply_migrations(db)
        version = db.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        assert version is not None


class TestSchemaConstraints:
    def test_accounts_pk(self, db):
        apply_migrations(db)
        db.execute("INSERT INTO accounts (id) VALUES ('111111111111')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO accounts (id) VALUES ('111111111111')")

    def test_audit_success_check_constraint(self, db):
        apply_migrations(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""
                INSERT INTO audit_events (principal, source_identity,
                    account_id, service, action, success)
                VALUES ('p', 'si', '111111111111', 'ec2', 'stop', 5)
            """)

    def test_diff_change_type_check_constraint(self, db):
        apply_migrations(db)
        db.execute("INSERT INTO accounts (id) VALUES ('111111111111')")
        db.execute("""
            INSERT INTO inventory_snapshots (account_id, region, service)
            VALUES ('111111111111', 'us-east-1', 'ec2')
        """)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""
                INSERT INTO resource_diffs (snapshot_a, snapshot_b,
                    resource_id, change_type)
                VALUES (1, 2, 'i-123', 'bogus')
            """)

    def test_resources_composite_pk(self, db):
        apply_migrations(db)
        db.execute("INSERT INTO accounts (id) VALUES ('111111111111')")
        db.execute("""
            INSERT INTO inventory_snapshots (account_id, region, service)
            VALUES ('111111111111', 'us-east-1', 'ec2')
        """)
        db.execute("""
            INSERT INTO resources (snapshot_id, resource_id, account_id,
                region, service)
            VALUES (1, 'i-123', '111111111111', 'us-east-1', 'ec2')
        """)
        # Same snapshot + resource_id → conflict
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""
                INSERT INTO resources (snapshot_id, resource_id, account_id,
                    region, service)
                VALUES (1, 'i-123', '111111111111', 'us-east-1', 'ec2')
            """)
