#!/bin/bash
# Initialize harness database with schema migrations
set -euo pipefail

DB_DIR="${HARNESS_DB_DIR:-$HOME/.cache/aws-harness}"
mkdir -p "$DB_DIR"

INVENTORY_DB="$DB_DIR/inventory.db"
AUDIT_DB="$DB_DIR/audit.db"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCHEMA_DIR="$(dirname "$SCRIPT_DIR")/harness_store/schemas"

echo "Initializing AWS Harness databases..."

for db in "$INVENTORY_DB" "$AUDIT_DB"; do
    echo "  Creating: $db"
    sqlite3 "$db" <<'SQL'
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
SQL
done

# Run migrations in order — errors are NOT masked (fail fast)
for schema in "$SCHEMA_DIR"/v*.sql; do
    if [ ! -f "$schema" ]; then
        echo "ERROR: No schema files found in $SCHEMA_DIR" >&2
        exit 1
    fi
    echo "  Applying: $(basename "$schema")"
    for db in "$INVENTORY_DB" "$AUDIT_DB"; do
        if ! sqlite3 "$db" < "$schema"; then
            echo "ERROR: Failed to apply $(basename "$schema") to $db" >&2
            exit 1
        fi
    done
done

echo "Database initialization complete."
echo "  Inventory DB: $INVENTORY_DB"
echo "  Audit DB:     $AUDIT_DB"
