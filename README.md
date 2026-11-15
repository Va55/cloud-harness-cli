# AWS Management Harness

<p align="center">
  <img alt="MCP server" src="https://img.shields.io/badge/MCP%20server-stdio-8A2BE2?style=for-the-badge">
  <img alt="24 tools" src="https://img.shields.io/badge/tools-24-1f6feb?style=for-the-badge">
  <img alt="read-only" src="https://img.shields.io/badge/mode-read--only%20%2B%20dry--run-2ea44f?style=for-the-badge">
  <img alt="tests" src="https://img.shields.io/badge/tests-393%20passing-brightgreen?style=for-the-badge">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-lightgrey?style=for-the-badge">
</p>

<p align="center"><b>Many AWS accounts. One operator. Zero console geography.</b><br>
A CLI first — and <b>24 typed tools your AI client can call over MCP</b>.</p>

> **Why it exists:** the AWS web console is a maze — this harness replaces
> console navigation geography with typed verbs. See [MOTIVATION.md](MOTIVATION.md).

---

## ⚡ Use it as an MCP server in 30 seconds

```bash
pip install -e . --break-system-packages   # 1. install (or: pipx install .)
harness doctor                             # 2. green = credentials + plugins OK
harness serve-mcp                          # 3. the server: stdio, no port, no daemon
```

Then wire it into your client — **one line each**:

| Client | Command |
|---|---|
| **Pi** | `pi mcp add aws-harness -- harness serve-mcp` |
| **Hermes** | `hermes mcp add aws-harness --command harness --args serve-mcp` |
| **Claude Code** | `claude mcp add aws-harness -- harness serve-mcp` |
| **VS Code** | `{"servers":{"aws-harness":{"type":"stdio","command":"harness","args":["serve-mcp"]}}}` → `.vscode/mcp.json` |

Ask your assistant **“run doctor, then whoami”** — and it is talking to real AWS.
Full per-client guide (config files, verification, troubleshooting):
**[docs/mcp-clients.md](docs/mcp-clients.md)**

### What the model gets

| | |
|---|---|
| **whoami · doctor · list_accounts · account_regions · console_url** | identity, health, accounts, regions, deep links |
| **ec2\_list\_instances · ec2\_describe · s3\_list\_buckets · s3\_bucket\_info · vpc\_list** | compute + storage + network inventory |
| **iam\_list\_users · iam\_find\_unused · iam\_check\_mfa** | identity hygiene across accounts |
| **lambda\_list\_functions · cloudfront\_list\_distributions** | serverless + edge |
| **security\_guardduty\_findings · security\_hub\_status** | security posture |
| **org\_list\_accounts · org\_list\_ous** | live AWS Organizations view |
| **backup\_list\_vaults · backup\_list\_jobs · cost\_total · inventory\_summarize** | backups, spend, local snapshot |
| **safe\_op\_dry\_run** | simulate a mutation — changes nothing |

### Why it is safe to point at real accounts

- 🔒 **Read + simulate only over MCP** — real mutations are CLI-only (`--yes`); a boolean an LLM can set is not a safety boundary
- 🧱 **`read_only` lock** for production businesses — enforced at one choke point in code, exit 2 before any API call
- ✂️ **50-row cap** on results — no context blow-ups
- 🧾 **Attribution** — MCP actions land in the audit trail as `harness:mcp`; CloudTrail sees `harness-<user>`
- 🔑 **ExternalId** on every AssumeRole (no confused-deputy), least-privilege policies in [docs/harness-needed_aws-roles.md](docs/harness-needed_aws-roles.md)

---

## Features

- **Multi-account management**: Organizations API discovery + manual overrides
- **Multi-region**: North America + Europe (region enablement detection)
- **Inventory**: Read-only resource discovery across accounts/regions
- **Cost overview**: Cost Explorer queries, budget status
- **Security posture**: GuardDuty, Security Hub, Config, Macie, WAF aggregation
- **Safe operations**: EC2 stop/start, Lambda invoke, IAM key rotation, CloudFront invalidation
- **Audit trail**: CloudTrail attribution with SourceIdentity + diff tracking
- **Plugin architecture**: Extensible service modules via entry points
- **MCP server (shipped)**: `harness serve-mcp` — 24 typed tools, so Pi / Hermes / Claude Code / VS Code become a natural-language interface over the same safety model ([client guide](docs/mcp-clients.md))

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

## Installation

```bash
# From source
pip install -e .

# From PyPI (future)
pip install aws-harness
```

## Configuration

Config file: `~/.config/aws-harness/config.yaml`

See [`docs/aws-reference.md`](docs/aws-reference.md) for full AWS service reference.
See [`docs/architecture.md`](docs/architecture.md) for architecture details.

## Phase 1 Scope (Current)

| Capability | Status |
|------------|--------|
| IAM (read-only) | ✅ |
| EC2 (read + stop/start) | ✅ |
| S3 (read-only) | ✅ |
| CloudFront (read + invalidate) | ✅ |
| Lambda (read + invoke) | ✅ |
| VPC (read + safe ops) | ✅ |
| Organizations (read) | ✅ |
| Cost (read-only) | ✅ |
| Security (read-only) | ✅ |
| Inventory (read-only) | ✅ |
| Audit trail (diff + trail) | ✅ |

Phase 2 (future): Terraform scaffolding, ECS/EKS, RDS, provisioning via IaC.

## Security

- No credentials in config files
- SSO/AssumeRole with ExternalId + SourceIdentity attribution
- Atomic credential cache (0600 permissions)
- Tag-based deletion guards
- Rate limiting per account/region/API

## License

MIT

## Documentation

See **docs/user-manual.md** — the user manual, and **docs/production-rollout-plan.md** — the plan to present for production-access approval.
For MCP clients: **docs/mcp-clients.md** — copy-paste setup for Pi, Hermes, Claude Code and VS Code (24 tools over stdio).
For AWS-side setup: **docs/harness-needed_aws-roles.md** — every role/user/permission the harness needs, with worked policy examples (read-only, cross-account trust + ExternalId, safe ops, the production double-lock).
