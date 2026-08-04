#!/usr/bin/env bash
#
# Ph3b3 — one-command installer.
#
#   curl -fsSL https://raw.githubusercontent.com/Astroson111/ph3b3/main/install.sh | bash
#
# This is the *bootstrap*: it gets a bare machine to the point where `./start.sh`
# works. It installs what setup.sh does not — Ollama and her models, the VAD
# model, a .env — then hands off to setup.sh for the venv, system packages and
# Piper voices. Running it twice is safe: every step checks before it acts.
#
# Nothing here phones home. The only things downloaded are Ollama, the language
# models, Python packages, and the hash-pinned voice models — all from their
# upstream sources, all onto your disk, none of it reported anywhere.
set -euo pipefail

REPO_URL="${PH3B3_REPO_URL:-https://github.com/Astroson111/ph3b3.git}"
BRANCH="${PH3B3_BRANCH:-main}"
INSTALL_DIR="${PH3B3_INSTALL_DIR:-$HOME/ph3b3}"
VOICES="${PH3B3_VOICES:-en}"     # en | all  (see setup.sh; 'en' is Alba alone, ~60 MB)
PULL_MODELS=1
ASSUME_YES=0

# ── Output helpers ────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    B=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; N=$'\033[0m'
else
    B=""; DIM=""; GRN=""; YEL=""; RED=""; N=""
fi
step() { echo; echo "${B}==> $*${N}"; }
ok()   { echo "  ${GRN}✓${N} $*"; }
note() { echo "  ${DIM}$*${N}"; }
warn() { echo "  ${YEL}!${N} $*"; }
die()  { echo; echo "${RED}✗ $*${N}" >&2; exit 1; }

# Prompts must read from the terminal, not stdin — stdin is this script when
# the installer is piped from curl.
ask_yes_no() {  # ask_yes_no <question> ; returns 0 for yes
    local q="$1" reply
    [ "$ASSUME_YES" = 1 ] && return 0
    [ -e /dev/tty ] || return 0          # non-interactive (CI): take the default
    read -r -p "  $q [Y/n] " reply < /dev/tty || return 0
    [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

usage() {
    cat <<'EOF'
Ph3b3 installer

  install.sh [options]

Options:
  --dir <path>        Where to install her       (default: ~/ph3b3)
  --branch <name>     Branch to install          (default: main)
  --voices en|all     Voice models to download   (default: en — Alba only, ~60 MB)
                      'all' fetches all 19 voices / 15 languages (~1.2 GB)
  --no-models         Skip the Ollama model pulls (~9 GB) — do them yourself later
  --yes               Answer yes to every prompt (unattended install)
  --help              This text

Environment overrides: PH3B3_INSTALL_DIR, PH3B3_BRANCH, PH3B3_VOICES, PH3B3_REPO_URL
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)        INSTALL_DIR="${2:?--dir needs a path}"; shift 2 ;;
        --branch)     BRANCH="${2:?--branch needs a name}"; shift 2 ;;
        --voices)     VOICES="${2:?--voices needs en or all}"; shift 2 ;;
        --no-models)  PULL_MODELS=0; shift ;;
        --yes|-y)     ASSUME_YES=1; shift ;;
        --help|-h)    usage; exit 0 ;;
        *)            die "Unknown option: $1  (try --help)" ;;
    esac
done
case "$VOICES" in en|all) ;; *) die "--voices must be 'en' or 'all', got '$VOICES'" ;; esac

cat <<EOF

${B}Ph3b3${N} — a fully local AI assistant.
${DIM}No cloud. No data centers. Built in a basement in Pennsylvania.${N}

EOF

# ── 1. Preflight ──────────────────────────────────────────────────────────────
# Fail here, loudly, rather than half-installing and failing at first boot.
step "Checking this machine"

[ "$(uname -s)" = "Linux" ] || die "Ph3b3 installs on Linux (Ubuntu 22.04+ is the tested target).
   On Windows, see the 'windows' branch for Ph3b3-Light under WSL2."

command -v apt-get >/dev/null 2>&1 || die "This installer uses apt (Debian/Ubuntu).
   On another distro, install the deps by hand — see INSTALL.md — then run ./setup.sh."
ok "Linux with apt"

command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.11 or newer."
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' \
    || die "Python $PY_VER found, but Ph3b3 needs 3.11 or newer.
   sudo apt install python3.11 python3.11-venv"
ok "Python $PY_VER"

if ! sudo -n true 2>/dev/null; then
    note "Some steps need sudo (apt packages, Ollama). You'll be prompted."
fi

# She needs the GPU for Hermes3, Whisper and Morpheus. Not fatal — a user may be
# installing on a box they'll add a card to — but it must not be a surprise later.
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)"
    ok "GPU: ${GPU:-detected}"
else
    warn "No NVIDIA GPU detected."
    note "Hermes3, Whisper and Morpheus need CUDA — she will install but run badly or not at all."
    ask_yes_no "Install anyway?" || exit 1
fi

# ~40 GB: models (~9 GB), torch + deps (~6 GB), voices, and her data directory.
NEED_GB=40
AVAIL_GB="$(df -BG --output=avail "$HOME" | tail -1 | tr -dc '0-9')"
if [ "${AVAIL_GB:-0}" -lt "$NEED_GB" ]; then
    warn "${AVAIL_GB} GB free in $HOME — a full install wants about ${NEED_GB} GB."
    ask_yes_no "Continue?" || exit 1
else
    ok "${AVAIL_GB} GB free"
fi

for pkg in git curl; do
    command -v "$pkg" >/dev/null 2>&1 || { note "installing $pkg"; sudo apt-get install -y -qq "$pkg"; }
done

# ── 2. Source ─────────────────────────────────────────────────────────────────
# If this script is being run from inside an existing clone, use that clone —
# don't clone a second copy alongside the one the user already has.
step "Getting Ph3b3"

SELF_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/setup.sh" ] && [ -f "$SELF_DIR/agent/server.py" ]; then
    PH3B3_DIR="$SELF_DIR"
    ok "Using this clone: $PH3B3_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
    PH3B3_DIR="$INSTALL_DIR"
    ok "Already installed at $PH3B3_DIR"
    if ask_yes_no "Pull the latest $BRANCH?"; then
        git -C "$PH3B3_DIR" fetch --quiet origin "$BRANCH"
        # Never clobber local edits — soul.md, .env and config are the user's.
        if git -C "$PH3B3_DIR" diff --quiet && git -C "$PH3B3_DIR" diff --cached --quiet; then
            git -C "$PH3B3_DIR" checkout --quiet "$BRANCH"
            git -C "$PH3B3_DIR" merge --ff-only --quiet "origin/$BRANCH" \
                && ok "Updated to latest $BRANCH" \
                || warn "Couldn't fast-forward — your branch has diverged. Merge by hand."
        else
            warn "You have uncommitted changes — leaving the working tree alone."
        fi
    fi
else
    [ -e "$INSTALL_DIR" ] && die "$INSTALL_DIR exists but isn't a Ph3b3 clone. Move it, or pass --dir <path>."
    note "Cloning $REPO_URL ($BRANCH) → $INSTALL_DIR"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    PH3B3_DIR="$INSTALL_DIR"
    ok "Cloned to $PH3B3_DIR"
fi
cd "$PH3B3_DIR"

# ── 3. Ollama + her models ────────────────────────────────────────────────────
# setup.sh does not do this, and without it she boots with no brain.
step "Ollama and language models"

if command -v ollama >/dev/null 2>&1; then
    ok "Ollama already installed"
else
    note "Installing Ollama from ollama.com"
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installed"
fi

if ! pgrep -x ollama >/dev/null 2>&1; then
    note "Starting Ollama"
    (ollama serve >/dev/null 2>&1 &)
    for _ in $(seq 1 20); do
        curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 && break
        sleep 1
    done
fi
curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1 \
    && ok "Ollama running on :11434" \
    || warn "Ollama isn't answering on :11434 — model pulls may fail."

if [ "$PULL_MODELS" = 1 ]; then
    # hermes3 is her brain; llava is every vision tool (camera, image describe).
    for model in hermes3 llava; do
        if ollama list 2>/dev/null | awk '{print $1}' | grep -q "^${model}\(:latest\)\?$"; then
            ok "$model already pulled"
        else
            note "Pulling $model (~4.7 GB) — this is the long part"
            ollama pull "$model"
            ok "$model pulled"
        fi
    done
else
    warn "Skipped model pulls (--no-models). Before first run:  ollama pull hermes3 && ollama pull llava"
fi

# ── 4. Configuration ──────────────────────────────────────────────────────────
# .env holds her credentials. We seed it from the example so start.sh doesn't
# warn, and leave the actual username/password to the first-run web wizard.
step "Configuration"

if [ -f .env ]; then
    ok ".env already exists — left untouched"
else
    cp .env.example .env
    chmod 600 .env
    ok "Created .env from .env.example"
    note "Web-UI credentials get set in the browser wizard on first run."
fi

# ── 5. Everything else (venv, apt packages, Piper voices) ─────────────────────
step "Running setup.sh"
note "System packages, Python venv, and Piper voices (--voices $VOICES)"
chmod +x setup.sh start.sh
PH3B3_VOICES="$VOICES" ./setup.sh

# ── 6. Verify ─────────────────────────────────────────────────────────────────
step "Checking the install"

FAILED=0
check() { if eval "$2"; then ok "$1"; else warn "$1 — MISSING"; FAILED=1; fi; }
check "Python venv"          '[ -x .venv/bin/python ]'
check "Piper TTS binary"     '[ -x .venv/bin/piper ] || command -v piper >/dev/null 2>&1'
check "Alba voice model"     '[ -f "${PH3B3_DATA:-$HOME/ph3b3_data}/voices/en_GB-alba-medium.onnx" ]'
check "Silero VAD model"     '[ -f models/silero_vad.onnx ]'
check "Her identity (soul)"  '[ -f soul/soul.md ]'
check ".env"                 '[ -f .env ]'
if [ "$PULL_MODELS" = 1 ]; then
    check "hermes3 in Ollama" 'ollama list 2>/dev/null | grep -q hermes3'
fi

# ── Done ──────────────────────────────────────────────────────────────────────
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if [ "$FAILED" = 0 ]; then
    echo "${GRN}${B}Ph3b3 is installed.${N}"
else
    echo "${YEL}${B}Installed, with gaps above.${N} See INSTALL.md for the manual steps."
fi
cat <<EOF

  ${B}Wake her up:${N}

      cd $PH3B3_DIR
      ./start.sh

  Then open the first-run setup wizard from any browser on your network:

      ${B}http://${HOST_IP:-localhost}:7331/setup${N}

  It walks you through her name for you, the web-UI username and password,
  and the optional pieces (weather key, music, remote access).

  ${DIM}Read README.md — especially "What you are talking to" — before you trust
  anything she says. Local does not mean correct.${N}

EOF
if [ "$VOICES" = "en" ]; then
    cat <<EOF
  ${DIM}She speaks English (Alba) right now. For all 15 languages (~1.2 GB):
      PH3B3_VOICES=all ./setup.sh${N}

EOF
fi
