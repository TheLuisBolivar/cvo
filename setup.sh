#!/usr/bin/env bash
# cv-optimizer — one-shot bootstrap script.
#
# Idempotent: safe to re-run. Anything already in place is skipped.

set -euo pipefail

print_help() {
    cat <<'EOF'
setup.sh — bootstrap cv-optimizer

What this script does (in order):
  1. Verifies Python 3.10+ is available.
  2. Creates a virtual environment at .venv/  (if missing).
  3. Upgrades pip inside the venv.
  4. Installs the package in editable mode  (`pip install -e .`)
     — this also exposes the `cvo` command inside the venv.
  5. Creates data/pdfs/ and data/json/ folders for your CVs / parsed JSON.
  6. Copies .env.example → .env  (only if .env does not exist).
  7. Runs `cvo setup`  (interactive provider + API-key wizard).
  8. Prints a "next steps" summary.

Usage:
  ./setup.sh                   Run setup (idempotent).
  SKIP_WIZARD=1 ./setup.sh     Skip the interactive wizard at step 7.
  ./setup.sh --help            Show this help.

After setup, you'll typically:
  source .venv/bin/activate
  $EDITOR .env                                 # paste your API keys
  cvo --help                                   # see all commands
  cvo run --cv examples/cv_example.json \
          --offer examples/offer_example.txt   # quick smoke test

Requirements:
  - python3 (3.10 or newer)
  - pip
  - Internet access (to install dependencies)
EOF
}

# ── Argument parsing ──────────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    print_help
    exit 0
fi
if [[ $# -gt 0 ]]; then
    echo "Unknown argument: $1" >&2
    echo "Run './setup.sh --help' for usage." >&2
    exit 2
fi

# ── Pretty printers ───────────────────────────────────────────────────
if [[ -t 1 ]]; then
    C_INFO='\033[36m'; C_OK='\033[32m'; C_WARN='\033[33m'; C_ERR='\033[31m'; C_BOLD='\033[1m'; C_OFF='\033[0m'
else
    C_INFO=''; C_OK=''; C_WARN=''; C_ERR=''; C_BOLD=''; C_OFF=''
fi
info() { printf "${C_INFO}ℹ  %s${C_OFF}\n" "$*"; }
ok()   { printf "${C_OK}✓  %s${C_OFF}\n"   "$*"; }
warn() { printf "${C_WARN}⚠  %s${C_OFF}\n" "$*"; }
err()  { printf "${C_ERR}✗  %s${C_OFF}\n"  "$*" >&2; }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

printf "\n${C_BOLD}cv-optimizer · setup${C_OFF}\n"
printf "Project root: %s\n\n" "$PROJECT_ROOT"

# ── 1. Python check ───────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found in PATH. Install Python 3.10+ first."
    exit 1
fi
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
info "Python detected: $PYTHON_VERSION"
python3 - <<'PY' || { err "Python >= 3.10 is required."; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
ok "Python version OK"

# ── 2. Virtual environment ────────────────────────────────────────────
if [[ -d .venv ]]; then
    ok ".venv already exists — reusing it"
else
    info "Creating virtual environment at .venv/"
    python3 -m venv .venv
    ok ".venv created"
fi

VENV_PIP=".venv/bin/pip"
VENV_PY=".venv/bin/python"

# ── 3. Upgrade pip ────────────────────────────────────────────────────
info "Upgrading pip inside the venv"
"$VENV_PIP" install --upgrade pip --quiet
ok "pip up to date"

# ── 4. Editable install ───────────────────────────────────────────────
info "Installing cv-optimizer in editable mode (this also installs deps)"
"$VENV_PIP" install -e . --quiet
if "$VENV_PY" -c "import cv_optimizer" 2>/dev/null; then
    ok "Package installed — \`cvo\` command is available inside the venv"
else
    err "Package import failed after install. Check the output above."
    exit 1
fi

# ── 5. Data folders ───────────────────────────────────────────────────
for dir in data/pdfs data/json data/docx data/offers output; do
    if [[ -d "$dir" ]]; then
        ok "$dir/ already exists"
    else
        mkdir -p "$dir"
        ok "Created $dir/"
    fi
    # .gitkeep so the (otherwise ignored) directory stays in git
    if [[ ! -f "$dir/.gitkeep" ]]; then
        : > "$dir/.gitkeep"
    fi
done

# ── 6. .env ───────────────────────────────────────────────────────────
if [[ -f .env ]]; then
    ok ".env already exists — leaving it untouched"
else
    if [[ -f .env.example ]]; then
        cp .env.example .env
        ok "Copied .env.example → .env  (edit it and add your API keys)"
    else
        warn ".env.example not found — skipping .env creation"
    fi
fi

# ── 7. Provider + API-key wizard ──────────────────────────────────────
# Skip the wizard in non-interactive runs (CI, scripts piped from stdin).
# Use SKIP_WIZARD=1 ./setup.sh to opt out explicitly.
if [[ -t 0 && "${SKIP_WIZARD:-0}" != "1" ]]; then
    info "Launching the provider + API-key wizard (\`cvo setup\`)…"
    info "Press Ctrl-C to skip — you can always run \`cvo setup\` later."
    printf "\n"
    if ! "$VENV_PY" -m cv_optimizer.cli setup; then
        warn "Wizard exited without finishing. Run \`cvo setup\` later when ready."
    fi
else
    info "Non-interactive shell or SKIP_WIZARD=1 — skipping \`cvo setup\`."
    info "Run it later with: source .venv/bin/activate && cvo setup"
fi

# ── 8. Summary ────────────────────────────────────────────────────────
printf "\n${C_BOLD}Next steps:${C_OFF}\n"
printf "  1. Activate the venv:    ${C_INFO}source .venv/bin/activate${C_OFF}\n"
printf "  2. Smoke test:\n"
printf "       ${C_INFO}cvo run --cv examples/cv_example.json --offer examples/offer_example.txt${C_OFF}\n"
printf "  3. Drop your CV PDFs in: ${C_INFO}data/pdfs/${C_OFF}  (gitignored)\n"
printf "     Parsed JSONs go in:   ${C_INFO}data/json/${C_OFF}  (gitignored)\n"
printf "  4. Re-run wizard later:  ${C_INFO}cvo setup${C_OFF}\n"
printf "\n"
ok "Setup complete."
