"""The transcriber's actual output is the input this parser gets.

Spoken head commands failed on the bench for a reason that had nothing to do
with the regex's logic: Whisper returned 'BB Lookdown' for "Phoebe, look down"
and 'VB Lookup' for "Phoebe, look up" — her name mangled and the two-word
phrase fused into one token. Both parsed as nothing and went to the model as
ordinary conversation, so the robot looked like it was ignoring the order.

These are the literal strings off the 2026-10-02 bench log, kept so the fix
cannot regress into "it works when I type it".

The negatives matter more than the positives. The whole-message anchor is the
only thing keeping "look up the weather" a search, and the wake-word list is
ENUMERATED rather than a wildcard precisely so "I look up" stays conversation.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "modules"))

import pytest
import dio_head


# Exactly as the transcriber produced them.
@pytest.mark.parametrize("heard,expect", [
    ("VB Lookup",    "up"),
    ("BB Lookdown",  "down"),
    # Third spelling, produced AFTER the first two were enumerated. This is why
    # the name slot is now subtractive rather than a list: 'CB' walked straight
    # past a list containing vb/bb/bebe on the very next attempt.
    ("CB lookup",    "up"),
])
def test_real_transcripts_from_the_bench(heard, expect):
    assert dio_head.parse(heard) == expect


@pytest.mark.parametrize("heard,expect", [
    ("DB look down", "down"),
    ("zq look up",   "up"),
])
def test_unseen_manglings_of_her_name_still_parse(heard, expect):
    """The failure is invisible as a parser bug.

    When the name slot rejects the utterance, no command runs, the turn goes to
    the model as conversation, and she performs the ordinary thinking tell — the
    same fixed pose every time, whatever was asked for. Astro: "she keeps making
    the same movements each time I ask to move." So an unseen mangling must not
    be able to silently disable the command.
    """
    assert dio_head.parse(heard) == expect


@pytest.mark.parametrize("heard", [
    "we look down", "they look left", "he looks up", "you look down",
    "that looks down on the valley", "now look up the answer",
    "let me look up that address",
])
def test_a_real_sentence_in_the_name_slot_is_still_conversation(heard):
    """Subtractive, not a wildcard: a pronoun or article there means a sentence."""
    assert dio_head.parse(heard) is None


@pytest.mark.parametrize("heard,expect", [
    ("Phoebe, look down.",                  "down"),
    ("Phoebe, look up.",                    "up"),
    ("phoebe lower your head",              "down"),
    ("Phoebe, can you tilt your head down?", "down"),
    ("Lookdown",                            "down"),
    ("look up",                             "up"),
    ("dio, look left",                      "left"),
    # Said on the bench and parsed as nothing, so it reached the model as
    # ordinary conversation while the robot sat still.
    ("Look to the right.",                  "right"),
    ("look to your left",                   "left"),
    ("Look right!",                         "right"),
])
def test_spoken_forms_match(heard, expect):
    assert dio_head.parse(heard) == expect


@pytest.mark.parametrize("heard", [
    "look up the weather",
    "can you look up the price of eggs",
    "I need to look up a word",
    "I look up",
    "I looked down at my shoes",
    "she looked down",
    "looking up at the stars",
    "what are you looking at",
    "take an image and analyze what you see",
    # "to the <dir>" must not swallow these: a direction followed by more
    # sentence is a description, not a command.
    "look to the right of the shelf",
    "turn to the left page",
    "It would be your left.",
])
def test_conversation_and_search_never_move_her(heard):
    """A widened command vocabulary costs ordinary conversation. This is the bill."""
    assert dio_head.parse(heard) is None


def test_the_name_slot_is_subtractive_not_a_wildcard():
    """Replaces an earlier test that required the name list to be enumerated.

    That rule was abandoned on purpose: enumerating Whisper's stabs at her name
    lost to 'CB' on the next attempt. An unknown token IS now accepted there —
    that is the fix — but a word that would make the sentence ordinary English
    is not, which is what keeps the widening from eating conversation.
    """
    assert dio_head.parse("zzz look up") == "up"      # unknown name: accepted
    assert dio_head.parse("the look up") is None      # article: a sentence
    assert dio_head.parse("it look down") is None
    assert dio_head.parse("can you look down") == "down"   # modal + you: an order
    assert dio_head.parse("you look down") is None         # a remark, not an order


# ── The release word ─────────────────────────────────────────────────────────
# A commanded direction LATCHES now, so the word that releases it has to work
# first time: if it misses, she is left pointed away with no obvious way back.
#
# Two separate bugs were found here on one bench run. Bare "Center" matched
# nothing at all, and the pattern was written `centre?` — which is "centr" plus
# an optional "e", so it accepted "centre" and "centr" and never "center". The
# American spelling, which is the one actually said, could not match.
@pytest.mark.parametrize("heard", [
    "Center", "center", "centre", "Centre.", "Phoebe, center",
    "center your head", "centre your head", "head center", "head home",
    "Look at me.", "face me", "face forward", "look straight ahead",
    "middle", "straighten up", "re-home",
])
def test_every_release_phrase_clears_a_held_direction(heard):
    assert dio_head.parse(heard) == "center"


@pytest.mark.parametrize("heard", [
    "center the image",
    "what is in the center",
    "the center of town",
    "centre it on the page",
])
def test_centre_in_a_sentence_is_not_a_release(heard):
    """Same anchor rule as the directions: the message must BE the command."""
    assert dio_head.parse(heard) is None
