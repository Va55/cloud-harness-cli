"""
Inventory Plugin — resource collection into the local store.

The core of the harness: collect resources across accounts × regions ×
services, snapshot them into SQLite, then query/summarize/diff locally.
This is the "weekly sweep" that replaces an hour of console clicking.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities
from harness_primitives.output import FailureMsg, WarningMsg

INVENTORY_CAPABILITIES = PluginCapabilities(
    name="inventory",
    display_name="Inventory",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=False,
    max_rps=(),
    rate_limit_strict=False,
)

# Which plugin resource types each inventory service maps to, and whether
# the service is global (single call, no region fan-out).
SERVICE_PLAN = {
    "ec2": {"types": ["instances", "security-groups", "volumes"], "is_global": False},
    "s3": {"types": ["buckets"], "is_global": True},   # one call, no fan-out
    "iam": {"types": ["users"], "is_global": True},
    "vpc": {"types": ["vpcs", "subnets"], "is_global": False},
    "lambda": {"types": ["functions"], "is_global": False},
    "cloudfront": {"types": ["distributions"], "is_global": True},
    "org": {"types": ["accounts"], "is_global": True},
}


class InventoryPlugin(BasePlugin):
    """Inventory collection and querying."""

    CAPABILITIES = INVENTORY_CAPABILITIES

    def __init__(self):
        from harness_plugins.registry import PluginRegistry
        self._registry = PluginRegistry()
        self._registry.load()

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None, **filters) -> Iterator[dict]:
        """Not applicable — inventory aggregates other plugins."""
        raise NotImplementedError("Inventory aggregates other plugins; use collect()")

    def get_resource(self, session: Any, resource_id: str, region: Optional[str] = None) -> Optional[dict]:
        raise NotImplementedError("Use inventory show against the store")

    def create_app(self) -> typer.Typer:
        """Typer sub-app for inventory commands."""
        inv_app = typer.Typer(name="inventory", help="Resource inventory")

        @inv_app.command("collect")
        def collect_cmd(
            account: Optional[str] = typer.Option(None, "--account",
                                                   help="Account ID/name/OU path"),
            services: str = typer.Option("ec2,s3", "--services",
                                           help="Comma-separated: ec2,s3,iam"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """Collect resources into the local inventory store."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                resolve_accounts,
            )

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, all_accounts)
                svc_list = [s.strip() for s in services.split(",") if s.strip()]
                result = self.collect(
                    accounts, svc_list, config, store, executor, region=region,
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @inv_app.command("summarize")
        def summarize_cmd(
            account: Optional[str] = typer.Option(None, "--account",
                                                   help="Filter by account ID"),
        ):
            """Resource counts by account/region/service (latest snapshot)."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime
            from harness_primitives.output import PartialResult
            from harness_store import database

            config = get_runtime(get_ctx().get("config"))
            store, _, _, executor = build_stack(config)
            try:
                account_id = None
                if account:
                    # Accept name too — resolve if possible, else pass through
                    from harness_primitives.accounts import ACCOUNT_ID_RE
                    account_id = account if ACCOUNT_ID_RE.fullmatch(account) else None
                    if account_id is None:
                        typer.echo("--account for summarize takes the 12-digit ID",
                                   err=True)
                        raise typer.Exit(2)
                summary = database.summarize(store, account_id=account_id)
                emit(PartialResult(success={"summary": summary}),
                     get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @inv_app.command("show")
        def show_cmd(
            service: str = typer.Option(..., "--service", help="Service: ec2|s3|iam"),
            account: Optional[str] = typer.Option(None, "--account",
                                                   help="12-digit account ID"),
            region: Optional[str] = typer.Option(None, "--region"),
        ):
            """Show collected resources (latest snapshot) from the store."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime
            from harness_primitives.output import PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, _, _, executor = build_stack(config)
            try:
                query = """
                    SELECT r.resource_id, r.arn, r.account_id, r.region, r.service,
                           r.state, r.tags_json
                    FROM resources r
                    JOIN inventory_snapshots s ON r.snapshot_id = s.id
                    WHERE s.id IN (
                        SELECT MAX(id) FROM inventory_snapshots
                        WHERE service = ?
                        GROUP BY account_id, region, service
                    ) AND r.service = ?
                """
                params: list = [service, service]
                if account:
                    from harness_primitives.accounts import ACCOUNT_ID_RE
                    if not ACCOUNT_ID_RE.fullmatch(account):
                        typer.echo("--account for show takes the 12-digit ID", err=True)
                        raise typer.Exit(2)
                    query += " AND r.account_id = ?"
                    params.append(account)
                if region:
                    query += " AND r.region = ?"
                    params.append(region)
                query += " LIMIT 500"
                rows = [dict(r) for r in store.execute(query, params).fetchall()]
                emit(PartialResult(success={service: rows}),
                     get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @inv_app.command("search")
        def search_cmd(
            tag: Optional[str] = typer.Option(None, "--tag",
                                               help='Tag filter: Key=Value'),
            name: Optional[str] = typer.Option(None, "--name",
                                                help="Name/tag substring match"),
            service: Optional[str] = typer.Option(None, "--service"),
            account: Optional[str] = typer.Option(None, "--account", help="12-digit ID"),
        ):
            """Search collected resources by tag or name."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, emit, get_runtime
            from harness_primitives.output import PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, _, _, executor = build_stack(config)
            try:
                query = """
                    SELECT r.resource_id, r.account_id, r.region, r.service,
                           r.state, r.tags_json
                    FROM resources r
                    JOIN inventory_snapshots s ON r.snapshot_id = s.id
                    WHERE s.id IN (
                        SELECT MAX(id) FROM inventory_snapshots
                        GROUP BY account_id, region, service
                    )
                """
                params: list = []
                if account:
                    from harness_primitives.accounts import ACCOUNT_ID_RE
                    if not ACCOUNT_ID_RE.fullmatch(account):
                        typer.echo("--account takes the 12-digit ID", err=True)
                        raise typer.Exit(2)
                    query += " AND r.account_id = ?"
                    params.append(account)
                if service:
                    query += " AND r.service = ?"
                    params.append(service)
                if tag:
                    # Tag JSON match: tags_json LIKE '%"Key": "Value"%'
                    if "=" not in tag:
                        typer.echo("--tag takes Key=Value", err=True)
                        raise typer.Exit(2)
                    key, _, value = tag.partition("=")
                    query += " AND r.tags_json LIKE ?"
                    params.append(f'%"{key}": "{value}"%')
                if name:
                    query += " AND (r.tags_json LIKE ? OR r.resource_id LIKE ?)"
                    params.extend([f'%{name}%', f'%{name}%'])
                query += " LIMIT 500"
                rows = [dict(r) for r in store.execute(query, params).fetchall()]
                emit(PartialResult(success={"matches": rows}),
                     get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @inv_app.command("export")
        def export_cmd(
            service: str = typer.Option(..., "--service", help="Service to export"),
            fmt: str = typer.Option("csv", "--format", help="csv|json"),
            account: Optional[str] = typer.Option(None, "--account", help="12-digit ID"),
        ):
            """Export collected resources (latest snapshot) as CSV or JSON."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import build_stack, get_runtime
            from harness_store import database

            config = get_runtime(get_ctx().get("config"))
            store, _, _, executor = build_stack(config)
            try:
                account_id = None
                if account:
                    from harness_primitives.accounts import ACCOUNT_ID_RE
                    if not ACCOUNT_ID_RE.fullmatch(account):
                        typer.echo("--account takes the 12-digit ID", err=True)
                        raise typer.Exit(2)
                    account_id = account
                summary = database.summarize(store, account_id=account_id)
                svc_rows = [s for s in summary if s["service"] == service]
                if not svc_rows:
                    typer.echo(f"No collected data for service '{service}' — "
                               "run 'inventory collect' first", err=True)
                    raise typer.Exit(1)

                # Pull the rows for the latest snapshots of this service
                query = """
                    SELECT r.resource_id, r.arn, r.account_id, r.region,
                           r.service, r.state, r.tags_json
                    FROM resources r
                    JOIN inventory_snapshots s ON r.snapshot_id = s.id
                    WHERE s.id IN (
                        SELECT MAX(id) FROM inventory_snapshots
                        WHERE service = ?
                        GROUP BY account_id, region, service
                    ) AND r.service = ?
                """
                params: list = [service, service]
                if account_id:
                    query += " AND r.account_id = ?"
                    params.append(account_id)
                rows = [dict(r) for r in store.execute(query, params).fetchall()]

                if fmt == "json":
                    import json as _json
                    typer.echo(_json.dumps(rows, indent=2))
                elif fmt == "csv":
                    import csv
                    import sys
                    writer = csv.DictWriter(
                        sys.stdout,
                        fieldnames=["resource_id", "arn", "account_id",
                                    "region", "service", "state", "tags_json"],
                    )
                    writer.writeheader()
                    writer.writerows(rows)
                else:
                    typer.echo(f"Unknown format: {fmt} (use csv|json)", err=True)
                    raise typer.Exit(2)
            finally:
                executor.shutdown()

        return inv_app

    # ─── Collection engine ──────────────────────────────────────

    def collect(self, accounts: list, services: list[str], config: Any,
                store: Any, executor: Any,
                region: Optional[str] = None) -> Any:
        """Collect resources for accounts × services into the store.

        Returns a PartialResult keyed by 'account:service' with counts.
        Failures (permission, throttling) are captured per account-service,
        never aborting the whole sweep.
        """
        from harness_primitives.output import PartialResult

        result = PartialResult()
        session_by_account = {a.id: executor.session_for(a) for a in accounts}

        for service in services:
            if service not in SERVICE_PLAN:
                result.warnings.append(
                    WarningMsg(account_id="-",
                               message=f"Unknown service for inventory: {service} "
                                       f"(supported: {', '.join(SERVICE_PLAN)})")
                )
                continue
            plan = SERVICE_PLAN[service]
            plugin = self._get_service_plugin(service)

            for account in accounts:
                for res_type in plan["types"]:
                    key = f"{account.id}:{service}:{res_type}"
                    try:
                        sess = session_by_account[account.id]
                        if plan["is_global"]:
                            rows = list(
                                plugin.list_resources(sess, None, type=res_type)
                            )
                            self._store_snapshot(
                                store, account.id, "_global", service, rows
                            )
                        else:
                            regions = ([region] if region else self._regions_for(
                                account, config, sess, store
                            ))
                            for r in regions:
                                rows = list(
                                    plugin.list_resources(sess, r, type=res_type)
                                )
                                self._store_snapshot(
                                    store, account.id, r, service, rows
                                )
                        result.success[key] = {"collected": True}
                    except Exception as e:
                        err = getattr(e, "response", {}).get("Error", {})
                        result.failures.append(FailureMsg(
                            account_id=account.id,
                            service=service,
                            error_code=err.get("Code", type(e).__name__),
                            message=str(err.get("Message", e))[:200],
                        ))
        return result

    def _get_service_plugin(self, service: str) -> BasePlugin:
        """Instantiate the target service's plugin."""
        plugin_cls = self._registry.get_plugin(service)
        return plugin_cls()

    def _regions_for(self, account: Any, config: Any, session: Any, store: Any) -> list[str]:
        """Enabled regions for an account (config ∩ detected)."""
        from harness_cli.runtime import regions_for
        return regions_for(account, config, session, store)

    def _store_snapshot(self, store: Any, account_id: str, region: str,
                         service: str, rows: list[dict]) -> int:
        """Create snapshot + insert resource rows."""
        from harness_store import database

        # Normalize rows to the store's shape
        normalized = []
        for row in rows:
            normalized.append({
                "resource_id": row["resource_id"],
                "arn": row.get("arn"),
                "tags": row.get("tags"),
                "state": row.get("state"),
                "raw": row.get("raw"),
            })
        # Ensure the account exists (FK constraint)
        if database.get_account(store, account_id) is None:
            database.upsert_account(store, account_id=account_id,
                                    discovery_source="inventory")
        snap = database.create_snapshot(store, account_id, region, service)
        return database.insert_resources(
            store, snap, account_id, region, service, normalized
        )
