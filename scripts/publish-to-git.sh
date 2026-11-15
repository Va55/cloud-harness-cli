#!/usr/bin/env bash
# ── Publish the harness to the giada git repo ────────────────────
# Stages a SANITIZED snapshot of the work copy, commits changes,
# pushes to giada.
#
#     ./scripts/publish-to-git.sh ["commit message"]
#
# Sanitization map lives OUTSIDE this repo (so it can never leak
# through publishing, and cannot be mangled by its own rules):
#   ~/.config/aws-harness/sanitize-map.tsv   (format: real<TAB>fake)
# Without that file, publishing is REFUSED — no raw real data goes
# to the repo by accident.
set -euo pipefail

WORK=~/work/aws-harness
STAGE=$HOME/.cache/aws-harness/git-stage
REMOTE=ssh://giada/tank/git/aws-harness.git
MAP=$HOME/.config/aws-harness/sanitize-map.tsv

say() { printf '» %s\n' "$*"; }

# 0. refuse to publish unsanitized real data
if [ ! -f "$MAP" ]; then
    say "ERROR: no sanitization map at $MAP"
    say "create it first (real<TAB>fake per line) — refusing to publish raw"
    exit 1
fi

# 1. persistent stage: clone once, overlay the work copy each run
say "preparing stage …"
if [ ! -d "$STAGE/.git" ]; then
    mkdir -p "$(dirname "$STAGE")"
    if ! git clone -q "$REMOTE" "$STAGE"; then
        git init -q -b main "$STAGE"
        git -C "$STAGE" remote add origin "$REMOTE"
    fi
fi
git -C "$STAGE" remote rename origin giada 2>/dev/null || true
# the stage ALWAYS works on main (clone of an empty repo may default
# to master on git < 3.0)
git -C "$STAGE" checkout -q -b main 2>/dev/null || true

say "overlaying $WORK …"
rsync -a --delete \
      --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
      --exclude='.pytest_cache' --exclude='.ruff_cache' \
      --exclude='.mypy_cache' --exclude='*.egg-info' \
      --exclude='.git' --exclude='.coverage' --exclude='infra/' \
      "$WORK/" "$STAGE/"

# 2. sanitize from the LOCAL map (never committed)
say "sanitizing from $MAP …"
python3 - "$STAGE" "$MAP" << 'PYEOF'
import pathlib, sys
stage, map_path = sys.argv[1], sys.argv[2]
subs = []
for line in pathlib.Path(map_path).read_text().splitlines():
    line = line.rstrip("\n")
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    parts = line.split("\t", 1)
    if len(parts) != 2 or not parts[0]:
        sys.exit(f"bad map line: {line!r}")
    subs.append(tuple(parts))
if not subs:
    sys.exit("empty sanitization map")
changed = 0
for p in pathlib.Path(stage).rglob("*"):
    if (not p.is_file() or ".git" in p.parts
            or p.suffix in {".pdf", ".xlsx", ".png", ".jpg", ".db",
                            ".coverage", ".pyc"}):
        continue
    try:
        src = p.read_text()
    except (UnicodeDecodeError, OSError):
        continue
    new = src
    for old, repl in subs:
        new = new.replace(old, repl)
    if new != src:
        p.write_text(new)
        changed += 1
print(f"  sanitized {changed} file(s)")
PYEOF

# 3. commit + push
cd "$STAGE"
git config user.name  "Team" 2>/dev/null || true
git config user.email "team@example.com" 2>/dev/null || true
if [ ! -f .gitignore ]; then
    printf '# Python\n__pycache__/\n*.pyc\n*.egg-info/\n.venv/\nbuild/\n' > .gitignore
    printf '# caches / coverage\n.pytest_cache/\n.ruff_cache/\n.mypy_cache/\n.coverage\n' >> .gitignore
    printf '# local state — never commit\n*.db\n*.db-journal\n*.db-wal\n*.db-shm\n.env\n*.secret\n' >> .gitignore
fi
git add -A
if git diff --cached --quiet; then
    say "no changes — repo already up to date"
    exit 0
fi
MSG="${1:-update $(date +%Y-%m-%d)}"
git commit -q -m "$MSG"
say "committed: $MSG"

say "pushing to $REMOTE …"
git push -q giada main
say "pushed ✓  ($(git -C "$STAGE" log --oneline | wc -l) commit(s) on main)"
