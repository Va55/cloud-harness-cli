# Project Motivation

> **The console is a place you navigate. The harness is a verb you type.**
> You cannot get lost where there is no geography.

> Why aws-harness exists. Read this before the architecture doc.

---

## The Problem

The target user of this harness **knows AWS concepts** — IAM policies, VPCs,
S3 lifecycles are not the problem. **The AWS web console is the problem.**

The console is a *place*: a 200+ service maze with a left-nav that regroups
every few months, a region selector that silently follows you into the wrong
empty screen, an account switcher that costs a sign-out/sign-in round trip,
and a different UI vocabulary for every service. The result is getting lost
navigating it — not because of missing AWS knowledge, but because the console
imposes **geography** on operations that should be **verbs**.

That distinction matters for how the problem should be solved: this user
does not need the concepts explained, does not need a guided wizard, and
does not need a simpler mental model. They need the same operations
expressed as repeatable commands that behave identically across accounts,
regions and redesigns.

---

## The Thesis

A command is a stable interface; a screen is a moving one. Expressed as a
verb, an operation can be typed, scripted, versioned and audited. Expressed
as a place, every UI redesign is a regression to your muscle memory.

`harness ec2 list-instances --all-accounts --all-regions` is the same command
next week and next year. It replaces a click-path that differs in every
service, changes with console redesigns, and cannot be repeated across twenty
accounts and eleven regions without an hour of sign-ins, selectors and tab
sprawl.

---

## Friction the Harness Eliminates

| Console problem | Harness answer |
|---|---|
| **Left-nav sprawl** — 200+ services, menu regroups, re-learning where things live | `harness <service> <verb>` — the command *is* the location; it never moves |
| **Silent region state** — region selector follows you; empty screens look like missing resources | Region is explicit per call: `--region` or `--all-regions`; no silent empty screens |
| **Account switching dance** — sign out, sign in, assume role, start over | `--account production` / `--all-accounts` — one flag, same mental context |
| **Inconsistent consoles** — every service has a different layout, breadcrumb, and search | One vocabulary everywhere; every plugin answers the same verbs |
| **"Which screen am I on?"** — broken breadcrumbs, old→new console redirects, tab multiplication | Command history *is* the breadcrumb trail; `↑` replays where you were |
| **20-tab cross-referencing** — "which instances, in which accounts, with which SGs?" | `harness inventory collect --all-accounts` then query the local store |
| **Silent partial failure** — dismissed error banners, spinners that never load | `PartialResult` prints every failed account with a reason; exit codes feed scripts |

---

## What This Project Is NOT

Honesty about scope, per the expert-reviewed design:

- **Not a console replacement.** The console remains better for first-time
  setup, visual debugging, and discovery (guided wizards, resource graphs,
  doc links). The harness is for the recurring, known-what-you-want work.
- **Not a conceptual tutor.** It does not reduce the cognitive load of
  *understanding* IAM evaluation or VPC routing — only the load of
  *navigating* the UI. For the target user above that is the right trade:
  the concepts are already in hand.
- **Not a provisioning tool (Phase 1).** Mutating infrastructure is
  delegated to Terraform/CDK; the harness reads state, runs safe ops, and
  scaffolds IaC. Deliberate — building a fifth IaC engine would fail.
- **Not friction-free itself.** A CLI has its own learning cost. The
  counterweights: one command vocabulary for all services, JSON output for
  scripting, `doctor` for self-diagnosis, and honest stubs that say
  "not yet implemented" instead of pretending.

---

## The Bridge: Deep Links

Console-native users should not be forced to choose sides.
`harness console <service> [resource-id] --region <r>` prints — or opens,
with `--open` — the **direct deep-link URL** to a specific resource in the
console:

- Navigate by command — never wander.
- Jump to the one screen where the console genuinely wins
  (a graph, a policy editor with validation).
- Zero browsing to get there.

This is the best of both: the terminal as the map, the console as the
zoomed-in view.

## The Second Layer: Conversational Interface

For Pi / Claude Code / Hermes-style interaction, the harness exposes its
plugin registry as an **MCP server** (`harness serve-mcp`, 24 typed tools)
— so any MCP-capable client becomes a natural-language interface over the
same tools, under the same safety gates: read and dry-run only, no path to
a real mutation, every call audited. Wiring per client is in
`docs/mcp-clients.md`.

`harness ask` covers the same ground without a model: natural language in,
but a deterministic router that can only select commands which exist.

Same principle as deep links: **typed verbs are the map; conversation is
a co-pilot — never a replacement for the deterministic CLI.**
Full design: `docs/architecture.md` §13.

---

## Success Criteria

The project justifies itself when, for the target user:

1. The **weekly "what exists where" sweep** — accounts × regions × services —
   is one command (`inventory collect` + `summarize`) instead of an hour of
   console clicking.
2. **No console session is opened to answer a question the harness can
   answer** — the console is reserved for the visual-only work: a resource
   graph, a policy editor with validation, first-time setup.
3. **Every failed account in a multi-account call reports its reason** —
   no silent SCP denials hiding behind a dismissed banner.

Criteria 1 and 3 are implemented and exercised against live AWS; criterion
2 is a usage habit rather than a feature, and it is the one that decides
whether the project was worth building. The build order that led here is in
`PROJECT_LOG.md`, phase by phase.

---

*Related: `docs/architecture.md` (v3.0 design), `PROJECT_LOG.md` (full history, audit, decisions).*
