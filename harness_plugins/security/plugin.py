"""
Security Plugin — findings aggregation (real implementation, read-only).

Phase 1: GuardDuty detectors + findings counts, Security Hub findings
counts. Findings are returned as summaries (counts by severity) — the
console deep-links are the right place to investigate individual ones.
Regional service (detectors are per-region).
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

SECURITY_CAPABILITIES = PluginCapabilities(
    name="security",
    display_name="Security",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=False,
    max_rps=(("guardduty", 15.0), ("securityhub", 5.0)),
    rate_limit_strict=False,
)

SEVERITY_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


class SecurityPlugin(BasePlugin):
    """Security findings aggregation plugin."""

    CAPABILITIES = SECURITY_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """GuardDuty findings summaries are the default listing."""
        yield from self.guardduty_findings(session, region)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        raise NotImplementedError("Security findings are summarized, not fetched")

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        raise NotImplementedError("Security Phase 1 is read-only")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "security", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def guardduty_findings(self, session: Any,
                           region: Optional[str] = None) -> Iterator[dict]:
        """GuardDuty findings summary per severity level, per region."""
        client = session.get_client("guardduty", region)

        # List detectors (usually one per region, but be thorough)
        try:
            detector_ids = []
            paginator = client.get_paginator("list_detectors")
            for page in paginator.paginate():
                detector_ids.extend(page.get("DetectorIds", []))
        except Exception as e:
            yield {"resource_id": "guardduty", "error": str(e)[:200]}
            return

        for detector_id in detector_ids:
            counts: dict[str, int] = {}
            for level in SEVERITY_LEVELS:
                try:
                    resp = client.get_findings_statistics(
                        DetectorId=detector_id,
                        FindingCriteria={
                            "Criterion": {
                                "severity": {
                                    "Gte": _severity_gte(level),
                                }
                            }
                        },
                        FindingStatisticTypes=["COUNT"],
                    )
                    stats = resp.get("FindingStatistics", {}).get("CountBySeverity", {})
                    counts[level] = sum(stats.values())
                except Exception:
                    counts[level] = -1  # signal error without aborting
            yield {
                "resource_id": f"guardduty:{detector_id[:12]}",
                "region": region,
                # NOTE: each count is "severity >= level" (cumulative), not
                # an exact bucket — GuardDuty statistics only support Gte.
                "count_gte": counts,
                "count_gte_medium": counts.get("MEDIUM", 0),
            }

    def securityhub_findings(self, session: Any,
                            region: Optional[str] = None) -> dict:
        """Security Hub findings summary.

        get_findings returns no total count, so an accurate summary
        requires full pagination (expensive). Until that's implemented,
        this reports enabled status only rather than fabricating counts.
        """
        client = session.get_client("securityhub", region)
        try:
            client.describe_hub()
            return {"resource_id": "security-hub", "region": region,
                    "enabled": True,
                    "note": "finding counts require full pagination — "
                            "use the Security Hub console for precise numbers"}
        except Exception as e:
            return {"resource_id": "security-hub", "region": region,
                    "enabled": False, "error": str(e)[:200]}

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        sec_app = typer.Typer(name="security", help="Security findings (read-only)")
        plugin = SecurityPlugin()

        @sec_app.command("guardduty")
        def guardduty_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """GuardDuty findings summary (counts by severity)."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                regions_for,
                resolve_accounts,
            )

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, all_accounts)

                def per_account(sess, acct):
                    regions = ([region] if region
                               else regions_for(acct, config, sess, store))
                    return executor.execute_across_regions(
                        regions,
                        lambda s, r: list(plugin.guardduty_findings(s, r)),
                        session=sess, account_id=acct.id, service="guardduty",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @sec_app.command("hub")
        def hub_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """Security Hub status per account/region."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack,
                emit,
                get_runtime,
                regions_for,
                resolve_accounts,
            )

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, all_accounts)

                def per_account(sess, acct):
                    regions = ([region] if region
                               else regions_for(acct, config, sess, store))
                    return executor.execute_across_regions(
                        regions,
                        lambda s, r: plugin.securityhub_findings(s, r),
                        session=sess, account_id=acct.id,
                        service="securityhub",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return sec_app


def _severity_gte(level: str) -> float:
    """GuardDuty severity thresholds (0.1–10.0 scale)."""
    return {
        "LOW": 1.0,
        "MEDIUM": 4.0,
        "HIGH": 7.0,
        "CRITICAL": 9.0,
    }.get(level, 1.0)
