#!/bin/bash
# timed demo with scene marks (for GIF highlight extraction)
B="\033[1;36m"; G="\033[1;32m"; Y="\033[1;33m"; N="\033[0m"
T0=$(date +%s.%N)
mark() { echo "$1 $(echo "$(date +%s.%N) - $T0" | bc)" >> /tmp/scene-marks.log; }

clear
echo -e "${B}  harness — multi-account AWS from the terminal${N}"
echo -e "  live against the real AWS sandbox · read-only · \$0.00"
sleep 2.5; mark banner

echo -e "\n${Y}\$ harness whoami${N}"
harness whoami 2>/dev/null; mark whoami; sleep 2.5

clear
echo -e "${Y}\$ harness account list${N}"
harness account list 2>/dev/null; mark accounts; sleep 2.5

clear
echo -e "${Y}\$ harness --all-accounts iam list-users${N}"
harness --all-accounts iam list-users 2>/dev/null; mark allaccounts; sleep 3

clear
echo -e "${Y}\$ harness ask \"show the backup vault\"${N}"
harness ask "show the backup vault" 2>/dev/null; mark ask; sleep 2.5

clear
echo -e "${Y}\$ sqlite3 audit.db \"SELECT …\"${N}"
sqlite3 -column ~/.cache/aws-harness/audit.db \
  "SELECT timestamp, source_identity, action, dry_run, success FROM audit_events ORDER BY rowid"
mark audit; sleep 2.5

clear
echo -e "${G}  ✓ one terminal · one credential set · two AWS accounts${N}"
echo -e "${G}    cross-account AssumeRole · audit trail · plain-English 'ask'${N}"
echo
echo -e "  ${B}harness${N} — the console you never have to open"
mark finale; sleep 8
