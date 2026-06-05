#!/usr/bin/env bash
export DISPLAY=:0
export SPOTIPY_CLIENT_ID="384543436c64412eb46a9bf929ae05d0"
export SPOTIPY_CLIENT_SECRET="d607fa08562f42c394ac0a395bc22468"
export SPOTIPY_REDIRECT_URI="http://127.0.0.1:8888/callback"
set -e
PH3B3_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PH3B3_DIR/.venv"
echo "Ph3b3 waking up on Nyx..."

# Ensure WireGuard VPN is up (10.0.0.1 = Nyx)
if ! ip addr show wg0 2>/dev/null | grep -q "10.0.0.1"; then
    echo "WireGuard wg0 not up — attempting to start..."
    sudo wg-quick up wg0 2>/dev/null && echo "WireGuard started." || echo "WARNING: Could not start WireGuard. Run: sudo wg-quick up wg0"
else
    echo "WireGuard up: $(ip addr show wg0 | grep 'inet ' | awk '{print $2}')"
fi

if ! pgrep -x ollama > /dev/null; then ollama serve & sleep 3; fi
if [ ! -d "$VENV" ]; then echo "Run setup.sh first"; exit 1; fi
source "$VENV/bin/activate"
NYX_IP=$(hostname -I | awk '{print $1}')
echo "Nyx: $NYX_IP:7331"
cd "$PH3B3_DIR"
exec python agent/server.py
