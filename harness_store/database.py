"""
SQLite store API — connections, migrations, typed queries.

Thread model: one connection per thread (callers create via
`connect()`, use as context manager). WAL + busy_timeout per design.
Migrations run from harness_store/schemas/*.sql with the metadata
table pre-created (migrations are idempotent — tested).
"""

import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA_DIR = Path(__file__).parent / "schemas"

# Tables that live in the audit DB vs inventory DB (both get the full
# schema for now — see PROJECT_LOG design debt; queries are namespaced).
BUSY_TIMEOUT_MS = 5000


def _harden_permissions(path: Path, mode: int, *, is_dir: bool) -> None:
    """Best-effort chmod (no-op where unsupported, e.g. Windows ACLs).

    The store holds live account IDs, resource inventory and the audit
    trail. Keep it owner-only: dir 0700, files 0600. Never fatal — a
    filesystem that refuses chmod must not break the harness.
    """
    try:
        if not is_dir or path.is_dir():
            path.chmod(mode)
    except (OSError, NotImplementedError):
        pass


def connect(db_path: Path) -> sqlite3.Connection:
    """Create a configured connection: WAL, busy_timeout, foreign keys ON."""
    db_path = Path(db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _harden_permissions(db_path.parent, 0o700, is_dir=True)
    conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_MS / 1000)
    _harden_permissions(db_path, 0o600, is_dir=False)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Row access by column name
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply all schema migrations in order. Idempotent. Returns count applied."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit()
    applied = 0
    for schema in sorted(SCHEMA_DIR.glob("v*.sql")):
        conn.executescript(schema.read_text())  # Raises on error — no masking
        conn.commit()
        applied += 1
    _ensure_business_column(conn)
    return applied


def _ensure_business_column(conn: sqlite3.Connection) -> None:
    """v005: accounts.business column (multi-business support).

    SQLite lacks ALTER TABLE ... ADD COLUMN IF NOT EXISTS, so this is a
    guarded Python migration — idempotent, checked via PRAGMA table_info.
    """
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(accounts)")]
    if cols and "business" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN business TEXT")
        conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM metadata WHERE key='schema_version'"
    ).fetchone()
    return int(row["value"]) if row else 0


# ─── Accounts ───────────────────────────────────────────────────

def upsert_account(conn: sqlite3.Connection, account_id: str,
                   name: Optional[str] = None,
                   ou_path: Optional[str] = None,
                   status: str = "ACTIVE",
                   regions_enabled: Optional[list[str]] = None,
                   discovery_source: str = "organizations",
                   business: Optional[str] = None) -> None:
    """Insert or update an account record.

    Partial upserts are merge-safe: callers that only know the regions
    (e.g. region detection) don't wipe the stored name/ou_path, and
    callers that only know identity (e.g. discovery) don't wipe the
    cached enabled regions. COALESCE keeps the existing value when
    the new one is NULL.
    """
    import json
    conn.execute("""
        INSERT INTO accounts (id, name, ou_path, status, regions_enabled,
                              discovery_source, last_seen, business)
        VALUES (?, ?, ?, ?, ?, ?,
                datetime('now'), ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(excluded.name, accounts.name),
            ou_path = COALESCE(excluded.ou_path, accounts.ou_path),
            status = COALESCE(NULLIF(excluded.status, 'ACTIVE'), accounts.status),
            regions_enabled = COALESCE(excluded.regions_enabled,
                                      accounts.regions_enabled),
            discovery_source = COALESCE(NULLIF(excluded.discovery_source,
                                               'organizations'),
                                        accounts.discovery_source),
            last_seen = datetime('now'),
            business = COALESCE(excluded.business, accounts.business)
    """, (
        account_id, name, ou_path, status,
        json.dumps(regions_enabled) if regions_enabled else None,
        discovery_source,
        business,
    ))
    conn.commit()


def list_accounts(conn: sqlite3.Connection,
                  include_suspended: bool = False) -> list[dict]:
    """List known accounts from the store."""
    query = ("SELECT id, name, ou_path, status, regions_enabled, "
             "last_seen, discovery_source, business FROM accounts")
    if not include_suspended:
        query += " WHERE status != 'SUSPENDED'"
    query += " ORDER BY id"
    rows = conn.execute(query).fetchall()
    import json
    return [{
        "id": r["id"],
        "name": r["name"],
        "ou_path": r["ou_path"],
        "status": r["status"],
        "regions_enabled": json.loads(r["regions_enabled"]) if r["regions_enabled"] else None,
        "last_seen": r["last_seen"],
        "discovery_source": r["discovery_source"],
        "business": r["business"],
    } for r in rows]


def get_account(conn: sqlite3.Connection, account_id: str) -> Optional[dict]:
    """Get one account by ID, or None."""
    for acct in list_accounts(conn, include_suspended=True):
        if acct["id"] == account_id:
            return acct
    return None


def clear_region_cache(conn: sqlite3.Connection) -> None:
    """Invalidate all cached region-enablement data (--refresh).

    Keeps identity fields (name, ou_path, status) — only the detection
    result is discarded so the next sweep re-detects.
    """
    conn.execute("UPDATE accounts SET regions_enabled = NULL")
    conn.commit()


# ─── Inventory ──────────────────────────────────────────────────

def create_snapshot(conn: sqlite3.Connection, account_id: str,
                    region: str, service: str) -> int:
    """Create an inventory snapshot, return its id."""
    cursor = conn.execute("""
        INSERT INTO inventory_snapshots (account_id, region, service)
        VALUES (?, ?, ?)
    """, (account_id, region, service))
    conn.commit()
    return cursor.lastrowid


def insert_resources(conn: sqlite3.Connection, snapshot_id: int,
                     account_id: str, region: str, service: str,
                     resources: list[dict]) -> int:
    """Insert resources for a snapshot. Each dict needs resource_id;
    optional: arn, tags (dict), state, raw (dict)."""
    import json
    count = 0
    for res in resources:
        conn.execute("""
            INSERT INTO resources (snapshot_id, resource_id, arn, account_id,
                                    region, service, tags_json, state, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_id,
            res["resource_id"],
            res.get("arn"),
            account_id,
            region,
            service,
            json.dumps(res["tags"], default=str) if res.get("tags") else None,
            res.get("state"),
            json.dumps(res.get("raw"), default=str) if res.get("raw") else None,
        ))
        count += 1
    conn.commit()
    return count


def summarize(conn: sqlite3.Connection,
               account_id: Optional[str] = None) -> list[dict]:
    """Resource counts by account/region/service (latest snapshot per tuple)."""
    query = """
        SELECT r.account_id, r.region, r.service, COUNT(*) as count
        FROM resources r
        JOIN inventory_snapshots s ON r.snapshot_id = s.id
        WHERE s.id IN (
            SELECT MAX(id) FROM inventory_snapshots
            GROUP BY account_id, region, service
        )
    """
    params: tuple = ()
    if account_id:
        query += " AND r.account_id = ?"
        params = (account_id,)
    query += " GROUP BY r.account_id, r.region, r.service ORDER BY r.account_id, r.service"
    return [dict(row) for row in conn.execute(query, params).fetchall()]


# ─── Audit ──────────────────────────────────────────────────────

def record_audit_event(conn: sqlite3.Connection, principal: str,
                       source_identity: str, account_id: str,
                       service: str, action: str,
                       resource_id: Optional[str] = None,
                       region: Optional[str] = None,
                       request_id: Optional[str] = None,
                       success: bool = True,
                       error_message: Optional[str] = None,
                       dry_run: bool = False,
                       raw: Optional[dict] = None) -> int:
    """Append an audit event. Returns the event id."""
    import json
    cursor = conn.execute("""
        INSERT INTO audit_events (principal, source_identity, account_id,
                                  region, service, action, resource_id,
                                  request_id, success, error_message,
                                  dry_run, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        principal, source_identity, account_id, region, service, action,
        resource_id, request_id, int(success), error_message,
        int(dry_run), json.dumps(raw, default=str) if raw else None,
    ))
    conn.commit()
    return cursor.lastrowid


def query_audit_trail(conn: sqlite3.Connection,
                      account_id: Optional[str] = None,
                      user: Optional[str] = None,
                      service: Optional[str] = None,
                      days: int = 7,
                      limit: int = 200) -> list[dict]:
    """Query recent audit events with optional filters."""
    query = """
        SELECT timestamp, principal, source_identity, account_id, region,
               service, action, resource_id, success, error_message, dry_run
        FROM audit_events
        WHERE timestamp >= datetime('now', ?)
    """
    params: list = [f"-{days} days"]
    if account_id:
        query += " AND account_id = ?"
        params.append(account_id)
    if user:
        query += " AND source_identity LIKE ?"
        params.append(f"%{user}%")
    if service:
        query += " AND service = ?"
        params.append(service)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(query, params).fetchall()]
