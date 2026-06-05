#!/usr/bin/env bash
set -e
PH3B3_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PH3B3_DIR/.venv"
echo "Ph3b3 Setup Starting..."
sudo apt update -qq
sudo apt install -y ffmpeg portaudio19-dev python3-pyaudio libsndfile1 v4l-utils
if [ ! -d "$VENV" ]; then python3 -m venv "$VENV"; fi
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$PH3B3_DIR/requirements.txt"
echo "Ph3b3 Setup Complete"
echo "Nyx IP: $(hostname -I | awk '{print $1}')"
