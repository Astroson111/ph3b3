"""One context window for HEAVY_MODEL, shared by every caller.

WHY THIS MODULE EXISTS. Ollama cannot hold one model at two context sizes. Ask
for the same model at a different num_ctx and it tears the runner down and
rebuilds it — the model stays "loaded" the whole time, so a residency check
still passes and nothing looks wrong.

Measured 2026-10-04 from ollama's own log, every single turn:

    load KvSize:4096   -> loaded runners count=1     triage
    load KvSize:16384  -> loaded runners count=1     chat
    load KvSize:4096   -> loaded runners count=1     triage
    load KvSize:16384  -> loaded runners count=1     chat

~1.25 s per rebuild, ~2.6 s per turn, on every turn she answers. It surfaced as
`load=2.05s` on the first generation of each turn once [gen] started logging
durations, and it had been invisible before that.

It also explains the 114 TRIAGE_FAILOPEN_EVICTED events: triage is
resident-only and fails open when the model looks absent, and the chat call was
rebuilding the runner out from under it every turn. Those were never a VRAM
shortage — and the "judge + chat = 16.1 GB on a 16 GB card" theory they fed was
wrong at the root, because triage.py:32 and server.py:99 read the SAME env var.
The judge IS the chat model.

So: callers do not choose a context size. They import NUM_CTX. A second number
anywhere costs a runner rebuild per turn, and tests/test_num_ctx_alignment.py
fails the build if one appears.
"""
import os

# The one window. PH3B3_CHAT_NUM_CTX is the knob, kept for backward
# compatibility with the name server.py introduced when it raised the window to
# fit the tool schemas.
#
# 16384 is deliberate and documented at server.py's CHAT_NUM_CTX: it costs
# roughly 2 GB more KV cache than 8192, which matters because Morpheus and
# ComfyUI compete for the same 16 GB card. Raising it further is not free.
NUM_CTX = int(os.getenv("PH3B3_CHAT_NUM_CTX", "16384"))

# Every model that must share NUM_CTX resolves from this env var. Listed here so
# the alignment test knows what "a HEAVY_MODEL call" means without guessing.
HEAVY_MODEL_ENV = ("PH3B3_HEAVY_MODEL", "PH3B3_MODEL")
