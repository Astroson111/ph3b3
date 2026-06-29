#!/usr/bin/env bash
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
LOG=""

# Stop ComfyUI (50-comfyui.rules covers this — no password)
if systemctl is-active --quiet comfyui.service; then
    systemctl stop comfyui.service
    LOG="ComfyUI stopped.\n"
else
    LOG="ComfyUI was not running.\n"
fi

# Evict all resident Ollama models via keep_alive:0
RUNNING=$(curl -sf "${OLLAMA_HOST}/api/ps" \
    | python3 -c "import sys,json; [print(m['model']) for m in json.load(sys.stdin).get('models',[])]" \
    2>/dev/null || true)

if [ -n "$RUNNING" ]; then
    while IFS= read -r model; do
        [ -n "$model" ] || continue
        curl -sf -X POST "${OLLAMA_HOST}/api/generate" \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"${model}\",\"keep_alive\":0}" -o /dev/null
        LOG+="Evicted: ${model}\n"
    done <<< "$RUNNING"
else
    LOG+="Ollama: no models loaded.\n"
fi

# Report GPU state
VRAM=$(nvidia-smi --query-gpu=name,memory.used,memory.free --format=csv,noheader 2>/dev/null \
    || echo "nvidia-smi unavailable")
LOG+="GPU: ${VRAM}"

notify-send -i /home/astroson/Downloads/ph3b3_face_wake_512.png \
    "⚡ GPU Freed" "$(printf '%b' "$LOG")" --expire-time=6000
