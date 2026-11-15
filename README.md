# AWS Management Harness

Multi-account, multi-region AWS management platform. CLI-first, Python/boto3. Single-operator: one user, many accounts, several businesses.

> **Why it exists:** the AWS web console is a maze — this harness replaces
> console navigation geography with typed verbs. See [MOTIVATION.md](MOTIVATION.md).

## Features

- **Multi-account management**: Organizations API discovery + manual overrides
- **Multi-region**: North America + Europe (region enablement detection)
- **Inventory**: Read-only resource discovery across accounts/regions
- **Cost overview**: Cost Explorer queries, budget status
- **Security posture**: GuardDuty, Security Hub, Config, Macie, WAF aggregation
- **Safe operations**: EC2 stop/start, Lambda invoke, IAM key rotation, CloudFront invalidation
- **Audit trail**: CloudTrail attribution with SourceIdentity + diff tracking
- **Plugin architecture**: Extensible service modules via entry points
- **Roadmap: conversational interface**: MCP server (`harness serve-mcp`) so pi / Claude Code / any MCP client becomes a natural-language interface over the same tools — see [architecture §13](docs/architecture.md)

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
For AWS-side setup: **docs/harness-needed_aws-roles.md** — every role/user/permission the harness needs, with worked policy examples (read-only, cross-account trust + ExternalId, safe ops, the production double-lock).
