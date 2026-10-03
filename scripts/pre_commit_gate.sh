#!/bin/bash
# Pre-commit gate for agent/ — undefined and unused names.
#
# WHY THIS EXISTS, precisely. On 2026-10-03 a change to the chat pipeline used a
# bare `session_id`; in _run_chat_pipeline the id only exists as
# body.get("session_id","default"). Every /chat turn returned HTTP 500 for
# thirteen minutes. The thing that let it through was treating `ast.parse` as a
# check: parsing proves the file is syntactically valid and says NOTHING about
# whether a name resolves. A NameError is a runtime failure.
#
# ruff's F821 catches exactly that case — verified against the real broken line
# before this gate was written.
#
#   F821  undefined name          <- the bug above
#   F841  local assigned, never used  <- usually a rename left half-done
#
# FAILS LOUDLY IF RUFF IS MISSING. A gate that skips when its tool is absent is
# the "green on nothing" failure: it reports success for having checked nothing.
# ruff is a dev dependency and deliberately NOT in requirements.txt (the service
# does not need it), so install it with:  .venv/bin/pip install ruff
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

RUFF=".venv/bin/ruff"
[ -x "$RUFF" ] || RUFF="$(command -v ruff 2>/dev/null)"
if [ -z "${RUFF:-}" ] || [ ! -x "$RUFF" ]; then
  echo "pre-commit: FAIL — ruff not found." >&2
  echo "  install it:  .venv/bin/pip install ruff" >&2
  echo "  this gate refuses to pass by skipping; see the note in this script." >&2
  exit 1
fi

echo "pre-commit: ruff check --select F821,F841 agent/"
if ! "$RUFF" check --select F821,F841 agent/; then
  echo >&2
  echo "pre-commit: FAIL — an undefined or unused name in agent/." >&2
  echo "  F821 is the class of bug that 500'd /chat on 2026-10-03." >&2
  exit 1
fi
echo "pre-commit: clean"
