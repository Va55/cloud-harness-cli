"""
`harness ask` — Tier 1 NL router (architecture §13.2).

Natural language → an EXISTING harness command. No agent loop, no LLM:
deterministic structured parsing. The router can only pick commands
that exist in the live CLI registry (introspected at runtime) — there
is no hallucination surface by construction.

    $ harness ask "show unused iam keys in prod"
    → harness iam find-unused --account prod

Safety model (§13.3):
- Read-only routes execute directly
- Mutating routes (start/stop/invalidate/rotate-keys/invoke) get
  --dry-run appended automatically; `--yes` executes for real
- Any command with a required argument that the query doesn't provide
  is refused with guidance, never guessed

Transparency: the resolved command is echoed to stderr before
execution (stdout stays pure data).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import typer

# ─── Language tables ─────────────────────────────────────────────
# Kept small and curated; the command LIST itself is introspected
# from the real app (see build_catalog) — only the synonyms live here.

SERVICE_ALIASES = {
    "ec2": {"ec2", "instances", "instance", "vms", "vm", "machines",
            "compute", "servers"},
    "iam": {"iam", "users", "user", "keys", "key", "roles", "role",
            "mfa", "identity"},
    "s3": {"s3", "buckets", "bucket", "storage", "objects"},
    "lambda": {"lambda", "functions", "function", "lambdas"},
    "cloudfront": {"cloudfront", "cdn", "distributions",
                   "distribution", "cache", "caches"},
    "vpc": {"vpc", "vpcs", "subnets", "subnet", "route-tables",
            "route", "networking", "nacls", "nat", "gateways",
            "endpoints", "flow", "flow-logs"},
    "backup": {"backup", "backups", "vault", "vaults", "recovery",
               "recovery-points", "snapshots"},
    "org": {"org", "organizations", "organisation", "ous"},
    "cost": {"cost", "costs", "spend", "spending", "billing", "bill",
             "much", "expensive", "price", "prices"},
    "security": {"security", "guardduty", "findings", "hub",
                 "securityhub", "threats"},
    "inventory": {"inventory", "resources", "search"},
    "account": {"account", "accounts", "businesses", "business",
                "regions"},
}

# Command keyword hints (beyond the command's own name tokens).
COMMAND_KEYWORDS = {
    ("ec2", "list-instances"): ["list", "show", "instances", "all"],
    ("ec2", "describe"): ["describe", "details", "info", "about"],
    ("ec2", "start"): ["start", "boot", "power", "up", "turn"],
    ("ec2", "stop"): ["stop", "shutdown", "halt", "down", "power"],
    ("ec2", "security-groups"): ["security-groups", "sgs", "firewall"],
    ("ec2", "audit"): ["audit", "public", "exposed", "open"],
    ("iam", "list-users"): ["list", "show", "who"],
    ("iam", "list-roles"): ["roles"],
    ("iam", "list-access-keys"): ["access-keys", "access"],
    ("iam", "check-mfa"): ["mfa", "check"],
    ("iam", "rotate-keys"): ["rotate", "rotate", "new", "change",
                              "refresh"],
    ("iam", "find-unused"): ["unused", "stale", "idle", "old"],
    ("iam", "audit"): ["audit", "mfa", "compliance"],
    ("s3", "list-buckets"): ["list", "show", "buckets"],
    ("s3", "bucket-info"): ["info", "details", "about"],
    ("s3", "public-check"): ["public", "exposed", "open", "check"],
    ("s3", "audit"): ["audit", "compliance"],
    ("cloudfront", "list-distributions"): ["list", "show",
                                           "distributions"],
    ("cloudfront", "invalidate"): ["invalidate", "clear", "purge",
                                   "refresh", "flush"],
    ("lambda", "list-functions"): ["list", "show", "functions"],
    ("lambda", "invoke"): ["invoke", "run", "call", "execute",
                           "trigger"],
    ("vpc", "list"): ["list", "show", "vpcs"],
    ("vpc", "subnets"): ["subnets"],
    ("vpc", "route-tables"): ["route", "tables"],
    ("vpc", "describe"): ["describe", "details", "deep", "info"],
    ("vpc", "internet-gateways"): ["internet", "igws", "igw"],
    ("vpc", "nat-gateways"): ["nat", "nat-gateways"],
    ("vpc", "nacls"): ["nacls", "acl", "acls"],
    ("vpc", "endpoints"): ["endpoints", "vpc-endpoints"],
    ("vpc", "flow-logs"): ["flow", "flow-logs", "logs", "logging"],
    ("backup", "list-vaults"): ["vaults", "vault", "list", "show"],
    ("backup", "list-plans"): ["plans", "plan"],
    ("backup", "list-recovery-points"): ["recovery", "points", "restore",
                                         "point"],
    ("backup", "list-jobs"): ["jobs", "job", "failed", "status"],
    ("backup", "audit"): ["audit", "failed", "compliance", "health"],
    ("backup", "start-backup"): ["start", "run", "trigger", "on-demand",
                                 "backup", "now"],
    ("org", "list-accounts"): ["list", "show", "accounts"],
    ("org", "list-ous"): ["ous", "units", "structure", "tree"],
    ("cost", "by-service"): ["service", "services", "breakdown",
                             "per"],
    ("cost", "total"): ["total", "overall", "sum", "how", "much"],
    ("security", "guardduty"): ["guardduty", "threats", "findings"],
    ("security", "hub"): ["hub", "securityhub"],
    ("inventory", "collect"): ["collect", "gather", "snapshot",
                               "refresh", "scan"],
    ("inventory", "summarize"): ["summary", "summarize", "overview",
                                 "count", "counts"],
    ("inventory", "show"): ["show", "display", "what"],
    ("inventory", "search"): ["search", "find", "where"],
    ("inventory", "export"): ["export", "dump", "csv"],
    ("account", "list"): ["list", "show", "which", "what"],
    ("account", "show"): ["show", "details", "info"],
    ("account", "regions"): ["regions", "enabled", "opted",
                              "which"],
    ("account", "assume"): ["assume", "credentials", "creds",
                            "export", "switch"],
}

# The command used when a service matched but no specific command did.
DEFAULT_COMMAND = {
    "ec2": "list-instances", "iam": "list-users",
    "s3": "list-buckets", "cloudfront": "list-distributions",
    "lambda": "list-functions", "vpc": "list",
    "org": "list-accounts", "cost": "total",
    "security": "guardduty", "inventory": "summarize",
    "account": "list", "backup": "list-vaults",
}

MUTATING = {("ec2", "start"), ("ec2", "stop"),
            ("cloudfront", "invalidate"), ("lambda", "invoke"),
            ("iam", "rotate-keys"), ("backup", "start-backup")}

# Commands supporting --all-accounts / --all-regions / --state
SUPPORTS_ALL_ACCOUNTS = {
    ("ec2", "list-instances"), ("ec2", "audit"),
    ("iam", "list-users"), ("iam", "list-roles"),
    ("iam", "find-unused"), ("iam", "audit"),
    ("cloudfront", "list-distributions"),
    ("lambda", "list-functions"), ("vpc", "list"),
    ("org", "list-accounts"), ("inventory", "collect"),
    ("security", "guardduty"), ("security", "hub"),
    ("backup", "list-vaults"), ("backup", "list-plans"),
    ("backup", "audit"),
}

# Commands with a required positional argument (never guessed).
NEEDS_ARG = {"ec2": {"describe": None, "start": "instance_id",
                     "stop": "instance_id"},
             "backup": {"start-backup": "resource ARN "
                                       "(plus --vault and --iam-role)"},
             "s3": {"bucket-info": "bucket", "public-check": "bucket"},
             "cloudfront": {"invalidate": "distribution_id"},
             "lambda": {"invoke": "function_name"},
             "iam": {"rotate-keys": "username",
                     "list-access-keys": "username",
                     "check-mfa": "username"}}

REGION_RE = re.compile(r"\b((?:us|eu|ap|ca|sa|af|me|il)-[a-z]+-\d)\b")
INSTANCE_RE = re.compile(r"\b(i-[0-9a-f]{8,17})\b", re.IGNORECASE)
DIST_RE = re.compile(r"\b(E[A-Z0-9]{13})\b")
ACCOUNT_ID_RE = re.compile(r"\b(\d{12})\b")
ARN_RE = re.compile(
    r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[\w:/*+-]+")

ALL_ACCOUNTS_PHRASES = ["all accounts", "every account",
                        "all the accounts", "across accounts",
                        "everywhere"]
ALL_REGIONS_PHRASES = ["all regions", "every region", "all the regions"]
DRY_RUN_PHRASES = ["dry run", "dry-run", "dryrun", "simulate",
                   "what if", "what-if"]
JSON_PHRASES = ["as json", "in json", "json output", "to json"]


@dataclass
class RouteResult:
    """A routed command. argv[0:2] is guaranteed to exist in the live
    CLI registry — route() cannot produce anything else."""
    service: str
    command: str
    argv: list[str] = field(default_factory=list)
    mutating: bool = False
    dry_run: bool = False            # --dry-run appended (auto or asked)
    missing_arg: Optional[str] = None  # required arg not in the query
    reason: str = ""

    @property
    def display(self) -> str:
        return "harness " + " ".join(self.argv)


def _build_catalog() -> dict[str, set[str]]:
    """Introspect the REAL command registry: {service: {commands}}.

    This is the anti-hallucination guarantee: route() verifies its
    output against this catalog before returning.
    """
    from harness_cli.main import app
    catalog: dict[str, set[str]] = {}
    for grp in app.registered_groups:
        sub = grp.typer_instance
        catalog[grp.name] = {
            c.name or c.callback.__name__.replace("_", "-")
            for c in sub.registered_commands
        }
    return catalog


def _tokens(query: str) -> list[str]:
    return re.findall(r"[a-z0-9-]+", query.lower())


def route(query: str) -> RouteResult:
    """Map natural language to a real harness command. Deterministic."""
    work = f" {query.lower()} "

    # ── Global modifiers ────────────────────────────────────────
    all_accounts = any(p in work for p in ALL_ACCOUNTS_PHRASES)
    all_regions = any(p in work for p in ALL_REGIONS_PHRASES)
    wants_json = any(p in work for p in JSON_PHRASES)
    for p in ALL_ACCOUNTS_PHRASES + ALL_REGIONS_PHRASES + \
            JSON_PHRASES:
        work = work.replace(p, " ")

    asked_dry_run = any(p in work for p in DRY_RUN_PHRASES)
    for p in DRY_RUN_PHRASES:
        work = work.replace(p, " ")

    # ── ARNs: strip BEFORE service detection (an ARN like
    #    arn:aws:ec2:…:instance/i-x contains 'ec2' and 'instance' —
    #    they must not steal the service from 'start a BACKUP') ────
    arn_tokens = ARN_RE.findall(work)
    work = ARN_RE.sub(" ", work)

    # ── Region ───────────────────────────────────────────────────
    region = None
    m = REGION_RE.search(work)
    if m:
        region = m.group(1)
        work = work.replace(region, " ")

    # ── Account ID (12 digits) ───────────────────────────────────
    account = None
    m = ACCOUNT_ID_RE.search(work)
    if m:
        account = m.group(1)
        work = work.replace(account, " ", 1)

    # ── Fixed commands (no service needed) ───────────────────────
    toks = _tokens(work)
    if "whoami" in toks or ("who" in toks and ("am" in toks
                                              or "is" in toks)):
        return RouteResult("whoami", "whoami",
                           _argv(["whoami"], account, None, region,
                                 False, False, wants_json))
    if "doctor" in toks or ("health" in toks and "check" in toks):
        return RouteResult("doctor", "doctor",
                           _argv(["doctor"], account, None, region,
                                 False, False, wants_json))
    if "plugins" in toks and ("what" in toks or "list" in toks
                              or "which" in toks or "show" in toks):
        return RouteResult("plugins", "plugins",
                           _argv(["plugins"], account, None, region,
                                  False, False, wants_json))

    # ── Service detection ───────────────────────────────────────
    catalog = _build_catalog()
    service, score = None, 0
    for svc, aliases in SERVICE_ALIASES.items():
        # The canonical name (first alias) outweighs incidental tokens:
        # 'start a backup of arn:…:instance/i-x' must be backup, not ec2
        # ('instance' inside the ARN must not steal the service).
        hits = len(aliases & set(toks))
        if svc in set(toks):
            hits += 1
        if svc in catalog and hits > score:
            service, score = svc, hits
    if service is None:
        raise ValueError(
            f"Couldn't find a service in: {query!r}. "
            "Try naming one: " + ", ".join(sorted(catalog)) + ". "
            "Examples: 'list ec2 instances in prod', "
            "'show unused iam keys', 'iam list-users --account dev'.")

    # ── Command detection ────────────────────────────────────────
    command, cscore = None, 0
    for (svc, cmd), kws in COMMAND_KEYWORDS.items():
        if svc != service or cmd not in catalog[service]:
            continue
        # Keyword hits weigh double; the command's own name tokens
        # weigh double too (what the user would type at the CLI).
        hits = 2 * len(set(kws) & set(toks))
        hits += 2 * len(set(_tokens(cmd.replace("-", " "))) & set(toks))
        if hits > cscore:
            command, cscore = cmd, hits
    if command is None or cscore == 0:
        command = DEFAULT_COMMAND.get(service)
        if command is None or command not in catalog[service]:
            raise ValueError(
                f"No commands found for service {service!r}.")

    # ── Positional arguments (BEFORE account phrases, so
    #    'rotate keys for alice' isn't read as --account alice) ──
    positionals: list[str] = []
    needs = NEEDS_ARG.get(service, {}).get(command)

    if (service, command) in {("ec2", "describe"), ("ec2", "start"),
                              ("ec2", "stop")}:
        m = INSTANCE_RE.search(work)
        if m:
            positionals.append(m.group(1).lower())
            work = work.replace(m.group(1), " ")
            needs = None
    elif (service, command) == ("cloudfront", "invalidate"):
        # Case-insensitive on the ORIGINAL query (IDs are uppercase;
        # the working copy is lowercased)
        m = re.search(r"\b([eE][A-Za-z0-9]{13})\b", query)
        if m:
            positionals.append(m.group(1).upper())
            work = work.replace(m.group(1).lower(), " ")
            needs = None
    elif (service, command) == ("lambda", "invoke"):
        m = re.search(r"\bfunction\s+([\w.-]+)", work) or \
            re.search(r"\binvoke\s+([\w.-]+)", work)
        if m:
            positionals.append(m.group(1))
            work = work[:m.start()] + " " + work[m.end():]
            needs = None
    elif needs == "username":
        m = (re.search(r"\buser\s+([\w.+=@-]+)", work)
             or re.search(r"\bkeys?\s+(?:for|of)\s+([\w.+=@-]+)", work)
             or re.search(r"\brotate\s+([\w.+=@-]+?)(?:'s)?\s+key", work)
             or re.search(r"\b(?:for|of)\s+([\w.+=@-]+?)"
                          r"(?:'s)?\s+(?:access\s+)?keys", work))
        if m and m.group(1) not in ("my", "the", "our", "his", "her",
                                    "their", "all", "some"):
            positionals.append(m.group(1))
            work = work[:m.start()] + " " + work[m.end():]
            needs = None
    elif needs and "resource ARN" in needs:
        if arn_tokens:
            positionals.append(arn_tokens[0])
            needs = None
    elif needs == "bucket":
        m = re.search(r"\bbucket\s+([a-z0-9][\w.-]*)", work) or \
            re.search(r"\b(?:bucket-info|public-check)\s+([\w.-]+)",
                      work)
        if m and m.group(1) not in ("info", "details", "about", "names",
                                    "list", "all", "every", "the"):
            positionals.append(m.group(1))
            work = work[:m.start()] + " " + work[m.end():]
            needs = None

    # ── Business / account phrases (from what's LEFT) ────────────
    business = None
    biz_m = re.search(
        r"\b(?:in|for|on)\s+(?:the\s+)?([\w][\w-]*)\s+business"
        r"(?:\s+(\w+))?", work)
    if biz_m:
        business = biz_m.group(2) or biz_m.group(1)
        work = work[:biz_m.start()] + " " + work[biz_m.end():]
    else:
        m = re.search(r"\bbusiness\s+([\w][\w-]*)\b", work)
        if m:
            business = m.group(1)
            work = work[:m.start()] + " " + work[m.end():]

    if not account:
        m = re.search(r"\b(?:in|for|on|under)\s+(?:the\s+)?"
                      r"(?:account\s+)?([a-z0-9][\w.-]*)", work)
        if m:
            candidate = m.group(1)
            if candidate not in ("the", "all", "this", "that", "every",
                                 "each", "my", "our", "user", "total",
                                 "sum", "summary", "business", "region"):
                account = candidate
                work = work[:m.start()] + " " + work[m.end():]

    # ── Backup job state filter (backup list-jobs) ────────────
    backup_state = None
    if (service, command) == ("backup", "list-jobs"):
        if re.search(r"\b(failed|failing|broken)\b", work):
            backup_state = "FAILED"
        elif re.search(r"\b(running|active|in-progress)\b", work):
            backup_state = "RUNNING"
        elif re.search(r"\b(aborted|cancelled|canceled)\b", work):
            backup_state = "ABORTED"

    # ── Instance state filter (ec2 list-instances) ──────────────
    state = None
    if (service, command) == ("ec2", "list-instances"):
        if re.search(r"\bstopped\b", work):
            state = "stopped"
        elif re.search(r"\bterminated\b", work):
            state = "terminated"
        elif "running" in toks:
            state = "running"

    mutating = (service, command) in MUTATING
    dry_run = mutating or asked_dry_run  # safety: mutations simulate

    argv = _argv([service, command] + positionals,
                 account, business, region,
                 all_accounts and (service, command)
                 in SUPPORTS_ALL_ACCOUNTS,
                 all_regions, wants_json, state=state)
    if backup_state:
        argv += ["--state", backup_state]
    if mutating and command in {"start", "stop", "invalidate", "invoke",
                                "rotate-keys", "start-backup"}:
        argv.append("--dry-run")

    result = RouteResult(service, command, argv, mutating=mutating,
                         dry_run=dry_run, missing_arg=needs)
    # Anti-hallucination: verify against the LIVE registry
    assert service in catalog and command in catalog[service], \
        f"routed to non-existent command: {service} {command}"
    return result


def _argv(cmd: list[str], account: Optional[str],
          business: Optional[str], region: Optional[str],
          all_accounts: bool, all_regions: bool,
          wants_json: bool, state: Optional[str] = None) -> list[str]:
    """Assemble the final command argv with context flags.

    Flag placement matters:
    - GLOBAL flags (--business, --all-regions, --output) must precede
      the service name — the service subcommands don't define them
    - Per-command flags (--account, --region, --state,
      --all-accounts) go after the command, where the subcommand
      defines them
    """
    global_flags: list[str] = []
    per_cmd = list(cmd)

    if business:
        global_flags += ["--business", business]
    if all_regions:
        global_flags.append("--all-regions")
    if wants_json:
        global_flags += ["--output", "json"]

    if account and per_cmd[0] not in ("whoami", "doctor",
                                      "plugins", "account"):
        # `account` subcommands define their own --account; for
        # fixed commands it makes no sense
        per_cmd += ["--account", account]
    elif account and per_cmd[0] == "account" and per_cmd[1] != "list":
        per_cmd += ["--account", account]
    if region and per_cmd[0] not in ("whoami", "doctor", "plugins",
                                     "account"):
        per_cmd += ["--region", region]
    if state:
        per_cmd += ["--state", state]
    if all_accounts:
        per_cmd.append("--all-accounts")

    return global_flags + per_cmd


def _global_flags_from_ctx() -> list[str]:
    """Round-trip the current global context through the CLI, so a
    nested app() invocation doesn't lose --business/--profile/etc."""
    from harness_cli.main import get_ctx
    ctx = get_ctx()
    flags: list[str] = []
    bool_flags = ("all-accounts", "all-regions", "dry-run", "verbose",
                  "quiet", "refresh")
    val_flags = ("profile", "account", "business", "role",
                 "external-id", "region", "output", "config")
    for name in bool_flags:
        if ctx.get(name):
            flags.append(f"--{name}")
    for name in val_flags:
        if ctx.get(name):
            flags += [f"--{name}", str(ctx[name])]
    return flags


def execute_route(route_result: RouteResult) -> None:
    """Run the routed command through the real CLI app."""
    import click

    from harness_cli.main import app
    argv = _global_flags_from_ctx() + route_result.argv
    typer.echo(f"→ harness {' '.join(route_result.argv)}", err=True)
    try:
        rv = app(argv, standalone_mode=False)
    except click.exceptions.Exit as e:
        raise typer.Exit(e.exit_code) from e
    except click.exceptions.UsageError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(2) from e
    # standalone_mode=False makes click RETURN the exit code instead
    # of raising Exit — a routed failure (exit 2) must not become 0.
    if isinstance(rv, int) and rv != 0:
        raise typer.Exit(rv)


def ask_command(
    query: Optional[str] = typer.Argument(None,
                                         help='e.g. "show unused iam '
                                               'keys in prod"'),
    yes: bool = typer.Option(False, "--yes",
                             help="Execute mutating commands for real "
                                  "(instead of the automatic --dry-run)"),
    show_catalog: bool = typer.Option(False, "--catalog",
                                      help="List routable commands "
                                           "and exit"),
):
    """Ask in natural language — routes to a real harness command.

    Deterministic router (no LLM): it can only pick commands that
    exist. Mutating commands always run with --dry-run unless
    --yes is given.
    """
    if show_catalog:
        catalog = _build_catalog()
        for svc in sorted(catalog):
            typer.echo(f"{svc}: {', '.join(sorted(catalog[svc]))}")
        raise typer.Exit(0)

    if not query:
        typer.echo("Provide a question, e.g. "
                   "harness ask \"show unused iam keys in prod\" "
                   "(or --catalog to list routable commands).",
                   err=True)
        raise typer.Exit(2)

    try:
        result = route(query)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e

    if result.missing_arg:
        typer.echo(
            f"I know what you mean ({result.display}) but the command "
            f"needs a {result.missing_arg} and I couldn't find one in "
            f"your question. Be explicit, e.g. add the instance ID, "
            "bucket name, username, or function name.",
            err=True,
        )
        typer.echo(f"→ {result.display} <{result.missing_arg}>", err=True)
        raise typer.Exit(2)

    if result.mutating and result.dry_run and not yes:
        # Mutations default to dry-run (safety model §13.3). --dry-run
        # is already in argv; tell the user what a real run looks like.
        real = [a for a in result.argv if a != "--dry-run"] + ["--yes"]
        typer.echo(
            "[dry-run] Mutating command — simulating. "
            f"Real run: harness {' '.join(real)}",
            err=True,
        )
    elif result.mutating and yes:
        # Safe ops dry-run by DEFAULT now — --yes must be passed
        # through, not merely --dry-run stripped, or the routed
        # command would silently simulate.
        result.argv = ([a for a in result.argv if a != "--dry-run"]
                       + ["--yes"])
        typer.echo("[--yes] Executing mutating command for real.",
                   err=True)

    execute_route(result)
