#!/usr/bin/env bash
export DISPLAY=:1
cd "$(dirname "$0")"
source .venv/bin/activate && python3 agent/chat_ui.py
