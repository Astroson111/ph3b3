"""dio_head.py — "look down" moves Dio's EYES, deterministically.

WHAT THIS DOES TODAY, corrected 2026-10-01. The device end of this lane calls
face.setGaze(yaw, pitch), and setGaze stores into _gazeYaw/_gazePitch, which are
consumed at ph3b3_face.h:208 as `gTX = _gazeYaw * EIR * 0.40f` — EIR is the eye
iris radius, so those are PUPIL DRAWING COORDINATES. "Look down" moves her drawn
eyes within their sockets on the screen. HER NECK DOES NOT MOVE.

NECK CONTROL IS NOT IMPLEMENTED. The servo API exists and her firmware already
uses it in gentleHome()/safeHome() — M5StackChan.Motion.moveX/moveY, with
isXMoving/isYMoving to wait and setTorqueEnabled to detach — but nothing on this
lane calls it. Wiring the neck is its own brief, blocked on a bench session that
first establishes the servos move at all.

This file said "reaches her neck" for a week, in six places, three of them
sentences she says out loud. It compiled, it unit-tested green, and it was
wrong: a function name is not evidence of what it does. The strings below now
describe the eyes, and a turn that explicitly asks for her HEAD or NECK gets
told plainly that it is not wired up.

Dio's head could not be commanded at all. Every Motion call in her firmware was
internal (idle wander, listening poses, boot homing); the only server->device
surfaces were the 20 s /emotion poll, which carries face state, and CamServer's
four camera routes. So "ph3b3, look down" had nowhere to go.

WHY :8080 AND NOT THE POLL. /emotion is right for STATE and wrong for a
command — "look down" should not arrive up to twenty seconds late. Her
CamServer already runs an HTTP server that Nyx already pushes to
(vision_module posts :8080/snapshot), and the host is learned and verified from
her own calls. So the lane exists; it needed one route.

MATCHING IS ANCHORED TO THE WHOLE MESSAGE. "look up" is the trap: "look up the
weather" is a search and must never move her eyes. Requiring the message to BE
the command, rather than to contain it, is what keeps those apart — and it is
deterministic, which is the rule this house arrived at four separate times this
week.

Failure is spoken, never silent: if her host is unknown or the POST fails she
says SHE COULD NOT REACH DIO — naming the transport, not a body part she did not
move — rather than a turn that looks like it worked.
"""
import re

import requests

PORT = 8080
TIMEOUT = 4.0

# The message must BE the command. "can you look down please" yes;
# "look up the weather" no; "I looked down at my shoes" no.
_CMD_RE = re.compile(
    r"^\s*(?:hey\s+|ok\s+)?(?:ph3b3|phoebe|dio)?[,\s]*"
    r"(?:can|could|would)?\s*(?:you\s+)?(?:please\s+)?"
    r"(?:look|turn|tilt|point)(?:\s+your\s+head)?\s+"
    r"(?P<dir>up|down|left|right|upward|downward|forward|ahead)"
    r"\s*(?:please|for\s+me|now|a\s+bit|a\s+little)?[.!?]*\s*$", re.I)

_CENTER_RE = re.compile(
    r"^\s*(?:hey\s+|ok\s+)?(?:ph3b3|phoebe|dio)?[,\s]*"
    r"(?:can|could|would)?\s*(?:you\s+)?(?:please\s+)?"
    r"(?:look\s+at\s+me|face\s+me|centre?\s+(?:your\s+)?head|head\s+(?:home|centre?)"
    r"|straighten\s+up|face\s+forward|re-?home(?:\s+your\s+head)?)"
    r"\s*(?:please|now)?[.!?]*\s*$", re.I)

_DIRS = {"up": "up", "upward": "up", "down": "down", "downward": "down",
         "left": "left", "right": "right", "forward": "center", "ahead": "center"}

# What she says on success. These describe EYES, which is what moves — "looking
# down" is exactly true of a gaze shift and claims nothing about her neck.
_SAID = {"down": "Looking down.", "up": "Looking up.",
         "left": "Looking left.", "right": "Looking right.",
         "center": "Back to centre."}

# An explicit ask for the HEAD or the NECK is a different request from "look
# down", and it is one this box cannot do. Answering it with a gaze shift would
# be the quiet lie this file was just corrected for: she would say "Looking
# down" and her head would not move, in front of someone watching the robot.
_NECK_RE = re.compile(r"\b(?:neck|head)\b", re.I)

NECK_NOT_WIRED = ("I can move my eyes, but my neck isn't wired up yet — "
                  "I'd be looking down without turning my head.")


def asks_for_neck(text: str) -> bool:
    """Did this turn name her head or neck specifically?

    Only consulted for messages that ARE a look command (parse() already said
    so), so "the head of the department" is never reached by it.
    """
    return bool(text and _NECK_RE.search(text))


def parse(text: str) -> str | None:
    """The command this message IS, or None. Pure text, no side effects."""
    if not text:
        return None
    if _CENTER_RE.match(text):
        return "center"
    m = _CMD_RE.match(text)
    return _DIRS.get(m.group("dir").lower()) if m else None


def send(cmd: str, host: str | None) -> str:
    """Push it to her and say what happened. Never raises."""
    if not host:
        return ("I couldn't reach Dio — I don't have her address right now. "
                "She has to have checked in since the last restart.")
    try:
        r = requests.post(f"http://{host}:{PORT}/head", params={"cmd": cmd},
                          timeout=TIMEOUT)
        if r.status_code == 200:
            return _SAID.get(cmd, f"Head {cmd}.")
        return (f"Dio didn't answer that — she returned {r.status_code} to "
                f"'{cmd}'. I'd rather say that than pretend I moved.")
    except Exception as exc:                      # noqa: BLE001
        return (f"I couldn't reach Dio ({exc.__class__.__name__}). "
                "I'd rather say that than pretend I moved.")
