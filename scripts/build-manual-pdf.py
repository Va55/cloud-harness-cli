#!/usr/bin/env python3
# ruff: noqa: N999  (hyphenated CLI script)
"""Build the harness user manual as a PDF (with real screenshots).

Screenshots are pre-rendered terminal images in /tmp/manual-shots/
(see the private development log). Content mirrors docs/user-manual.md,
restructured for print with embedded examples.

Usage: python3 scripts/build-manual-pdf.py [output.pdf]
"""

import json
import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents

SHOTS = "/tmp/manual-shots"
META = json.load(open(os.path.join(SHOTS, "meta.json")))

# ─── palette & styles ─────────────────────────────────────────────

INK = colors.HexColor("#1a2330")
ACCENT = colors.HexColor("#0e7490")
CODE_BG = colors.HexColor("#f2f5f8")
MUTED = colors.HexColor("#5b6b7a")

S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17,
                          leading=21, textColor=INK, spaceBefore=18,
                          spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                          leading=17, textColor=ACCENT, spaceBefore=14,
                          spaceAfter=6),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                            leading=14, textColor=INK, spaceAfter=6),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=10,
                              leading=14, textColor=INK, leftIndent=14,
                              bulletIndent=4, spaceAfter=3),
    "code": ParagraphStyle("code", fontName="Courier", fontSize=8.5,
                            leading=11, textColor=INK, backColor=CODE_BG,
                            borderPadding=6, leftIndent=6, rightIndent=6,
                            spaceAfter=8),
    "caption": ParagraphStyle("caption", fontName="Helvetica-Oblique",
                               fontSize=8.5, leading=11, textColor=MUTED,
                               alignment=1, spaceBefore=2, spaceAfter=10),
    "quote": ParagraphStyle("quote", fontName="Helvetica-Oblique",
                             fontSize=11, leading=15, textColor=ACCENT,
                             leftIndent=20, rightIndent=20, spaceAfter=6),
}

TOC_STYLE = ParagraphStyle("toc", fontName="Helvetica", fontSize=10.5,
                            leading=15, textColor=INK)


# ─── helpers ─────────────────────────────────────────────────────

def h1(text, doc_toc):
    return Paragraph(text, S["h1"])


def body(text):
    return Paragraph(text, S["body"])


def bullets(items):
    return [Paragraph(f"• {i}", S["bullet"]) for i in items]


def code(text):
    return XPreformatted(text, S["code"])


def shot(key, caption, max_width_pt=470):
    """Screenshot scaled to the page width."""
    w, h = META[key]
    scale = min(max_width_pt / (w * 72 / 96), 1.0)
    img = Image(os.path.join(SHOTS, f"{key}.png"),
                width=w * 72 / 96 * scale,
                height=h * 72 / 96 * scale)
    img.hAlign = "CENTER"
    return [img, Paragraph(caption, S["caption"])]


def simple_table(header, rows, widths=None):
    data = [header] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, CODE_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d2dc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ─── page furniture ───────────────────────────────────────────────

def on_page(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 1.2 * cm, "Cloud Harness CLI — User Manual")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"page {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#d5dde5"))
        canvas.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
    canvas.restoreState()


class ManualDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):  # noqa: N802 (reportlab override)
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            text = flowable.getPlainText()
            self.notify("TOCEntry", (0, text, self.page))


self_toc = None
self_doc = None


# ─── content ──────────────────────────────────────────────────────

def build(out_path):
    doc = ManualDoc(out_path, pagesize=A4,
                    leftMargin=2 * cm, rightMargin=2 * cm,
                    topMargin=2 * cm, bottomMargin=2.2 * cm,
                    title="Cloud Harness CLI — User Manual",
                    author="Cloud Harness CLI project")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=on_page)])

    toc = TableOfContents()
    toc.levelStyles = [TOC_STYLE]
    global self_toc, self_doc
    self_toc = toc
    self_doc = doc

    story = []

    # cover
    story.append(Spacer(1, 5 * cm))
    story.append(Paragraph("Cloud Harness CLI", ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=34, leading=40,
        textColor=INK, alignment=1)))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Multi-account, multi-region AWS management — "
                       "from the terminal", ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=13, leading=18,
        textColor=ACCENT, alignment=1)))
    story.append(Spacer(1, 1.2 * cm))
    story.append(Paragraph("User Manual — comprehensive edition with live "
                       "examples", ParagraphStyle(
        "sub2", fontName="Helvetica-Oblique", fontSize=10, leading=14,
        textColor=MUTED, alignment=1)))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("All example outputs in this manual were captured "
                       "live against a real AWS environment (read-only; "
                       "$0.00).", ParagraphStyle(
        "sub3", fontName="Helvetica", fontSize=8.5, leading=12,
        textColor=MUTED, alignment=1)))
    story.append(PageBreak())

    # TOC
    story.append(Paragraph("Contents", S["h1"]))
    story.append(toc)
    story.append(PageBreak())

    # 1 what this is
    story.append(h1("1 · What this is", toc))
    story.append(body(
        "The harness is a command-line tool for managing AWS without the "
        "web console. It exists because the console fights you at scale: "
        "hundreds of services in the left nav, a silent region selector, "
        "and a sign-out/sign-in dance for every account. The harness "
        "replaces all of that with verbs."))
    story.append(Paragraph(
        "“Web console is cognitive harassment for me.” — the operator, "
        "live during testing, to AWS's own assistant", S["quote"]))
    story.append(simple_table(
        ["Console friction", "Harness equivalent"],
        [["200+ services in the left nav",
          "harness ec2 …, harness iam … — verbs, not menus"],
         ["Silent region selector",
          "Region is explicit; enablement detected per account"],
         ["Sign out / sign in to switch accounts",
          "--account / --all-accounts — role assumption automatic"],
         ["Four consoles to check one thing",
          "One command, all accounts, one table"]]))
    story.append(Spacer(1, 6))
    story.append(body(
        "Everything the harness mutates runs dry-run by default and lands "
        "in a local audit trail. Deleting is not implemented — by design: "
        "reads and safe operations only; provisioning belongs to "
        "Terraform/CDK."))

    # 2 quick start
    story.append(h1("2 · Quick start", toc))
    story.append(code(
        "# install (from the repo)\n"
        "cd ~/work/cloud-harness-cli && pip install -e . --break-system-packages\n"
        "\n"
        "# 1. create your config (see §4) — or import from a spreadsheet:\n"
        "python3 scripts/import-accounts-xlsx.py accounts.xlsx \\\n"
        "    ~/.config/cloud-harness/config.yaml\n"
        "\n"
        "# 2. check your identity\n"
        "harness whoami\n"
        "# 3. full health check\n"
        "harness doctor\n"
        "# 4. see your accounts\n"
        "harness account list"))
    story.extend(shot("whoami", "Figure 1 — whoami: identity + attribution"))
    story.extend(shot("doctor", "Figure 2 — doctor: credentials, regions, plugins"))

    # 3 concepts
    story.append(h1("3 · Core concepts", toc))
    story.append(simple_table(
        ["Concept", "Meaning"],
        [["Business", "A group of accounts sharing one credential set "
          "(one AWS profile). --business scopes any command to it."],
         ["Account", "One AWS account — reached via its business's own "
          "credentials (the login account) or by assuming a role into it, "
          "exactly like the console's switch-role, but scripted."],
         ["Profile", "A named credential set in ~/.aws/credentials. "
          "Each business has one."],
         ["Role assumption", "sts assume-role with full CloudTrail "
          "attribution — the harness's sessions are always identifiable "
          "(harness-*)."],
         ["Region detection", "The harness asks each account which "
          "regions are enabled and sweeps only those (cached 24 h; "
          "--refresh forces re-detection)."],
         ["Safe op", "A mutating action with guardrails: dry-run default, "
          "audit-logged, no deletes."],
         ["Partial failure", "A sweep of 12 accounts with 1 failure "
          "yields 11 results + the failure reason — never a total crash."],
         ["read_only lock", "A config flag that makes mutations "
          "technically impossible for flagged businesses (§14)."]],
        widths=[3.2 * cm, 12.3 * cm]))

    # 4 config
    story.append(h1("4 · The configuration file", toc))
    story.append(body(
        "Location: ~/.config/cloud-harness/config.yaml (or --config PATH). "
        "A fully annotated example lives in "
        "harness_config/examples/example-inventory.yaml."))
    story.append(code(
        "accounts:\n"
        "  discovery: manual            # 'manual' = use the lists below\n"
        "  businesses:\n"
        "    - name: alpha\n"
        "      profile: alpha           # ← THIS business's credentials\n"
        "      read_only: true          # ← the production safety lock\n"
        "      role_arn: \"arn:aws:iam::{account_id}:role/OpsAccess\"\n"
        "      default_account: prod\n"
        "      accounts:\n"
        "        - id: \"111111111111\"\n"
        "          name: prod\n"
        "        - id: \"222222222222\"   # login account: no role → direct\n"
        "          name: shared          # profile credentials\n"
        "  defaults:\n"
        "    profile: default\n"
        "    session_tags:\n"
        "      harness_user: \"$USER\"\n"
        "  default_account: prod"))
    story.append(body("Account targeting resolves most-specific-first:"))
    story.append(simple_table(
        ["--account 123456789012", "exact account ID"],
        [["--account prod", "account NAME (unambiguous, or add --business)"],
         ["--account ou-xxx/yyy", "OU path (organizations discovery)"],
         ["--account self", "whatever account the profile belongs to"],
         ["--business alpha", "scope to a business (alone: its default)"],
         ["(nothing)", "config default_account, else a clean error — "
          "never a silent guess"]]))
    story.append(body("Environment overrides: CLOUD_HARNESS_ACCOUNT, "
                  "CLOUD_HARNESS_PROFILE."))

    # 5 global options
    story.append(h1("5 · Global options & exit codes", toc))
    story.append(code(
        "--business NAME        scope to one business\n"
        "--account ID|NAME|OU   target one account\n"
        "--all-accounts         sweep every (or the business's) accounts\n"
        "--region NAME          one region instead of the enabled sweep\n"
        "--all-regions          all CONFIGURED regions, skip detection\n"
        "--profile NAME         credential profile override\n"
        "--role ARN             force this role for every account\n"
        "--external-id ID       ExternalId for cross-account assumption\n"
        "--output json|table|yaml|text\n"
        "--dry-run              simulate mutating commands\n"
        "--verbose / --quiet    full failure messages / silent success\n"
        "--refresh              clear credential + region caches\n"
        "--config PATH          different config file"))
    story.append(simple_table(
        ["Exit code", "Meaning"],
        [["0", "all good"], ["1", "partial — some targets failed"],
         ["2", "fatal — config error, credentials, everything failed"]]))
    story.append(body("Scripts can rely on these codes."))

    # 6 system commands
    story.append(h1("6 · System commands", toc))
    story.extend(shot("plugins", "Figure 3 — plugins: the 11 loaded plugins"))
    story.append(body(
        "harness console SERVICE [ID] prints the exact console deep-link "
        "for a resource (--open opens the browser) — the bridge back to "
        "the web UI for the services the harness doesn't cover. Navigate "
        "by URL; never wander."))

    # 7 accounts
    story.append(h1("7 · Accounts", toc))
    story.append(code(
        "harness account list [--include-suspended]\n"
        "harness account show --account prod\n"
        "harness account regions --account prod\n"
        "harness account assume --account prod   # export-ready temp creds"))
    story.extend(shot("accounts", "Figure 4 — account list"))
    story.extend(shot("regions", "Figure 5 — account regions (config ∩ enabled)"))
    story.append(body(
        "account assume prints shell exports for eval: "
        "eval $(harness account assume --account prod 2>/dev/null). "
        "Credentials are temporary (STS) — never long-lived keys."))

    # 8 the heart: cross-account
    story.append(h1("8 · One command, every account", toc))
    story.append(body(
        "The core of the tool: sweep every account in one command, one "
        "table, one exit code. Cross-account access happens by role "
        "assumption with ExternalId — silently, safely, audited."))
    story.append(code("$ harness --all-accounts iam list-users"))
    story.extend(shot("allusers", "Figure 6 — both accounts, one table "
                                "(cross-account via AssumeRole)"))

    # 9 services
    story.append(h1("9 · Service commands", toc))
    story.append(simple_table(
        ["Service", "Commands"],
        [["iam", "list-users · list-roles · list-access-keys USER · "
          "check-mfa USER · find-unused [--days N] · audit · "
          "rotate-keys USER (safe op)"],
         ["ec2", "list-instances [--state …] · describe ID · start/stop ID "
          "(safe ops) · security-groups · audit"],
         ["s3", "list-buckets · bucket-info BUCKET · public-check · audit"],
         ["cloudfront", "list-distributions · invalidate (safe op)"],
         ["lambda", "list-functions · invoke (safe op)"],
         ["vpc", "list · describe · subnets · route-tables · "
          "internet-gateways · nat-gateways · nacls · endpoints · "
          "flow-logs · audit"],
         ["backup", "list-vaults · list-plans · list-recovery-points · "
          "list-jobs [--state FAILED] · audit · start-backup (safe op)"],
         ["org", "list-accounts · list-ous"],
         ["cost", "by-service · total"],
         ["security", "guardduty · hub"],
         ["inventory", "collect · summarize · show · search · export"]],
        widths=[2.6 * cm, 12.9 * cm]))
    story.append(Spacer(1, 4))
    story.extend(shot("instances", "Figure 7 — ec2 list-instances "
                               "(the seeded test instance, stopped)"))
    story.extend(shot("vpc_audit", "Figure 8 — vpc audit: real security findings"))
    story.extend(shot("backup", "Figure 9 — backup list-vaults"))
    story.extend(shot("guardduty", "Figure 10 — security guardduty"))
    story.extend(shot("cost", "Figure 11 — cost total (real Cost Explorer)"))
    story.extend(shot("inventory", "Figure 12 — inventory summarize"))

    # 10 ask
    story.append(h1("10 · Plain English: harness ask", toc))
    story.append(body(
        "ask converts a sentence into one of the real commands above — "
        "deterministically (no AI): it can only pick commands that exist, "
        "mutations always dry-run first (--yes executes for real), and "
        "missing arguments are refused, never guessed."))
    story.extend(shot("ask1", "Figure 13 — ask: sentence → command → result"))
    story.extend(shot("ask2", "Figure 14 — ask: region question"))
    story.append(body("harness ask --catalog lists everything the router "
                  "understands."))

    # 11 mcp
    story.append(h1("11 · AI assistants: harness serve-mcp", toc))
    story.append(body(
        "An MCP server (stdio) exposing the harness as 17 typed tools for "
        "any MCP client — pi, Claude Code, VSCode Copilot, Cursor. The "
        "client brings the LLM; the harness stays the deterministic "
        "core. Wire-up:"))
    story.append(code(
        '# pi / Claude Code:\n'
        'claude mcp add cloud-harness-cli -- harness serve-mcp\n'
        '# VSCode settings.json (agent mode):\n'
        '"mcp": {"servers": {"cloud-harness-cli":\n'
        '    {"command": "harness", "args": ["serve-mcp"]}}}'))
    story.extend(shot("mcp", "Figure 15 — the 17 tools the server exposes"))
    story.append(body(
        "Read-only + dry-run only: an LLM-facing server cannot trigger "
        "real mutations in v1 — execution stays in the CLI. Results are "
        "capped at 50 rows; MCP-origin actions are audited as "
        "harness:mcp, distinguishable from human CLI actions."))

    # 12 safety
    story.append(h1("12 · Safety model", toc))
    story.extend(bullets([
        "Dry-run is the default for every mutating command (EC2 uses "
        "AWS's native DryRun, Lambda its DryRun parameter, key rotation "
        "runs a read-only simulation).",
        "Secrets never go to stdout — rotate-keys writes the new secret "
        "to a 0600 file and prints only its location.",
        "Every mutating action is audit-logged locally with attribution "
        "(§13).",
        "No delete commands exist, by design. Removing resources is "
        "IaC/console territory.",
        "Every call appears in CloudTrail with harness-* session names "
        "and source identity harness-<user>.",
    ]))
    story.append(Paragraph("12.1 · The read_only lock (production)", S["h2"]))
    story.append(body(
        "For production businesses, mutations can be made technically "
        "impossible — not discouraged, impossible:"))
    story.append(code(
        "businesses:\n"
        "  - name: alpha\n"
        "    profile: alpha-readonly\n"
        "    read_only: true      # ← mutations REFUSED, in code"))
    story.extend(shot("ro_refusal", "Figure 16 — the lock refusing a stop "
                                 "command (exit 2, clean error, AWS "
                                 "never contacted)"))
    story.append(body(
        "Precedence: account read_only > business > defaults. Covers "
        "typed commands, typos, mis-routed ask requests, and MCP "
        "agents. Reads and dry-run simulations remain available. "
        "Covered by 15 dedicated automated tests — a code-level "
        "guarantee, not a policy promise."))

    # 13 audit
    story.append(h1("13 · The audit trail", toc))
    story.extend(shot("audit", "Figure 17 — every mutation recorded with "
                           "attribution and dry-run flags"))
    story.append(code(
        'sqlite3 ~/.cache/cloud-harness/audit.db \\\n'
        '  "SELECT timestamp, source_identity, action, resource_id,\n'
        '          dry_run, success FROM audit_events ORDER BY rowid"'))

    # 14 where things live
    story.append(h1("14 · Where things live", toc))
    story.append(simple_table(
        ["Path", "Content"],
        [["~/.config/cloud-harness/config.yaml", "your configuration"],
         ["~/.cache/cloud-harness/inventory.db",
          "accounts, region cache, inventory snapshots"],
         ["~/.cache/cloud-harness/audit.db", "audit trail"],
         ["~/.cache/cloud-harness/credentials/",
          "rotated key secrets (0600 files)"]],
        widths=[6.5 * cm, 9 * cm]))

    # 15 troubleshooting
    story.append(h1("15 · Troubleshooting", toc))
    story.append(simple_table(
        ["Symptom", "Meaning / fix"],
        [["The config profile (x) could not be found",
          "Profile name doesn't match ~/.aws/credentials — fix the "
          "profile: values (§4)."],
         ["Account name 'prod' is ambiguous (2 matches in businesses…)",
          "Two businesses have that name — add --business or the ID."],
         ["No account specified and no default configured",
          "Say what you mean: --account, --business, or set "
          "default_account."],
         ["AccessDenied on cross-account calls",
          "The trust role or ExternalId doesn't match — check "
          "harness account show --account X (prints the ARN that "
          "would be assumed)."],
         ["…denied by SCP / opt-in noise during sweeps",
          "Governance-level restrictions; --refresh re-detects "
          "enablement, --region targets a specific region."],
         ["[WARN] this org blocks session tags / source identity",
          "If an organisation denies sts:TagSession/SetSourceIdentity "
          "— the harness degrades to RoleSessionName attribution and "
          "continues (expected, safe)."],
         ["Exit 1 vs 2",
          "1 = some targets failed (see the failure block; --verbose "
          "for full messages); 2 = nothing worked (credentials, "
          "config, permissions)."]],
        widths=[5.8 * cm, 9.7 * cm]))

    # 16 limitations
    story.append(h1("16 · Current limitations (honest)", toc))
    story.extend(bullets([
        "No provisioning — creating/modifying resources is out of scope "
        "(Terraform/CDK territory). Reads and safe ops only.",
        "No deletes, ever, in v1.",
        "AWS Backup: restores are not automated (find the recovery "
        "point, restore via console/IaC); recovery-point deletion is "
        "not implemented (data loss).",
        "Cost data cached 24 h; region enablement 24 h (--refresh "
        "bypasses both).",
        "The ask router is deterministic (no AI): it understands "
        "service names, common verbs, IDs, and phrases like 'in prod' — "
        "it does not hold a conversation.",
        "Rate limits: Cost Explorer is serialized at 0.5 req/s per "
        "account by the harness itself.",
    ]))

    # appendix
    story.append(h1("Appendix A · Rollout to production", toc))
    story.append(body(
        "For approval-ready material — scope tables, the lock's "
        "technical explanation, risk analysis, staged rollout, "
        "instant-abort procedure, and the read-only IAM policy — see "
        "an internal approval checklist is used before production access. Summary: "
        "read-only IAM user per business + read_only: true in config = "
        "the tool can look but never touch."))
    story.append(h1("Appendix B · Glossary", toc))
    story.append(simple_table(
        ["Term", "Definition"],
        [["AssumeRole", "STS operation for cross-account access; the "
          "harness's sessions carry RoleSessionName harness-*."],
         ["ExternalId", "Confused-deputy guard for cross-account trust; "
          "configured per business/defaults."],
         ["SCP", "Service Control Policy — org-level permission fence; "
          "the harness reports SCP denials as classified failures."],
         ["SourceIdentity", "CloudTrail human attribution; sts-limited "
          "charset, degrades gracefully where orgs block it."],
         ["MCP", "Model Context Protocol — the agent-interface wire "
          "format used by serve-mcp."],
         ["PartialResult", "The harness's result container: successes "
          "+ classified failures + exit code."]],
        widths=[3.4 * cm, 12.1 * cm]))

    doc.multiBuild(story)  # two passes: collect TOC entries, then render
    print(f"PDF written: {out_path}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Desktop/harness-user-manual.pdf")
    build(out)
