"""Clarifying questions must carry their own answer.

A question that names nothing — "Which file do you mean?" — asks the user to
guess at a list only this process can see. It costs a turn and teaches nothing,
which makes it worse than not asking.

This one reached production the usual way: it was the EXAMPLE in the triage
prompt, and the model emitted the example verbatim. The example is gone, but
these test the SHAPE, because the next model will phrase its own dead end.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import triage  # noqa: E402


@pytest.mark.parametrize("q", [
    "Which file do you mean?",
    "which one do you mean?",
    "What story do you mean?",
    "Which document?",
    "which book did you want?",
    "  Which item do you mean?  ",
    "What thing do you mean?",
    "Which record?",
])
def test_bare_questions_are_dropped(q):
    assert triage._scrub_bare_ask(q) is None, f"{q!r} survived — it names nothing"


@pytest.mark.parametrize("q", [
    "Which of your saved singers should I use?",
    "I have these stories: Charles and Eliza. Which did you want?",
    "What sort of sound are you after — style, mood, tempo?",
    "Which folder should I write it to, Pictures or Desktop?",
    "What date range do you want the report to cover?",
])
def test_informative_questions_survive(q):
    assert triage._scrub_bare_ask(q) == q, f"{q!r} was dropped but it carries context"


def test_dropped_question_falls_back_to_naming_what_is_missing():
    out = triage._clarifying(["the story title"], "read me that one", "Which file do you mean?")
    assert "Which file do you mean" not in out
    assert "the story title" in out, "the fallback did not say what it was short of"


def test_fallback_is_never_empty():
    assert triage._clarifying([], "x", "Which one?").strip()


def test_the_prompt_no_longer_ships_a_bare_example():
    """The example was the source. If it comes back, so does the behaviour."""
    assert "Which file do you mean" not in triage._SYSTEM


def test_the_prompt_asks_for_answerable_questions():
    assert "never a bare question" in triage._SYSTEM.lower()


def test_artist_scrub_still_works():
    """The existing guard must not be broken by the new one being chained onto it."""
    out = triage._clarifying([], "make me a song", "Which artist should it sound like?")
    assert "artist" not in out.lower()
    assert "style" in out.lower() or "sound" in out.lower()
