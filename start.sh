#!/usr/bin/env bash
set -e

PH3B3_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PH3B3_DIR/.venv"

# ── WireGuard note (for auditors) ─────────────────────────────────────────────
# There is NO WireGuard here, by design. Remote access is a user-toggled control,
# not a boot step: POST /iris/tunnel in agent/server.py runs `wg-quick up/down
# wg0`. The tunnel is DOWN by default (zero exposure at home). WG keys/config live
# in /etc/wireguard (root-owned, backed up by Rhea). Audit the tunnel there — this
# script only loads .env and starts the server.

# Load credentials and config from .env
if [ -f "$PH3B3_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$PH3B3_DIR/.env"
    set +a
else
    echo "WARNING: .env not found. Copy .env.example to .env and fill in your values."
fi

export DISPLAY="${DISPLAY:-:0}"
export SPOTIPY_REDIRECT_URI="${SPOTIPY_REDIRECT_URI:-http://127.0.0.1:8888/callback}"

echo "Ph3b3 waking up..."

if ! pgrep -x ollama > /dev/null; then
    ollama serve &
    sleep 3
fi

if [ ! -d "$VENV" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source "$VENV/bin/activate"

HOST_IP=$(hostname -I | awk '{print $1}')
PORT="${PH3B3_PORT:-7331}"
SCHEME="http"
if [ -n "${PH3B3_SSL_CERT:-}" ] && [ -n "${PH3B3_SSL_KEY:-}" ]; then
    SCHEME="https"
fi
echo "Ph3b3 running at $SCHEME://$HOST_IP:$PORT"
if [ "$SCHEME" = "https" ]; then
    echo "  (self-signed cert — browser will warn once; click Advanced → Proceed)"
fi

if [ ! -f "$HOME/ph3b3_data/setup_complete" ]; then
    echo ""
    echo "┌─────────────────────────────────────────────────────────┐"
    echo "│  Ph3b3 FIRST-TIME SETUP                                 │"
    echo "│  Open this address in any browser on this network:      │"
    echo "│                                                         │"
    echo "│  $SCHEME://$HOST_IP:$PORT/setup"
    echo "│                                                         │"
    echo "└─────────────────────────────────────────────────────────┘"
    echo ""
fi

cd "$PH3B3_DIR"
exec python agent/server.py
