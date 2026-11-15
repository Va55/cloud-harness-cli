"""
Shared CLI runtime wiring.

Standard pipeline for every command that touches AWS:

    config → store → session → resolver → executor → run → format → exit code

Eliminates per-command boilerplate; every command gets consistent
account resolution, region handling, partial-failure semantics, and
output formatting for free.

Global flags honored here:
- --all-regions   → regions_for skips enablement detection (all configured)
- --quiet         → emit suppresses success output (errors still print)
- --verbose       → emit shows full failure messages
- --refresh       → build_stack clears the credential cache AND the
                    per-account region-enablement cache before running
"""

from pathlib import Path
from typing import Any, Optional

import typer

from harness_primitives.accounts import Account, AccountResolver
from harness_primitives.config import HarnessConfig, load_config
from harness_primitives.executor import HarnessExecutor
from harness_primitives.output import PartialResult, format_output
from harness_store import database

# Region-enablement cache TTL: a newly enabled region shows up within
# a day at most, and --refresh forces re-detection immediately.
REGION_CACHE_TTL_HOURS = 24


def get_runtime(config_path: Optional[str] = None,
                quiet: bool = False) -> HarnessConfig:
    """Load config; fail loudly (exit 2) if invalid."""
    try:
        return load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        if not quiet:
            typer.echo(f"Config error: {e}", err=True)
        raise typer.Exit(2) from e


def build_stack(config: HarnessConfig):
    """Build the full stack: store, session, resolver, executor.

    --refresh: clears the credential cache and the region-enablement
    cache (both are cross-command caches that can go stale).
    """
    from harness_cli.main import build_session, get_ctx

    store = database.connect(Path(config.inventory.sqlite_path))
    # Migrations are idempotent and cheap — running them on every
    # command makes a fresh install work without a separate init step
    database.migrate(store)
    if get_ctx().get("refresh"):
        from harness_primitives.credentials import CredentialCache
        CredentialCache().clear_all()
        database.clear_region_cache(store)
    session = build_session(config)
    resolver = AccountResolver(config, session, store)
    executor = HarnessExecutor(config)
    return store, session, resolver, executor


def resolve_accounts(resolver: AccountResolver,
                    account_arg: Optional[str],
                    all_accounts: bool) -> list[Account]:
    """Resolve the target account list per CLI flags/env/config.

    --business scopes the resolution: with --all-accounts it means
    "all accounts of that business"; with --account it disambiguates
    account names shared between businesses.

    The GLOBAL --all-accounts (before the subcommand) ORs with the
    per-command flag — a global flag must never be a silent no-op
    (same principle as the --dry-run fix, audit pass 2 #1; found live
    in pass 3: `harness --all-accounts iam list-users` swept one
    account only).
    """
    from harness_cli.main import get_ctx
    ctx = get_ctx()
    business = ctx.get("business")
    if all_accounts or ctx.get("all_accounts"):
        return resolver.resolve_all(business=business)
    return [resolver.resolve(account_arg, business=business)]


def ensure_mutable(account: Any) -> None:
    """Hard safety rail: mutating commands REFUSE on read_only accounts.

    The check lives here so every mutating command body inherits it
    with one call — a typo, a mis-routed `ask`, or an eager LLM via MCP
    all hit the same wall. Reads and dry-runs are unaffected.
    """
    if getattr(account, "read_only", False):
        from harness_primitives.failure import FailureCategory, HarnessError
        biz = f" (business '{account.business}')" if account.business else ""
        raise HarnessError(
            f"Account {account.id}{biz} is READ-ONLY — mutations are "
            f"disabled in config (accounts.*.read_only). This is a "
            f"production-safety lock; only reads and dry-runs are "
            f"permitted. To change it, the account owner must edit the "
            f"config — do not work around it.",
            FailureCategory.PERMISSION,
            account.id,
        )


def config_regions(config: HarnessConfig) -> list[str]:
    """All configured regions (North America ∪ Europe)."""
    return sorted(
        set(config.regions.north_america.members)
        | set(config.regions.europe.members)
    )


def regions_for(account: Account, config: HarnessConfig,
                session: Any, store: Any,
                detect_enabled: bool = True) -> list[str]:
    """Regions to sweep for an account.

    Precedence:
      1. --all-regions flag → all configured regions, no detection
      2. Per-account override (config manual accounts[].regions)
      3. Config accounts.defaults.regions (if set)
      4. Config regions ∩ regions actually enabled for the account
         (EC2 DescribeRegions, cached ≤24h in the store)
      5. Config regions (when detection is unavailable)

    Detection is ON by default: sweeping regions an account has not
    enabled produces a wall of OptInRequired/AuthFailure noise on every
    multi-account run.

    NOTE: `session` must be the ACCOUNT's session (cross-account
    aware), not the management session — detection describes the
    account's own enablement.
    """
    from harness_cli.main import get_ctx

    if get_ctx().get("all_regions"):
        return config_regions(config)

    if account.regions:
        return account.regions
    if config.accounts.defaults.regions:
        return config.accounts.defaults.regions

    configured = config_regions(config)
    if not detect_enabled:
        return configured

    enabled = _enabled_regions_cached(account, session, store)
    if enabled is None:
        return configured  # detection unavailable → use configured set
    usable = [r for r in configured if r in enabled]
    return usable or configured


def _enabled_regions_cached(account: Account, session: Any,
                            store: Any) -> Optional[list[str]]:
    """Enabled regions for an account, cached in the store (≤24h TTL).

    Returns None when detection is not possible (so the caller can fall
    back to the configured set rather than failing the whole sweep).
    """
    try:
        existing = database.get_account(store, account.id)
        if existing:
            import json as _json
            from datetime import datetime, timedelta, timezone
            raw = existing.get("regions_enabled")
            cached = _json.loads(raw) if isinstance(raw, str) else raw
            if cached:
                # TTL: a stale entry (older than REGION_CACHE_TTL_HOURS,
                # judged by the account's last_seen) is re-detected.
                last_seen = existing.get("last_seen")
                fresh = False
                if last_seen:
                    try:
                        seen = datetime.fromisoformat(str(last_seen))
                        if seen.tzinfo is None:
                            seen = seen.replace(tzinfo=timezone.utc)
                        fresh = (datetime.now(timezone.utc) - seen
                                 < timedelta(hours=REGION_CACHE_TTL_HOURS))
                    except (ValueError, TypeError):
                        fresh = False
                if fresh:
                    return list(cached)

        # Detection uses the account's own session (cross-account aware)
        from harness_primitives.regions import get_enabled_regions
        enabled = get_enabled_regions(session, account.id)
        database.upsert_account(
            store, account_id=account.id,
            name=account.name, ou_path=account.ou_path,
            regions_enabled=enabled,
            discovery_source=account.discovery_source,
        )
        return enabled
    except Exception:
        # Permissions/network/region-detection failure → caller falls back
        return None


def emit(result: PartialResult, output_format: str = "table") -> None:
    """Print the result and exit with the partial-failure exit code.

    Honors --quiet (suppress success output; failures still print) and
    --verbose (full failure messages).
    """
    from harness_cli.main import get_ctx
    ctx = get_ctx()
    quiet = ctx.get("quiet", False)
    verbose = ctx.get("verbose", False)

    if quiet and result.exit_code == 0:
        raise typer.Exit(0)  # success + --quiet → say nothing

    typer.echo(format_output(result, output_format, verbose=verbose))
    raise typer.Exit(result.exit_code)


def record_audit(config: HarnessConfig, *, action: str, service: str,
                 account_id: str = "unknown", region: Optional[str] = None,
                 resource_id: Optional[str] = None, success: bool = True,
                 error_message: Optional[str] = None,
                 dry_run: bool = False, principal: Optional[str] = None,
                 source_identity: Optional[str] = None) -> None:
    """Append a mutating action to the local audit trail.

    Called by every mutating command (ec2 start/stop, iam rotate-keys,
    cloudfront invalidate) — the team's "who did what" record. Failures
    to WRITE the audit record must never fail the operation: best-effort
    with a stderr warning.
    """
    try:
        conn = database.connect(Path(config.audit.sqlite_path))
        database.migrate(conn)  # idempotent; audit DB may not exist yet
        database.record_audit_event(
            conn,
            principal=principal or "unknown",
            source_identity=source_identity or principal or "unknown",
            account_id=account_id,
            region=region,
            service=service,
            action=action,
            resource_id=resource_id,
            success=success,
            error_message=error_message,
            dry_run=dry_run,
        )
    except Exception as e:
        typer.echo(f"[WARN] Could not write audit event: {e}", err=True)
