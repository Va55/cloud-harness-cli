"""
`harness serve-mcp` — Tier 2 agent interface (architecture §13.2).

An MCP server over stdio exposing the harness as TOOLS. The client
(pi, Claude Code, VSCode Copilot, Cursor) brings the LLM; the harness
stays the deterministic, tested core.

Design (DeepSeek-reviewed, Phase 2b):
- ~20 FLAT, TYPED tools — no free-form params/union schemas (small
  local models are unreliable with polymorphic schemas)
- READ-ONLY + DRY-RUN safe ops only in v1 — real mutations stay in
  the CLI (a boolean an LLM can set is not a safety boundary)
- `harness_ask` is NOT exposed (redundant decision layer inside an
  LLM-facing server)
- Results TRUNCATED (max 50 rows + count) — a 24-account sweep must
  not blow the client's context window
- stdout purity: handlers NEVER print (stdout is the JSON-RPC channel)
- Progress notifications on account sweeps
- MCP-origin actions audit-logged as `harness:mcp:<user>`

Client wiring:
    # pi / Claude Code:
    claude mcp add cloud-harness-cli -- harness serve-mcp
    # VSCode settings.json (agent mode):
    "mcp": {"servers": {"cloud-harness-cli":
        {"command": "harness", "args": ["serve-mcp"]}}}
"""

import asyncio
import json as _json
from typing import Any, Literal, Optional

from mcp.server.fastmcp import Context, FastMCP

# ─── constants ──────────────────────────────────────────────────

MAX_ROWS = 50          # context-window guard
MCP_AUDIT_ID = "harness:mcp"   # audit principal for MCP-origin actions

mcp = FastMCP(
    "cloud-harness-cli",
    instructions="AWS management harness: read-only AWS visibility "
                 "across accounts/businesses/regions + dry-run "
                 "simulations of safe operations. Mutations execute "
                 "via the `harness` CLI, not here.",
)

# ─── plumbing ────────────────────────────────────────────────────

async def _progress(ctx: Optional[Context], done: int, total: int) -> None:
    """Report progress, tolerating contexts without a request session
    (in-process calls/tests: 'Context is not available')."""
    if ctx is None:
        return
    try:
        await ctx.report_progress(done, total)
    except Exception:
        pass  # no request context — progress is best-effort

def _truncate(data: Any) -> Any:
    """Cap list payloads; never blow the client's context window."""
    if isinstance(data, list) and len(data) > MAX_ROWS:
        return {"rows": data[:MAX_ROWS],
                "total_count": len(data),
                "truncated": True,
                "note": f"showing {MAX_ROWS} of {len(data)} — "
                        "narrow the query or use the CLI for the full list"}
    if isinstance(data, dict):
        for k, v in list(data.items()):
            data[k] = _truncate(v)
    return data


def _sweep(collect_fn, *, account: Optional[str],
           business: Optional[str], all_accounts: bool,
           region: Optional[str] = None) -> dict:
    """One pipeline run: config → resolver → executor → PartialResult.

    Pure: prints NOTHING (stdout is the MCP protocol channel); returns
    a JSON-safe dict. Account/business come per-call — never session
    state (implicit context is a cross-account hazard).
    """
    import harness_cli.main as cli_main
    from harness_cli.main import get_ctx
    from harness_cli.runtime import (
        build_stack,
        get_runtime,
        regions_for,
        resolve_accounts,
    )
    cli_main._CTX.update({"account": account, "business": business,
                          "all_accounts": all_accounts or None,
                          "region": region})

    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        accounts = resolve_accounts(resolver, account, all_accounts)

        def per_account(sess, acct):
            if region:
                return collect_fn(sess, region)
            # per-account enabled regions (same rule as the CLI)
            regions = regions_for(acct, config, sess, store)
            out = {}
            for r in regions:
                out[r] = collect_fn(sess, r)
            return out

        result = executor.execute_across_accounts(
            accounts, per_account)
        return _result_json(result)
    finally:
        executor.shutdown()
        # restore ctx so the outer CLI state isn't polluted
        cli_main._CTX.update({"account": None, "business": None,
                              "all_accounts": None, "region": None})


def _result_json(result) -> dict:
    """PartialResult → JSON-safe dict with status + failures."""
    from harness_primitives.output import _json_safe
    data = _json.loads(_json.dumps(
        {"success": result.success,
         "failures": [f.__dict__ for f in result.failures],
         "warnings": [w.message for w in result.warnings]},
        default=_json_safe))
    data["status"] = ("all_failed" if result.failures and
                      not result.success else
                      "partial_failure" if result.failures else
                      "success")
    return _truncate(data)


# ─── horizontal tools ───────────────────────────────────────────

@mcp.tool()
def whoami() -> dict:
    """Current AWS identity + harness attribution (account, user ARN)."""
    from harness_cli.main import build_session
    session = build_session()
    ident = session.get_sts_client().get_caller_identity()
    return {"arn": ident["Arn"], "account": ident["Account"],
            "user_id": ident.get("UserId"),
            "source_identity": session.source_identity}


@mcp.tool()
def doctor() -> dict:
    """Health check: credentials, region enablement, plugins, config."""
    from harness_cli.main import build_session
    from harness_plugins.registry import PluginRegistry

    out = {}
    session = build_session()
    try:
        ident = session.get_sts_client().get_caller_identity()
        out["credentials"] = {"ok": True, "account": ident["Account"]}
        try:
            regions = session.get_enabled_regions()
            out["enabled_regions"] = {"ok": True, "count": len(regions),
                                      "sample": regions[:8]}
        except Exception as e:
            out["enabled_regions"] = {"ok": False, "error": str(e)[:120]}
    except Exception as e:
        out["credentials"] = {"ok": False, "error": str(e)[:120]}
    registry = PluginRegistry()
    registry.load()
    out["plugins"] = sorted(registry.available_plugins)
    out["warnings"] = list(registry.load_warnings)
    return out


@mcp.tool()
def list_accounts(business: Optional[str] = None) -> dict:
    """List known AWS accounts (ID, name, business, source)."""
    import harness_cli.main as cli_main
    from harness_cli.main import get_ctx
    from harness_cli.runtime import build_stack, get_runtime
    cli_main._CTX.update({"business": business})
    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        accounts = resolver.resolve_all(business=business)
        return {"accounts": [
            {"id": a.id, "name": a.name, "business": a.business,
             "status": a.status, "source": a.discovery_source}
            for a in accounts]}
    finally:
        executor.shutdown()
        cli_main._CTX.update({"business": None})


@mcp.tool()
def account_regions(account: str) -> dict:
    """Regions in scope for one account (config ∩ enabled, cached ≤24h)."""
    from harness_cli.runtime import build_stack, config_regions, get_runtime, regions_for

    config = get_runtime(None)
    store, session, resolver, executor = build_stack(config)
    try:
        acct = resolver.resolve(account)
        sess = executor.session_for(acct)
        regions = regions_for(acct, config, sess, store)
        configured = config_regions(config)
        return {"account": acct.id, "regions": regions,
                "skipped": [r for r in configured if r not in regions]}
    finally:
        executor.shutdown()


@mcp.tool()
def console_url(service: str, resource_id: Optional[str] = None,
                region: Optional[str] = None) -> dict:
    """The AWS console deep-link for a resource (navigate without the
    console: hand this URL to the human when the web UI is needed)."""
    from harness_cli.deeplinks import build_console_url
    try:
        return {"url": build_console_url(service, resource_id, region)}
    except ValueError as e:
        return {"error": str(e)}


# ─── per-service read tools (typed, no free-form params) ────────

@mcp.tool()
async def ec2_list_instances(account: Optional[str] = None,
                            business: Optional[str] = None,
                            region: Optional[str] = None,
                            all_accounts: bool = False,
                            state: Optional[Literal[
                                "running", "stopped", "pending",
                                "terminated"]] = None,
                            ctx: Context = None) -> dict:
    """List EC2 instances. state: running|stopped|pending|terminated."""
    from harness_plugins.ec2.plugin import EC2Plugin
    await _progress(ctx, 0, 1)
    result = await asyncio.to_thread(
        _sweep,
        lambda s, r: list(EC2Plugin().list_instances(s, r, state=state)),
        account=account, business=business,
        all_accounts=all_accounts, region=region)
    await _progress(ctx, 1, 1)
    return result


@mcp.tool()
def ec2_describe(instance_id: str, account: Optional[str] = None,
                 region: Optional[str] = None) -> dict:
    """One EC2 instance's details."""
    from harness_plugins.ec2.plugin import EC2Plugin
    return _sweep(lambda s, r: EC2Plugin().get_resource(
        s, instance_id, region=r) or
        {"error": f"instance {instance_id} not found in {r}"},
        account=account, business=None, all_accounts=False,
        region=region)


@mcp.tool()
def s3_list_buckets(account: Optional[str] = None,
                    business: Optional[str] = None,
                    all_accounts: bool = False) -> dict:
    """List S3 buckets."""
    from harness_plugins.s3.plugin import S3Plugin
    return _sweep(lambda s, r: list(S3Plugin().list_buckets(s)),
        account=account, business=business,
        all_accounts=all_accounts, region="us-east-1")


@mcp.tool()
def s3_bucket_info(bucket: str, account: Optional[str] = None) -> dict:
    """One S3 bucket's details (region, encryption, versioning, ACL)."""
    from harness_plugins.s3.plugin import S3Plugin
    return _sweep(lambda s, r: S3Plugin().bucket_info(s, bucket) or
        {"error": f"bucket {bucket} not found"},
        account=account, business=None, all_accounts=False,
        region="us-east-1")


@mcp.tool()
async def iam_list_users(account: Optional[str] = None,
                        business: Optional[str] = None,
                        all_accounts: bool = False,
                        ctx: Context = None) -> dict:
    """List IAM users across accounts."""
    from harness_plugins.iam.plugin import IAMPlugin
    await _progress(ctx, 0, 1)
    result = await asyncio.to_thread(
        _sweep,
        lambda s, r: list(IAMPlugin().list_users(s)),
        account=account, business=business,
        all_accounts=all_accounts)
    await _progress(ctx, 1, 1)
    return result


@mcp.tool()
def iam_find_unused(days: int = 90, account: Optional[str] = None,
                   business: Optional[str] = None,
                   all_accounts: bool = False) -> dict:
    """Access keys unused for more than N days (default 90)."""
    from harness_plugins.iam.plugin import IAMPlugin
    return _sweep(lambda s, r: IAMPlugin().find_unused(s, days=days),
        account=account, business=business, all_accounts=all_accounts)


@mcp.tool()
def iam_check_mfa(username: str, account: Optional[str] = None) -> dict:
    """MFA status for one IAM user."""
    from harness_plugins.iam.plugin import IAMPlugin
    return _sweep(lambda s, r: IAMPlugin().check_mfa(s, username),
        account=account, business=None, all_accounts=False)


@mcp.tool()
def vpc_list(account: Optional[str] = None,
             business: Optional[str] = None,
             region: Optional[str] = None,
             all_accounts: bool = False) -> dict:
    """List VPCs."""
    from harness_plugins.vpc.plugin import VPCPlugin
    return _sweep(lambda s, r: list(VPCPlugin().list_vpcs(s, r)),
        account=account, business=business, all_accounts=all_accounts,
        region=region)


@mcp.tool()
def backup_list_vaults(account: Optional[str] = None,
                       business: Optional[str] = None,
                       region: Optional[str] = None,
                       all_accounts: bool = False) -> dict:
    """List AWS Backup vaults (lock state, recovery points)."""
    from harness_plugins.backup.plugin import BackupPlugin
    return _sweep(lambda s, r: list(BackupPlugin().list_vaults(s, r)),
        account=account, business=business, all_accounts=all_accounts,
        region=region)


@mcp.tool()
def backup_list_jobs(state: Optional[Literal[
                         "COMPLETED", "FAILED", "RUNNING", "ABORTED"]] = None,
                     account: Optional[str] = None,
                     region: Optional[str] = None) -> dict:
    """List AWS Backup jobs; state: COMPLETED|FAILED|RUNNING|ABORTED."""
    from harness_plugins.backup.plugin import BackupPlugin
    valid = ("COMPLETED", "FAILED", "RUNNING", "ABORTED")
    if state and state.upper() not in valid:
        return {"error": f"state must be one of {valid}"}
    return _sweep(lambda s, r: list(BackupPlugin().list_jobs(
        s, r, state=state)),
        account=account, business=None, all_accounts=False,
        region=region)


@mcp.tool()
def cost_total(account: Optional[str] = None,
               days: int = 30) -> dict:
    """Total unblended cost for the period (CE, 0.5 TPS, cached 24h)."""
    from harness_plugins.cost.plugin import CostPlugin
    return _sweep(lambda s, r: CostPlugin().total(s, days=days),
        account=account, business=None, all_accounts=False,
        region="us-east-1")


# ─── v2 surface: the 5 previously CLI-only plugins (read-only) ───

@mcp.tool()
async def lambda_list_functions(account: Optional[str] = None,
                                business: Optional[str] = None,
                                region: Optional[str] = None,
                                all_accounts: bool = False,
                                runtime: Optional[str] = None) -> dict:
    """Lambda functions (name, runtime, handler, last modified).

    runtime: optional filter e.g. "python3.12" — None lists all.
    """
    from harness_plugins.aws_lambda.plugin import LambdaPlugin
    return await asyncio.to_thread(
        _sweep,
        lambda s, r: list(LambdaPlugin().list_functions(
            s, r, runtime=runtime)),
        account=account, business=business, all_accounts=all_accounts,
        region=region)


@mcp.tool()
async def security_guardduty_findings(
        account: Optional[str] = None,
        business: Optional[str] = None,
        region: Optional[str] = None,
        all_accounts: bool = False) -> dict:
    """GuardDuty findings summary per severity, per region (per detector)."""
    from harness_plugins.security.plugin import SecurityPlugin
    return await asyncio.to_thread(
        _sweep,
        lambda s, r: list(SecurityPlugin().guardduty_findings(s, r)),
        account=account, business=business, all_accounts=all_accounts,
        region=region)


@mcp.tool()
async def security_hub_status(
        account: Optional[str] = None,
        business: Optional[str] = None,
        region: Optional[str] = None,
        all_accounts: bool = False) -> dict:
    """Security Hub enabled status per region (no counts — hub-only)."""
    from harness_plugins.security.plugin import SecurityPlugin
    return await asyncio.to_thread(
        _sweep,
        lambda s, r: SecurityPlugin().securityhub_findings(s, r),
        account=account, business=business, all_accounts=all_accounts,
        region=region)


@mcp.tool()
def org_list_accounts(account: Optional[str] = None) -> dict:
    """LIVE AWS Organizations view: all accounts in the org (orgs API).

    Different from `list_accounts` (harness config): this is what
    AWS itself reports. Only the management account can call it —
    pass account="management" (or your management account's name/ID);
    member accounts get AccessDenied from AWS by design.
    """
    from harness_plugins.org.plugin import OrgPlugin
    return _sweep(lambda s, r: list(OrgPlugin().list_accounts(s)),
        account=account, business=None, all_accounts=False,
        region="us-east-1")


@mcp.tool()
def org_list_ous(account: Optional[str] = None) -> dict:
    """LIVE org structure: root + all organizational units, recursive.

    Management account only — pass account="management" (or its ID).
    """
    from harness_plugins.org.plugin import OrgPlugin
    return _sweep(lambda s, r: list(OrgPlugin().list_ous(s)),
        account=account, business=None, all_accounts=False,
        region="us-east-1")


@mcp.tool()
def cloudfront_list_distributions(account: Optional[str] = None,
                                  business: Optional[str] = None) -> dict:
    """CloudFront distributions (global service, per account)."""
    from harness_plugins.cloudfront.plugin import CloudFrontPlugin
    return _sweep(
        lambda s, r: list(CloudFrontPlugin().list_distributions(s)),
        account=account, business=business, all_accounts=False,
        region="us-east-1")


@mcp.tool()
def inventory_summarize(account: Optional[str] = None) -> dict:
    """Resource counts by account/region/service from the latest
    collected snapshot (LOCAL store — no AWS call).

    Reflects the last `harness inventory collect`; empty until then.
    account: optional 12-digit account ID filter (name also accepted).
    """
    import harness_cli.main as cli_main
    from harness_cli.main import get_ctx
    from harness_cli.runtime import build_stack, get_runtime
    from harness_primitives.accounts import ACCOUNT_ID_RE
    from harness_store import database

    cli_main._CTX.update({"account": account, "business": None,
                          "all_accounts": None, "region": None})
    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        account_id = account
        if account and not ACCOUNT_ID_RE.fullmatch(account):
            # accept a name too — resolve to the 12-digit ID
            account_id = None
            for a in resolver.resolve_all():
                if a.name == account:
                    account_id = a.id
                    break
        summary = database.summarize(store, account_id=account_id)
        return {"summary": summary}
    finally:
        executor.shutdown()
        cli_main._CTX.update({"account": None})


# ─── dry-run safe ops (v1: simulation only, never execution) ─────

SAFE_OPERATIONS = {
    "ec2:start": "ec2",
    "ec2:stop": "ec2",
    "cloudfront:invalidate": "cloudfront",
    "lambda:invoke": "lambda",
    "iam:rotate-keys": "iam",
    "backup:start-backup": "backup",
}


@mcp.tool()
def safe_op_dry_run(operation: Literal[
                        "ec2:start", "ec2:stop",
                        "cloudfront:invalidate", "lambda:invoke",
                        "iam:rotate-keys", "backup:start-backup"],
                    resource_id: str,
                    account: Optional[str] = None,
                    region: Optional[str] = None,
                    params: Optional[dict] = None) -> dict:
    """SIMULATE a mutating operation (dry-run; never executes).

    operation: ec2:start | ec2:stop | cloudfront:invalidate |
    lambda:invoke | iam:rotate-keys | backup:start-backup
    params: optional object for operation extras
    (e.g. {"vault": "v", "iam_role": "..."})

    Real execution happens in the `harness` CLI (`--yes`) — by design,
    an LLM-facing server cannot trigger real mutations in v1.
    """
    from harness_cli.runtime import build_stack, get_runtime, record_audit

    if operation not in SAFE_OPERATIONS:
        return {"error": f"unknown operation {operation!r}. "
                f"Valid: {sorted(SAFE_OPERATIONS)}"}
    service, _, op = operation.partition(":")
    extra = dict(params or {})

    from harness_cli.main import get_ctx
    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        acct = resolver.resolve(account)
        sess = executor.session_for(acct)
        plugin = {"ec2": "harness_plugins.ec2.plugin.EC2Plugin",
                  "cloudfront": "harness_plugins.cloudfront.plugin."
                                "CloudFrontPlugin",
                  "lambda": "harness_plugins.aws_lambda.plugin."
                            "LambdaPlugin",
                  "iam": "harness_plugins.iam.plugin.IAMPlugin",
                  "backup": "harness_plugins.backup.plugin."
                            "BackupPlugin"}[service]
        mod, cls = plugin.rsplit(".", 1)
        import importlib
        plugin_obj = getattr(importlib.import_module(mod), cls)()

        try:
            data = plugin_obj.dry_run_simulate(
                sess, op, **{"resource_id": resource_id,
                             "region": region, **extra})
        except NotImplementedError:
            # plugins with native DryRun simulate via the real call
            data = {"service": service, "operation": op,
                    "resource_id": resource_id,
                    "status": "would_execute (native DryRun in CLI)"}

        record_audit(
            config, action=f"dry-run:{op}", service=service,
            account_id=acct.id, region=region, resource_id=resource_id,
            success=True, dry_run=True,
            principal=MCP_AUDIT_ID,
            source_identity=MCP_AUDIT_ID,
        )
        return {"simulated": True, "operation": operation,
                "data": data,
                "note": "dry-run only — execute via the harness CLI"}
    finally:
        executor.shutdown()


# ─── entry point ─────────────────────────────────────────────────

def serve() -> None:
    """Run the MCP server over stdio (launched by the MCP client)."""
    # NOTHING may print to stdout here — it is the JSON-RPC channel.
    mcp.run("stdio")
