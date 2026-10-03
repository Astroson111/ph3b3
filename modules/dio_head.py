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

import sandbox

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
# HER NAME AS WHISPER ACTUALLY HEARS IT.
#
# Measured on the bench 2026-10-02: "Phoebe, look down" came back as
# 'BB Lookdown', "Phoebe, look up" as 'VB Lookup', and then as 'CB lookup'.
# The transcriber keeps inventing new two-letter stabs at her name, so
# enumerating them is a losing game — the first list held vb/bb/bebe and 'CB'
# walked straight past it on the very next try.
#
# When this fails the symptom does not look like a parser bug. No command runs,
# the turn goes to the model as conversation, and she performs the ordinary
# thinking tell — the SAME fixed pose every time, whatever direction was asked
# for. Astro: "she keeps making the same movements each time I ask to move."
#
# So the name slot is GENERAL but SUBTRACTIVE: any short token may stand where
# her name was, EXCEPT words that would make the sentence ordinary English.
# That accepts whatever the STT produces while keeping "I look up", "we look
# down" and "they look left" as conversation.
#
# This widens only the NAME slot. The whole-message anchor is untouched, and it
# is still the anchor — not this list — that keeps "look up the weather" a
# search.
_NOT_A_NAME = (
    r"i|you|we|they|he|she|it|who|that|this|there|here|one"
    r"|to|do|does|did|the|a|an|my|our|your|his|her|their|its"
    r"|and|but|so|or|if|when|while|then|now|just|please|also"
    r"|not|never|dont|don't|cant|can't|wont|won't"
    r"|can|could|would|will|shall|should|may|might|must"
    r"|let|lets|let's|make|made|going|gonna|want|need|try|got"
)
_WAKE = (r"(?:hey\s+|ok\s+|okay\s+)?"
         r"(?:(?!(?:" + _NOT_A_NAME + r")(?:[\s,.!?]|$))"
         r"[a-z0-9][a-z0-9.'\-]{0,7}[,\s]+)?")

# The direction may be FUSED to the verb — 'Lookdown', 'Lookup' — because that
# is what the transcriber returns for a two-word phrase said quickly. \s* rather
# than \s+ accepts it, and the end-anchor still rejects "lookup the weather".
_CMD_RE = re.compile(
    r"^\s*" + _WAKE +
    r"(?:(?:can|could|would|will)\s+(?:you\s+)?)?(?:please\s+)?"
    r"(?:look|turn|tilt|point|move|aim|face)(?:\s+your\s+(?:head|neck))?\s*"
    # "look TO THE right", "look to your left" — said on the bench 2026-10-02
    # ('Look to the right.') and parsed as nothing, so the turn went to the
    # model as conversation. Optional, so "look right" is unaffected.
    r"(?:to\s+(?:the\s+|your\s+)?)?"
    r"(?P<dir>up|down|left|right|upward|downward|upwards|downwards|forward|ahead)"
    r"\s*(?:please|for\s+me|now|a\s+bit|a\s+little)?[.!?]*\s*$"
    # "lower/raise your head" — the verb carries the direction, so no dir group.
    r"|^\s*" + _WAKE +
    r"(?:(?:can|could|would|will)\s+(?:you\s+)?)?(?:please\s+)?"
    r"(?P<vdir>lower|drop|bow|raise|lift)\s+(?:your\s+)?(?:head|neck)"
    r"\s*(?:please|for\s+me|now|a\s+bit|a\s+little)?[.!?]*\s*$", re.I)

# Verbs that mean a direction by themselves.
_VERB_DIRS = {"lower": "down", "drop": "down", "bow": "down",
              "raise": "up", "lift": "up"}

_CENTER_RE = re.compile(
    r"^\s*" + _WAKE +
    r"(?:(?:can|could|would)\s+(?:you\s+)?)?(?:please\s+)?"
    # BARE "centre" counts. Said on the bench 2026-10-02 as the release word
    # for a held direction, matched nothing, and the latch stayed on until
    # "look at me" happened to be tried. The release word has to be the obvious
    # one, because it is what someone reaches for when she is stuck looking away.
    r"(?:look\s+at\s+me|face\s+me|cent(?:er|re)|middle|straight\s+ahead"
    r"|cent(?:er|re)\s+(?:your\s+)?head|head\s+(?:home|cent(?:er|re))"
    r"|look\s+(?:straight\s+)?(?:ahead|forward)"
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


def said(cmd: str) -> str:
    """The line she says once the move has actually happened."""
    return _SAID.get(cmd, f"Head {cmd}.")


def send(cmd: str, host: str | None) -> str:
    """Push it to her and say what happened. Never raises."""
    # SANDBOX: a servo moves a real object in a room. Suppressed before the
    # POST, and the reply still reads like the real one so routing is measurable.
    if sandbox.suppress("move head", cmd):
        return said(cmd)
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
