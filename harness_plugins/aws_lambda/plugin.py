"""
Lambda Plugin — serverless functions (real implementation).

Regional service. Phase 1: read (functions, layers) + safe op (invoke).
"""

from typing import Any, Iterator, Optional

import typer

from harness_plugins.base import BasePlugin, PluginCapabilities

LAMBDA_CAPABILITIES = PluginCapabilities(
    name="lambda",
    display_name="Lambda",
    supports_read=True,
    supports_create=False,
    supports_update=False,
    supports_delete=False,
    supports_safe_ops=True,
    is_global_service=False,
    max_rps=(("lambda", 5.0),),
    rate_limit_strict=False,
)


class LambdaPlugin(BasePlugin):
    """Lambda service plugin."""

    CAPABILITIES = LAMBDA_CAPABILITIES

    # ─── BasePlugin interface ─────────────────────────────────

    def list_resources(self, session: Any, region: Optional[str] = None,
                       **filters) -> Iterator[dict]:
        filters.pop("type", None)  # 'functions' is the only inventory type
        yield from self.list_functions(session, region, **filters)

    def get_resource(self, session: Any, resource_id: str,
                     region: Optional[str] = None) -> Optional[dict]:
        """Get one function's configuration."""
        client = session.get_client("lambda", region)
        try:
            resp = client.get_function_configuration(FunctionName=resource_id)
            return self._function_row(resp)
        except client.exceptions.ResourceNotFoundException:
            return None

    def safe_op(self, session: Any, operation: str, resource_id: str,
                region: Optional[str] = None, **params) -> dict:
        """Safe ops: invoke (optionally with payload)."""
        if operation != "invoke":
            raise NotImplementedError(f"Lambda does not support safe op: {operation}")
        return self.invoke(session, resource_id, region,
                           payload=params.get("payload"))

    def dry_run_simulate(self, session: Any, operation: str, **params) -> dict:
        return {"service": "lambda", "operation": operation,
                "params": params, "status": "would_execute"}

    # ─── Operations ────────────────────────────────────────────

    def list_functions(self, session: Any, region: Optional[str] = None,
                       runtime: Optional[str] = None) -> Iterator[dict]:
        """List Lambda functions with pagination."""
        client = session.get_client("lambda", region)
        paginator = client.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                if runtime and fn.get("Runtime") != runtime:
                    continue
                yield self._function_row(fn)

    def invoke(self, session: Any, function_name: str,
               region: Optional[str] = None,
               payload: Optional[str] = None,
               dry_run: bool = False) -> dict:
        """Invoke a function (safe op). Returns status + parsed response.

        dry_run=True uses Lambda's native Invoke DryRun parameter:
        validates permissions without executing the function.
        """
        import json
        client = session.get_client("lambda", region)
        kwargs = {
            "FunctionName": function_name,
            "LogType": "Tail",
        }
        if dry_run:
            kwargs["DryRun"] = True
        if payload:
            kwargs["Payload"] = payload.encode()
        resp = client.invoke(**kwargs)

        result: dict = {
            "function": function_name,
            "status_code": resp["StatusCode"],
            "error_type": resp.get("FunctionError"),
        }
        # Read payload (never raise on function error — report it)
        payload_resp = resp.get("Payload")
        if payload_resp is not None:
            body = payload_resp.read()
            if body:
                text = body.decode("utf-8", errors="replace")
                try:
                    result["response"] = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    result["response"] = text[:500]
        return result

    @staticmethod
    def _function_row(fn: dict) -> dict:
        return {
            "resource_id": fn["FunctionName"],
            "arn": fn.get("FunctionArn"),
            "runtime": fn.get("Runtime"),
            "state": fn.get("State") or fn.get("Status"),
            "memory_mb": fn.get("MemorySize"),
            "timeout_s": fn.get("Timeout"),
            "last_modified": str(fn.get("LastModified", "")),
            "raw": fn,
        }

    # ─── CLI ────────────────────────────────────────────────────

    def create_app(self) -> typer.Typer:
        lam_app = typer.Typer(name="lambda", help="Lambda management")
        plugin = LambdaPlugin()

        @lam_app.command("list-functions")
        def list_functions_cmd(
            account: Optional[str] = typer.Option(None, "--account"),
            region: Optional[str] = typer.Option(None, "--region"),
            runtime: Optional[str] = typer.Option(None, "--runtime"),
            all_accounts: bool = typer.Option(False, "--all-accounts"),
        ):
            """List Lambda functions across accounts × regions."""
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
                        lambda s, r: list(plugin.list_functions(s, r, runtime=runtime)),
                        session=sess, account_id=acct.id, service="lambda",
                    )

                result = executor.execute_across_accounts(accounts, per_account)
                emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        @lam_app.command("invoke")
        def invoke_cmd(
            function_name: str = typer.Argument(..., help="Function name"),
            payload: Optional[str] = typer.Option(None, "--payload",
                                                   help='JSON payload, e.g. \'{"k":1}\''),
            account: Optional[str] = typer.Option(None, "--account"),
            region: str = typer.Option(..., "--region"),
            dry_run: bool = typer.Option(False, "--dry-run"),
        ):
            """Invoke a Lambda function (safe op)."""
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
                effective_dry_run = bool(dry_run or get_ctx().get("dry_run"))
                try:
                    data = plugin.invoke(sess, function_name, region,
                                          payload=payload,
                                          dry_run=effective_dry_run)
                    record_audit(
                        config, action="invoke", service="lambda",
                        account_id=acct.id, region=region,
                        resource_id=function_name, success=True,
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    emit(PartialResult(success={function_name: data}),
                         get_ctx().get("output", "table"))
                except typer.Exit:
                    raise  # emit() success — NOT a failure
                except Exception as e:
                    err = getattr(e, "response", {}).get("Error", {})
                    record_audit(
                        config, action="invoke", service="lambda",
                        account_id=acct.id, region=region,
                        resource_id=function_name, success=False,
                        error_message=str(err.get("Message", e))[:300],
                        dry_run=effective_dry_run,
                        principal=sess.source_identity,
                    )
                    result = PartialResult()
                    result.failures.append(FailureMsg(
                        account_id=acct.id, region=region, service="lambda",
                        error_code=err.get("Code", type(e).__name__),
                        message=str(err.get("Message", e))[:300],
                    ))
                    emit(result, get_ctx().get("output", "table"))
            finally:
                executor.shutdown()

        return lam_app
