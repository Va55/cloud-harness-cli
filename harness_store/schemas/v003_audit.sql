-- v003_audit.sql
-- Audit trail events (append-only)

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    principal TEXT NOT NULL,
    source_identity TEXT NOT NULL,
    account_id TEXT NOT NULL,
    region TEXT,
    service TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_id TEXT,
    request_id TEXT,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    error_message TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_account ON audit_events(account_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(source_identity, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action, timestamp);
