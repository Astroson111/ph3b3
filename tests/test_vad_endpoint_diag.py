"""
VAD endpoint diagnostics — why a turn did or did not end.

WHAT THIS IS FOR. 13 of 59 speech turns reach Dio's 8s backstop instead of
ending when she stops talking. Silero is not the problem: max probability was
0.999 in the failures and 0.998 in the successes, at identical levels. The
suspicion is the run counter — the endpoint needs `_min_silence` CONSECUTIVE
frames below `speech_off` and resets to zero on any single frame above it, so
one breath or fan transient in an otherwise-quiet pause restarts the count.

But that is a reading of the code, not an observation, and the two candidate
shapes need opposite fixes:

    max_sub_run == 0            she never actually stopped → threshold is the
                                lever (or she really did talk for eight seconds)
    0 < max_sub_run < need      she DID stop and the counter kept being reset →
                                a windowed rule fixes it; lowering the threshold
                                would cost real endpoints on quiet speech

So this measures rather than assumes, and carries a SHADOW evaluation of the
proposed windowed-majority rule — computed, logged, never acted on — so the fix
can be judged on real traffic before it changes any behaviour.

PRIVACY INVARIANT. This path judges frames and discards them. Nothing here may
hold, log or derive a sample value. Numbers ABOUT a turn only.

Run:  .venv/bin/python -m pytest tests/test_vad_endpoint_diag.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import audio_monitor as A  # noqa: E402


class Scripted(A.AudioMonitor):
    """The real state machine, fed scripted probabilities — no model, no audio."""

    def __init__(self, min_silence_ms=700):
        self.speech_on, self.speech_off = 0.5, 0.35
        self._min_speech = max(1, int(250 / A._FRAME_MS))
        self._min_silence = max(1, int(min_silence_ms / A._FRAME_MS))
        self._spike_over = 12.0
        self.reset()

    def feed(self, p):
        speech = p >= (self.speech_off if self._active else self.speech_on)
        if self._active:
            self._active_frames += 1
            sub = p < self.speech_off
            self._sub_frames += int(sub)
            if sub:
                self._cur_sub += 1
            elif self._cur_sub:
                self._sub_runs.append(self._cur_sub)
                self._cur_sub = 0
            self._shadow_win.append(sub)
            if len(self._shadow_win) > self._min_silence:
                self._shadow_win.pop(0)
            if (self._shadow_at is None and len(self._shadow_win) == self._min_silence
                    and sum(self._shadow_win) >= 0.8 * self._min_silence):
                self._shadow_at = self._n
        if speech:
            self._speech_run += 1
            self._silence_run = 0
            if self._speech_run >= self._min_speech:
                self._active = True
                self.had_speech = True
        else:
            self._silence_run += 1
            self._speech_run = 0
            if self._active and self._silence_run >= self._min_silence:
                self._active = False
                self.endpoint = True
        self._n += 1


def _talk(m, n=30):
    for _ in range(n):
        m.feed(0.99)


# ── the diagnostic tells the two shapes apart ────────────────────────────────

def test_a_speaker_who_never_pauses_reads_as_never_paused():
    m = Scripted(); _talk(m)
    for _ in range(120):
        m.feed(0.9)
    d = m.endpoint_diag()
    assert m.endpoint is False
    assert d["max_sub_run"] == 0, "no pause should mean no sub-threshold run"
    assert d["shadow_at_s"] is None, "the windowed rule must not fire either"


def test_a_pause_broken_by_spikes_reads_as_counter_reset():
    """The suspected real shape: she stops, but a stray frame keeps restarting
    the count, so the live rule never reaches `need`."""
    m = Scripted()
    _talk(m)
    need = m._min_silence
    for _ in range(6):
        for _ in range(need - 3):
            m.feed(0.05)
        m.feed(0.8)                      # one spike resets the live counter
    d = m.endpoint_diag()
    assert m.endpoint is False, "the live rule should still miss"
    assert 0 < d["max_sub_run"] < d["need"], \
        f"expected a partial run, got {d['max_sub_run']}/{d['need']}"
    assert d["sub_runs"] >= 5
    assert d["sub_pct"] > 60


def test_a_clean_pause_still_fires_and_is_not_flagged():
    m = Scripted(); _talk(m)
    for _ in range(m._min_silence + 2):
        m.feed(0.02)
    assert m.endpoint is True
    assert m.endpoint_diag()["max_sub_run"] >= m._min_silence


# ── the shadow rule, measured but never acted on ─────────────────────────────

def test_the_shadow_rule_would_have_ended_the_broken_turn():
    """The whole point: evidence that the proposed fix works, before shipping."""
    m = Scripted(); _talk(m)
    need = m._min_silence
    for _ in range(6):
        for _ in range(need - 3):
            m.feed(0.05)
        m.feed(0.8)
    d = m.endpoint_diag()
    assert d["shadow_at_s"] is not None, "the windowed rule should have fired"
    assert m.endpoint is False, "and the LIVE rule must be unchanged by it"


def test_the_shadow_rule_does_not_fire_on_continuous_speech():
    """It must be more forgiving, not indiscriminate."""
    m = Scripted(); _talk(m)
    for _ in range(120):
        m.feed(0.95)
    assert m.endpoint_diag()["shadow_at_s"] is None


def test_the_shadow_changes_no_behaviour():
    """It is computed and logged. Nothing reads it to make a decision."""
    src = (REPO / "modules" / "audio_monitor.py").read_text(encoding="utf-8")
    body = src[src.index("def push("):src.index("def endpoint_diag(")]
    # _shadow_at may be WRITTEN in push, never branched on to set endpoint
    for line in body.splitlines():
        if "endpoint = True" in line:
            assert "_shadow" not in line
    assert "_shadow_at" not in src[src.index("def feed_bytes("):]


# ── privacy invariant ────────────────────────────────────────────────────────

def test_the_diagnostic_is_numbers_only():
    """This path judges frames and discards them. A diagnostic that leaked a
    sample value would break the invariant the whole lane is built on."""
    m = Scripted(); _talk(m)
    for _ in range(40):
        m.feed(0.1)
    d = m.endpoint_diag()
    for k, v in d.items():
        assert v is None or isinstance(v, (int, float)), \
            f"{k} is {type(v).__name__}, not a number"


def test_nothing_in_the_monitor_retains_samples():
    """The window must hold VERDICTS about frames, never frame data.

    Checked as a property rather than by variable name — the first version
    asserted on `_shadow_win.append(sub)` and broke the moment the windows were
    renamed, which says nothing about privacy either way.
    """
    import ast
    src = (REPO / "modules" / "audio_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    push = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "push")

    SAMPLES = {"frame_int16", "ff", "f", "inp", "raw", "_byte_buf", "_context"}
    appends = 0
    for n in ast.walk(push):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "append"):
            continue
        target = ast.unparse(n.func.value)
        if "win" not in target and "run" not in target and "_sub" not in target:
            continue
        appends += 1
        arg = n.args[0]
        # a comparison result, or a plain counter — never a sample container
        names = {x.id for x in ast.walk(arg) if isinstance(x, ast.Name)}
        assert not (names & SAMPLES), \
            f"{target}.append() receives sample data: {ast.unparse(arg)}"
        # A comparison result, a counter, or a literal. An ast.Attribute is
        # allowed because `self._cur_sub` is an int counter — the SAMPLES check
        # above is what actually guards privacy; this only bars a whole
        # expression being smuggled in.
        assert isinstance(arg, (ast.Compare, ast.Name, ast.Constant, ast.Attribute)), \
            f"{target}.append() receives something unexpected: {ast.unparse(arg)}"
    assert appends, "no window appends found — has push() been restructured?"

    # and whatever a window IS assigned must not be a sample container either
    for n in ast.walk(push):
        if isinstance(n, ast.Assign) and any(
                "win" in ast.unparse(t) for t in n.targets):
            names = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
            assert not (names & SAMPLES), \
                f"a window is assigned sample data: {ast.unparse(n)}"


def test_the_server_log_line_carries_no_audio():
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('"[vad] %s diag')
    seg = src[i:i + 700]
    for smell in ("raw", "frame_int16", "ff", "samples", "bytes"):
        assert f"{smell}," not in seg and f"{smell})" not in seg, \
            f"the diag log references {smell!r}"


def test_diagnostics_never_break_the_stream():
    """A broken diagnostic must not take a live conversation down with it."""
    # Checked structurally, not by a fixed window: the first version used 900
    # characters and broke the moment the block grew, which is a test that
    # fails on its own success.
    import ast
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "vad_stream")
    guarded = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Try) and "endpoint_diag" in ast.unparse(n):
            assert any(h.type is None or "Exception" in ast.unparse(h.type)
                       for h in n.handlers), "the diag block catches nothing broad"
            guarded = True
    assert guarded, "the diagnostic block is not wrapped — it can kill the stream"


def test_no_speech_streams_are_not_logged():
    """19 of 78 streams saw no speech. They have nothing to explain, and logging
    them would bury the ones that do."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('"[vad] %s diag')
    assert "if mon.had_speech:" in src[max(0, i - 900):i]
