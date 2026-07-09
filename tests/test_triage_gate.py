"""
Tests for the triage gate (modules/triage.py) — fail-open behaviour + parsing.

Run:  .venv/bin/python tests/test_triage_gate.py
No GPU / no Ollama / no model load — httpx.AsyncClient is faked so every path
(timeout, conn error, malformed output, evicted model) is exercised deterministically.
Covers TEST GATES 3 (timeout fail-open) and 4 (malformed → never 500/silence),
plus the strict-JSON / prose-fallback / resident-only paths.
"""
import asyncio
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import triage          # noqa: E402
import httpx           # noqa: E402

# capture the cause-differentiated log lines
_logs: list[str] = []
class _Cap(logging.Handler):
    def emit(self, r): _logs.append(r.getMessage())
triage.log.addHandler(_Cap()); triage.log.setLevel(logging.INFO)

HERMES = [{"name": triage.HERMES_MODEL}]

class _Resp:
    def __init__(self, d): self._d = d
    def json(self): return self._d

def _fake_client(ps_models, post_fn):
    class C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, timeout=None): return _Resp({"models": ps_models})
        async def post(self, url, json=None, timeout=None): return post_fn()
    return C

def run(user, ctx, ps_models, post_fn):
    triage.httpx.AsyncClient = _fake_client(ps_models, post_fn)
    _logs.clear()
    return asyncio.run(triage.triage_gate(user, ctx))

def content(c): return lambda: _Resp({"message": {"content": c}})
def raises(exc):
    def _p(): raise exc
    return _p

_results = []
def check(name, ok, extra=""):
    _results.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name, (f"  [{extra}]" if extra and not ok else ""))

# ── strict JSON: hold ─────────────────────────────────────────────────────────
r = run("summarize the file", "", HERMES,
        content('{"answerable": false, "missing": ["file"], "question": "Which file?"}'))
check("strict JSON hold → answerable=False + question", (not r.answerable) and r.question == "Which file?", extra=str(r))
check("hold carries missing fields", r.missing == ["file"], extra=str(r.missing))

# ── strict JSON: pass ─────────────────────────────────────────────────────────
r = run("capital of France", "", HERMES, content('{"answerable": true, "missing": [], "question": null}'))
check("strict JSON pass → answerable=True", r.answerable, extra=str(r))

# ── GATE 3: timeout → fail open, cause-differentiated ─────────────────────────
r = run("x", "", HERMES, raises(httpx.TimeoutException("t")))
check("GATE3 timeout → fail OPEN (answerable=True)", r.answerable)
check("GATE3 logs TRIAGE_FAILOPEN_TIMEOUT", any("TRIAGE_FAILOPEN_TIMEOUT" in m for m in _logs), extra=str(_logs))

# ── conn error → fail open CONN ───────────────────────────────────────────────
r = run("x", "", HERMES, raises(httpx.ConnectError("down")))
check("conn error → fail OPEN + TRIAGE_FAILOPEN_CONN", r.answerable and any("TRIAGE_FAILOPEN_CONN" in m for m in _logs), extra=str(_logs))

# ── GATE 4: malformed non-JSON, no verdict → fail open PARSE (never raises) ────
r = run("x", "", HERMES, content("sorry, I got confused and produced nothing useful"))
check("GATE4 garbage → fail OPEN + TRIAGE_FAILOPEN_PARSE", r.answerable and any("TRIAGE_FAILOPEN_PARSE" in m for m in _logs), extra=str(_logs))

# ── prose fallback: verdict recoverable from non-strict text ──────────────────
r = run("summarize the file", "", HERMES, content('Reasoning… answerable: false. question: "Which file did you mean?"'))
check("prose fallback → answerable=False", not r.answerable, extra=str(r))
check("prose fallback recovers question", r.question == "Which file did you mean?", extra=str(r.question))

# ── fenced JSON (model wrapped it) still parses ───────────────────────────────
r = run("x", "", HERMES, content('```json\n{"answerable": true}\n```'))
check("fenced JSON parses → answerable=True", r.answerable, extra=str(r))

# ── resident-only: model evicted → fail open EVICTED, no reload attempt ───────
def _boom(): raise AssertionError("post must NOT be called when Hermes is evicted")
r = run("x", "", [], _boom)   # empty /api/ps → not resident
check("evicted model → fail OPEN + TRIAGE_FAILOPEN_EVICTED", r.answerable and any("TRIAGE_FAILOPEN_EVICTED" in m for m in _logs), extra=str(_logs))
check("evicted → triage inference NOT attempted (no reload)", not any("must NOT be called" in m for m in _logs))

passed = sum(1 for _, ok in _results if ok)
print(f"\n{passed}/{len(_results)} passed")
sys.exit(0 if passed == len(_results) else 1)
