"""
Cost Plugin — Cost Explorer queries (real implementation, read-only).

GLOBAL + STRICT: Cost Explorer throttles at 0.5 requests/second per
account (one call every 2 seconds). All CE calls are serialized per
account through the rate limiter; the CLI exposes grouped summaries
(GroupBy collapses dimensions — one call instead of many).
"""

import time
from datetime import date, timedelta
from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

COST_CAPABILITIES = PluginCapabilities(
    name="cost",
    display_name="Cost Explorer",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=True,
    max_rps=(("ce", 0.5),),  # 0.5 TPS — the strictest API
    rate_limit_strict=True,
)

# Simple 24h result cache: cost data is already ~24h stale at AWS
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 24 * 3600


class CostPlugin(BasePlugin):
    """Cost Explorer plugin."""

    CAPABILITIES = COST_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """Cost data isn't a resource list — use by_service/total."""
        raise NotImplementedError("Use cost by-service / total queries")

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        raise NotImplementedError("Use cost by-service / total queries")

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        raise NotImplementedError("Cost is read-only")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "cost", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def by_service(self, session: Any, account_id: str = "unknown",
                   days: int = 30) -> dict:
        """Cost grouped by service over the last N days.

        Cached 24h — cost data is delayed anyway. Serialized through
        the CE rate limiter by the caller (executor service='ce').
        """
        cache_key = f"{account_id}:by-service:{days}:{date.today()}"
        cached = _CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        end = date.today()
        start = end - timedelta(days=days)
        client = session.get_client("ce", "us-east-1")
        resp = client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        # Aggregate per service across all months in range
        per_service: dict[str, float] = {}
        for result in resp.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                svc = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                per_service[svc] = per_service.get(svc, 0.0) + amount

        data = {
            "period": f"{start} → {end}",
            "currency": "USD",
            "by_service": dict(sorted(per_service.items(),
                                      key=lambda kv: -kv[1])),
            "total": round(sum(per_service.values()), 2),
        }
        _CACHE[cache_key] = (time.time(), data)
        return data

    def total(self, session: Any, account_id: str = "unknown",
              days: int = 30) -> dict:
        """Total unblended cost for the period (one CE call)."""
        cache_key = f"{account_id}:total:{days}:{date.today()}"
        cached = _CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]

        end = date.today()
        start = end - timedelta(days=days)
        client = session.get_client("ce", "us-east-1")
        resp = client.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )
        total = sum(
            float(res["Total"]["UnblendedCost"]["Amount"])
            for res in resp.get("ResultsByTime", [])
        )
        data = {
            "period": f"{start} → {end}",
            "currency": "USD",
            "total": round(total, 2),
        }
        _CACHE[cache_key] = (time.time(), data)
        return data

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        cost_app = typer.Typer(name="cost", help="Cost Explorer (read-only)")
        plugin = CostPlugin()

        @cost_app.command("by-service")
        def by_service_cmd(
            days: int = typer.Option(30, "--days", help="Look-back days"),
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Cost grouped by service. Cached 24h; 0.5 TPS respected."""
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

                def per_account(sess, acct):
                    return plugin.by_service(sess, account_id=acct.id, days=days)

                # service='ce' → executor serializes at 0.5 TPS per account
                result = executor.execute_across_accounts(
                    accounts, per_account, service="ce"
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @cost_app.command("total")
        def total_cmd(
            days: int = typer.Option(30, "--days", help="Look-back days"),
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Total cost for the period."""
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

                def per_account(sess, acct):
                    return plugin.total(sess, account_id=acct.id, days=days)

                result = executor.execute_across_accounts(
                    accounts, per_account, service="ce"
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return cost_app
