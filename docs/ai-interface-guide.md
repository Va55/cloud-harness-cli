# AI Interface Guide — using the harness with and without an LLM

*One tool, four interfaces. This guide explains which to use when,
and — if you choose an LLM — which brain to attach and how to wire
it. All configurations use the same harness underneath, with the same
safety model.*

---

## The options at a glance

| # | Interface | LLM? | Best for |
|---|---|---|---|
| 1 | **The CLI** (`harness …`) | none | everything — the primary interface; scripts, cron, muscle memory |
| 2 | **`harness ask`** | **none** (deterministic router) | faster than typing full commands; the safety of no-AI: it can only pick real commands |
| 3 | **`serve-mcp` + local model** | local | conversational exploration; data stays in-house |
| 4 | **`serve-mcp` + sanctioned API** | cloud | at work / sanctioned endpoints; best-in-class reliability |

**No option changes what the harness is allowed to do** — the
`read_only` lock, dry-run defaults, and audit trail apply to all of
them equally.

---

## Without an LLM

### 1 · The CLI — always

```
harness --all-accounts iam find-unused --days 90
harness ec2 list-instances --state stopped --region eu-north-1
```

Deterministic, scriptable, exit codes you can build on. Everything
below is a convenience layer on top of this — nothing requires an LLM.

### 2 · `harness ask` — natural language without AI

```
harness ask "show unused iam keys in prod"
  → harness iam find-unused --account prod
harness ask "stop instance i-0abc123456789def0 in eu-west-1"
  [dry-run] Mutating command — simulating. Real run: … (--yes)
harness ask --catalog          # everything the router knows
```

Why it contains no LLM (deliberately):
- **no hallucination surface** — it can only pick commands that exist;
  missing arguments are refused, never guessed
- **works offline** — no model, no API, no latency beyond AWS itself
- mutations always route with `--dry-run` first; `--yes` executes

---

## With an LLM — the MCP server

`harness serve-mcp` exposes 24 typed tools over stdio (read-only +
dry-run simulation only; **real mutations are impossible via MCP in
v1 — execution stays in the CLI**). The client brings the LLM:

### The wire-up (same for any client)

```bash
# pi / Claude Code:
claude mcp add aws-harness -- harness serve-mcp
pi mcp add aws-harness -- harness serve-mcp

# VSCode settings.json (agent mode):
"mcp": {"servers": {"aws-harness":
    {"command": "harness", "args": ["serve-mcp"]}}}

# Cursor / any MCP client: same pattern — command `harness`,
# args ["serve-mcp"]
```

Verify: the client should list 24 tools
(whoami, doctor, list_accounts, account_regions, console_url,
ec2_*, s3_*, iam_*, vpc_list, backup_*, cost_total, safe_op_dry_run).

### Choosing the brain

| Brain | Pros | Cons |
|---|---|---|
| **Local small model** (proven: a 2B instruct at Q4, ~1.5 GB) | private — AWS data stays in-house; free; offline | slower; needs the right serving flags (below) |
| **Cloud, sanctioned API** (e.g., a Haiku-class model at work) | fastest, most reliable, best MCP behavior | tool results transit the provider; only use a **sanctioned** endpoint for company data |
| **Local large model** (a 30B+ instruct on GPU) | best of both | needs the hardware |

**Empirical floor (tested, not guessed):** a 2B-class instruct model
with native tool-calling is sufficient for the harness — the 24 small
typed schemas were designed for exactly that. Models without native
tool-calling or agent tuning will fail the multi-turn loop even if
they can emit one valid call.

### Serving a local model (llama.cpp)

```bash
llama-server -m /path/to/model-2B-Q4_K_M.gguf \
    -ngl 0 -c 16384 -t 8 --host 0.0.0.0 --port 8085 --jinja
```

The flags that matter for tool-calling:
- `--jinja` — uses the model's chat template for tool schemas
  (without it, tool calls are not parsed)
- `-c 16384` — the harness's schemas + results need ~8–16K context
- **give the client ≥1000 output tokens** — small models think
  (reasoning tokens) before emitting a tool call; a tight output cap
  looks like a hung model

Then point the client at the endpoint (e.g., pi's models.json
provider entry with `baseUrl: http://<host>:8085/v1`).

### Testing a brain before you trust it

The two-round test (what separates a model that *serves* the harness
from one that merely looks capable):
1. **Round 1** — a question that requires a tool call, 3+ tools
   available: does it pick the right one with valid JSON arguments?
2. **Round 2** — feed back a tool result: does it make the correct
   follow-up call (the multi-turn loop)?

Both must pass, ideally at temperature 0.2 and 0.7. Models that pass
round 1 but die on round 2 (empty answers) are not capable, whatever
their single-call demo suggests.

---

## Data governance (read this before choosing an LLM)

Whatever brain is attached **sees every tool result**: account IDs,
resource inventories, IAM user lists, security findings. Ask one
question:

- **Company/sensitive data** → use a sanctioned endpoint (or local),
  never a random public API; and the production rollout plan
  should say out loud that an AI sees the inventory as part of "the
  tool looks"
- **Personal/sandbox data** → any brain you like

The audit trail records which interface did what either way:
CLI actions as `harness-<user>`, MCP actions as `harness:mcp`.

---

## What an LLM can and cannot do through the harness

| | Status |
|---|---|
| Read (lists, audits, costs, inventory search) | ✅ |
| Simulate a mutation (`safe_op_dry_run`) | ✅ — changes nothing |
| Execute a real mutation | ❌ impossible via MCP in v1 (CLI-only by design) |
| Mutate a `read_only: true` business by ANY path | ❌ blocked in code |
| Overflow your context | ❌ results capped at 50 rows |
| Act unattributed | ❌ audit trail + CloudTrail both record it |

---

## After upgrading the harness (the restart dance)

Tool definitions are loaded at process start on both sides — a
mid-session upgrade leaves both layers stale in different ways:

1. **the server**: `harness serve-mcp` imports tool decorators at
   startup → `pi mcp remove aws-harness && pi mcp add aws-harness
   -- harness serve-mcp` (or restart the host process)
2. **the client session**: the codemode/tool registry caches tool
   definitions from session start → **restart the session** to see
   new tools, even when `pi mcp list` already shows them

`pi mcp list --json` is the honest check for what the *server*
offers; the session cache is the other half. (Verified live by the
operator during the 17 → 24-tool upgrade: server showed 24, session
still saw 17 until restart.)

---

*Related docs: user-manual.md §10 (ask) and §11 (serve-mcp reference) ·
architecture.md §13 (the three-tier design) ·
production-rollout-plan.md (approvals for company data).*
