"""Her spoken strings describe what the hardware does TODAY.

UPDATED 2026-10-02. The neck is now wired — eyes lead via setGaze, the servos
follow via Motion.moveX/moveY, verified by watching the robot move. So the
refusal this file used to enforce ("my neck isn't wired up yet") became the false
statement and was removed, exactly as the earlier neck CLAIMS were removed when
they were false.

What this file still guards is the thing that does not change: a transport
failure must name the TRANSPORT, not a body part. "I couldn't reach Dio" is true
when the POST fails; "my neck isn't responding" was never knowable from a failed
HTTP request and is still forbidden.

THE CORRECTION, 2026-10-01. This module said "look down reaches her neck" in six
places, three of them sentences she says out loud. It was wrong for a week. The
device end calls face.setGaze(yaw, pitch), and setGaze stores into
_gazeYaw/_gazePitch, consumed at ph3b3_face.h:208 as

    gTX =  _gazeYaw   * (float)EIR * 0.40f;     // EIR = eye iris radius

i.e. PUPIL DRAWING COORDINATES. "Look down" moves her drawn eyes on the screen.
Her neck never moves. The servo API exists — M5StackChan.Motion.moveX/moveY,
used by gentleHome()/safeHome() — and nothing on this lane calls it.

It compiled, it unit-tested green, and it was false: a function name is not
evidence of what it does. This file is the guard against the claim coming back,
and it is deliberately coupled to the firmware fact — when the neck IS wired,
the mutation test below is what tells you to update this file rather than
letting a stale "not wired" message outlive the limitation.

Same family as the camera weld (no claim of sight without a capture that
returned) and the fleet weld (no claim of state without telemetry): no claim of
MOTION without something that moves.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import dio_head  # noqa: E402

SRC = (ROOT / "modules" / "dio_head.py").read_text(encoding="utf-8")
SERVER = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")

# Every string this module can SAY. Collected from the code, not hand-listed, so
# a new spoken string cannot be added without this test seeing it.
def _spoken():
    out = list(dio_head._SAID.values())
    out.append(dio_head.send("down", None))                 # no-host branch
    out.append(dio_head.send("down", "127.0.0.1:1"))        # unreachable branch
    return [s for s in out if s]


_NECK_CLAIM = re.compile(
    r"\b(?:my|her)\s+neck\b"
    r"|\bneck\s+(?:is|isn't|is not)\s+(?:responding|moving)\b"
    r"|\breach(?:es|ed)?\s+(?:my|her)\s+neck\b"
    r"|\b(?:turn|turning|moved|moving)\s+(?:my|her)\s+head\b", re.I)


def test_transport_failures_name_the_transport_not_a_body_part():
    for line in (dio_head.send("down", None), dio_head.send("down", "127.0.0.1:1")):
        assert "dio" in line.lower(), f"the failure does not name who was unreachable:\n{line}"
        assert "neck" not in line.lower(), f"a transport error blamed the neck:\n{line}"


def test_a_turn_naming_the_head_is_now_accepted():
    """It was refused while the neck was unwired. The neck moves now, so naming
    it is an ordinary command — refusing it would be the lie pointing the other
    way."""
    for text in ("turn your head down", "centre your head", "re-home your head",
                 "tilt your head left"):
        assert dio_head.parse(text), f"{text!r} is no longer recognised at all"
    assert not hasattr(dio_head, "NECK_NOT_WIRED"), \
        "the not-wired refusal is back, and it is false"


def test_a_plain_look_command_is_untouched():
    """Eyes and neck both move for an ordinary gaze request."""
    for text in ("look down", "ph3b3, look down", "can you look left please",
                 "look at me"):
        assert dio_head.parse(text), f"{text!r} stopped being a command"


def test_look_up_the_weather_is_still_not_a_command():
    assert dio_head.parse("look up the weather") is None


def test_the_docstring_describes_what_it_does_today():
    """Checked on the SUMMARY LINE, not the whole docstring.

    The body deliberately quotes the old false claim while explaining that it
    was false, and a whole-text grep fails on its own explanation — the sixth
    time that has happened in this suite. The summary line is what a reader
    takes as the module's claim about itself, so that is what is pinned."""
    head = SRC[:SRC.index('"""', 3)]
    summary = head.splitlines()[0]
    assert "eyes" in summary.lower() and "neck" in summary.lower(), \
        f"the summary line no longer says what moves:\n  {summary}"
    assert "NECK CONTROL IS NOT IMPLEMENTED" not in head, \
        "the docstring still says the neck is unwired, which is now false"


def test_the_server_import_comment_is_honest():
    """It may name the neck now — the neck moves. What it must NOT do is claim
    the neck is unwired, which was true yesterday and is false today."""
    line = next(l for l in SERVER.splitlines() if l.startswith("import dio_head"))
    assert "not wired" not in line.lower() and "isn't wired" not in line.lower(), \
        f"the import comment still says the neck is unwired:\n  {line}"


# ── teeth ────────────────────────────────────────────────────────────────────
def test_reinserting_a_neck_claim_goes_red():
    """Mutation: without this, the test above passes because today's strings
    happen to be clean, not because the check works."""
    for bad in ("My neck isn't responding — I couldn't reach her.",
                "I can't reach my neck right now.",
                "Turning my head down."):
        assert _NECK_CLAIM.search(bad), f"the guard would not catch: {bad!r}"


def test_the_guard_does_not_flag_honest_wording():
    for ok in ("Looking down.", "Back to centre.",
               "I couldn't reach Dio — I don't have her address right now.",
               "Dio didn't answer that — she returned 500 to 'down'."):
        assert not _NECK_CLAIM.search(ok), f"honest wording flagged: {ok!r}"
