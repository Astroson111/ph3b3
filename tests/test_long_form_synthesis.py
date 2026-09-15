"""
Long-form synthesis must survive a slow voice — regression suite.

THE BUG THIS GUARDS. A shelved story is ~5,400 characters and about six minutes
of speech. `synthesize_to_b64` hands the WHOLE thing to one Piper subprocess
under a fixed 30-second wall-clock cap, so whether a story can be read aloud
depends entirely on how fast the selected voice happens to be:

    en_GB-alba-medium    9.4 s   ok
    en_GB-jenny_dioco    10.8 s  ok
    en_US-ryan-high      32.9 s  TIMES OUT
    en_GB-cori-high      34.2 s  TIMES OUT

Measured on Nyx, same story, same delivery flags. Every `-high` voice is over
the cap and every `-medium` voice is under it, which means selecting a
higher-quality voice silently costs you the ability to be read to.

And it fails SILENTLY: TimeoutExpired is caught, logged, and returned as None,
which /chat renders as an empty audio field. The reply text arrives, the audio
does not, and nothing anywhere says why.

The cap is not new — it dates to 59d94f2 (2026-07-13), two months before the
Rung 4 TTS work that was suspected. The chunker refactor in Rung 4 is provably
innocent: its output is byte-identical to the old implementation on all three
shelved stories at both chunk sizes (see test_tts_chunker.py and the findings).
What changed was the SELECTED VOICE.

Run:  .venv/bin/python -m pytest tests/test_long_form_synthesis.py -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import tts_module                        # noqa: E402
from tts_module import TTSModule         # noqa: E402

# Measured on Nyx: a high-quality Piper voice renders a shelved story at roughly
# this cost per character. Alba is about a third of it.
SECONDS_PER_CHAR_HIGH = 34.2 / 5367

STORY = ("The crooked man walked a crooked mile, and thought about it the whole "
         "way there. " * 60)          # ~5,400 chars, the size of a real telling


class _FakePiper:
    """Stands in for the subprocess: refuses to finish inside too small a budget.

    It does not sleep — it asserts the CONTRACT. Given a text that needs N
    seconds on the slowest installed voice, a caller that allows less than N has
    not given synthesis room to happen, and the real Piper would raise exactly
    this.
    """

    def __init__(self, sec_per_char=SECONDS_PER_CHAR_HIGH):
        self.sec_per_char = sec_per_char
        self.calls = []

    def __call__(self, cmd, input=None, capture_output=True, timeout=None, **kw):
        text = (input or b"").decode("utf-8", "ignore")
        needed = len(text) * self.sec_per_char
        self.calls.append({"chars": len(text), "timeout": timeout, "needed": needed})
        if timeout is not None and needed > timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return subprocess.CompletedProcess(cmd, 0, b"\x00\x01" * (len(text) * 40), b"")


@pytest.fixture
def piper(monkeypatch):
    fake = _FakePiper()
    monkeypatch.setattr(tts_module.subprocess, "run", fake)
    monkeypatch.setattr(tts_module, "_resolve_voice",
                        lambda c=None: (tts_module.VOICE_MODEL, "latin", ""))
    return fake


def test_a_story_still_gets_audio_on_a_slow_voice(piper):
    """The regression, stated as an outcome rather than a mechanism.

    A six-minute story must come back as audio whichever approved voice is
    selected. Today it comes back as None on every -high voice, and the caller
    renders that as no audio at all.
    """
    t = TTSModule()
    t._available = True
    out = t.synthesize_to_b64(STORY, None, 1.12, 0.55)
    assert out, (
        "long-form synthesis produced NO AUDIO on a slow voice — "
        f"{len(piper.calls)} piper call(s), "
        f"budget {piper.calls[0]['timeout'] if piper.calls else '?'}s for "
        f"{piper.calls[0]['needed']:.0f}s of work" if piper.calls else "no calls")


def test_the_synthesis_budget_scales_with_the_text(piper):
    """Whatever the fix, the invariant is the same: the time allowed has to
    follow the size of the job, or the job's size decides whether it happens."""
    t = TTSModule()
    t._available = True
    t.synthesize_to_b64(STORY, None, 1.12, 0.55)
    assert piper.calls, "nothing was synthesised at all"
    if len(piper.calls) == 1:
        c = piper.calls[0]
        assert c["timeout"] is None or c["timeout"] >= c["needed"], (
            f"one {c['chars']}-char job given {c['timeout']}s but needing "
            f"{c['needed']:.0f}s — the cap decides, not the text")
    else:
        for c in piper.calls:
            assert c["timeout"] is None or c["timeout"] >= c["needed"], (
                f"a {c['chars']}-char chunk still exceeds its {c['timeout']}s budget")


def test_a_short_reply_is_unaffected(piper):
    """The ordinary path must not change: short replies already fit easily."""
    t = TTSModule()
    t._available = True
    assert t.synthesize_to_b64("Hello, I'm Phoebe.", None)


def test_a_synthesis_that_times_out_does_not_return_silently(piper):
    """Failing quietly is how this shipped: the reply text arrives, the audio
    field is empty, and nothing says why. Same rule as the voice fallback —
    dead air must be announced or raised, never simply returned."""
    piper.sec_per_char = 10.0          # nothing will fit, however it is chunked
    t = TTSModule()
    t._available = True
    out = t.synthesize_to_b64(STORY, None, 1.12, 0.55)
    assert out is None
    assert getattr(t, "last_error", None), (
        "synthesis failed and left no trace a caller could surface — "
        "the caller cannot tell 'no audio' from 'text-only by design'")
