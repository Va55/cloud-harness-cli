# AWS Management Harness

Multi-account, multi-region AWS read and audit surface for a single
operator. Written in Python/boto3. **One capability set, two
interfaces** — a CLI you drive, and an MCP server your assistant drives.

<p>
  <img alt="python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="tests" src="https://img.shields.io/badge/tests-393%20passing-2ea44f?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square">
</p>

**Status.** Phase 1 + 2 complete and exercised against live AWS. Read
by default; write access is limited to a small set of safe operations,
dry-run first, and is refused outright for businesses marked
`read_only`. No provisioning and no deletes — that remains Terraform
or CDK territory.

**Why it exists.** Navigating the AWS console across several accounts,
businesses and regions costs more attention than the decision it
supports. This harness replaces console navigation with typed verbs
that can be scripted, audited and delegated to an assistant. See
[MOTIVATION.md](MOTIVATION.md).

```bash
pip install -e . --break-system-packages     # or: pipx install .
harness doctor                               # credentials, regions, plugins
```

## Two interfaces, one capability set

|  | **The tool — `harness`** | **The server — `harness serve-mcp`** |
|---|---|---|
| Who drives it | you: terminal, script, cron | your AI client |
| How you talk to it | commands, flags, `--output json` | 24 typed tools over JSON-RPC (stdio) |
| Additional setup | none | one registration line in the client |
| Can it change AWS | yes — safe operations, dry-run by default, `--yes` executes | **no** — read and simulate only |
| Output | tables or JSON, real exit codes | typed JSON, 50-row cap |
| Typical use | routine work, audits, scheduled checks, scripting | "what exists, what is exposed, what does it cost" in prose |

Both surfaces call the same plugin methods. The MCP surface is
deliberately the stricter subset of the CLI — see
[Safety model](#safety-model) for why.

### Tool, assistant, or both?

The harness ships no model, no prompt and no API key. Whether it acts
as a tool or as an assistant depends entirely on what you attach to it:

| Mode | Who drives it | Deterministic | Can change AWS |
|---|---|---|---|
| **Plain CLI** | you — terminal, script, cron | yes | yes (`--yes`) |
| **`harness ask "…"`** | you, in prose | **yes** — a router that can only select commands which exist, and refuses when arguments are missing | yes (`--yes`; dry-run by default) |
| **CLI + MCP client with a model** | the model, through 24 typed tools | no — the model chooses | **no** — read and dry-run only |

Attaching an MCP client that has an LLM is what turns the same tool
into an AWS assistant: prose in, tool calls out. Note the direction —
the assistant gets *fewer* permissions than the operator, not more.
`harness ask` is the no-LLM middle ground: natural language in, but a
deterministic router with no ability to invent a command.

### As a tool — the CLI

Twenty-five commands across eleven plugins. Installed above, it works
immediately:

```bash
harness doctor                                   # health: credentials, regions, plugins
harness account list                             # known accounts, all businesses
harness --business alpha account list            # one business (global flag)
harness --all-accounts iam find-unused --days 90 # one sweep, every account
harness ec2 list-instances --state stopped --region eu-north-1
harness vpc audit --account production           # IGW, NAT, NACL, flow logs
harness cost total --days 30                     # Cost Explorer
harness console ec2 i-0abc1234 --region eu-north-1   # deep link, no navigation
```

Natural language without an LLM — a deterministic router that can only
select commands which exist, and routes every mutation through
`--dry-run` first:

```bash
harness ask "show unused iam keys in prod"
#   → harness iam find-unused --account prod
```

Global flags, before or after the subcommand: `--business`,
`--account`, `--all-accounts`, `--all-regions`, `--region`,
`--output table|json`, `--dry-run`, `--quiet`, `--verbose`,
`--profile`, `--role`, `--external-id`, `--refresh`.

### As a server — MCP

The same capability set, exposed for an AI client. One stdio process —
no listener, no daemon, no port, no credentials in transit; the client
spawns it as a child process.

```bash
harness serve-mcp                                # JSON-RPC on stdio
```

Client registration — one line each:

| Client | Registration |
|---|---|
| Pi | `pi mcp add aws-harness -- harness serve-mcp` |
| Hermes | `hermes mcp add aws-harness --command harness --args serve-mcp` |
| Claude Code | `claude mcp add aws-harness -- harness serve-mcp` |
| VS Code | `{"servers":{"aws-harness":{"type":"stdio","command":"harness","args":["serve-mcp"]}}}` in `.vscode/mcp.json` |

A reasonable first exchange: *"run doctor, then whoami"*. The client
should report 24 tools. Configuration files, verification and a
troubleshooting table are in **[docs/mcp-clients.md](docs/mcp-clients.md)**.

### Tool surface (the 24 MCP tools)

| Domain | Tools |
|---|---|
| Identity and orientation | `whoami` · `doctor` · `list_accounts` · `account_regions` · `console_url` |
| Compute, storage, network | `ec2_list_instances` · `ec2_describe` · `s3_list_buckets` · `s3_bucket_info` · `vpc_list` |
| Identity hygiene | `iam_list_users` · `iam_find_unused` · `iam_check_mfa` |
| Serverless and edge | `lambda_list_functions` · `cloudfront_list_distributions` |
| Security posture | `security_guardduty_findings` · `security_hub_status` |
| Organization | `org_list_accounts` · `org_list_ous` (management account) |
| Backups, cost, inventory | `backup_list_vaults` · `backup_list_jobs` · `cost_total` · `inventory_summarize` |
| Simulation | `safe_op_dry_run` — returns the plan, performs nothing |

### Safety model

The constraint that shaped the MCP surface: **a boolean an LLM can set
is not a safety boundary**. Consequently the server is not given the
ability to mutate.

- **Read and simulate only over MCP.** Execution of changes happens in
  the CLI, behind `--yes`. There is no MCP path to a real mutation.
- **`read_only` is enforced once, in code** (`ensure_mutable`), before
  any API call, and exits 2. Business- and account-level, with account
  overriding business.
- **Result sets are capped at 50 rows** over MCP so a sweep cannot
  consume a model's context.
- **Every action is attributable**: CLI actions appear as
  `harness-<operator>` in CloudTrail, MCP calls additionally land in the
  audit trail as `harness:mcp`.
- **Least privilege and ExternalId** on every AssumeRole — no
  confused-deputy exposure. Policies are in
  [docs/harness-needed_aws-roles.md](docs/harness-needed_aws-roles.md).

### What it is not

- Not a provisioning tool. No creates, no deletes, no drift management.
- Not a multi-user service. One operator, one machine, per-account
  credentials.
- Not a replacement for the console. It covers the routine questions —
  what exists, what it costs, what is exposed — not every edge case.

## Design

- **Multi-account by construction.** Accounts come from the Organizations
  API or explicit config; nothing is inferred from the profile you
  happen to have loaded.
- **Multi-region with detection.** Region scope per account is the
  intersection of configuration and what AWS reports as enabled, cached
  for 24 hours.
- **Every action attributable.** AssumeRole carries an ExternalId and
  requests `SourceIdentity`; where the organization blocks it, the
  harness falls back to session-name attribution rather than failing.
- **Plugins, not monolith.** Eleven service plugins behind a
  capability-based interface, loaded through entry points.
- **One capability set, two surfaces.** The CLI and the MCP server call
  the same plugin methods; the MCP surface is the stricter subset.

## Configuration

`~/.config/aws-harness/config.yaml` — accounts, businesses, regions,
role ARNs, ExternalIds, `read_only` flags. Credentials never live in
this file: profiles, SSO or AssumeRole only.

```bash
harness init-db          # local store: accounts, inventory snapshots, audit trail
```

See [`docs/architecture.md`](docs/architecture.md) for internals and
[`docs/aws-reference.md`](docs/aws-reference.md) for the AWS service
reference.

## Capability matrix

| Service | Read | Safe operation |
|---|---|---|
| IAM | users, keys, MFA, policies | access-key rotation |
| EC2 | instances, images | start / stop |
| S3 | buckets, encryption, policy, ACL, PAB | — |
| CloudFront | distributions | cache invalidation |
| Lambda | functions, configuration | invocation |
| VPC | VPCs, subnets, IGW/NAT, NACLs, routes, endpoints, flow logs | — |
| Organizations | accounts, roots, OUs (management account) | — |
| Cost Explorer | totals, per service | — |
| Security | GuardDuty findings, Security Hub status | — |
| Backup | vaults, plans, recovery points, jobs | start backup job |
| Inventory | collected snapshots, diffs, search | — |

Read paths are safe to run anywhere. Safe operations default to
`--dry-run`; `--yes` executes, and `read_only` businesses refuse them.

Out of scope by design: provisioning, deletion, drift management
(Terraform/CDK), and anything requiring a persistent daemon.

## Credential handling

- No credentials in configuration files — profiles, SSO or AssumeRole
  only.
- Derived credentials are cached atomically at mode 0600, in a 0700
  directory, written with `O_EXCL` and no symlink following.
- Secrets are never written to stdout or logs; rotation writes the new
  key to a 0600 file and prints the path.
- Per-account, per-region, per-API rate limiting (Cost Explorer is
  serialized at 0.5 TPS).

## Documentation

| Document | For |
|---|---|
| [docs/user-manual.md](docs/user-manual.md) | every command, with live-verified output |
| [docs/mcp-clients.md](docs/mcp-clients.md) | wiring Pi, Hermes, Claude Code, VS Code |
| [docs/ai-interface-guide.md](docs/ai-interface-guide.md) | which interface, which model, data governance |
| [docs/harness-needed_aws-roles.md](docs/harness-needed_aws-roles.md) | IAM policies for each plugin, worked examples |
| [docs/production-rollout-plan.md](docs/production-rollout-plan.md) | what to present for production access |
| [docs/architecture.md](docs/architecture.md) | internals, decisions, trade-offs |
| [MOTIVATION.md](MOTIVATION.md) | why this exists |

## License

MIT
