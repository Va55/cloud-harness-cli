#!/usr/bin/env bash
# ── Cloud Harness CLI installer (Linux / macOS / WSL2) ──────────────────
#
# Installs the CLI into its own virtual environment and leaves everything
# else alone. It never touches ~/.aws, never edits an existing config, and
# never runs anything against AWS.
#
#   ./scripts/install.sh                    install from this checkout
#   ./scripts/install.sh --dry-run          show what would happen
#   ./scripts/install.sh --prefix DIR       install under DIR (default ~/.local/share/cloud-harness-cli)
#   ./scripts/install.sh --from-git URL     install from a git ref instead of this checkout
#   ./scripts/install.sh --no-mcp           CLI only, skip the MCP server dependency
#   ./scripts/install.sh --init-db          also create the local store
#   ./scripts/install.sh --force            replace an existing venv / config template
#
# Exits non-zero on failure. Safe to re-run.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$(cd "$SELF_DIR/.." && pwd)"

PREFIX="${CLOUD_HARNESS_PREFIX:-$HOME/.local/share/cloud-harness-cli}"
FROM_GIT=""
WITH_MCP=1
DRY_RUN=0
INIT_DB=0
FORCE=0

say()  { printf '\033[1;36m»\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = "1" ]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)  DRY_RUN=1 ;;
        --no-mcp)   WITH_MCP=0 ;;
        --init-db)  INIT_DB=1 ;;
        --force)    FORCE=1 ;;
        --prefix)   shift; PREFIX="${1:?--prefix needs a directory}" ;;
        --from-git) shift; FROM_GIT="${1:?--from-git needs a URL}" ;;
        -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)          die "unknown option: $1 (try --help)" ;;
    esac
    shift
done

VENV="$PREFIX/venv"
BINDIR="$VENV/bin"
CONFIG_DIR="${CLOUD_HARNESS_CONFIG_DIR:-$HOME/.config/cloud-harness}"
CONFIG_FILE="$CONFIG_DIR/config.yaml"

# ── 1. Python ≥ 3.11 ────────────────────────────────────────────────────
command -v python3 >/dev/null || die "python3 not found — install Python 3.11+ first"
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || die "Python 3.11+ required, found $PYVER"
say "Python $PYVER ✓"

# ── 2. Plan ─────────────────────────────────────────────────────────────
SPEC="."
if [ -n "$FROM_GIT" ]; then
    SPEC="cloud-harness-cli${WITH_MCP:+[mcp]} @ git+$FROM_GIT"
elif [ "$WITH_MCP" = "1" ]; then
    SPEC=".[mcp]"
fi

say "Install target : $PREFIX"
say "Source         : ${FROM_GIT:-$SOURCE_DIR}"
say "Extras         : $([ "$WITH_MCP" = "1" ] && echo mcp || echo none)"
say "Config         : $CONFIG_FILE ($([ -f "$CONFIG_FILE" ] && echo "exists — left untouched" || echo "template will be created"))"

if [ -d "$VENV" ] && [ "$FORCE" != "1" ] && [ "$DRY_RUN" != "1" ]; then
    die "$VENV already exists — re-run with --force to replace it (existing install is left intact until then)"
fi

# ── 3. Virtual environment ──────────────────────────────────────────────
say "Creating virtual environment…"
if [ -d "$VENV" ] && [ "$FORCE" = "1" ]; then
    run rm -rf "$VENV"
fi
run mkdir -p "$PREFIX"
run python3 -m venv "$VENV"
PY="$BINDIR/python"

# ── 4. Install the package (non-editable, built from a copy) ────────────
# Editable installs are for development; an installer ships a built
# package. A temporary copy keeps build artefacts out of the source tree.
say "Installing the package…"
if [ -z "$FROM_GIT" ]; then
    BUILD_SRC="$(mktemp -d)"
    trap 'rm -rf "$BUILD_SRC"' EXIT
    if [ "$DRY_RUN" = "1" ]; then
        printf '  [dry-run] copy source tree (%s) -> %s\n' "$SOURCE_DIR" "$BUILD_SRC"
    else
        tar -C "$SOURCE_DIR" \
            --exclude=.git --exclude=.venv --exclude='*.egg-info' \
            --exclude=build --exclude=dist --exclude='__pycache__' \
            -cf - . | tar -C "$BUILD_SRC" -xf -
    fi
    SPEC_PATH="$BUILD_SRC"
else
    SPEC_PATH="$SPEC"
fi
run "$PY" -m pip install --quiet --upgrade pip
if [ -z "$FROM_GIT" ]; then
    run "$PY" -m pip install --quiet "$SPEC_PATH$([ "$WITH_MCP" = "1" ] && echo "[mcp]")"
else
    run "$PY" -m pip install --quiet "$SPEC"
fi

# ── 5. Configuration: create a template only if nothing is there ────────
if [ -f "$CONFIG_FILE" ]; then
    say "Config exists — not modified: $CONFIG_FILE"
else
    say "Writing config template: $CONFIG_FILE"
    run mkdir -p "$CONFIG_DIR"
    if [ -f "$SOURCE_DIR/harness_config/templates/config.yaml" ]; then
        run cp "$SOURCE_DIR/harness_config/templates/config.yaml" "$CONFIG_FILE"
    else
        run printf '# Cloud Harness CLI config — see docs/user-manual.md\naccounts:\n  defaults: {}\n' > "$CONFIG_FILE"
    fi
    run chmod 600 "$CONFIG_FILE"
fi

# ── 6. Optional: local store ────────────────────────────────────────────
if [ "$INIT_DB" = "1" ]; then
    say "Initialising the local store…"
    run "$BINDIR/harness" init-db || warn "init-db failed — will be created on first use"
else
    say "Local store: not created (pass --init-db to create it now)"
fi

# ── 7. Verify ───────────────────────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
    say "Dry run — nothing was changed."
    exit 0
fi

say "Verifying…"
"$BINDIR/harness" version || die "harness did not run — see errors above"
"$BINDIR/harness" plugins | head -3 || true
if [ "$WITH_MCP" = "1" ]; then
    "$PY" -c "from mcp.server.fastmcp import FastMCP" \
        && say "MCP server dependency present ✓" \
        || warn "MCP SDK missing — 'harness serve-mcp' will not start"
fi

cat <<EOF

Installed to: $VENV
Command     : $BINDIR/harness

Add it to PATH:
    echo 'export PATH="$BINDIR:\$PATH"' >> ~/.bashrc && source ~/.bashrc

Next:
    1. AWS profiles in ~/.aws/credentials (or SSO), then edit
       $CONFIG_FILE
    2. Verify:  harness whoami && harness doctor
    3. Optional: harness serve-mcp   (MCP clients: docs/mcp-clients.md)

Nothing was changed outside $PREFIX and $CONFIG_DIR.
EOF
