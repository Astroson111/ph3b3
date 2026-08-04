"""Unit tests for the --sentence-silence guard in modules/tts_module.py.

Run:  .venv/bin/python -m pytest tests/test_tts_silence.py -q

Regression cover for the shelf-reading noise bug: Piper sizes an inter-sentence
pause in BYTES as int(seconds * rate * 2), and an ODD count writes half a sample,
putting every sample after that pause one byte out of phase — static with
gunfire-like cracks. shelf.TELL_SILENCE = 0.55 s at 22050 Hz is exactly such a
value (24255 bytes). These tests are pure arithmetic: no Piper, no audio.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules"))
from tts_module import _safe_sentence_silence, _even, PIPER_RATE  # noqa: E402

RATE = PIPER_RATE


def pad_bytes(flag_value: str, rate: int = RATE) -> int:
    """The byte count Piper derives from the flag we hand it."""
    return int(float(flag_value) * rate * 2)


def is_clean(flag_value: str, rate: int = RATE) -> bool:
    return pad_bytes(flag_value, rate) % 2 == 0


# ── the guard makes every pause land on a whole sample ────────────────────────

# 0.55/0.25/0.70/0.75 are the values measured as corrupt against real Piper.
@pytest.mark.parametrize("sec", [0.0, 0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.55, 0.6,
                                 0.7, 0.75, 0.8, 0.9, 1.0, 1.25, 1.55, 2.0])
def test_pause_is_always_a_whole_sample(sec):
    assert is_clean(_safe_sentence_silence(sec))


def test_the_exact_bug_value():
    """0.55 s is what shelf.TELL_SILENCE asks for, and what broke the reading."""
    assert pad_bytes("0.55") == 24255 and pad_bytes("0.55") % 2 == 1   # the bug
    assert is_clean(_safe_sentence_silence(0.55))                      # the fix


def test_correction_is_inaudible():
    """A pause may shift by at most half a sample (~23 us at 22050 Hz), plus the
    6-decimal formatting rounding (<=5e-7 s)."""
    tol = 1.0 / (2 * RATE) + 1e-6
    for sec in (0.25, 0.55, 0.7, 0.75, 1.55):
        assert abs(float(_safe_sentence_silence(sec)) - sec) <= tol


def test_already_clean_values_are_untouched():
    for sec in (0.5, 0.6, 0.8, 1.0):
        assert float(_safe_sentence_silence(sec)) == pytest.approx(sec)


def test_prefers_a_longer_pause():
    """A deliberate beat is never trimmed toward nothing."""
    assert float(_safe_sentence_silence(0.55)) >= 0.55


def test_clamped_and_total_on_junk():
    assert float(_safe_sentence_silence(-3.0)) == 0.0
    assert float(_safe_sentence_silence(99.0)) <= 2.0
    assert is_clean(_safe_sentence_silence(-3.0))
    assert is_clean(_safe_sentence_silence(99.0))


def test_zero_stays_zero():
    assert float(_safe_sentence_silence(0.0)) == 0.0


# ── the even-trim backstop ────────────────────────────────────────────────────

def test_even_trims_only_odd_streams():
    assert _even(b"\x01\x02\x03\x04") == b"\x01\x02\x03\x04"
    assert _even(b"\x01\x02\x03") == b"\x01\x02"
    assert _even(b"") == b""
    assert _even(b"\x01") == b""


def test_even_output_is_always_frombuffer_safe():
    import numpy as np
    for n in range(0, 9):
        assert len(_even(b"\x7f" * n)) % 2 == 0
        np.frombuffer(_even(b"\x7f" * n), dtype="<i2")   # must not raise
