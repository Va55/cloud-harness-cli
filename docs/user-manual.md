# Cloud Harness CLI — User Manual

*Initial release · for the single operator managing many accounts across
several businesses.*

---

## 1. What this is

The harness is a command-line tool for managing AWS **without the web
console**. It exists because the console fights you at scale:

| Console friction | Harness equivalent |
|---|---|
| 200+ services in the left nav | `harness ec2 …`, `harness iam …` — verbs, not menus |
| Silent region selector | Region is explicit, and enablement is *detected* per account |
| Sign out / sign in to switch accounts | `--account`, `--all-accounts` — role assumption is automatic |
| Four different consoles to check one thing | One command, all accounts, one table |

Everything the harness mutates (start/stop instances, rotate keys,
invalidate caches, invoke functions) runs **dry-run by default** and
lands in a **local audit trail**. Deleting is not implemented — that's
deliberate (Phase 1 is read + safe ops; provisioning belongs to
Terraform/CDK).

---

## 2. Quick start

```bash
# install (from the repo)
cd ~/work/cloud-harness-cli
pip install -e . --break-system-packages

# 1. create your config (see §4) — or import from your accounts
#    spreadsheet:
python3 scripts/import-accounts-xlsx.py \
    ~/Desktop/AWS_ACCOUNTS_AND_ADMIN_ROLES.xlsx \
    ~/.config/cloud-harness/config.yaml
# then fix the profile: names in the file to match ~/.aws/credentials

# 2. check your identity
harness whoami

# 3. full health check
harness doctor

# 4. see your accounts
harness account list
```

If `whoami` prints your ARN and `doctor` passes, you're ready.

---

## 3. Core concepts

| Concept | Meaning |
|---|---|
| **Business** | A group of accounts that share one set of credentials (one AWS profile). You have several; each has its own login. `--business` scopes any command to one. |
| **Account** | One AWS account, reached either with its business's own credentials (the login account) or by **assuming a role** into it — exactly like the console's *switch role*, but scripted. |
| **Profile** | A named credential set in `~/.aws/credentials`. Each business has one. |
| **Role assumption** | The harness calls `sts assume-role` for you, with full CloudTrail attribution (`harness:<user>` appears as the source identity — you can always see it was the harness acting). |
| **Region detection** | The harness asks each account which regions it has enabled, and only sweeps those (cached 24 h; `--refresh` forces re-detection). |
| **Safe op** | A mutating action with guardrails: dry-run default, audit-logged, no deletes. |
| **Partial failure** | When a sweep hits 12 accounts and 1 fails, you get 11 results + the failure reason — the run never dies on one bad account. |

---

## 4. The config file

Location: `~/.config/cloud-harness/config.yaml` (or pass `--config PATH`).
A complete, annotated example is in
`harness_config/examples/example-inventory.yaml`.

```yaml
accounts:
  discovery: manual            # 'manual' = use the accounts: lists below
  businesses:
    - name: alpha
      profile: alpha           # ← THIS business's credentials (must
                               #   match a profile in ~/.aws/credentials)
      discovery: manual
      role_arn: "arn:aws:iam::{account_id}:role/OpsAccess"  # optional
                               # template: how to reach OTHER accounts
                               # inside this business
      default_account: prod    # used when you pass --business alpha
                               # without --account
      accounts:
        - id: "111111111111"
          name: prod
          role_arn: "arn:aws:iam::111111111111:role/prod-full-admin-trust-role"
        - id: "222222222222"   # the login account: no role_arn →
          name: shared         # direct profile credentials
    - name: beta
      profile: beta
      # ...same shape...

  # Defaults when nothing more specific applies (single-account setups
  # don't need businesses at all — just this):
  defaults:
    profile: default
    # role_arn: "arn:aws:iam::{account_id}:role/OpsAccess"
    # external_id: my-secret-external-id
    session_tags:
      harness_user: "$USER"
```

**How account targeting resolves** (most specific wins):

```
--account 123456789012     exact account ID
--account prod             account NAME (must be unambiguous, or add --business)
--account ou-xxx/yyy       OU path (Organizations discovery mode)
--account self             whatever account your profile belongs to
--business alpha           scope to a business (with --all-accounts:
                           all accounts of THAT business; alone: its
                           default account)
(nothing)                  config default_account, else an error —
                           the harness never silently picks for you
```

Environment overrides: `CLOUD_HARNESS_ACCOUNT`, `CLOUD_HARNESS_PROFILE`.

---

## 5. Global options

Put these **before** the command:

```
--business NAME        Scope to one business
--account ID|NAME|OU   Target one account
--all-accounts         Sweep every (or the business's) accounts
--region NAME          One region instead of the enabled sweep
--all-regions          All CONFIGURED regions, skip enablement detection
--profile NAME         Credential profile (else config/business default)
--role ARN             Force this role for every account in the run
--external-id ID       ExternalId for cross-account assumption
--output json|table|yaml|text    (default: table)
--dry-run              Simulate mutating commands (they also dry-run
                       by default — this covers plugins' own flags)
--verbose / --quiet    Full failure messages / suppress success output
--refresh              Clear credential + region caches first
--config PATH          Use a different config file
```

Exit codes: `0` all good · `1` partial (some failed) · `2` fatal /
everything failed. Scripts can rely on this.

---

## 6. Commands

### 6.1 System

```
harness whoami              # who am I, with harness attribution
harness doctor              # credentials + regions + plugins + config
harness plugins             # loaded plugins and capabilities
harness version
harness console ec2 i-123... # print the console deep-link (--open opens it)
```

`console` is the bridge back to the web UI: when you *do* need the
console (a service the harness doesn't cover), this prints the exact
URL — navigate by command, never wander.

### 6.2 Accounts

```
harness account list [--include-suspended]      # all known accounts
harness account show --account prod            # details + role resolution
harness account regions --account prod         # regions in scope
harness account assume --account prod          # print export-ready
                                                # temporary credentials
```

`account assume` outputs shell exports:

```bash
eval $(harness account assume --account prod 2>/dev/null)
aws sts get-caller-identity    # you are now in prod
```

Credentials are temporary (STS) — never long-lived keys.

### 6.3 Per-service (read + safe ops)

```
harness iam      list-users | list-roles | list-access-keys USER
                 check-mfa USER | find-unused [--days N] | audit
                 rotate-keys USER [--output-file PATH]   # safe op
harness ec2      list-instances [--state running|stopped]
                 describe INSTANCE_ID | security-groups | audit
                 start INSTANCE_ID --region R | stop INSTANCE_ID --region R
harness s3       list-buckets | bucket-info BUCKET | public-check BUCKET | audit
harness cloudfront list-distributions | invalidate DIST_ID --paths '/*'
harness lambda   list-functions | invoke FUNCTION --region R [--payload '{"k":1}']
harness vpc      list | describe VPC_ID | subnets | route-tables
                 internet-gateways | nat-gateways | nacls | endpoints
                 flow-logs | audit
harness backup   list-vaults | list-plans | list-recovery-points --vault V
                 list-jobs [--state FAILED] | audit
                 start-backup ARN --vault V --iam-role R   # safe op
harness org      list-accounts | list-ous
harness cost     by-service | total
harness security guardduty | hub
harness inventory collect [--services ec2,s3,iam] | summarize | show
                 search [--tag Name=web] | export [--format csv]
```

Every read command accepts `--account`, `--all-accounts`, and
`--output json` (plus `--business` globally).

### 6.4 Examples you'll actually use

```bash
# Who has stale keys across the whole business?
harness --business alpha iam find-unused --days 90 --all-accounts

# Every stopped instance, everywhere:
harness --all-accounts ec2 list-instances --state stopped

# Is anything publicly exposed?
harness --all-accounts s3 audit

# What does one instance look like?
harness ec2 describe i-0abc123456789def0 --account prod --region eu-west-1

# Stop that instance — safe ops dry-run by default; --yes executes:
harness ec2 stop i-0abc123456789def0 --region eu-west-1   # dry-run (the default)
harness ec2 stop i-0abc123456789def0 --yes               # real (--region optional — auto-detected)

# Rotate a user's keys (secret → 0600 file, never the screen):
harness iam rotate-keys alice --account prod --yes
# → Secret written to ~/.cache/cloud-harness/credentials/AKIA….secret (0600)

# Are backups actually working? (the question that matters)
harness --all-accounts backup audit
harness --business alpha backup list-jobs --state FAILED --region eu-west-1
harness backup list-recovery-points --vault prod-vault --account prod

# Network visibility:
harness vpc flow-logs --all-accounts       # who has traffic logging?
harness vpc nat-gateways --all-accounts    # the silent cost driver
harness --all-accounts vpc audit           # no flow logs / public subnets

# Take a snapshot of everything, then query it offline:
harness --all-accounts inventory collect --services ec2,s3,iam
harness inventory summarize
harness inventory search --tag env=prod
```

---

## 7. `harness ask` — plain English

`ask` converts a sentence into one of the real commands above — it
cannot invent commands, and mutating routes always dry-run first
(`--yes` executes for real).

```bash
$ harness ask "show unused iam keys in prod"
→ harness iam find-unused --account prod

$ harness ask "stop instance i-0abc123456789def0 in eu-west-1"
[dry-run] Mutating command — simulating. Real run: … --yes
→ harness ec2 stop i-0abc123456789def0 --region eu-west-1 --dry-run

$ harness ask "which regions are enabled for prod"
→ harness account regions --account prod

$ harness ask "failed backup jobs in prod"
→ harness backup list-jobs --account prod --state FAILED

$ harness ask --catalog       # list everything the router knows
```

Global flags compose with it: `harness --business alpha --output json
ask "list users"`.

If `ask` can't route your sentence it says so and lists the valid
services — it never guesses. If a command needs something the sentence
didn't contain (an instance ID, a username), it refuses with what's
missing instead of inventing one.

---

## 8. MCP server — agents as the interface

`harness serve-mcp` exposes the harness as tools for any MCP client
(pi, Claude Code, VSCode Copilot agent mode, Cursor):

```bash
# pi / Claude Code:
claude mcp add cloud-harness-cli -- harness serve-mcp
# VSCode settings.json (agent mode):
"mcp": {"servers": {"cloud-harness-cli":
    {"command": "harness", "args": ["serve-mcp"]}}}
```

*Which brain to attach, how to serve a local model, and the
data-governance trade-offs — see **docs/ai-interface-guide.md** (the
consolidated with/without-LLM decision guide). Per-client setup
(Pi, Hermes, Claude Code, VS Code): **docs/mcp-clients.md**.*

24 typed tools (no free-form params): whoami, doctor, list_accounts,
account_regions, console_url, ec2_list_instances/describe,
s3_list_buckets/bucket_info, iam_list_users/find_unused/check_mfa,
vpc_list, backup_list_vaults/list_jobs, cost_total,
lambda_list_functions, security_guardduty_findings/security_hub_status,
org_list_accounts/list_ous (management account only),
cloudfront_list_distributions, inventory_summarize (local snapshot),
and `safe_op_dry_run` (operation, resource_id) — **simulation only**:
an LLM-facing server cannot trigger real mutations in v1; execution
stays in the CLI (`--yes`). Results are capped at 50 rows. MCP-origin
actions are audit-logged as `harness:mcp` — distinguishable from your
human CLI actions.

## 8b. Safety model

1. **Dry-run is the default for every mutating command** —
   `--dry-run`/`--yes` semantics per command; EC2 uses AWS's native
   DryRun, Lambda its DryRun parameter, rotations run a read-only
   simulation.
2. **Secrets never go to stdout.** `rotate-keys` writes the new secret
   to a 0600 file and prints only its location.
3. **Every mutating action is audit-logged locally** with your
   attribution:
   ```bash
   sqlite3 ~/.cache/cloud-harness/audit.db \
     "SELECT timestamp, source_identity, action, resource_id, dry_run
      FROM audit_events ORDER BY timestamp DESC LIMIT 10"
   ```
4. **No delete commands exist.** Removing resources is out of scope —
   use the console or IaC.
5. **Attribution everywhere:** every call the harness makes appears in
   CloudTrail with `SourceIdentity = harness-<you>` and session tags —
   your actions are distinguishable from console clicks and other
   automation.

---

## 9. Where things live

| Path | Content |
|---|---|
| `~/.config/cloud-harness/config.yaml` | your config |
| `~/.cache/cloud-harness/inventory.db` | accounts, region cache, inventory snapshots |
| `~/.cache/cloud-harness/audit.db` | audit trail (what you did, when) |
| `~/.cache/cloud-harness/credentials/` | rotated key secrets (0600 files) |

`--refresh` clears the credential and region caches; inventory and
audit data are kept (retention configurable in config).

---

## 10. Troubleshooting

| Symptom | Meaning / fix |
|---|---|
| `The config profile (x) could not be found` | A profile name in your config doesn't match `~/.aws/credentials`. Fix the `profile:` values (§4). |
| `Account name 'prod' is ambiguous (2 matches in businesses: …)` | Two businesses have an account with that name. Add `--business` or use the 12-digit ID. |
| `No account specified and no default configured` | Say what you mean: `--account`, `--business X` (needs a `default_account`), or set `CLOUD_HARNESS_ACCOUNT`. |
| `AccessDenied` on every cross-account call | The trust role doesn't allow your profile, or the ExternalId doesn't match. Check `harness account show --account X` (prints the ARN that would be assumed). |
| `OptInRequired` / `auth failure` noise during a sweep | Use `--refresh` to re-detect enablement, or `--region` for the specific region. Detection is cached 24 h. |
| `[WARN] Region detection failed` | The account's credentials lack `ec2:DescribeRegions`. The sweep falls back to configured regions. |
| Exit code 1 vs 2 | 1 = some targets failed (see the failure block in output, `--verbose` for full messages); 2 = nothing worked (credentials, config, permissions). |
| Rate-limit errors on cost commands | Cost Explorer allows 0.5 req/s per account — the harness already serializes; don't run parallel cost commands. |

For harness bugs, the full history and design rationale are in
`docs/architecture.md`.

---

### 8c. The read_only lock (production safety)

For production businesses, flag the lock in config — mutations are
then technically impossible, not just discouraged:

```yaml
accounts:
  businesses:
    - name: alpha
      profile: alpha-readonly
      read_only: true          # ← mutations REFUSED, in code
```

Precedence: account `read_only` > business > defaults. Every mutating
command (start/stop, rotate-keys, invalidate, invoke, start-backup)
refuses with a clear error before contacting AWS; reads and dry-run
simulations stay available. Covered by 15 dedicated tests. See
the internal approval checklist kept outside this repository.

### 10b. Windows

The harness runs natively on Windows (Python 3.11+ from python.org,
then `pip install .`), with the usual AWS setup
(`%USERPROFILE%\.aws\credentials` — same profile format). Platform
notes:

- Paths (`~/.config/cloud-harness/`, `~/.cache/cloud-harness/`) map to
  your Windows profile automatically
- `console --open` uses the default browser via the Windows shell API
- **One caveat**: the 0600 permission on secret files is a POSIX
  concept — on Windows, files are protected by your user profile's
  NTFS permissions instead (no other local user can read them by
  default), but there is no per-file 0600 bit. If you need stricter
  isolation on Windows, use BitLocker or a dedicated user account.
- WSL2 alternative: runs exactly as on Linux with zero differences —
  `pip install -e .` inside a WSL Ubuntu and you're done

## 11. Current limitations

- **No provisioning.** Creating/modifying resources is out of scope
  (Terraform/CDK territory). Reads and safe ops only.
- **No deletes**, ever, in v1.
- Cost data is cached 24 h; region enablement 24 h (`--refresh` to
  bypass).
- Organizations-based discovery assumes each business's profile can
  call `organizations:ListAccounts`; otherwise use `manual` account
  lists (§4) — which is what the import script generates.
- **AWS Backup:** restores are not automated (high blast radius —
  find the recovery point with `list-recovery-points`, restore via
  console/IaC); recovery-point deletion is not implemented (data loss).
- The `ask` router is deterministic (no AI): it understands service
  names, common verbs, IDs, and phrases like "in prod", "all
  accounts", "in business alpha" — it does not hold a conversation.
