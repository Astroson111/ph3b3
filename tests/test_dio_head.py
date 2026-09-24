""""Look down" reaches her neck, and "look up the weather" does not.

Dio's head could not be commanded at all before this: every Motion call in her
firmware was internal, and the only server->device surfaces were the 20 s
/emotion poll (face state) and four camera routes. The first premise this was
built on was wrong — the servos were thought to be dead, and they are not; she
was doing her idle side-to-side scan the whole time. So this is a missing
feature, not a repair.

THE TRAP THIS FILE EXISTS FOR: "look up". "Look up the weather" is a search.
Matching is anchored to the WHOLE message — the message must BE the command,
not contain it — which is what keeps those apart deterministically.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import dio_head  # noqa: E402


COMMANDS = [
    ("look down", "down"), ("look up", "up"),
    ("can you look down please", "down"), ("ph3b3, look up", "up"),
    ("turn your head left", "left"), ("tilt your head down", "down"),
    ("look right now", "right"), ("look down a bit", "down"),
    ("look at me", "center"), ("centre your head", "center"),
    ("face forward", "center"), ("straighten up", "center"),
    ("re-home your head", "center"),
]


@pytest.mark.parametrize("text,expected", COMMANDS)
def test_a_head_command_is_recognised(text, expected):
    assert dio_head.parse(text) == expected


# Every one of these must leave her head alone.
NOT_COMMANDS = [
    "look up the weather",
    "look up the capital of France",
    "can you look up that story",
    "look up how to make bread",
    "I looked down at my shoes",
    "what does it look like",
    "look at this image",
    "don't look down",
    "tell me a joke",
    "what is the capital of France",
]


@pytest.mark.parametrize("text", NOT_COMMANDS)
def test_conversation_is_never_mistaken_for_a_command(text):
    assert dio_head.parse(text) is None, f"{text!r} would have moved her head"


def test_look_up_the_weather_is_the_case_that_matters():
    """Called out on its own because it is the one that would be worst: a web
    search silently becomes a servo move."""
    assert dio_head.parse("look up") == "up"
    assert dio_head.parse("look up the weather") is None


# ── failure is spoken, never silent ──────────────────────────────────────────
def test_an_unknown_host_says_so_rather_than_pretending():
    out = dio_head.send("down", None)
    assert "can't reach my neck" in out
    assert "address" in out


def test_an_unreachable_device_says_so():
    out = dio_head.send("down", "203.0.113.1")     # TEST-NET-3, never routable
    assert "isn't responding" in out
    assert "rather say that than pretend" in out


def test_every_direction_has_something_to_say():
    for cmd in ("down", "up", "left", "right", "center"):
        assert dio_head._SAID[cmd]


# ── where it sits ────────────────────────────────────────────────────────────
def test_the_command_is_claimed_above_the_triage_gate():
    """A held turn never reaches the motor."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("_head_cmd = dio_head.parse") < src.index("_triage = (_TriagePass()")


def test_the_server_uses_the_verified_dio_host():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("_head_reply = dio_head.send(")
    assert 'vision, "dio_host"' in src[i:i + 200], \
        "the command is not addressed to the host vision actually verified"
