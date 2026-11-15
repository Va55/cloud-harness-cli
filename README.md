# AWS Management Harness

Multi-account, multi-region AWS read and audit surface for a single
operator. Written in Python/boto3 and CLI first; the same capability
set is exposed as **24 typed MCP tools** for use from an AI client.

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

## Use as an MCP server

One stdio server. No listener, no daemon, no port, no credentials in
transit — the client spawns it as a child process.

```bash
pip install -e . --break-system-packages     # or: pipx install .
harness doctor                               # credentials, regions, plugins
harness serve-mcp                            # JSON-RPC on stdio
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

### Tool surface

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

- **Read and simulate only.** Execution of changes happens in the CLI,
  behind `--yes`. There is no MCP path to a real mutation.
- **`read_only` is enforced once, in code** (`ensure_mutable`), before
  any API call, and exits 2. Business- and account-level, with account
  overriding business.
- **Result sets are capped at 50 rows** so a sweep cannot consume a
  model's context.
- **Every action is attributable**: MCP calls are recorded in the audit
  trail as `harness:mcp`; CloudTrail sees the session as
  `harness-<operator>`.
- **Least privilege and ExternalId** on every AssumeRole — no
  confused-deputy exposure. Policies are in
  [docs/harness-needed_aws-roles.md](docs/harness-needed_aws-roles.md).

### What it is not

- Not a provisioning tool. No creates, no deletes, no drift management.
- Not a multi-user service. One operator, one machine, per-account
  credentials.
- Not a replacement for the console. It covers the routine questions —
  what exists, what it costs, what is exposed — not every edge case.

---

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

## Quick Start

```bash
# Install
pip install -e .

# Configure AWS credentials (CLI profiles)
aws configure --profile prod
aws sso login --profile staging  # if using IAM Identity Center

# Initialize database
harness init-db

# Check health
harness doctor

# List accounts
harness account list

# Collect inventory
harness inventory collect --account production --all-regions --output json

# View cost
harness cost explorer --start 2025-01-01 --end 2025-01-31 --account production
```

## Configuration

Config file: `~/.config/aws-harness/config.yaml`

See [`docs/aws-reference.md`](docs/aws-reference.md) for full AWS service reference.
See [`docs/architecture.md`](docs/architecture.md) for architecture details.

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

Out of scope by design: provisioning, deletion, drift management (Terraform/CDK), and anything requiring a persistent daemon.

## Credential handling

- No credentials in configuration files — profiles, SSO or AssumeRole
  only.
- Derived credentials are cached atomically at mode 0600, in a 0700
  directory, written with `O_EXCL` and no symlink following.
- Secrets are never written to stdout or logs; rotation writes the new
  key to a 0600 file and prints the path.
- Per-account, per-region, per-API rate limiting (Cost Explorer is
  serialized at 0.5 TPS).

## License

MIT

## Documentation

See **docs/user-manual.md** — the user manual, and **docs/production-rollout-plan.md** — the plan to present for production-access approval.
For MCP clients: **docs/mcp-clients.md** — copy-paste setup for Pi, Hermes, Claude Code and VS Code (24 tools over stdio).
For AWS-side setup: **docs/harness-needed_aws-roles.md** — every role/user/permission the harness needs, with worked policy examples (read-only, cross-account trust + ExternalId, safe ops, the production double-lock).
