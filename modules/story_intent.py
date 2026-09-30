"""Asking for a story and asking her to invent one are different requests.

2026-09-29, live: "Can you make up a story about King Tom and the story of Earth
and Mars?" came back "I don't have anything called King Tom — it isn't on my
shelf or in what I've filed. I'd rather tell you that than make one up." She was
asked to make one up.

The gate that produced that is right about retells and knows nothing about
intent: triage.classify() reaches its named-but-absent tier on the SHAPE of a
missing item and decides on RESOLUTION alone, so "tell me X" and "make up X" are
identical inputs to it. The decline is deterministic and fires above the model —
the journal shows no model call for those turns — so the split has to be
deterministic too. House law: what must be true is not left to a prompt.

WHAT THIS MODULE IS NOT ALLOWED TO DO. It must never turn a RETELL of an absent
work into an invention. That is the Dunwich failure: on 2026-09-25 a weaker gate
let "The Lighthouse at Dunwich" through and she produced a 2015 horror film, then
a public-domain summary, then a 1930s radio serial — three fabrications from one
missing veto. The verbs here are therefore explicit asks to CREATE, never
anything that merely sounds open-ended.
"""
from __future__ import annotations

import re

# ── Invention: an explicit ask to create something that does not exist ───────
# Each alternative names a making verb. "tell me a story" is deliberately NOT
# here — it is a request for a story, and she has a shelf; only "tell me a NEW
# story" is an ask to invent.
_INVENTION_RE = re.compile(
    r"\b(?:make|makes|making)\s+(?:me\s+)?(?:up\s+)?(?:a|an|one|another)\b"
    r"[^.?!]{0,30}\b(?:up\b|story|tale|yarn|fable|legend)"
    r"|\bmake\s+(?:one|it|something)\s+up\b"
    r"|\bmake\s+up\b[^.?!]{0,30}\b(?:story|tale|yarn|fable|legend|one)\b"
    r"|\binvent\b|\bmake[- ]believe\b"
    r"|\b(?:write|create|compose|dream)\s+(?:me\s+)?(?:up\s+)?(?:a|an|another)\b"
    r"|\bcome\s+up\s+with\b"
    r"|\bimagine\s+(?:a|an|another|me)\b"
    r"|\b(?:a|an|another)\s+(?:brand[- ]?)?new\s+(?:story|tale|one)\b"
    r"|\bnew\s+story\s+about\b",
    re.I)

# A retell asks for something that already exists. Checked FIRST, so a turn that
# carries both ("tell me the story of X") can never be read as an invention.
_RETELL_RE = re.compile(
    r"\btell\s+me\s+(?:the\s+)?story\s+of\b"
    r"|\b(?:read|recite|retell|replay)\s+(?:me\s+)?\b"
    r"|\bstory\s+of\b[^.?!]{0,40}\bagain\b"
    r"|\b(?:what|how)\s+(?:happens|does|did)\b[^.?!]{0,30}\b(?:end|happen|go)\b"
    r"|\bagain\b\s*[.?!]?$",
    re.I)


def is_invention(text: str) -> bool:
    """Did this turn explicitly ask her to make something up?

    Retell wins ties. "Tell me the story of King Tom again" contains neither
    making verb, but a phrasing that carried both would be a retell — the
    conservative direction, because the cost of reading a retell as an invention
    is a fabricated work presented as a real one.
    """
    t = (text or "").strip()
    if not t:
        return False
    if _RETELL_RE.search(t) and not re.search(r"\bnew\b", t, re.I):
        return False
    return bool(_INVENTION_RE.search(t))


# ── A declarative premise is not a request at all ────────────────────────────
# "King Tom is the story of Earth and Mars." asserts something; it asks for
# nothing. Answering it with "I don't have anything called King Tom" is a refusal
# to a turn that made no request, which reads as contradicting the user rather
# than as honesty about the shelf.
_PREMISE_RE = re.compile(
    r"^\s*(?P<name>[A-Z][\w'\-]*(?:\s+(?:of|at|the|and|in|on|a|an|for|to)\s+[A-Z][\w'\-]*"
    r"|\s+[A-Z][\w'\-]*)*)\s+(?:is|was|are|were)\s+(?:a|an|the)?\s*"
    r"(?:story|tale|book|legend|myth|yarn|fable)\b")

_QUESTION_HEAD_RE = re.compile(
    r"^\s*(?:what|who|where|when|why|how|is|are|was|were|do|does|did|can|could|"
    r"will|would|should|tell|read|make|write|invent|create|imagine|come)\b", re.I)


def declarative_premise(text: str) -> str | None:
    """The name asserted by "X is the story of Y", or None.

    Returns None for anything shaped like a question, including "is King Tom a
    story?" — that IS a question about the shelf and the ordinary path answers
    it honestly.
    """
    t = (text or "").strip()
    if not t or t.endswith("?"):
        return None
    if _QUESTION_HEAD_RE.match(t):
        return None
    m = _PREMISE_RE.match(t)
    return m.group("name").strip() if m else None


def offer_line(name: str) -> str:
    """The answer to a premise about a work she does not have.

    Not a decline: the turn asked for nothing, so there is nothing to refuse. It
    says plainly that she does not have it and offers the thing she can do.
    """
    return (f"I don't have a {name} on my shelf — that one's new to me. "
            f"Want me to make it up?")


def announce_line() -> str:
    """Said with an invented story, so it is never mistaken for canon."""
    return "This one's new — not from the shelf."
