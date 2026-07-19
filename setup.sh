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
if [ ! -f "$PH3B3_DIR/soul/soul.md" ]; then
    cp "$PH3B3_DIR/soul/soul_public.md" "$PH3B3_DIR/soul/soul.md"
    echo "Soul seeded from soul_public.md — customise soul/soul.md to give Ph3b3 her full identity."
fi

# ── Piper TTS voices (one-time download; ZERO runtime network fetches) ─────────
# Alba (en) is Phoebe's voice; the others power the Language & Voice selector.
# ~60 MB each. Skips any already present. Must match config/voices.yaml.
VOICE_DIR="${PH3B3_DATA:-$HOME/ph3b3_data}/voices"
mkdir -p "$VOICE_DIR"
HF="https://huggingface.co/rhasspy/piper-voices/resolve/main"
declare -A VOICES=(
  [en_GB-alba-medium]="en/en_GB/alba/medium"
  [es_ES-davefx-medium]="es/es_ES/davefx/medium"
  [fr_FR-siwis-medium]="fr/fr_FR/siwis/medium"
  [de_DE-thorsten-medium]="de/de_DE/thorsten/medium"
  [zh_CN-huayan-medium]="zh/zh_CN/huayan/medium"
)
echo "Fetching Piper voices (~300 MB total, one-time) → $VOICE_DIR"
for name in "${!VOICES[@]}"; do
  if [ -f "$VOICE_DIR/$name.onnx" ]; then echo "  $name already present"; continue; fi
  echo "  downloading $name (~60 MB)..."
  curl -fsSL "$HF/${VOICES[$name]}/$name.onnx"      -o "$VOICE_DIR/$name.onnx"
  curl -fsSL "$HF/${VOICES[$name]}/$name.onnx.json" -o "$VOICE_DIR/$name.onnx.json"
done

echo "Ph3b3 Setup Complete"
echo "Nyx IP: $(hostname -I | awk '{print $1}')"
