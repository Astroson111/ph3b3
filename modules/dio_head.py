"""dio_head.py — "look down" moves Dio's eyes AND her neck, deterministically.

WHAT THIS DOES TODAY, verified on the bench 2026-10-02: the eyes lead via
face.setGaze and the NECK FOLLOWS via M5StackChan.Motion.moveX/moveY. The head
physically turns. Confirmed by watching the robot, which is the only authority
that counts here.

THE HISTORY, kept because it cost a week. This file once claimed "look down
reaches her neck" while the device end called ONLY face.setGaze — which drives
her drawn pupils (ph3b3_face.h:208, gTX = _gazeYaw * EIR), not a servo. It
compiled, it unit-tested green, and her neck never moved: a function name is not
evidence of what it does. On 2026-10-01 the strings were corrected to describe
the eyes and an explicit neck request was refused honestly. On 2026-10-02 the
firmware was rewritten onto the servos and verified moving, so the refusal became
the false statement and was removed in turn.

Both corrections were right when made. The rule they share is that these strings
describe what the hardware does TODAY, and they change when it does.

Every target is an OFFSET FROM HER SAVED HOME POSE, set on her own screen under
Settings -> Head Position, so "look down" means the same gesture wherever she is
mounted and "centre" returns to the angle her room needs.

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
# VERBS, widened 2026-10-02. The list was look/turn/tilt/point, and the first
# thing actually said to her on the bench was "Phoebe, can you move your head
# down?" — which parsed as nothing, went to the model as ordinary conversation,
# and produced a speaking-gaze motion that read as the robot ignoring the order.
# "move" is the obvious word for a thing that moves; so are lower/raise/drop/lift.
#
# Widening a COMMAND vocabulary is not free — every verb added is a turn that can
# no longer be ordinary conversation — so the anchoring stays strict: the message
# must BE the command end to end, which is what keeps "look up the weather" and
# "I moved my head" out of it.
_CMD_RE = re.compile(
    r"^\s*(?:hey\s+|ok\s+)?(?:ph3b3|phoebe|dio)?[,\s]*"
    r"(?:can|could|would|will)?\s*(?:you\s+)?(?:please\s+)?"
    r"(?:look|turn|tilt|point|move|aim|face)(?:\s+your\s+(?:head|neck))?\s+"
    r"(?P<dir>up|down|left|right|upward|downward|upwards|downwards|forward|ahead)"
    r"\s*(?:please|for\s+me|now|a\s+bit|a\s+little)?[.!?]*\s*$"
    # "lower/raise your head" — the verb carries the direction, so no dir group.
    r"|^\s*(?:hey\s+|ok\s+)?(?:ph3b3|phoebe|dio)?[,\s]*"
    r"(?:can|could|would|will)?\s*(?:you\s+)?(?:please\s+)?"
    r"(?P<vdir>lower|drop|bow|raise|lift)\s+(?:your\s+)?(?:head|neck)"
    r"\s*(?:please|for\s+me|now|a\s+bit|a\s+little)?[.!?]*\s*$", re.I)

# Verbs that mean a direction by themselves.
_VERB_DIRS = {"lower": "down", "drop": "down", "bow": "down",
              "raise": "up", "lift": "up"}

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

def parse(text: str) -> str | None:
    """The command this message IS, or None. Pure text, no side effects."""
    if not text:
        return None
    if _CENTER_RE.match(text):
        return "center"
    m = _CMD_RE.match(text)
    if not m:
        return None
    if m.group("dir"):
        return _DIRS.get(m.group("dir").lower())
    vd = m.group("vdir")
    return _VERB_DIRS.get(vd.lower()) if vd else None


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
