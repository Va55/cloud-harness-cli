"""
CloudFront Plugin — CDN (real implementation).

Global service — never fan out per region. Phase 1: read (distributions)
+ safe op (cache invalidation).
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

CLOUDFRONT_CAPABILITIES = PluginCapabilities(
    name="cloudfront",
    display_name="CloudFront",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=True,
    is_global_service=True,
    max_rps=(("cloudfront", 2.0),),
    rate_limit_strict=False,
)


class CloudFrontPlugin(BasePlugin):
    """CloudFront service plugin."""

    CAPABILITIES = CLOUDFRONT_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        yield from self.list_distributions(session)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        client = session.get_client("cloudfront", "us-east-1")
        try:
            resp = client.get_distribution(Id=resource_id)
            return self._distribution_row(resp["Distribution"])
        except client.exceptions.NoSuchDistribution:
            return None

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        """Safe ops: create_invalidation."""
        if operation != "invalidate":
            raise NotImplementedError(
                f"CloudFront does not support safe op: {operation}"
            )
        return self.invalidate(session, resource_id,
                               paths=params.get("paths", ["/*"]))

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "cloudfront", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def list_distributions(self, session: Any) -> Iterator[dict]:
        """List distributions (global — single call)."""
        client = session.get_client("cloudfront", "us-east-1")
        paginator = client.get_paginator("list_distributions")
        for page in paginator.paginate():
            for dist in page.get("DistributionList", {}).get("Items", []):
                yield self._distribution_row(dist)

    def invalidate(self, session: Any, distribution_id: str,
                   paths: Optional[list[str]] = None) -> dict:
        """Create a cache invalidation (safe op)."""
        client = session.get_client("cloudfront", "us-east-1")
        caller_ref = f"harness-{distribution_id}-{__import__('time').time_ns()}"
        resp = client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": len(paths or ["/*"]),
                          "Items": paths or ["/*"]},
                "CallerReference": caller_ref,
            },
        )
        inv = resp["Invalidation"]
        return {
            "distribution_id": distribution_id,
            "invalidation_id": inv["Id"],
            "status": inv["Status"],
            "paths": paths or ["/*"],
        }

    @staticmethod
    def _distribution_row(dist: dict) -> dict:
        """Normalize a distribution summary/full record."""
        aliases = dist.get("Aliases", {}).get("Items", [])
        origins = dist.get("Origins", {}).get("Items", [])
        return {
            "resource_id": dist["Id"],
            "arn": dist.get("ARN"),
            "domain": dist.get("DomainName"),
            "state": dist.get("Status"),
            "enabled": dist.get("Enabled"),
            "aliases": aliases,
            "origin_domains": [o.get("DomainName") for o in origins],
            "last_modified": str(dist.get("LastModifiedTime", "")),
            "raw": dist,
        }

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        cf_app = typer.Typer(name="cloudfront", help="CloudFront management")
        plugin = CloudFrontPlugin()

        @cf_app.command("list-distributions")
        def list_distributions_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List CloudFront distributions (global service)."""
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
                    return list(plugin.list_distributions(sess))

                result = executor.execute_across_accounts(
                    accounts, per_account, service="cloudfront"
                )
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @cf_app.command("invalidate")
        def invalidate_cmd(
            distribution_id: str = typer.Argument(..., help="Distribution ID (E...)"),
            paths: str = typer.Option("/*", "--paths",
                                       help="Comma-separated paths to invalidate"),
            account: Optional[str] = typer.Option(None, "--account"),
            dry_run: bool = typer.Option(False, "--dry-run"),
        ):
            """Create a cache invalidation (safe op)."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
        build_stack,
        emit,
        ensure_mutable,
        get_runtime,
        record_audit,
    )
            from harness_primitives.output import FailureMsg, PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                acct = resolver.resolve(account)
                sess = executor.session_for(acct)
                ensure_mutable(acct)
                path_list = [p.strip() for p in paths.split(",") if p.strip()]
                effective_dry_run = bool(
                    dry_run or get_ctx().get("dry_run")
                )
                try:
                    if effective_dry_run:
                        data = plugin.dry_run_simulate(
                            sess, "invalidate", distribution_id,
                            paths=path_list,
                        )
                    else:
                        data = plugin.safe_op(sess, "invalidate", distribution_id,
                                              paths=path_list)
                    record_audit(
                        config, action="invalidate", service="cloudfront",
                        account_id=acct.id, region="_global",
                        resource_id=distribution_id, success=True,
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    emit(PartialResult(success={distribution_id: data}),
                         get_ctx().get("output", "table"))
                except typer.Exit:
                    raise  # emit() success — NOT a failure
                except Exception as e:
                    err = getattr(e, "response", {}).get("Error", {})
                    record_audit(
                        config, action="invalidate", service="cloudfront",
                        account_id=acct.id, region="_global",
                        resource_id=distribution_id, success=False,
                        error_message=str(err.get("Message", e))[:300],
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    result = PartialResult()
                    result.failures.append(FailureMsg(
                        account_id=acct.id, service="cloudfront",
                        error_code=err.get("Code", type(e).__name__),
                        message=str(err.get("Message", e))[:300],
                    ))
                    emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return cf_app
