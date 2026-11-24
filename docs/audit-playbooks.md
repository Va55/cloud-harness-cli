# Audit playbooks — guided journeys through the CLI

The [user manual](user-manual.md) lists every command. This page answers the
question before that: *which* commands, in *which* order, answer the questions
an operator actually asks — and how to read what comes back.

Every command here is a **read**. Reads are safe to run anywhere, on any
account, at any hour; safe operations (dry-run by default, `--yes` to execute)
are covered in the manual §6.3 and are deliberately not part of these journeys.

Two conventions that make sweeps predictable:

- App-level flags (`--business`, `--account`, `--all-accounts`, `--region`,
  `--all-regions`, `--output`, `--quiet`, `--verbose`, `--refresh`) go
  **before** the subcommand — placed after it, they are rejected with
  `No such option`. Only the command's own options (`--days`, `--state`,
  `--service`, …) go after it.
- Exit codes: **0** all good · **1** partial failure — some account or region
  failed while others returned data · **2** total failure, invalid config, or a
  usage error. Exit 1 means the sweep is *incomplete*: the output tells you
  which accounts were unreachable, and a partial sweep should never be filed
  as a complete audit.

---

## P1 — Orientation: what exists, and can we reach it

```bash
harness doctor                                  # credentials, regions, plugins
harness whoami                                  # the identity behind every call
harness account list                            # all accounts, all businesses
harness --business acme account list            # one business
harness account show --account prod             # one account + role-assumption check
harness account regions --account prod          # regions the harness will sweep
harness plugins                                 # loaded plugins + capabilities
```

**Reading it.** `account regions` is the intersection of config and what AWS
reports as enabled, cached 24 h. If an expected region is missing, run once
with `--refresh` before concluding anything about it. `account show` tells you
whether a role *would* be assumed — a trust-policy problem surfaces there
instead of as a mystery `AccessDenied` later.

## P2 — Public exposure: storage and compute

```bash
harness s3 audit                                # every bucket, public-exposure check
harness --all-accounts s3 audit                 # same, every account
harness s3 bucket-info my-bucket                # location, encryption, versioning, PAB
harness s3 public-check my-bucket               # one bucket, explicit verdict
harness ec2 audit                               # public instances + wide-open security groups
harness ec2 security-groups --region eu-north-1  # the rule sets themselves
```

**Reading it.** `public-check` (and `audit`) name the responsible mechanism in
their `reasons` — an ACL grant to `AllUsers`/`AuthenticatedUsers`, a policy
`Principal:*`, or no Public Access Block. Record that reason, not just
"public". `bucket-info` is complementary posture, not the verdict: it shows
encryption, versioning and the PAB configuration, but not ACL or policy. PAB
with all four settings on is a definitive "private" — `public-check`
short-circuits there.

## P3 — Credential hygiene

```bash
harness iam audit                               # users without MFA
harness --all-accounts iam audit                # every account
harness iam find-unused --days 90               # access keys unused for 90+ days
harness iam list-users                          # the raw list
harness iam list-access-keys <username>         # keys per user: status, age
harness iam check-mfa <username>                # one user, explicit verdict
```

**Reading it.** `find-unused` is the finding that matters: an active key with no
recent use is dormant attack surface. Age alone is not the signal —
`list-access-keys` shows age, `find-unused` shows *disuse*. Rotation is a safe
op (`iam rotate-keys`, dry-run by default) — see the manual §6.3.

## P4 — Network posture

```bash
harness vpc audit                               # no flow logs, public subnets, odd NAT states
harness vpc list
harness vpc describe vpc-0123456789abcdef0       # subnets, IGW, flow logs for one VPC
harness vpc subnets --region eu-north-1
harness vpc route-tables --region eu-north-1
harness vpc internet-gateways --region eu-north-1
harness vpc nat-gateways --region eu-north-1     # NAT gateways bill hourly — cost angle
harness vpc nacls --region eu-north-1            # rule counts
harness vpc flow-logs                            # visibility, or its absence
harness vpc endpoints                            # cost + data-exfiltration angle
```

**Reading it.** No flow logs means no forensics after an incident — that is the
headline finding. A public subnet is only meaningful together with its route
table (does it have an IGW route?) and the security groups in it (P2). NAT
gateways and VPC endpoints are both cost and egress-control questions.

## P5 — Edge and serverless inventory

```bash
harness cloudfront list-distributions           # global service — no --region needed
harness lambda list-functions                  # functions, configuration
harness --all-accounts lambda list-functions --runtime python3.12
```

**Reading it.** Both are inventory, not posture — pairing them with
`security guardduty` and `ec2 audit` is what turns a list into a finding.

## P6 — Backups

```bash
harness backup list-vaults                      # lock status, recovery point count
harness backup list-plans
harness backup list-jobs --state FAILED         # the command that matters
harness backup list-recovery-points --vault my-vault
harness backup audit                            # failed jobs + vaults with zero recovery points
```

**Reading it.** A vault with zero recovery points is a backup plan that has
never produced anything — the most common silent failure. `list-jobs --state
FAILED` gives the recent evidence; `audit` gives the structural hole.

## P7 — Cost

```bash
harness cost total --days 30
harness --all-accounts cost total --days 7
harness cost by-service --days 30
```

**Reading it.** `by-service` is cached 24 h and rate-limited to 0.5 TPS, so
query the window once and reuse the answer. Two windows (7 vs 30 days) separate
a spike from a step change. Cost Explorer lags up to ~24 h — never attribute
today's spend from it.

## P8 — What AWS is already telling us

```bash
harness security guardduty                      # finding counts by severity
harness security hub                            # Security Hub status per account/region
harness --all-accounts security guardduty
```

**Reading it.** These are counts and enablement statuses, not finding bodies.
If GuardDuty is not enabled in an account, that is itself the finding — an
account with no detector reports nothing at all.

## P9 — Snapshot, search, export

```bash
harness inventory collect                       # default services: ec2,s3
harness inventory collect --services ec2,s3,iam
harness --all-accounts inventory collect
harness inventory summarize                     # counts by account/region/service
harness inventory show --service s3             # latest snapshot
harness inventory search --tag Environment=prod
harness inventory export --service ec2 --format csv
```

**Reading it.** Collection writes to the local SQLite store; `summarize`,
`show`, `search` and `export` read the *latest snapshot*, so a stale snapshot
is indistinguishable from a stable estate unless you note when it was
collected. Two snapshots a week apart, diffed, are a cheap change log.

## Deep links instead of console navigation

```bash
harness console s3 my-bucket
harness console ec2 i-0123456789abcdef0 --region eu-north-1
harness console iam alice
harness console cloudfront E1ABCDEFGHIJKL
harness console lambda my-function --region eu-north-1
harness console vpc vpc-0123456789abcdef0 --region eu-north-1
```

Prints the exact console URL for one resource (`--open` launches a browser).

## Natural language without an LLM

```bash
harness ask "show unused iam keys in prod"      # → harness iam find-unused --account prod
harness ask --catalog                           # everything the router knows
```

A deterministic router: it can only select commands that exist and refuses when
arguments are missing. Mutating routes run as dry-run unless `--yes` is given.

## A findings report you can paste into a ticket

```
Scope: business acme, 4 accounts, eu-north-1 + eu-west-1 · 1 account unreachable (exit 1)

| Account | Region | Resource | Evidence | Severity |
|---|---|---|---|---|
| prod | global | bucket acme-logs | s3 bucket-info: no PAB, policy allows * | exposed |
| dev | eu-north-1 | key AKIA… (alice) | iam find-unused --days 90 | risky |
| prod | eu-north-1 | vpc-0123… | vpc audit: no flow logs | hygiene |

Evidence commands are reproducible as written.
Next (read-only): harness --output json --all-accounts s3 audit
Console: harness console s3 acme-logs
```
