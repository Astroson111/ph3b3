#!/usr/bin/env bash
set -e

PH3B3_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PH3B3_DIR/.venv"

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

# Bring up WireGuard if WG_INTERFACE is set in .env
if [ -n "${WG_INTERFACE:-}" ]; then
    if ! ip addr show "$WG_INTERFACE" 2>/dev/null | grep -q "inet "; then
        echo "WireGuard $WG_INTERFACE not up — attempting to start..."
        sudo wg-quick up "$WG_INTERFACE" 2>/dev/null \
            && echo "WireGuard started." \
            || echo "WARNING: Could not start WireGuard. Run: sudo wg-quick up $WG_INTERFACE"
    else
        echo "WireGuard up: $(ip addr show "$WG_INTERFACE" | grep 'inet ' | awk '{print $2}')"
    fi
fi

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
echo "Ph3b3 running at $HOST_IP:$PORT"

cd "$PH3B3_DIR"
exec python agent/server.py
