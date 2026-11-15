# Using the harness MCP server from MCP clients

*Copy-paste setup for Pi, Hermes, Claude Code and VS Code (plus any
other MCP client). One stdio server, 24 typed tools, read-only +
dry-run only.*

---

## What you are connecting to

```
harness serve-mcp          # stdio, JSON-RPC, no port, no daemon
```

- **24 tools**: whoami, doctor, list_accounts, account_regions,
  console_url, ec2_list_instances/describe, s3_list_buckets/bucket_info,
  iam_list_users/find_unused/check_mfa, vpc_list, backup_list_vaults/
  list_jobs, cost_total, lambda_list_functions,
  security_guardduty_findings/hub_status, org_list_accounts/ous,
  cloudfront_list_distributions, inventory_summarize,
  safe_op_dry_run
- **read + simulate only** — real mutations are impossible over MCP
  (execution stays in the CLI with `--yes`). The `read_only` business
  lock applies on top of that
- results capped at 50 rows; MCP actions are audit-logged as
  `harness:mcp`
- the client's LLM sees every tool result — see "Which brain" in
  `ai-interface-guide.md` before pointing a cloud model at company data

### Prerequisites (each client inherits only what it can see)

```bash
harness doctor          # credentials, regions, plugins — must be green
which harness           # note the absolute path for GUI clients
```

GUI-launched clients (VS Code, Cursor) often **do not inherit your
shell PATH** — if `harness` is not found, use the absolute path from
`which harness` (e.g. `/home/USER/.local/bin/harness`) in `command`.

The server reads `~/.config/aws-harness/config.yaml` and your AWS
profiles from the environment/`~/.aws`; nothing needs to be passed in
unless you want a per-project config (`HARNESS_CONFIG`).

---

## Pi

```bash
pi mcp add aws-harness -- harness serve-mcp
pi mcp list                       # → connected, 24 tools
```

- config: `~/.pi/agent/mcp.json` (user) or `--local` for the project
  file `.pi/mcp.json`
- inside a session: `/mcp` to inspect/reconnect,
  `/reload` after external changes
- tools reach the model as `mcp__aws-harness__<tool>` and are callable
  from codemode as `mcp__aws_harness.<tool>`
- JSON equivalent:

```json
{"mcpServers": {"aws-harness": {"command": "harness", "args": ["serve-mcp"]}}}
```

✅ Verified: `aws-harness: connected, 24 tools (codemode, global)`.

## Hermes

```bash
hermes mcp add aws-harness --command harness --args serve-mcp
hermes mcp test aws-harness       # connection + tool discovery
hermes mcp list                   # → ✓ enabled
```

- the add is interactive: it asks **"Enable all 24 tools? [Y/n/select]"**
  — answer `Y` (or `select` to expose only some; `hermes mcp configure
  aws-harness` changes it later)
- non-interactive/scripted: `printf 'Y\n' | hermes mcp add aws-harness
  --command harness --args serve-mcp`
- config lands in `~/.hermes/config.yaml`
- running sessions need `/reload-mcp` (or a new session)
- remove with `hermes mcp remove aws-harness`

✅ Verified: `✓ Connected (1649ms) · ✓ Tools discovered: 24`,
`24/24 tools enabled`.

## Claude Code

```bash
claude mcp add aws-harness -- harness serve-mcp      # project/local scope
claude mcp add --scope user aws-harness -- harness serve-mcp   # all projects
claude mcp list
```

- `/mcp` inside Claude Code shows the server, its tools and their state
- JSON equivalents: project `.mcp.json`, or user `~/.claude.json`

```json
{"mcpServers": {"aws-harness": {"type": "stdio",
  "command": "harness", "args": ["serve-mcp"]}}}
```

- the `--` before the command matters: everything after it is the
  stdio command line, not flags for `claude`
- scope names differ by version (`local`, `project`, `user`); `claude
  mcp add --help` lists yours

## VS Code

VS Code has two configuration shapes — use the first unless you know
you need the legacy one.

**Current (Copilot harness, portable `mcpServers` format):**

```json
// ~/.copilot/mcp-config.json  (global)  or  <workspace>/.mcp.json
{
  "mcpServers": {
    "aws-harness": {
      "type": "stdio",
      "command": "harness",
      "args": ["serve-mcp"]
    }
  }
}
```

Or without editing files: Command Palette → **Chat: Open
Customizations → MCP Servers → Add Server**, destination *Global →
Copilot Global*, and give the command `harness` with argument
`serve-mcp`.

**Legacy VS Code agent mode (`servers` key):**

```json
// .vscode/mcp.json
{"servers": {"aws-harness": {"type": "stdio",
  "command": "harness", "args": ["serve-mcp"]}}}
```

Verify with **MCP: List Servers** (Command Palette) — it should show
24 tools after connecting. On Linux/macOS a GUI-launched VS Code may
need the absolute path (see Prerequisites).

## Cursor / any other MCP client

Almost every client accepts the same stdio entry (`mcpServers`,
`command` + `args`):

```json
{"mcpServers": {"aws-harness": {"command": "harness", "args": ["serve-mcp"]}}}
```

If a client only supports HTTP transport, bridge it locally:

```bash
npx -y supergateway --stdio "harness serve-mcp" --port 8811
# then point the client at http://127.0.0.1:8811/mcp
```

---

## Verify the hookup

Any client, one question is enough:

> "Use the aws-harness tools: run `doctor`, then `whoami`."

Expected: `doctor` reports credentials OK + 11 plugins; `whoami`
returns your ARN with source identity `harness-<user>`. The client's
tool list should show **24** entries.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `command not found: harness` | GUI client has no shell PATH | use the absolute path from `which harness` |
| client shows **17** tools | stale registry (pre-v0.2 surface) | restart the client session; server restart alone is not enough |
| tools list empty / server won't start | `harness` import error | run `harness doctor` in a terminal — fix that first |
| all tools return credential errors | client env lacks AWS profile | set `AWS_PROFILE` in the server's `env`, or rely on the config file |
| a tool times out (default ~60 s) | regional sweep across many regions | pass `region=` to narrow; or set the client's per-request timeout |
| `AccessDenied` in `failures` | IAM policy for that service missing | see `harness-needed_aws-roles.md` §2 |
| tools appear but never called | model can't do multi-turn tool use | 2B+ instruct model with native tool-calling; ≥1000 output tokens |

**Restart discipline after upgrading the harness:** restart the
server (`<client> mcp remove/add`) *and* the client session — the
tool registry is read at session start.

---

## What a client can and cannot do

| | Over MCP |
|---|---|
| List/inspect resources, costs, security findings, org structure | ✅ |
| Simulate a mutation (`safe_op_dry_run`) — nothing changes | ✅ |
| Execute a real mutation (start/stop, rotate keys, invalidate) | ❌ CLI-only by design |
| Mutate a `read_only: true` business by any path | ❌ blocked in code |
| Act without attribution | ❌ audit log records `harness:mcp` |

---

*Related: `ai-interface-guide.md` (which interface, which model) ·
`user-manual.md` §11 (tool reference) ·
`harness-needed_aws-roles.md` (IAM for each tool) ·
`production-rollout-plan.md` (company-data approvals).*
