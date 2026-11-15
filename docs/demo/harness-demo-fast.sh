#!/bin/bash
# 15-second cut of the harness demo (for GIF capture)
B="\033[1;36m"; G="\033[1;32m"; Y="\033[1;33m"; N="\033[0m"

clear
echo -e "${B}  harness — multi-account AWS from the terminal${N}"
echo -e "  live against the real AWS sandbox · read-only · \$0.00"
sleep 1.6

clear
echo -e "${Y}\$ harness whoami${N}"
harness whoami 2>/dev/null
sleep 1.4

clear
echo -e "${Y}\$ harness account list${N}"
harness account list 2>/dev/null
sleep 1.4

clear
echo -e "${Y}\$ harness --all-accounts iam list-users${N}"
harness --all-accounts iam list-users 2>/dev/null
sleep 2.2

clear
echo -e "${Y}\$ harness ask \"show the backup vault\"${N}"
harness ask "show the backup vault" 2>/dev/null
sleep 1.8

clear
echo -e "${Y}\$ sqlite3 audit.db \"SELECT …\"${N}"
sqlite3 -column ~/.cache/cloud-harness/audit.db \
  "SELECT timestamp, source_identity, action, dry_run, success
   FROM audit_events ORDER BY rowid"
sleep 2.0

clear
echo -e "${G}  ✓ one terminal · one credential set · two AWS accounts${N}"
echo -e "${G}    cross-account AssumeRole · audit trail · plain-English 'ask'${N}"
echo
echo -e "  ${B}harness --help${N}   — the console you never have to open"
sleep 4
