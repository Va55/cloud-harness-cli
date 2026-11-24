"""
Route 53 Plugin — DNS (real implementation).

Global service — never fan out per region. Read-only by design: DNS
changes are the kind of operation that needs a human reading the diff,
and the harness has no business performing them.

Scope: hosted zones, record sets, health checks. Registrar operations
(domain registration, expiry) live on the separate `route53domains`
endpoint and are not covered here.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

ROUTE53_CAPABILITIES = PluginCapabilities(
    name="route53",
    display_name="Route 53",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=True,
    max_rps=(("route53", 5.0),),
    rate_limit_strict=False,
)


class Route53Plugin(BasePlugin):
    """Route 53 service plugin."""

    CAPABILITIES = ROUTE53_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        yield from self.list_hosted_zones(session)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        client = session.get_client("route53", "us-east-1")
        zones = self._zones(client, zone_id=self._normalize_zone_id(resource_id))
        return next(iter(zones), None)

    def create_app(self) -> typer.Typer:
        r53_app = typer.Typer(name="route53", help="Route 53 management (read-only)")
        plugin = Route53Plugin()

        @r53_app.command("zones")
        def zones_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List hosted zones (global service)."""
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
                    return list(plugin.list_hosted_zones(sess))

                result = executor.execute_across_accounts(
                    accounts, per_account, service="route53")
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @r53_app.command("records")
        def records_cmd(
            zone: str = typer.Argument(..., help="Hosted zone ID (Z...) or name (example.com)"),
            record_type: Optional[str] = typer.Option(
                None, "--type", help="Filter by record type (A, AAAA, CNAME, MX, TXT, ...)"),
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List record sets in a hosted zone."""
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
                wanted = record_type.upper() if record_type else None

                def per_account(sess, acct):
                    rows = list(plugin.list_record_sets(sess, zone))
                    if wanted:
                        rows = [r for r in rows if r["type"] == wanted]
                    return rows

                result = executor.execute_across_accounts(
                    accounts, per_account, service="route53")
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @r53_app.command("health-checks")
        def health_checks_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List Route 53 health checks."""
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
                    return list(plugin.list_health_checks(sess))

                result = executor.execute_across_accounts(
                    accounts, per_account, service="route53")
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return r53_app

    # ─── Service methods ──────────────────────────────────────

    def list_hosted_zones(self, session: Any, private_only: Optional[bool] = None,
                          ) -> Iterator[dict]:
        """List hosted zones (public and private)."""
        client = session.get_client("route53", "us-east-1")
        for row in self._zones(client):
            if private_only is not None and bool(row["private"]) != private_only:
                continue
            yield row

    def list_record_sets(self, session: Any, zone: str,
                         record_type: Optional[str] = None) -> Iterator[dict]:
        """List record sets for a zone given by ID (Z...) or name."""
        client = session.get_client("route53", "us-east-1")
        zone_id = self._normalize_zone_id(zone)
        if "." in zone_id:                     # a zone name, not an ID
            zone_id = self._resolve_zone_id(client, zone)
        paginator = client.get_paginator("list_resource_record_sets")
        for page in paginator.paginate(HostedZoneId=zone_id):
            for rr in page.get("ResourceRecordSets", []):
                if record_type and rr.get("Type") != record_type.upper():
                    continue
                yield self._record_row(rr, zone_id)

    def list_health_checks(self, session: Any) -> Iterator[dict]:
        """List health checks."""
        client = session.get_client("route53", "us-east-1")
        paginator = client.get_paginator("list_health_checks")
        for page in paginator.paginate():
            for hc in page.get("HealthChecks", []):
                yield self._health_check_row(hc)

    # ─── Helpers ──────────────────────────────────────────────

    def _zones(self, client: Any, zone_id: Optional[str] = None) -> Iterator[dict]:
        paginator = client.get_paginator("list_hosted_zones")
        for page in paginator.paginate():
            for zone in page.get("HostedZones", []):
                if zone_id and self._normalize_zone_id(zone["Id"]) != self._normalize_zone_id(zone_id):
                    continue
                yield self._zone_row(zone)

    def _resolve_zone_id(self, client: Any, zone: str) -> str:
        """Accept a zone name (example.com) where an ID is expected."""
        name = zone.rstrip(".")
        for page in client.get_paginator("list_hosted_zones").paginate():
            for candidate in page.get("HostedZones", []):
                if candidate["Name"].rstrip(".") == name:
                    return self._normalize_zone_id(candidate["Id"])
        from harness_primitives.failure import FailureCategory, HarnessError

        raise HarnessError(
            f"hosted zone not found: {zone}", FailureCategory.FATAL)

    @staticmethod
    def _normalize_zone_id(zone_id: str) -> str:
        """Canonical form: the bare zone ID (no /hostedzone/ prefix).

        AWS returns "/hostedzone/Z..."; operators copy either form. Zone
        IDs never contain a dot, which is how a name is told apart.
        """
        return zone_id.replace("/hostedzone/", "")

    @staticmethod
    def _zone_row(zone: dict) -> dict:
        config = zone.get("Config") or {}
        private = bool(config.get("PrivateZone", False))
        raw_id = zone.get("Id", "")
        return {
            "resource_id": raw_id.replace("/hostedzone/", ""),
            "name": zone.get("Name", "").rstrip("."),
            "private": private,
            "record_count": zone.get("ResourceRecordSetCount"),
            "comment": config.get("Comment"),
            "raw": zone,
        }

    @staticmethod
    def _record_row(rr: dict, zone_id: str) -> dict:
        values = rr.get("ResourceRecords") or []
        target = rr.get("AliasTarget") or {}
        return {
            "resource_id": f"{zone_id.replace('/hostedzone/', '')}/{rr.get('Name', '').rstrip('.')}/{rr.get('Type', '')}",
            "name": rr.get("Name", "").rstrip("."),
            "type": rr.get("Type"),
            "ttl": rr.get("TTL"),
            "values": ", ".join(v.get("Value", "") for v in values)[:200] or None,
            "alias": target.get("DNSName", "").rstrip(".") or None,
            "raw": rr,
        }

    @staticmethod
    def _health_check_row(hc: dict) -> dict:
        config = hc.get("HealthCheckConfig") or {}
        return {
            "resource_id": hc.get("Id", ""),
            "name": f"{config.get('Type', 'unknown')} → "
                    f"{config.get('FullyQualifiedDomainName') or config.get('IPAddress') or ''}",
            "type": config.get("Type"),
            "target": (config.get("FullyQualifiedDomainName")
                       or config.get("IPAddress")
                       or config.get("ResourcePath")),
            "disabled": config.get("Disabled", False),
            "raw": hc,
        }
