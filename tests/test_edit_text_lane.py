"""Correcting text inside an existing picture is refused DETERMINISTICALLY.

Her self-knowledge block already said the lane was in trials. She declined the
instruction: asked "Can you fix the text in an existing image?" on fresh
sessions with the same prompt, she answered "Yes, I can fix the text in an
existing image… takes about 25 seconds" on some turns and gave the honest
"this is still being trialled" on others.

That is the third time in one evening an instruction was mistaken for a control
— the story fabrication, the note above the shelf injection, and this. So the
answer stops being a sentence she can talk past and becomes the same
deterministic refusal every other unavailable operation gets.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import apelles  # noqa: E402


TRIAL_OFF = (False, "the trial for it hasn't finished, so it isn't switched on yet",
             "set PH3B3_QWEN_EDIT=on once the trial passes")


@pytest.fixture
def lane(monkeypatch):
    """Drive the refusal from the injected state, the way the server does."""
    def _set(state):
        monkeypatch.setattr(apelles, "text_edit_state", lambda: state)
    return _set


# ── the turns it must claim ──────────────────────────────────────────────────
REFUSE = [
    "Can you fix the text in an existing image?",
    "fix the text in this image",
    "can you correct the lettering in that picture",
    "the words in the poster came out wrong, can you fix them",
    "change the text in this photo",
    "the spelling in the image is wrong, correct it",
    "redo the caption in that render",
    "replace the wording in this jpeg",
    "the text in my picture is garbled",
]


@pytest.mark.parametrize("text", REFUSE)
def test_an_edit_text_turn_is_answered_deterministically(lane, text):
    lane(TRIAL_OFF)
    out = apelles.blocked_request(text)
    assert out, f"{text!r} reached the model instead of the refusal"
    assert "isn't switched on yet" in out


# ── and the turns it must NOT ────────────────────────────────────────────────
# Generation with readable text WORKS. A refusal that swallowed it would deny a
# capability she has, which is the same dishonesty pointing the other way.
PASS_THROUGH = [
    "make me a poster with readable text",
    "generate an image of a shop sign that says OPEN",
    "draw a picture with the words HELLO on it",
    "can you make an image where the text is legible",
    "fix the typo in my document",
    "write me a caption for this photo",
    "tell me a story about a sign painter",
    "what image engines do you have",
    "what's the weather like",
]


@pytest.mark.parametrize("text", PASS_THROUGH)
def test_generation_and_unrelated_turns_are_not_intercepted(lane, text):
    lane(TRIAL_OFF)
    assert apelles.blocked_request(text) is None, \
        f"{text!r} was refused as an edit-text request"


# ── every state of the switch ────────────────────────────────────────────────
def test_the_lane_being_on_means_no_interception_at_all(lane):
    lane((True, None, None))
    assert apelles.blocked_request("fix the text in this image") is None


def test_each_off_state_gives_its_own_reason(lane):
    """Three different sentences, because they are three different facts: the
    engine is off, the edit lane is off, the trial has not finished."""
    seen = set()
    for state in [
        (False, "the second image engine — the one that gets lettering right — "
                "is switched off on this box", "set PH3B3_QWEN=on and restart"),
        (False, "the image edit lane is off, so I can make new pictures but not "
                "change one you already have", "set PH3B3_EDIT_LANE=1 and restart"),
        TRIAL_OFF,
    ]:
        lane(state)
        out = apelles.blocked_request("fix the text in this image")
        assert out and state[1] in out
        seen.add(out)
    assert len(seen) == 3, "two different off-states produce the same sentence"


def test_the_refusal_never_claims_the_capability(lane):
    lane(TRIAL_OFF)
    out = apelles.blocked_request("Can you fix the text in an existing image?").lower()
    assert not re.search(r"\byes,? i can fix the text\b", out)
    assert "25 second" not in out, "it quotes a turnaround for a lane that is off"
    assert "didn't produce" in out, "the honesty line is missing"


def test_it_offers_the_route_that_does_work(lane):
    """Never only a no: making a NEW picture with the lettering right is a
    different lane and it works today."""
    lane(TRIAL_OFF)
    out = apelles.blocked_request("fix the text in this image").lower()
    assert "new image" in out and "lettering" in out


# ── one reader for one switch ────────────────────────────────────────────────
def test_apelles_does_not_parse_the_flags_itself():
    """The flags live in server.py and are INJECTED, the same way
    morpheus.qwen_open is. Two readers of one switch is how a capability map
    starts disagreeing with the thing it describes."""
    src = (ROOT / "modules" / "apelles.py").read_text(encoding="utf-8")
    for flag in ("PH3B3_QWEN_EDIT", "PH3B3_EDIT_LANE", "PH3B3_QWEN"):
        assert flag not in src, f"apelles reads {flag} directly instead of being told"


def test_the_server_injects_the_state_after_both_flags_exist():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("QWEN_EDIT_ENABLED = ") < src.index("apelles.text_edit_state = ")
    assert src.index("EDIT_LANE_ENABLED = ") < src.index("apelles.text_edit_state = ")


def test_the_capability_map_and_the_refusal_read_the_same_hook(lane):
    """The map is cached and the refusal is live, so they are allowed to be
    computed at different times — but never from different sources."""
    src = (ROOT / "modules" / "apelles.py").read_text(encoding="utf-8")
    assert src.count("text_edit_state()") >= 2
    i = src.index('cap("edit_text_in_image"')
    assert "text_edit_state()" in src[i - 400:i], \
        "the capability map entry is not derived from the injected state"


def test_the_refusal_runs_before_triage_can_hold_the_turn():
    """blocked_request already sits above the gate; this lane depends on that,
    because a held turn never reaches the refusal either."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("apelles.blocked_request(user_msg)") < \
           src.index("_triage = (_TriagePass()")
