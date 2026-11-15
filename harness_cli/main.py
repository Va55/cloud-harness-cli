"""
AWS Harness CLI — Main Entry Point

Usage:
    harness [global-options] <command> [subcommand] [options]

Global options:
    --profile PROFILE       AWS CLI profile (default: config or 'default')
    --account ACCOUNT_ID    AWS account ID, name, or OU path
    --business NAME         Scope to one business (its accounts + credentials)
    --role ROLE_ARN         Assume this role before executing (overrides
                            config for every account in the run)
    --external-id ID        External ID for cross-account security
    --region REGION         Override target region
    --all-regions           Sweep ALL configured regions (skip enablement
                            detection)
    --all-accounts          Execute across all discovered accounts
    --output FORMAT         json|table|yaml|text (default: table)
    --dry-run               Simulate mutating commands without executing
                            (refused with an error where not supported)
    --verbose, -v           Verbose output (full failure messages)
    --quiet, -q             Suppress success output (errors still print)
    --config PATH           Custom config file path
    --refresh               Clear credential + region-enablement caches
"""

import os
import re
from typing import Optional

import typer

from harness_primitives.failure import HarnessError

app = typer.Typer(
    name="harness",
    help="Multi-account AWS management harness",
    add_completion=False,
    no_args_is_help=True,
)

# ─── Global context ────────────────────────────────────────────
# Populated by the @app.callback() below, read by subcommands via get_ctx().

_CTX: dict = {}


def get_ctx() -> dict:
    """Get the parsed global options (set by the app callback)."""
    return dict(_CTX)


def _validate_account(value: Optional[str]) -> Optional[str]:
    """Validate --account: accepts 12-digit ID, name, or OU path.

    - 12-digit numeric string → account ID
    - ou-xxxx/... or starts with 'ou-' → OU path
    - anything else → treated as an account *name* (resolved later
      against the Organizations account map); must be a reasonable
      identifier. A *numeric* string that isn't 12 digits is always
      an error — nobody names accounts '12345'.
    """
    if value is None:
        return value
    if re.fullmatch(r"\d{12}", value):
        return value
    if value.startswith("ou-"):
        return value
    # Numeric but wrong length — always a malformed account ID
    if value.isdigit():
        raise typer.BadParameter(
            f"Account ID must be exactly 12 digits, got {len(value)}: '{value}'"
        )
    if re.fullmatch(r"[\w][\w.-]*", value) and len(value) <= 100:
        return value  # account name — resolved at execution time
    raise typer.BadParameter(
        f"Invalid account: '{value}'. Use a 12-digit ID, an OU path "
        f"(ou-xxxx/...), or an account name (letters/digits/dash/dot)."
    )


@app.callback()
def main_callback(
    ctx: typer.Context,
    profile: Optional[str] = typer.Option(
        None, "--profile", help="AWS CLI profile (default: config or 'default')"),
    account: Optional[str] = typer.Option(
        None, "--account", callback=_validate_account,
        help="AWS account ID (12 digits), name, or OU path (ou-...)"),
    business: Optional[str] = typer.Option(
        None, "--business",
        help="Scope to one business (its accounts + credentials)"),
    role: Optional[str] = typer.Option(
        None, "--role", help="Assume this role ARN before executing"),
    external_id: Optional[str] = typer.Option(
        None, "--external-id", help="External ID for cross-account security"),
    region: Optional[str] = typer.Option(
        None, "--region", help="Override target region"),
    all_regions: bool = typer.Option(
        False, "--all-regions", help="Execute across all enabled regions"),
    all_accounts: bool = typer.Option(
        False, "--all-accounts", help="Execute across all discovered accounts"),
    output_format: str = typer.Option(
        "table", "--output", help="Output format: json|table|yaml|text"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Simulate without executing"),
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Verbose output"),
    quiet: bool = typer.Option(
        False, "-q", "--quiet", help="Suppress non-essential output"),
    config: Optional[str] = typer.Option(
        None, "--config", help="Custom config file path"),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Clear credential + region caches before running"),
):
    """AWS Management Harness — Multi-account, multi-region AWS management."""
    if output_format not in ("json", "table", "yaml", "text"):
        raise typer.BadParameter(
            f"Invalid output format: '{output_format}'. "
            "Use json|table|yaml|text."
        )
    _CTX.clear()
    _CTX.update({
        "profile": profile,
        "account": account,
        "business": business,
        "role": role,
        "external_id": external_id,
        "region": region,
        "all_regions": all_regions,
        "all_accounts": all_accounts,
        "output": output_format,
        "dry_run": dry_run,
        "verbose": verbose,
        "quiet": quiet,
        "config": config,
        "refresh": refresh,
    })
    ctx.obj = dict(_CTX)


# ─── Session helper (respects global options) ──────────────────

def build_session(config=None):
    """Build a HarnessSession from global options + config defaults.

    Profile precedence (highest first):
      1. --profile explicitly given on the command line
      2. AWS_HARNESS_PROFILE env override (applied to config at load time)
      3. config accounts.defaults.profile
      4. "default"
    """
    from harness_primitives.session import HarnessSession

    g = get_ctx()
    if g.get("refresh"):
        from harness_primitives.credentials import CredentialCache
        CredentialCache().clear_all()

    if config is None:
        try:
            from harness_primitives.config import load_config
            config = load_config(g.get("config"))
        except (FileNotFoundError, ValueError):
            config = None  # invalid config must not break --version etc.

    # --profile defaults to None so explicit use is detectable.
    cli_profile = g.get("profile")
    if cli_profile:
        profile = cli_profile
    elif config is not None:
        profile = config.accounts.defaults.profile
    else:
        profile = "default"

    # Region: explicit --region > config primary > None (session decides)
    region = g.get("region")
    if region is None and config is not None:
        region = config.regions.north_america.primary

    return HarnessSession(
        profile=profile,
        role_arn=g.get("role"),
        external_id=g.get("external_id"),
        region=region,
    )


# ─── System Commands ────────────────────────────────────────────

@app.command()
def whoami():
    """Show current identity (caller ID + session attribution)."""
    session = build_session()
    try:
        sts = session.get_sts_client()
        resp = sts.get_caller_identity()
        typer.echo(f"ARN:             {resp['Arn']}")
        typer.echo(f"Account:         {resp['Account']}")
        typer.echo(f"User:            {resp.get('UserId', 'N/A')}")
        typer.echo(f"Source identity: {session.source_identity}")
        g = get_ctx()
        if g.get("role"):
            typer.echo(f"Role (--role):   {g['role']}")
        else:
            typer.echo("Role (--role):   (none — using profile credentials)")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from e


@app.command()
def doctor(
    account: Optional[str] = typer.Option(
        None, "--account", callback=_validate_account, help="Account to check"),
):
    """Health check: credentials, region enablement, plugin availability, config."""
    checks_failed = False

    # 1. Credentials
    session = build_session()
    try:
        sts = session.get_sts_client()
        resp = sts.get_caller_identity()
        typer.echo(f"[OK]   Credentials valid (account {resp['Account']})")
    except Exception as e:
        typer.echo(f"[FAIL] Credentials: {e}")
        checks_failed = True

    # 2. Region enablement (only if credentials work)
    if not checks_failed:
        try:
            enabled = session.get_enabled_regions()
            region_str = ", ".join(enabled[:5])
            if len(enabled) > 5:
                region_str += f", ... (+{len(enabled) - 5})"
            typer.echo(f"[OK]   Enabled regions: {len(enabled)} ({region_str})")
        except Exception as e:
            typer.echo(f"[WARN] Region detection failed: {e}")

    # 3. Plugin registry
    from harness_plugins.registry import PluginRegistry
    registry = PluginRegistry()
    registry.load()
    if registry.load_warnings:
        for w in registry.load_warnings:
            typer.echo(f"[WARN] Plugin: {w}")
    typer.echo(f"[OK]   Plugins loaded: {len(registry.available_plugins)} "
               f"({', '.join(registry.available_plugins)})")

    # 4. Config file
    g = get_ctx()
    if g.get("config"):
        from pathlib import Path
        cfg = Path(g["config"]).expanduser()
        if cfg.exists():
            typer.echo(f"[OK]   Config file: {cfg}")
        else:
            typer.echo(f"[FAIL] Config file not found: {cfg}")
            checks_failed = True
    else:
        typer.echo("[OK]   Config: using defaults (no --config specified)")

    if checks_failed:
        typer.echo("\nDoctor check FAILED")
        raise typer.Exit(1)
    typer.echo("\nDoctor check passed")


@app.command()
def console(
    service: str = typer.Argument(..., help="Service: ec2|s3|iam|cloudfront|lambda|vpc"),
    resource_id: Optional[str] = typer.Argument(None, help="Resource ID (i-..., bucket, user, EY...), function name"),
    region: Optional[str] = typer.Option(None, "--region", help="Region for regional resources"),
    open_browser: bool = typer.Option(False, "--open", help="Open in browser (xdg-open)"),
):
    """Print (or open) the direct console deep-link for a resource.

    Navigate by command — never wander. Jump straight to the one
    console screen worth seeing (see MOTIVATION.md).
    """
    from harness_cli.deeplinks import build_console_url
    try:
        url = build_console_url(service, resource_id, region)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from e

    if open_browser:
        import subprocess
        try:
            if os.name == "nt":
                # Windows: the shell association API (no external binary)
                os.startfile(url)  # noqa: S606  (intended: default browser)
            else:
                subprocess.run(["xdg-open", url], check=True,
                               capture_output=True)
            typer.echo(f"Opened: {url}")
        except (subprocess.CalledProcessError, FileNotFoundError,
                OSError) as e:
            typer.echo(f"Could not open browser ({e}). URL:", err=True)
            typer.echo(url)
            raise typer.Exit(1) from e
    else:
        typer.echo(url)


@app.command()
def version():
    """Show version info."""
    import importlib.metadata
    try:
        v = importlib.metadata.version("aws-harness")
    except importlib.metadata.PackageNotFoundError:
        v = "0.1.0-dev"
    typer.echo(f"aws-harness {v}")


@app.command()
def plugins():
    """List loaded plugins and their capabilities."""
    from harness_plugins.registry import PluginRegistry
    registry = PluginRegistry()
    registry.load()
    if registry.load_warnings:
        for w in registry.load_warnings:
            typer.echo(f"[WARN] {w}", err=True)

    g = get_ctx()
    plugin_list = registry.list_plugins()
    if not plugin_list:
        typer.echo("No plugins loaded")
        raise typer.Exit(1)

    if g.get("output") == "json":
        import json
        typer.echo(json.dumps(plugin_list, indent=2))
        return

    typer.echo(f"{'Name':<15} {'Version':<10} {'Read':<6} {'SafeOps':<9} {'Global':<8}")
    typer.echo("-" * 55)
    for p in plugin_list:
        typer.echo(
            f"{p['name']:<15} {p['version']:<10} "
            f"{str(p['supports_read']):<6} {str(p['supports_safe_ops']):<9} "
            f"{str(p['is_global_service']):<8}"
        )

    warnings = registry.validate()
    for w in warnings:
        typer.echo(f"[WARN] {w}", err=True)


# ─── Plugin sub-apps ───────────────────────────────────────────
# Each plugin registers its own Typer sub-app under the main app.

# ─── NL router ─────────────────────────────────────────────────

@app.command("serve-mcp")
def serve_mcp():
    """MCP server (stdio) — expose the harness to MCP clients
    (pi, Claude Code, VSCode Copilot). See architecture §13 Tier 2."""
    from harness_cli.mcp_server import serve
    serve()


def _register_ask():
    """Register the `harness ask` NL router (architecture §13.2 Tier 1)."""
    from harness_cli.ask import ask_command
    app.command(name="ask")(ask_command)


_register_ask()


def _register_plugins():
    """Discover plugins and attach their CLI sub-apps."""
    from harness_plugins.registry import PluginRegistry
    registry = PluginRegistry()
    registry.load()
    for name in registry.available_plugins:
        plugin_cls = registry.get_plugin(name)
        try:
            plugin = plugin_cls()
            sub_app = plugin.create_app()
        except NotImplementedError:
            continue  # Plugin has no CLI commands
        except Exception as e:
            import sys
            print(f"Warning: plugin {name} CLI unavailable: {e}", file=sys.stderr)
            continue
        if sub_app is not None:
            app.add_typer(sub_app, name=name)


# ─── Account management ────────────────────────────────────────

account_app = typer.Typer(name="account", help="Account discovery and identity")
app.add_typer(account_app, name="account")


@account_app.command("list")
def account_list(
    discovery: str = typer.Option("both", "--discovery",
                                   help="both|organizations|manual"),
    include_suspended: bool = typer.Option(False, "--include-suspended"),
):
    """List known accounts (Organizations-discovered + manual config)."""
    from harness_cli.runtime import build_stack, get_runtime

    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        mode = discovery.lower()
        if mode not in ("both", "organizations", "manual"):
            typer.echo(f"Invalid --discovery: '{discovery}' "
                       "(use both|organizations|manual)", err=True)
            raise typer.Exit(2)
        if mode in ("both", "organizations"):
            try:
                # include_org=True: the flag means what it says, even when
                # config accounts.discovery is 'manual' (audit pass 2, #13)
                resolver.discover(include_org=True)
            except Exception as e:
                if mode == "organizations":
                    typer.echo(f"Discovery failed: {e}", err=True)
                    raise typer.Exit(2) from e
                typer.echo(f"[WARN] Organizations discovery failed: {e}", err=True)
                # 'both' mode: an org failure must NOT abort the manual
                # accounts (they're independent sources) — persist them.
                try:
                    resolver.discover(include_org=False)
                except Exception as e2:
                    typer.echo(f"[WARN] Manual account discovery failed: "
                               f"{e2}", err=True)

        biz = get_ctx().get("business")
        accounts = resolver.resolve_all(business=biz,
                                        include_suspended=include_suspended)
        g = get_ctx()
        if g.get("output") == "json":
            import json as _json
            typer.echo(_json.dumps([
                {"id": a.id, "name": a.name, "ou_path": a.ou_path,
                 "status": a.status, "source": a.discovery_source,
                 "business": a.business}
                for a in accounts
            ], indent=2))
        else:
            typer.echo(f"{'Account ID':<15} {'Name':<22} "
                       f"{'Business':<14} {'OU path':<22} {'Source':<15}")
            typer.echo("-" * 90)
            for a in accounts:
                typer.echo(f"{a.id:<15} {(a.name or '-'):<22} "
                           f"{(a.business or '-'):<14} "
                           f"{(a.ou_path or '-'):<22} {a.discovery_source:<15}")
            typer.echo(f"\n{len(accounts)} account(s)")
    finally:
        executor.shutdown()


@account_app.command("show")
def account_show(
    account: str = typer.Option(..., "--account", help="Account ID/name/OU path"),
):
    """Show one account's details and whether a role would be assumed."""
    from harness_cli.runtime import build_stack, get_runtime

    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        acct = resolver.resolve(account, business=get_ctx().get("business"))
        role = acct.role_arn or config.accounts.defaults.role_arn_for(acct.id)
        typer.echo(f"Account:        {acct.id}")
        typer.echo(f"Name:           {acct.name or '-'}")
        typer.echo(f"Business:       {acct.business or '-'}")
        typer.echo(f"OU path:        {acct.ou_path or '-'}")
        typer.echo(f"Status:         {acct.status}")
        typer.echo(f"Source:         {acct.discovery_source}")
        typer.echo(f"Profile:        {acct.profile or config.accounts.defaults.profile}")
        typer.echo(f"Role ARN:       {role or '(none — using profile credentials)'}")
        typer.echo(f"Cross-account:  {'yes' if role else 'no'}")
    finally:
        executor.shutdown()


@account_app.command("regions")
def account_regions(
    account: str = typer.Option(..., "--account"),
    detect: bool = typer.Option(True, "--detect/--no-detect",
                                 help="Detect enabled regions via EC2 DescribeRegions"),
):
    """Show the regions the harness will sweep for an account."""
    from harness_cli.runtime import (
        build_stack,
        config_regions,
        get_runtime,
        regions_for,
    )

    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        acct = resolver.resolve(account, business=get_ctx().get("business"))
        sess = executor.session_for(acct)
        regions = regions_for(acct, config, sess, store, detect_enabled=detect)
        configured = config_regions(config)
        typer.echo(f"Account {acct.id}: {len(regions)} region(s) in scope")
        for r in regions:
            typer.echo(f"  {r}")
        if detect and len(regions) < len(configured):
            skipped = [r for r in configured if r not in regions]
            typer.echo(f"\nSkipped (not enabled / detection unavailable): "
                       f"{', '.join(skipped)}")
    finally:
        executor.shutdown()


@account_app.command("assume")
def account_assume(
    account: str = typer.Option(..., "--account"),
    duration: int = typer.Option(3600, "--duration", help="Seconds"),
):
    """Assume the account's role and print export-ready env vars.

    Credentials are printed as shell exports for `eval $(...)` use.
    They are temporary (STS) credentials — never long-lived keys.
    """
    from harness_cli.runtime import build_stack, get_runtime

    config = get_runtime(get_ctx().get("config"))
    store, session, resolver, executor = build_stack(config)
    try:
        biz = get_ctx().get("business")
        acct = resolver.resolve(account, business=biz)
        biz_cfg = config.accounts.business(acct.business) if acct.business else None
        role = (acct.role_arn
                or (biz_cfg.role_arn_for(acct.id) if biz_cfg else None)
                or config.accounts.defaults.role_arn_for(acct.id))
        if not role:
            typer.echo(
                f"No role ARN for account {acct.id}. Configure "
                "accounts.defaults.role_arn (e.g. "
                "'arn:aws:iam::{account_id}:role/HarnessAccess') or set "
                "a per-account role in config manual accounts.",
                err=True,
            )
            raise typer.Exit(2)

        from harness_primitives.session import HarnessSession
        biz_cfg = (config.accounts.business(acct.business)
                   if acct.business else None)
        sess = HarnessSession(
            profile=acct.profile or config.accounts.defaults.profile,
            role_arn=role,
            external_id=(biz_cfg.external_id if biz_cfg
                         else config.accounts.defaults.external_id),
            session_tags=config.accounts.defaults.session_tags,
            account_id=acct.id,
            region=config.regions.north_america.primary,
        )
        try:
            creds = sess.assume_role_credentials(duration=duration)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(2) from e
        except Exception as e:
            typer.echo(f"AssumeRole failed for {role}: {e}", err=True)
            raise typer.Exit(2) from e
        typer.echo(f"export AWS_ACCESS_KEY_ID={creds['AccessKeyId']}")
        typer.echo(f"export AWS_SECRET_ACCESS_KEY={creds['SecretAccessKey']}")
        typer.echo(f"export AWS_SESSION_TOKEN={creds['SessionToken']}")
        typer.echo(f"export AWS_REGION={config.regions.north_america.primary}")
        typer.echo(f"# expires: {creds['Expiration'].isoformat()}", err=True)
        typer.echo(f"# account: {acct.id} role: {role}", err=True)
        typer.echo(f"# attribution: {sess.source_identity} "
                   f"(visible in CloudTrail)", err=True)
    finally:
        executor.shutdown()



_register_plugins()


def main():
    """Entry point for the harness CLI."""
    try:
        app()
    except HarnessError as e:
        # Clean two-line error instead of a traceback (UX debt, paid)
        typer.echo(f"Error: {e.message}", err=True)
        typer.echo(f"(category: {e.category.value}"
                   + (f", account: {e.account_id}" if e.account_id else "")
                   + ")", err=True)
        raise SystemExit(2) from e


if __name__ == "__main__":
    main()
