# Motivation

This document states the problem Cloud Harness CLI addresses, the design
response it implements, and the criteria by which the result should be
judged. Architectural detail lives in `docs/architecture.md`.

---

## The problem

The AWS web console is an interface optimised for exploration. It is
adequate when an operation is unfamiliar: wizards guide first-time
setup, resource graphs explain relationships, policy editors validate
syntax, documentation is one click away.

It is a poor interface for work that is already understood and must be
repeated — the routine question "which instances, in which accounts, in
which regions, and what do they cost" — for four structural reasons.

**1. Navigation state is implicit.** Region and account are selection
state held by the interface, not arguments in a request. A region
selector that persists across pages turns a wrong click into an empty
screen that is indistinguishable from an account that genuinely has no
resources. An account switch costs a sign-out and sign-in, or a
role-assumption round trip that resets the context of the task. The
operator carries this state in their head, and it is the main source of
wrong conclusions drawn from a correct-looking screen.

**2. Vocabulary differs per service.** Every service names its primary
objects, its list view, its filter model and its detail page
differently. Knowledge does not transfer: familiarity with the EC2
console does not indicate where IAM access-key age is displayed, or how
S3 versioning is toggled.

**3. The interface moves.** Left navigation is regrouped, consoles are
migrated from old to new layouts, and controls are relocated. Each
redesign is a small cost paid by every user, repeatedly, and it
invalidates whatever learned path existed before.

**4. Work does not compose.** Console output is a rendered page. It
cannot be filtered across twenty accounts in one pass, cannot be
diffed against last week, cannot be scheduled, and cannot be attached
to a change record. Cross-account questions — "which instances in every
account have a public IP" — become twenty tab sets and manual
comparison.

The consequence is not a knowledge gap. The concepts are the part that
works; the interface is the part that costs time and produces error.

### The environment this was built for

A common setting for this work is a managed client machine: a locked-down
desktop on which the terminal is not the primary interface, access to the
cloud provider is console-first, and the shell conveniences an operator
normally relies on are absent, restricted, or unavailable.

Working that way is possible. It is also slow in a way that does not
appear in any measurement: every operation costs an extra step, and the
console is frequently the only sanctioned path to an answer.

The harness assumes the opposite starting point — a terminal, one
vocabulary, explicit targeting and composable output. It also runs
natively on non-Unix clients, so an operator who cannot choose the
desktop is not excluded.

---

## The design response

**Model operations as verbs with explicit state, not as places with
implicit state.**

A command is a stable interface: it can be typed, scripted, versioned,
diffed and audited. A screen is a moving one: its layout is a detail
that changes without notice.

That single decision determines the rest of the design.

- **Explicit targeting.** Account and region are arguments —
  `--account`, `--all-accounts`, `--region`, `--all-regions` — never
  inherited selection state. A query that spans accounts says so, and
  its output says which account produced which row.
- **One vocabulary.** Every plugin answers the same verbs: list,
  describe, audit, and a small set of safe operations. Learning the
  harness once is learning it for all services.
- **Composable output.** Tables for reading, `--output json` for
  scripting, meaningful exit codes, and a report of every account that
  failed and why — so a partial result is never mistaken for a complete
  one.
- **Stable under UI change.** The command is written once and keeps
  working when the console is redesigned.

`harness ec2 list-instances --all-accounts --all-regions` is the same
command next week and next year.

---

## Console friction and the design response

| Console friction | Mechanism | Design response |
|---|---|---|
| Left-nav sprawl: 200+ services, regrouping, re-learning where things live | Navigation is a location that must be found | `harness <service> <verb>` — the command names the operation, and does not move |
| Region state follows the user; empty screens look like absent resources | Implicit selection state | Region is explicit per call: `--region` or `--all-regions` |
| Account switching requires sign-out/sign-in or role reassumption | Identity and context are per-session | `--account` / `--all-accounts`, one invocation |
| Each service has its own layout, breadcrumb and search model | No shared vocabulary | One vocabulary across all plugins |
| Broken breadcrumbs, old→new console redirects, tab multiplication | No durable record of position | Shell history is the record; commands are re-runnable |
| Cross-account questions require parallel browsing | Output is rendered, not queryable | `inventory collect --all-accounts`, then query the local store |
| Errors appear as dismissible banners; partial failures look like empty results | Failures are visual, not mechanical | `PartialResult` lists each failed account and reason; exit codes are non-zero |

---

## Scope

Stated explicitly, because overstating scope is the usual failure mode
of tooling like this.

- **Not a console replacement.** The console remains the better tool
  for first-time setup, visual debugging, resource graphs and
  documentation. The harness covers recurring, well-understood work.
- **Not a conceptual tutor.** It does not reduce the effort of
  understanding IAM evaluation or VPC routing. It reduces the effort of
  *navigating* to the answer.
- **Not a provisioning tool.** Creation, deletion and drift management
  belong to Terraform or CDK. The harness reads state, performs a small
  set of safe operations, and stays out of infrastructure definition.
- **Not free of learning cost.** A CLI has its own cost. The
  counterweights are a single vocabulary, JSON output, `doctor` for
  self-diagnosis, and honest "not implemented" responses instead of
  silent stubs.

---

## Interoperability: deep links

The console is the correct destination for visual work — a resource
graph, a policy editor with validation, a first-time wizard.
`harness console <service> [resource-id] --region <region>` prints, or
opens with `--open`, the direct URL for a specific resource.

The intent is not to prevent console use, but to remove the browsing
required to reach a specific screen: the terminal locates the resource,
the console renders it.

---

## Interoperability: MCP

The same plugin registry is exposed as an MCP server
(`harness serve-mcp`, 24 typed tools), so an MCP-capable client can
query the harness in natural language. The server is deliberately
narrower than the CLI:

- read and dry-run only — there is no MCP path to a real mutation;
- results capped at 50 rows;
- every call recorded in the audit trail as `harness:mcp`.

`harness ask` provides the same convenience without a model: natural
language input, resolved by a deterministic router that can only select
commands which exist, with mutations routed through `--dry-run` first.

Client wiring is in `docs/mcp-clients.md`; the rationale for the
permission split is in `docs/architecture.md` §13.

---

## Evaluation

The project justifies its existence when the following hold in routine
use.

1. **The periodic estate sweep** — accounts × regions × services — is
   one command (`inventory collect`, then `inventory summarize`)
   instead of a manual pass across consoles.
2. **No console session is opened to answer a question the harness can
   answer.** The console is reserved for visual work.
3. **Every failed account in a multi-account call reports its reason.**
   No partial result is silently presented as a complete one.

Criteria 1 and 3 are implemented and exercised against live AWS.
Criterion 2 is a usage outcome rather than a feature, and it is the one
that determines whether the project was worth building.

---

*Related: `docs/architecture.md` (design and decisions) ·
`docs/user-manual.md` (commands).*
