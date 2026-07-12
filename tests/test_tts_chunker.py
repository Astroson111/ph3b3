"""Unit tests for modules/tts_chunker.py — the chunked-TTS sentence splitter.

Run:  .venv/bin/python -m pytest tests/test_tts_chunker.py -q
The Crooked Man of Flintstone (in ~/ph3b3_data/stories.json) is the primary
fixture: long, real punctuation, em-dashes, contractions.
"""
import os
import re
import sys
import json

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules"))
from tts_chunker import split_for_tts, split_sentences, DEFAULT_MAX_CHARS  # noqa: E402

MAX = DEFAULT_MAX_CHARS


def _norm(t):
    return re.sub(r"\s+", " ", t or "").strip()


def _crooked_text():
    p = os.path.expanduser("~/ph3b3_data/stories.json")
    if not os.path.exists(p):
        pytest.skip("stories.json fixture not present")
    d = json.load(open(p))
    for s in d.get("ph3b3_stories", []):
        if s.get("title") == "The Crooked Man of Flintstone":
            return s["story"]
    pytest.skip("Crooked Man fixture not in stories.json")


def _assert_invariants(text, chunks, max_chars=MAX):
    for c in chunks:
        assert c, "no empty chunk"
        assert c == c.strip(), f"chunk not stripped: {c!r}"
        assert len(c) <= max_chars, f"chunk over cap ({len(c)}>{max_chars}): {c[:60]!r}"
    # lossless: rejoining chunks reproduces the whitespace-normalised input
    assert " ".join(chunks) == _norm(text), "round-trip must reconstruct normalised text"


# ── Crooked Man fixture ──────────────────────────────────────────────────────
def test_crooked_bounded_and_lossless():
    text = _crooked_text()
    chunks = split_for_tts(text)
    assert len(chunks) > 5
    _assert_invariants(text, chunks)


def test_crooked_reasonable_chunk_count():
    chunks = split_for_tts(_crooked_text())
    # ~5.3 KB / 300 -> many chunks, but packed by sentence (not per-word/per-sentence spam)
    assert 12 <= len(chunks) <= 80, f"unexpected chunk count {len(chunks)}"


def test_crooked_first_chunk_is_fast_sized():
    # time-to-first-audio depends on chunk 0 being small
    chunks = split_for_tts(_crooked_text())
    assert 0 < len(chunks[0]) <= MAX


@pytest.mark.parametrize("mc", [80, 150, 300, 500])
def test_crooked_max_chars_param(mc):
    text = _crooked_text()
    _assert_invariants(text, split_for_tts(text, max_chars=mc), max_chars=mc)


# ── edge cases the brief named ───────────────────────────────────────────────
def test_single_short_sentence():
    assert split_for_tts("Hello there.") == ["Hello there."]


def test_no_terminal_punctuation():
    t = "just some text with no period at the end"
    assert split_for_tts(t) == [t]


def test_empty_and_blank():
    assert split_for_tts("") == []
    assert split_for_tts("   \n\t ") == []


def test_abbreviations_not_split():
    t = "Dr. Smith and Mr. Jones went to St. Louis. They arrived at 9 a.m. sharp."
    sents = split_sentences(t)
    assert len(sents) == 2, f"abbrev over-split: {sents}"
    assert sents[0].startswith("Dr. Smith")
    assert sents[1].startswith("They arrived")
    _assert_invariants(t, split_for_tts(t))


def test_dialogue_end_of_sentence():
    t = 'He turned and said, "Get out." Then he left.'
    sents = split_sentences(t)
    assert len(sents) == 2, f"{sents}"
    assert sents[0].endswith('out."')
    _assert_invariants(t, split_for_tts(t))


def test_dialogue_midsentence_stays_together():
    t = 'She said "run." and never looked back.'
    assert len(split_sentences(t)) == 1, "inline quote must not split the sentence"


def test_monster_sentence_word_split_under_cap():
    long = ("word " * 200).strip()  # 999 chars, no terminator
    chunks = split_for_tts(long, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) >= 8
    assert " ".join(chunks) == long  # word-split is lossless


def test_multi_sentence_packs_to_cap():
    t = "One. Two. Three. Four. Five."
    chunks = split_for_tts(t, max_chars=12)
    # each chunk holds as many whole sentences as fit under 12 chars
    assert all(len(c) <= 12 for c in chunks)
    assert " ".join(chunks) == t


def test_contractions_and_emdash_lossless():
    t = ("The old woman said you shouldn't run when you hear it. "
         "He's not fast — crooked men aren't. But you shouldn't linger either.")
    chunks = split_for_tts(t)
    _assert_invariants(t, chunks)
    assert len(chunks) >= 1
