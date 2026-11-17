"""
Organizations Plugin — org structure (real implementation, read-only).

Global service. Phase 1: list accounts, list OUs.
Note: account discovery for the resolver already uses list_accounts;
this plugin exposes the same data (plus OUs) as CLI commands.
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

ORG_CAPABILITIES = PluginCapabilities(
    name="org",
    display_name="Organizations",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=False,
    is_global_service=True,
    max_rps=(("organizations", 10.0),),
    rate_limit_strict=False,
)


class OrgPlugin(BasePlugin):
    """Organizations service plugin."""

    CAPABILITIES = ORG_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        """List accounts (default)."""
        yield from self.list_accounts(session)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Get one account by ID."""
        client = session.get_client("organizations", "us-east-1")
        try:
            acct = client.describe_account(AccountId=resource_id)["Account"]
            return self._account_row(acct)
        except client.exceptions.AccountNotFoundException:
            return None

    def safe_op(self, session: Any, operation: str, resource_id: str, **params) -> dict:
        raise NotImplementedError("Org Phase 1 is read-only")

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "org", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def list_accounts(self, session: Any) -> Iterator[dict]:
        """List all accounts in the organization."""
        client = session.get_client("organizations", "us-east-1")
        paginator = client.get_paginator("list_accounts")
        for page in paginator.paginate():
            for acct in page.get("Accounts", []):
                yield self._account_row(acct)

    def list_ous(self, session: Any) -> Iterator[dict]:
        """List the root and all organizational units (recursive)."""
        client = session.get_client("organizations", "us-east-1")
        roots = client.list_roots()["Roots"]
        for root in roots:
            yield {
                "resource_id": root["Id"],
                "name": root["Name"],
                "type": "Root",
                "arn": root.get("Arn"),
            }
            yield from self._walk_ous(client, root["Id"], path=root["Name"])

    def _walk_ous(self, client: Any, parent_id: str, path: str,
                  depth: int = 0) -> Iterator[dict]:
        """Recursively walk OUs under a parent (depth-guarded)."""
        if depth > 20:
            return
        paginator = client.get_paginator("list_organizational_units_for_parent")
        for page in paginator.paginate(ParentId=parent_id):
            for ou in page.get("OrganizationalUnits", []):
                ou_path = f"{path}/{ou['Name']}"
                yield {
                    "resource_id": ou["Id"],
                    "name": ou["Name"],
                    "type": "OU",
                    "path": ou_path,
                    "arn": ou.get("Arn"),
                }
                yield from self._walk_ous(client, ou["Id"], ou_path, depth + 1)

    @staticmethod
    def _account_row(acct: dict) -> dict:
        return {
            "resource_id": acct["Id"],
            "name": acct.get("Name"),
            "email": acct.get("Email"),
            "status": acct.get("Status"),
            "joined": str(acct.get("JoinedTimestamp", "")),
            "raw": acct,
        }

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        org_app = typer.Typer(name="org", help="Organizations (read-only)")
        plugin = OrgPlugin()

        @org_app.command("list-accounts")
        def list_accounts_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """List all accounts in the organization."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack, emit, get_runtime, resolve_accounts,
            )
            from harness_primitives.output import FailureMsg, PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, False)
                result = PartialResult()
                for acct in accounts:
                    try:
                        sess = executor.session_for(acct)
                        result.success[acct.id] = list(
                            plugin.list_accounts(sess))
                    except Exception as e:
                        # Members are denied org reads by design — a
                        # failure entry, never a raw traceback.
                        err = getattr(e, "response", {}).get("Error", {})
                        result.failures.append(FailureMsg(
                            account_id=acct.id, service="org",
                            error_code=err.get("Code", type(e).__name__),
                            message=str(err.get("Message", e))[:300],
                        ))
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @org_app.command("list-ous")
        def list_ous_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
        ):
            """List the root and all OUs (recursive)."""
            from harness_cli.main import get_ctx
            from harness_cli.runtime import (
                build_stack, emit, get_runtime, resolve_accounts,
            )
            from harness_primitives.output import FailureMsg, PartialResult

            config = get_runtime(get_ctx().get("config"))
            store, session, resolver, executor = build_stack(config)
            try:
                accounts = resolve_accounts(resolver, account, False)
                result = PartialResult()
                for acct in accounts:
                    try:
                        sess = executor.session_for(acct)
                        result.success[acct.id] = list(plugin.list_ous(sess))
                    except Exception as e:
                        err = getattr(e, "response", {}).get("Error", {})
                        result.failures.append(FailureMsg(
                            account_id=acct.id, service="org",
                            error_code=err.get("Code", type(e).__name__),
                            message=str(err.get("Message", e))[:300],
                        ))
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return org_app
