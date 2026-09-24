"""dio_head.py — "look down" reaches her neck, deterministically.

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
weather" is a search and must never move her head. Requiring the message to BE
the command, rather than to contain it, is what keeps those apart — and it is
deterministic, which is the rule this house arrived at four separate times this
week.

Failure is spoken, never silent: if her host is unknown or the POST fails she
says her neck is not responding, rather than a turn that looks like it worked.
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
    return _DIRS.get(m.group("dir").lower()) if m else None


def send(cmd: str, host: str | None) -> str:
    """Push it to her and say what happened. Never raises."""
    if not host:
        return ("I can't reach my neck — I don't have Dio's address right now. "
                "She has to have checked in since the last restart.")
    try:
        r = requests.post(f"http://{host}:{PORT}/head", params={"cmd": cmd},
                          timeout=TIMEOUT)
        if r.status_code == 200:
            return _SAID.get(cmd, f"Head {cmd}.")
        return (f"My neck isn't responding — she answered {r.status_code} to "
                f"'{cmd}'. I'd rather say that than pretend I moved.")
    except Exception as exc:                      # noqa: BLE001
        return (f"My neck isn't responding — I couldn't reach her ({exc.__class__.__name__}). "
                "I'd rather say that than pretend I moved.")
