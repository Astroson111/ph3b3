"""
GPU calls must not own the event loop — regression suite.

THE INCIDENT. The panel stopped answering. The mechanism, found by reading
rather than by log evidence: Whisper's Python API is synchronous and runs on
CUDA, and three call sites invoked it (or Piper) directly from an `async def`.
FastAPI has one event loop in this process, so for the duration of that call
NOTHING was served — not /panel, not /health, not the chat stream — and if the
call never returned, nothing ever would be again.

    agent/server.py  /transcribe        stt.transcribe_file()   ~560 calls in 21 days
    agent/server.py  execute_tool       stt.listen()            blocks >=10s BY DESIGN
    agent/server.py  execute_tool       tts.speak()             default blocking=True

The `listen` tool had never once been called in 21 days of journal, so it was a
dormant landmine rather than the culprit. /transcribe ran on every voice turn.

WHAT THE FIX GUARANTEES, precisely: to_thread frees the LOOP, which is the part
that failed; wait_for frees the CALLER, so a wedged call produces a spoken
failure instead of a request that never answers. Neither kills the worker
thread. A stuck CUDA call keeps running until the driver returns it — the
server staying reachable is the promise, not the card being freed.

Run:  .venv/bin/python -m pytest tests/test_event_loop_not_blocked.py -v
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "agent" / "server.py"
sys.path.insert(0, str(REPO / "modules"))

SRC = SERVER.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
LINES = SRC.splitlines()

# Attributes on these modules reach a GPU or a subprocess and block until done.
BLOCKING = {
    ("stt", "listen"), ("stt", "transcribe_file"),
    ("tts", "synthesize_to_b64"), ("tts", "synth_pcm"),
}


def _async_defs():
    return [n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef)]


def _guarded(node):
    """True if this call is dispatched off the loop."""
    ctx = "\n".join(LINES[max(0, node.lineno - 4):node.lineno])
    return "to_thread" in ctx or "_gpu_bound" in ctx


def _direct_nodes(fn):
    """Walk an async def WITHOUT descending into nested function bodies.

    A blocking call inside a nested `def` is not on the loop at that point —
    what decides is how the nested def is dispatched. /voice/review does exactly
    this: a sync `_synth_ok` helper handed to asyncio.to_thread. Counting its
    innards as loop-blocking is a false positive, so nested defs are checked
    separately by test_a_nested_blocking_helper_is_dispatched_off_the_loop.
    """
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield n
        stack.extend(ast.iter_child_nodes(n))


def _nested_defs(fn):
    return [n for n in ast.iter_child_nodes(fn)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_no_blocking_gpu_call_runs_directly_on_the_event_loop():
    offenders = []
    for fn in _async_defs():
        for n in _direct_nodes(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            base = n.func.value
            if not isinstance(base, ast.Name):
                continue
            if (base.id, n.func.attr) in BLOCKING and not _guarded(n):
                offenders.append(f"{fn.name}():{n.lineno}  {LINES[n.lineno-1].strip()[:70]}")
    assert not offenders, (
        "a synchronous GPU call sits directly on the event loop — every route "
        "in the process stops while it runs:\n  " + "\n  ".join(offenders))


def test_every_tts_speak_in_an_async_def_is_non_blocking():
    """speak(blocking=True) runs a Piper subprocess on the loop. One call site
    relied on the default and froze the server on the STT failure path."""
    offenders = []
    for fn in _async_defs():
        for n in _direct_nodes(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "speak"):
                continue
            base = n.func.value
            if not (isinstance(base, ast.Name) and base.id == "tts"):
                continue
            kw = {k.arg: ast.unparse(k.value) for k in n.keywords}
            if kw.get("blocking") != "False" and not _guarded(n):
                offenders.append(f"{fn.name}():{n.lineno}  blocking={kw.get('blocking','DEFAULT True')}")
    assert not offenders, (
        "tts.speak blocks the event loop at:\n  " + "\n  ".join(offenders))


# ── the budget is measured, not invented ─────────────────────────────────────

def test_the_transcription_budget_scales_with_the_audio():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_srv", SERVER)
    # Importing server.py has side effects; read the constants instead.
    ns = {}
    for name in ("_STT_S_PER_AUDIO_S", "_STT_MIN_BUDGET_S", "_STT_MAX_BUDGET_S"):
        m = [ln for ln in LINES if ln.startswith(name)]
        assert m, f"{name} is gone — the budget stopped being a stated number"
        exec(m[0], ns)
    budget = lambda a: max(ns["_STT_MIN_BUDGET_S"],
                           min(ns["_STT_MAX_BUDGET_S"], a * ns["_STT_S_PER_AUDIO_S"]))
    # Measured on Nyx: 0.071s per audio-second on an idle card. A budget that
    # does not clear a real turn by a wide margin will cut off real speech.
    assert budget(0.26) >= 1.0, "a typical clip must not be near its own cap"
    assert budget(110.9) >= 110.9 * 0.071 * 10, "under 10x headroom over measured"
    assert budget(10_000) <= ns["_STT_MAX_BUDGET_S"], "no upper bound on the wait"


def test_a_timeout_is_surfaced_not_swallowed():
    """The failure mode this whole fix exists to end is silence. A transcription
    that times out must produce something the caller can render."""
    block = SRC[SRC.index("async def transcribe_audio"):]
    block = block[:block.index("\n@app.")] if "\n@app." in block else block
    assert "asyncio.TimeoutError" in block, "the timeout is not caught at /transcribe"
    seg = block[block.index("asyncio.TimeoutError"):][:600]
    assert "speak" in seg, "a timed-out turn says nothing to the person waiting"
    assert "_persist_capture" in seg, "a timed-out capture is not kept on record"


def test_the_listen_tool_budget_covers_its_own_recording():
    """listen() records for `duration` seconds BEFORE it transcribes. A budget
    that ignores that cuts off every long recording as if it had hung."""
    i = SRC.index('elif name == "listen"')
    seg = SRC[i:i + 900]
    assert "_gpu_bound" in seg, "listen() still runs on the event loop"
    assert "_dur +" in seg, "the budget ignores the recording duration"
    assert "blocking=False" in seg, "the failure line still speaks on the loop"


def test_a_nested_blocking_helper_is_dispatched_off_the_loop():
    """The other half of the exclusion above: a sync helper that wraps a
    blocking call is fine ONLY because it is handed to to_thread. If someone
    ever calls it directly, the loop blocks and the main scan would not see it."""
    offenders = []
    for fn in _async_defs():
        for nested in _nested_defs(fn):
            blocks = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and (n.func.value.id, n.func.attr) in BLOCKING
                for n in ast.walk(nested))
            if not blocks:
                continue
            body = "\n".join(LINES[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
            if f"to_thread({nested.name}" not in body:
                offenders.append(f"{fn.name}() -> {nested.name}():{nested.lineno}")
    assert not offenders, (
        "a helper wrapping a blocking GPU call is invoked on the loop:\n  "
        + "\n  ".join(offenders))
