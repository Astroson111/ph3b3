"""
VAD tuning — configurable thresholds and the switchable endpoint rule.

The brief asked for thresholds "tunable in config, not hardcoded". They were
hardcoded, and `AudioMonitor()` was constructed with no arguments at all.

The rule itself is now switchable too, defaulting to the shipped behaviour:

  consecutive  min_silence_ms of UNBROKEN quiet, reset to zero by any single
               frame above speech_off. Brittle by construction: one breath or
               fan transient in a pause restarts the count and the turn rides to
               Dio's 8s backstop. 13 of 59 speech turns ended that way, with
               Silero at 0.999 confidence throughout.

  windowed     window_frac of the last min_silence_ms below speech_off. Same
               latency on a clean pause, survives a spike.

Default is `consecutive` ON PURPOSE. This ships measurement plus the option, not
a behaviour change — the shadow diagnostic evaluates whichever rule is NOT live,
so flipping the config gives a real before/after either way.

Run:  .venv/bin/python -m pytest tests/test_vad_tuning.py -v
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import audio_monitor as A  # noqa: E402


class Sim(A.AudioMonitor):
    """The real decision logic, scripted probabilities — no model, no audio."""

    def __init__(self, rule="consecutive", frac=0.8, min_silence_ms=700):
        self.speech_on, self.speech_off = 0.5, 0.35
        self._min_speech = max(1, int(250 / A._FRAME_MS))
        self._min_silence = max(1, int(min_silence_ms / A._FRAME_MS))
        self._spike_over = 12.0
        self.endpoint_rule, self.window_frac = rule, frac
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
            self._live_win.append(sub)
            if len(self._live_win) > self._min_silence:
                self._live_win.pop(0)
            self._shadow_win = self._live_win
            if self._shadow_at is None:
                if self.endpoint_rule == "consecutive":
                    if (len(self._live_win) >= self._min_silence
                            and sum(self._live_win) >= self.window_frac * self._min_silence):
                        self._shadow_at = self._n
                elif self._cur_sub >= self._min_silence:
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
            if self._active and self._endpoint_now():
                self._active = False
                self.endpoint = True
        self._n += 1


def _spiky(m):
    """A real pause, broken once per cycle — the shape that defeats the counter."""
    for _ in range(30):
        m.feed(0.99)
    for _ in range(6):
        for _ in range(m._min_silence - 3):
            m.feed(0.05)
        m.feed(0.8)


def _clean(m):
    for _ in range(30):
        m.feed(0.99)
    for _ in range(m._min_silence + 2):
        m.feed(0.02)


# ── the default does not change behaviour ────────────────────────────────────

def test_the_shipped_default_is_the_shipped_rule():
    """This ships an option, not a behaviour change."""
    assert A._DEFAULTS["endpoint_rule"] == "consecutive"
    assert A.load_tuning()["endpoint_rule"] == "consecutive"


def test_the_default_still_misses_the_spiky_pause():
    """Unchanged: the bug is still there until someone flips the config."""
    m = Sim("consecutive"); _spiky(m)
    assert m.endpoint is False


# ── the windowed rule fixes it without breaking the healthy path ─────────────

def test_windowed_catches_the_pause_the_counter_missed():
    m = Sim("windowed"); _spiky(m)
    assert m.endpoint is True


@pytest.mark.parametrize("rule", ["consecutive", "windowed"])
def test_a_clean_pause_ends_the_turn_under_either_rule(rule):
    """The fix must not change what already works."""
    m = Sim(rule); _clean(m)
    assert m.endpoint is True


@pytest.mark.parametrize("rule", ["consecutive", "windowed"])
def test_continuous_speech_never_ends_the_turn(rule):
    """And it must not become trigger-happy — that would cut people off."""
    m = Sim(rule)
    for _ in range(200):
        m.feed(0.95)
    assert m.endpoint is False


def test_windowed_still_requires_a_full_window():
    """A brief dip must not end a turn — window_frac of a FULL window, not of
    whatever has accumulated so far."""
    m = Sim("windowed")
    for _ in range(30):
        m.feed(0.99)
    for _ in range(m._min_silence // 2):
        m.feed(0.02)
    assert m.endpoint is False


# ── the shadow always evaluates the OTHER rule ───────────────────────────────

def test_the_shadow_tracks_whichever_rule_is_not_live():
    """So flipping the config gives a before/after in both directions."""
    m = Sim("consecutive"); _spiky(m)
    assert m.endpoint is False
    assert m.endpoint_diag()["shadow_at_s"] is not None, \
        "with consecutive live, the shadow should show windowed would have fired"

    m = Sim("windowed"); _spiky(m)
    assert m.endpoint is True
    assert m.endpoint_diag()["shadow_at_s"] is None, \
        "with windowed live, the shadow (consecutive) should show it would NOT have"


# ── config ───────────────────────────────────────────────────────────────────

def test_the_tuning_file_exists_and_parses():
    d = json.loads((REPO / "config" / "vad_tuning.json").read_text(encoding="utf-8"))
    for k in ("speech_on", "speech_off", "min_speech_ms", "min_silence_ms",
              "endpoint_rule", "window_frac"):
        assert k in d, f"{k} is not tunable from the file"


def test_a_broken_tuning_file_falls_back_rather_than_failing(tmp_path):
    """A typo in a tuning file must never take her hearing offline."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert A.load_tuning(bad) == A._DEFAULTS


def test_an_unknown_rule_falls_back_to_the_shipped_one(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"endpoint_rule": "telepathy"}), encoding="utf-8")
    assert A.load_tuning(f)["endpoint_rule"] == "consecutive"


def test_partial_files_are_merged_not_replaced(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"speech_off": 0.2}), encoding="utf-8")
    t = A.load_tuning(f)
    assert t["speech_off"] == 0.2
    assert t["min_silence_ms"] == A._DEFAULTS["min_silence_ms"]


def test_the_thresholds_are_no_longer_hardcoded_at_the_call_site():
    """server.py used to construct AudioMonitor() with no arguments at all."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    assert "audio_monitor.AudioMonitor()" not in src
    assert "audio_monitor.load_tuning()" in src


def test_tuning_is_read_per_stream_so_a_change_needs_no_restart():
    import ast
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "vad_stream")
    assert "load_tuning()" in ast.unparse(fn), \
        "tuning must be loaded inside the handler, not captured at import"
