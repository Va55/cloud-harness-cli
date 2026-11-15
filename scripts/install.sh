#!/usr/bin/env bash
# ── AWS Harness installer (Linux / macOS / WSL2) ─────────────────
# One command from a fresh machine to a working harness:
#     ./scripts/install.sh
# Idempotent: safe to re-run. Options via env:
#     SKIP_VENV=1   install with pip --user instead of a venv
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

say() { printf '\033[1;36m»\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Python ≥ 3.11
command -v python3 >/dev/null || die "python3 not found — install Python 3.11+ first"
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11+ required, found $PYVER"
say "Python $PYVER ✓"

# 2. Install (venv by default; SKIP_VENV=1 for pip --user)
if [ "${SKIP_VENV:-0}" = "1" ]; then
    say "Installing with pip --user (PEP 668 systems: adds --break-system-packages)"
    PIP_FLAGS=(--user)
    python3 -m pip install --dry-run -q . >/dev/null 2>&1 \
        || PIP_FLAGS+=(--break-system-packages)
    python3 -m pip install "${PIP_FLAGS[@]}" -e . -q
    BINDIR="$HOME/.local/bin"
else
    say "Creating venv at ~/.venvs/aws-harness"
    python3 -m venv "$HOME/.venvs/aws-harness"
    # shellcheck disable=SC1091
    source "$HOME/.venvs/aws-harness/bin/activate"
    python3 -m pip install -q --upgrade pip
    python3 -m pip install -q -e . ".[test]" 2>/dev/null \
        || python3 -m pip install -q -e .
    BINDIR="$HOME/.venvs/aws-harness/bin"
fi

# 3. PATH check
if ! command -v harness >/dev/null 2>&1; then
    case ":$PATH:" in
        *":$BINDIR:"*) ;;
        *) say "Add $BINDIR to PATH, e.g.:"
           echo "    echo 'export PATH=\"$BINDIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
           ;;
    esac
fi

# 4. Local store init
command -v harness >/dev/null 2>&1 && "$REPO_DIR/scripts/init-db.sh" || true

# 5. Verify
say "Verifying…"
harness version || die "harness command not on PATH (see note above)"
harness plugins | head -3

cat <<'EOF'

✓ Installed. Next:
    1. Credentials: put your AWS profiles in ~/.aws/credentials
    2. Config:       cp harness_config/templates/config.yaml \
                         ~/.config/aws-harness/config.yaml  (then edit)
       — or import from a spreadsheet:
         python3 scripts/import-accounts-xlsx.py accounts.xlsx \
             ~/.config/aws-harness/config.yaml
    3. Verify:        harness whoami && harness doctor

Docs: docs/user-manual.md · docs/production-rollout-plan.md
EOF
