"""The letterform metric, locked.

word_accuracy() decides whether a render ships. It replaced character
similarity because difflib rates 'OEPN LTAE' at 77.8% against 'OPEN LATE' —
a scrambled word keeps every character, so an unreadable sign passed.

These run offline: no ollama, no GPU, no renders.
"""
import importlib.util
import pathlib

import pytest

_p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "palamedes_gate.py"
_spec = importlib.util.spec_from_file_location("palamedes_gate", _p)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_correct_read_scores_one():
    assert gate.word_accuracy("FRESH BREAD DAILY", "FRESH BREAD DAILY") == 1.0


def test_scrambled_scores_zero():
    """The measured degraded controls. Character similarity gave these
    72.7-82.4%, which is why the metric changed."""
    for got, want in (("FSREH BARED DILAY", "FRESH BREAD DAILY"),
                      ("OEPN LTAE", "OPEN LATE"),
                      ("MIAN SERETT", "MAIN STREET")):
        assert gate.word_accuracy(got, want) == 0.0, f"{got!r} passed as {want!r}"
        assert gate.score(got, want) > 0.7, \
            "char similarity no longer rates this highly — the metric's reason to exist"


def test_one_wrong_word_is_not_a_pass():
    """A sign with one wrong word is a wrong sign."""
    v = gate.verdict("FRESH BREAD DIALY", "FRESH BREAD DAILY")
    assert v["word_accuracy"] < 1.0 and v["pass"] is False


def test_partial_credit_is_proportional():
    assert gate.word_accuracy("FRESH BREAD XXXXX", "FRESH BREAD DAILY") == pytest.approx(2 / 3)


def test_reader_noise_does_not_earn_a_pass():
    """tesseract's best variant on a perfect render. It must not pass."""
    assert gate.word_accuracy("RE BIL EN E NE L A", "OPEN LATE") == 0.0


def test_case_and_punctuation_are_normalised():
    assert gate.word_accuracy("open, late!", "OPEN LATE") == 1.0


def test_empty_read_scores_zero():
    """tesseract returned '' on a visibly perfect render — that is a failure,
    never a pass."""
    assert gate.word_accuracy("", "OPEN LATE") == 0.0
    assert gate.verdict("", "OPEN LATE")["pass"] is False


def test_empty_target_does_not_divide_by_zero():
    assert gate.word_accuracy("anything", "") == 0.0


def test_order_matters():
    assert gate.word_accuracy("LATE OPEN", "OPEN LATE") < 1.0
