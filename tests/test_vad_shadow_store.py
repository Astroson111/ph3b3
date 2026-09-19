"""
The shadow evaluation, logged and forgotten.

WHY IT IS STORED RATHER THAN LOGGED. A journal line answers the question once,
to whoever is grepping at the time, and then rotates away. The question here —
"would a windowed-majority endpoint have caught the turns the live rule missed,
and by how much" — needs to accumulate across many turns before it means
anything. So it goes into `vad_turns`, which already exists for exactly this,
is bounded and self-trimming, and is already served at /vad/turns.

WHY NOT MNEMOSYNE. That is her memory of her own life. Device telemetry in it
would be the same class of collision as two meanings of "canon" — a store whose
contents no longer match its name, and every later reader has to know which
kind of row they are looking at.

NOTHING READS THESE TO DECIDE ANYTHING. They accumulate and wait. When there is
enough, `summary()` answers the question in one sentence.

Run:  .venv/bin/python -m pytest tests/test_vad_shadow_store.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import vad_turns as V  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "LOG_PATH", tmp_path / "vad_turns.jsonl")
    return tmp_path


def _missed(run, need=21, at_ms=None, dur_ms=8000, pct=70, runs=4):
    return {"why": "shadow", "end": V.END_CAP, "ok": True, "dur_ms": dur_ms,
            "sh_run": run, "sh_need": need, "sh_at_ms": at_ms,
            "sh_pct": pct, "sh_runs": runs}


# ── the fields survive the round trip ────────────────────────────────────────

def test_shadow_fields_are_stored_and_read_back(store):
    V.record("stackchan", _missed(18, at_ms=1470))
    row = V.recent(10)[0]
    assert row["sh_run"] == 18 and row["sh_need"] == 21
    assert row["sh_at_ms"] == 1470


def test_unknown_fields_are_still_dropped(store):
    """The allowlist is the protection: a future field cannot start writing
    itself here without a deliberate edit."""
    V.record("stackchan", dict(_missed(18), transcript="hello there",
                               audio_b64="AAAA"))
    row = V.recent(10)[0]
    assert "transcript" not in row and "audio_b64" not in row


# ── the report answers the question ──────────────────────────────────────────

def test_no_data_says_so_rather_than_implying_zero(store):
    r = V.summary()
    assert r["shadow_turns"] == 0
    assert r["shadow_would_fire"] is None, "None, not 0 — absence is not a result"
    assert r["shadow_verdict"] == "no data yet"


def test_it_reports_how_many_missed_turns_the_new_rule_would_catch(store):
    for _ in range(3):
        V.record("stackchan", _missed(18, at_ms=1500))     # would have fired
    V.record("stackchan", _missed(19, at_ms=None))         # still would not
    r = V.summary()
    assert r["shadow_turns"] == 4
    assert r["shadow_would_fire"] == 3
    assert "3/4" in r["shadow_verdict"]


def test_it_reports_how_much_sooner(store):
    V.record("stackchan", _missed(18, at_ms=1500, dur_ms=8000))
    r = V.summary()
    assert r["shadow_saved_ms_avg"] == 6500
    assert "6500ms sooner" in r["shadow_verdict"]


def test_it_separates_counter_resets_from_never_paused(store):
    """The two shapes need opposite fixes, so the report must not blend them."""
    V.record("stackchan", _missed(0))          # never paused
    V.record("stackchan", _missed(18, at_ms=1400))   # counter reset
    V.record("stackchan", _missed(15, at_ms=1600))   # counter reset
    v = V.summary()["shadow_verdict"]
    assert "2 looked like counter-resets" in v
    assert "1 never paused" in v


def test_only_genuine_misses_count(store):
    """A turn that ended by tap or by a working endpoint is not evidence either
    way, and folding it in would flatter whichever rule is being tested."""
    V.record("stackchan", _missed(18, at_ms=1500))
    V.record("stackchan", {"why": "shadow", "end": V.END_VADEND, "ok": True,
                           "sh_run": 21, "sh_need": 21, "sh_at_ms": 700,
                           "dur_ms": 900})
    V.record("stackchan", {"why": "shadow", "end": V.END_TAP, "ok": True,
                           "sh_run": 3, "sh_need": 21, "dur_ms": 2000})
    assert V.summary()["shadow_turns"] == 1


# ── it changes nothing ───────────────────────────────────────────────────────

def test_the_shadow_is_never_read_to_make_a_decision():
    """It may be formatted for a log and written to a row. It may not appear in
    a condition that changes what the stream does.

    Checked against the AST: the first version grepped lines and flagged the log
    line's own `... if shadow_at_s is not None else "never"`, which is display
    formatting, not control flow.
    """
    import ast
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def mentions_shadow(node):
        return "shadow" in ast.unparse(node).lower()

    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef) or fn.name != "vad_stream":
            continue
        for n in ast.walk(fn):
            # an if/while whose TEST depends on a shadow value would be control flow
            if isinstance(n, (ast.If, ast.While)) and mentions_shadow(n.test):
                raise AssertionError(
                    f"shadow drives control flow: {ast.unparse(n.test)[:70]}")
            # a send back to the device must not depend on it either
            if isinstance(n, ast.Await) and mentions_shadow(n):
                raise AssertionError(f"shadow reaches an await: {ast.unparse(n)[:70]}")
        break
    else:
        raise AssertionError("vad_stream not found — has it been renamed?")


def test_the_store_is_bounded():
    """Log-and-forget only works if forgetting is safe. This file must not grow
    without limit on a box that renders video."""
    src = (REPO / "modules" / "vad_turns.py").read_text(encoding="utf-8")
    assert "_trim_if_needed" in src
    assert "_trim_if_needed()" in src[src.index("def record("):]


def test_it_did_not_land_in_mnemosyne():
    """Her memory of her own life stays that. Telemetry has its own store.

    Scoped to the record STATEMENT rather than a window of surrounding source —
    the first version used a 1500-character window and caught an unrelated
    mention elsewhere in the file.
    """
    import ast
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        call = ast.unparse(n)
        if '"why": \'shadow\'' in call or "'why': 'shadow'" in call:
            found = True
            assert n.func.attr == "record"
            assert ast.unparse(n.func.value) == "vad_turns", \
                f"shadow row written to {ast.unparse(n.func.value)}"
            assert "mnemosyne" not in call.lower()
    assert found, "the shadow record call was not found"


def test_the_stored_row_carries_no_audio_or_text(store):
    V.record("stackchan", _missed(18, at_ms=1470))
    row = V.recent(1)[0]
    for k, v in row.items():
        if isinstance(v, str):
            assert len(v) < 40, f"{k} holds a long string: {v[:50]}"
            assert " " not in v.strip() or k in ("ts",), \
                f"{k} looks like prose, not a tag: {v!r}"
