#!/usr/bin/env bash
# start_ph3b3.sh — bring Ph3b3 up cleanly:
#   1. verify Ollama is serving and the chat model is pulled
#   2. activate the virtualenv
#   3. free port 7331 if something is holding it
#   4. launch the FastAPI app (agent/server.py -> app) under uvicorn
set -euo pipefail

# Resolve the repo root from this script's own location, so it works no matter
# where the repo is cloned or which directory you launch it from.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$SCRIPT_DIR"

# --- Load config from .env (falls back to sane defaults) -------------------
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
MODEL="${PH3B3_MODEL:-hermes3}"
HOST="${PH3B3_HOST:-0.0.0.0}"
PORT="${PH3B3_PORT:-7331}"
VENV="$SCRIPT_DIR/.venv"

# --- 1. Verify Ollama is serving Hermes3 -----------------------------------
echo "[1/4] Checking Ollama at $OLLAMA_HOST ..."
if ! curl -sf -m 5 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    # Not up. If ollama is installed locally, start it; otherwise it's remote
    # (e.g. on the Windows host via WSL mirroring) and we just wait/fail.
    if command -v ollama >/dev/null 2>&1; then
        echo "      Ollama not responding — starting 'ollama serve'..."
        nohup ollama serve >/dev/null 2>&1 &
        for _ in $(seq 1 15); do
            curl -sf -m 2 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && break
            sleep 1
        done
    fi
fi
if ! curl -sf -m 5 "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
    echo "ERROR: Ollama is not reachable at $OLLAMA_HOST." >&2
    exit 1
fi
# Confirm the model is pulled. Tags JSON looks like "name":"hermes3:latest";
# matching "$MODEL (with the leading quote) avoids false positives.
if ! curl -sf -m 5 "$OLLAMA_HOST/api/tags" | grep -q "\"${MODEL}"; then
    echo "ERROR: model '$MODEL' is not pulled. Run:  ollama pull $MODEL" >&2
    exit 1
fi
echo "      Ollama OK — '$MODEL' is available."

# --- 2. Activate the virtualenv --------------------------------------------
echo "[2/4] Activating venv ..."
if [ ! -f "$VENV/bin/activate" ]; then
    echo "ERROR: venv not found at $VENV — run ./setup.sh first." >&2
    exit 1
fi
# shellcheck source=/dev/null
. "$VENV/bin/activate"

# --- 3. Free port $PORT if held --------------------------------------------
echo "[3/4] Ensuring port $PORT is free ..."
if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then
    echo "      Port $PORT in use — stopping the holder(s)..."
    lsof -ti "tcp:$PORT" | xargs -r kill 2>/dev/null || true
    sleep 1
    if lsof -ti "tcp:$PORT" >/dev/null 2>&1; then   # stubborn — force it
        lsof -ti "tcp:$PORT" | xargs -r kill -9 2>/dev/null || true
        sleep 1
    fi
fi

# --- 4. Launch uvicorn ------------------------------------------------------
# agent/ is not a Python package, so point uvicorn at it with --app-dir
# (absolute, so server.py's ROOT = repo root resolves correctly).
echo "[4/4] Starting Ph3b3 on http://$HOST:$PORT ..."
exec uvicorn server:app --app-dir "$SCRIPT_DIR/agent" --host "$HOST" --port "$PORT" --log-level warning
