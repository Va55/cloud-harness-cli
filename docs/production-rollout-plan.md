# AWS Harness — Production Rollout Plan

*For business owners / stakeholders. This is the document you present
when asking for approval. It states exactly what is being requested,
what is guaranteed, and how to stop.*

---

## 1. Executive summary (one minute read)

**The ask:** permission to run a read-only command-line tool against
selected AWS accounts, so account management stops requiring the AWS
web console.

**The guarantee in one sentence:** the tool is *configured with a
hard safety lock* that makes it technically impossible for it to
change anything in the approved accounts — not by the operator's
hand, not by a typo, not by an AI agent. It can only look.

**What it does:** lists users, instances, buckets, VPCs, backup vaults
and costs across accounts; answers questions in plain text; produces
an auditable record of everything it looked at.

**What it costs:** $0 (read-only API calls are free).

**How to stop:** revoke the read-only IAM user it uses. The tool is
dead instantly — nothing of it remains inside the accounts.

---

## 2. What is being approved, precisely

| Item | Value |
|---|---|
| Tool | `aws-harness` (private CLI, single operator) |
| Accounts | the named accounts only — listed per business below |
| Operations | **READ-ONLY API calls only** (describe/list/get) |
| Credentials | one dedicated read-only IAM user per business |
| Schedule | off-hours window initially; then on-demand by the operator |
| Duration | standing permission, revocable at any time by the account owner |

**Explicitly NOT approved (and technically blocked, see §3):**
starting/stopping instances, rotating keys, invoking functions,
invalidating caches, creating or deleting *anything*.

---

## 3. The safety lock (the technical guarantee)

Each approved business is flagged in the tool's configuration:

```yaml
businesses:
  - name: <business>
    profile: <business-read-only-credentials>
    read_only: true          # ← the lock
```

With `read_only: true`, every mutating command in the tool **refuses
before contacting AWS at all**:

```
$ harness ec2 stop i-0abc… --account prod
Error: Account 111111111111 (business 'alpha') is READ-ONLY — mutations
are disabled in config (accounts.*.read_only). This is a
production-safety lock; only reads and dry-runs are permitted.
```

The lock is enforced at the single choke point every mutating command
passes, and covers:

| Vector | Status |
|---|---|
| Operator typing a mutation command | ❌ refused, exit code 2 |
| A typo in account selection | ❌ refused (the lock is per-account, not per-command) |
| Natural-language requests (`harness ask "stop the server"`) | ❌ routed, then refused by the same wall |
| AI agents (MCP server) | ❌ the server is read-only + dry-run by design; and the lock applies to anything it routes |
| Bypass by editing the config | possible only by whoever holds the operator's machine — the same person who holds the master credentials. That is a people problem, not a tool problem |

This enforcement is **covered by automated tests** (15 dedicated
tests) — it is a code-level guarantee, not a policy promise.

---

## 4. What the business will observe

1. **CloudTrail** (their compliance view): read API calls
   (`ListUsers`, `DescribeInstances`, `ListBuckets`, …) attributed to
   the dedicated read-only IAM user, with session names
   `harness-<account>-<pid>`. We will provide the exact session-name
   pattern in advance so their monitoring can be pre-briefed. A
   mutation attempt — from anyone — will NOT appear from this tool,
   because it never reaches AWS.
2. **API traffic**: modest read volume (tens of calls per inspection
   run), bounded by built-in rate limiting. No service quotas are at
   risk.
3. **Costs**: $0. Read calls are free.
4. **Nothing installed inside the accounts.** The tool runs on the
   operator's machine only. No agents, no roles assumed without
   approval, no data leaving the operator's machine except the read
   API calls themselves.

---

## 5. Risk analysis (honest)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The tool mutates something | **Technically impossible** with the lock on (§3) | — | Lock + tests |
| Excessive API rate causes throttling for others | Very low | Low | Built-in per-account/per-service rate limiting; scheduled runs are small |
| Read data exposure | Low | Low | The tool's output stays on the operator's machine; the operator already has full access to this data via the console |
| Credentials compromise of the read-only user | Low | **Read-only by IAM policy** — the worst case is someone can look, not touch | Keys stored per OS best practice (0600), rotation supported by the tool, revocable instantly |
| Operator error outside the tool | Same as today | — | Out of scope: the operator already holds these credentials; the tool reduces (not increases) surface by removing console wandering |

**The honest bottom line:** the only new thing this introduces is a
dedicated *read-only* IAM identity and some free API reads. The
tool's mutation surface — the thing that could hurt a production
business — is switched off at the configuration level and cannot be
reached without an explicit, deliberate config change by the same
person who already owns the master credentials.

---

## 6. Staged rollout

| Stage | Scope | When |
|---|---|---|
| 0 | This document approved by the business owner; read-only IAM user created by the business's own admin (we provide the exact IAM policy JSON); monitoring pre-briefed on the `harness-*` session pattern | before anything runs |
| 1 | **One account.** `whoami`, `doctor`, `list users/instances/buckets` — proof run, off-hours | week 1 |
| 2 | **Whole business** (its approved accounts), read sweep + local inventory | week 2+ |
| 3 | Steady state: on-demand reads, cross-business summaries, plain-English questions | ongoing |

Mutations are never in any stage. If a mutation capability is ever
requested (e.g. stop/start during maintenance windows), that is a
**separate, explicit approval** with its own change-control — the
config flag comes off only then, per business.

---

## 7. Instant-abort procedure (for the business)

1. In the AWS console: IAM → Users → find the dedicated read-only user
   (name agreed in Stage 0) → **Deactivate / delete its access keys**.
2. Effect is immediate. No cleanup inside the accounts is needed —
   the tool installs nothing there.
3. (Optional belt-and-braces: the tool's own config can be pointed at
   nothing with a one-line change on the operator's machine.)

---

## 8. Approval sign-off

| Business | Accounts in scope | Read-only IAM user | Owner approval (name/date) |
|---|---|---|---|
| 1. __________ | ______________________ | ____________________ | ______________________ |
| 2. __________ | ______________________ | ____________________ | ______________________ |
| 3. __________ | ______________________ | ____________________ | ______________________ |
| 4. __________ | ______________________ | ____________________ | ______________________ |
| 5. __________ | ______________________ | ____________________ | ______________________ |

---

## Appendix A — What the tool is (for the technically minded)

A single-operator CLI over the AWS API (Python/boto3) with:
- per-business credential isolation (one profile per business)
- automatic cross-account role resolution (with ExternalId
  confused-deputy protection)
- per-account region detection (only enabled regions are queried)
- built-in rate limiting per account and service
- a full local audit trail of every action (who, what, when,
  dry-run or not)
- CloudTrail attribution on every call (`harness-*` session names)
- a read-only lock (§3) enforced in code and covered by tests
- an optional MCP server for AI assistants — read-only + simulation
  only; execution of real changes is not possible through it (v1)

The tool has been tested end-to-end against a dedicated AWS sandbox
organization, including deliberately-attempted mutations (verified
refused) and failure-mode handling against real permission denials.

## Appendix B — The IAM policy to attach to the read-only user (per business)

```
AWS-managed policy: ReadOnlyAccess
```
(or the narrower custom set: ec2:Describe*, iam:List*, iam:Get*,
s3:List*, s3:GetBucket*, backup:List*, lambda:List*,
cloudtrail:LookupEvents, ce:GetCostAndUsage, guardduty:List*)

No write permissions. No `:*Delete`, no `Create`, no `Update`,
no `sts:AssumeRole` unless cross-account reading is explicitly
approved (then: a dedicated role with the same read-only shape).
