#!/bin/bash
# ── CLOUD HARNESS CLI — LIVE DEMO ────────────────────────────────────
# Runs against the real AWS sandbox (all calls READ-ONLY, $0 cost)

B="\033[1;36m"   # banner
G="\033[1;32m"   # green
Y="\033[1;33m"   # yellow
N="\033[0m"

step() {
    echo -e "\n${B}═════════════════════════════════════════════════════════════${N}"
    echo -e "${B} $1${N}"
    echo -e "${B}═════════════════════════════════════════════════════════════${N}"
    sleep 1.2
}
run() {
    echo -e "${Y}\$ $*${N}"
    sleep 0.4
    "$@"
    echo
    sleep 1.6
}

clear
echo -e "${B}"
echo "  ██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗██╗     ███████╗"
echo "  ██║ ██╔╝██╔════╝██╔══██╗████╗ ████║██╔════╝██║     ██╔════╝"
echo "  █████╔╝ █████╗  ██████╔╝██╔████╔██║█████╗  ██║     ███████╗"
echo "  ██╔═██╗ ██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ██║     ╚════██║"
echo "  ██║  ██╗███████╗██║  ██║██║ ╚═╝ ██║███████╗███████╗███████║"
echo "  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝╚══════╝"
echo -e "${N}"
echo "  multi-account AWS from the terminal — no console required"
echo
echo -e "  ${G}►${N} Live demo against the real AWS sandbox"
echo -e "  ${G}►${N} Every command: read-only. Cost: \$0.00"
echo
read -p "  Press ENTER to start…" _

step "1/8 — Who am I? Identity + CloudTrail attribution"
run harness whoami

step "2/8 — Health check: credentials, region detection, 11 plugins"
run harness doctor

step "3/8 — Your accounts (both, from the local inventory store)"
run harness account list

step "4/8 — One command, BOTH accounts — cross-account via AssumeRole"
echo -e "${Y}\$ harness --all-accounts iam list-users${N}"
sleep 0.4
harness --all-accounts iam list-users
echo
sleep 1.6

step "5/8 — The seeded test instance (found, stopped, after our start/stop test)"
run harness ec2 list-instances --region eu-north-1

step "6/8 — Plain English → command (the deterministic 'ask' router)"
echo -e "${Y}\$ harness ask \"show the backup vault\"${N}"
sleep 0.4
harness ask "show the backup vault" 2>&1
echo
echo -e "${Y}\$ harness ask \"which regions are enabled for the member account\"${N}"
sleep 0.4
harness ask "which regions are enabled for member" 2>&1
echo
sleep 1.6

step "7/8 — Security check: network audit (real findings)"
run harness vpc audit

step "8/8 — The audit trail — every mutation recorded, with attribution"
echo -e "${Y}\$ sqlite3 ~/.cache/cloud-harness/audit.db \"SELECT …\"${N}"
sleep 0.4
sqlite3 -column ~/.cache/cloud-harness/audit.db \
  "SELECT timestamp, source_identity, action, resource_id, dry_run, success
   FROM audit_events ORDER BY rowid"
echo
sleep 2

echo -e "${G}"
echo "  ✓ DEMO COMPLETE — everything ran from one terminal, one set of"
echo "    credentials, across two AWS accounts."
echo -e "${N}"
echo "  Try it yourself:  harness --help        — all commands"
echo "                    harness ask --catalog — what the NL router knows"
echo "                    harness --all-accounts <any-list-command>"
echo
read -p "  Press ENTER to close this window…" _
