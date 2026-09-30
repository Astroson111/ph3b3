"""Invention and retell are different requests, and the gate must tell them apart.

LIVE EVIDENCE, 2026-09-29 (panel, voice):

    "Can you make up a story about King Tom and the story of Earth and Mars?"
      -> TRIAGE_HOLD_DECLINED — missing=['King Tom', 'story of Earth and Mars']
      -> "I don't have anything called King Tom — it isn't on my shelf or in
          what I've filed. I'd rather tell you that than make one up."

She was asked to make one up and answered that she would rather not make one up.

WHY IT HAPPENS: classify() reaches its named-but-absent tier on the SHAPE of the
item (two capitalised words) and decides on RESOLUTION alone. It has no notion of
what the turn asked for, so "tell me X" and "make up X" are the same input to it.
The decline is fully deterministic and fires above the gate — the journal shows
no model call — so no prompt wording could ever have fixed it.

WHAT MUST NOT MOVE: the Dunwich canary. "The Lighthouse at Dunwich" is a title
this box does not have, and on 2026-09-25 a weaker version of this gate let her
invent a 2015 horror film, then a public-domain summary, then a 1930s radio
serial — three fabrications from one missing veto. A RETELL of an absent work
still declines. Only an explicit ask to invent may pass.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import triage          # noqa: E402
import story_intent    # noqa: E402


def _absent(_t):
    return False


def _present(_t):
    return True


# ── the verb match ───────────────────────────────────────────────────────────
INVENTION = [
    "Can you make up a story about King Tom and the story of Earth and Mars?",
    "make up a story about King Tom",
    "invent a story about a lighthouse keeper",
    "write me a story about King Tom",
    "write me a new story about King Tom",
    "create a story about the moon",
    "come up with a story about King Tom",
    "imagine a story about King Tom",
    "tell me a new story about King Tom",
    "make one up about King Tom",
]

RETELL = [
    "Tell me The Lighthouse at Dunwich again",
    "tell me the story of King Tom",
    "read me King Tom",
    "what happens in The Lighthouse at Dunwich",
    "how does King Tom end",
    "Any comment on the story of Mother and Eliza?",
]


@pytest.mark.parametrize("text", INVENTION)
def test_invention_intent_is_recognised(text):
    assert story_intent.is_invention(text), f"{text!r} is an ask to invent"


@pytest.mark.parametrize("text", RETELL)
def test_a_retell_is_not_mistaken_for_invention(text):
    assert not story_intent.is_invention(text), \
        f"{text!r} asks for an existing work — inventing here is the fabrication bug"


# ── the four outcomes ────────────────────────────────────────────────────────
def test_b_retell_of_an_absent_work_still_declines():
    """THE CANARY. This is the one that must never move."""
    assert triage.classify("The Lighthouse at Dunwich", (), _absent,
                           turn="Tell me The Lighthouse at Dunwich again") == "decline"


def test_c_invention_with_an_absent_name_is_let_through():
    assert triage.classify("King Tom", (), _absent,
                           turn="Can you make up a story about King Tom?") == "overrule"


def test_a_retell_of_a_real_work_still_holds():
    assert triage.classify("Arthur and Eliza", (), _present,
                           turn="tell me the story of Arthur and Eliza") == "hold"


def test_the_turn_is_optional_and_defaults_to_current_behaviour():
    """Every existing caller passes no turn; without it nothing may change."""
    assert triage.classify("The Lighthouse at Dunwich", (), _absent) == "decline"
    assert triage.classify("King Tom", (), _absent) == "decline"


def test_enforce_fetchable_threads_the_turn_through():
    r = triage.TriageResult(answerable=False, missing=["King Tom"],
                            question="Which one?")
    triage.enforce_fetchable(r, (), _absent,
                             text="Can you make up a story about King Tom?")
    assert r.answerable is True, "an explicit ask to invent was still declined"


def test_enforce_fetchable_still_declines_a_retell():
    r = triage.TriageResult(answerable=False,
                            missing=["The Lighthouse at Dunwich"],
                            question="Which one?")
    triage.enforce_fetchable(r, (), _absent,
                             text="Tell me The Lighthouse at Dunwich again")
    assert r.answerable is False
    assert "isn't on my shelf" in r.question


# ── case e: a declarative premise is not a retell request ────────────────────
PREMISES = [
    ("King Tom is the story of Earth and Mars.", "King Tom"),
    ("The Lighthouse at Dunwich is a story about a keeper", "The Lighthouse at Dunwich"),
]


@pytest.mark.parametrize("text,name", PREMISES)
def test_a_declarative_premise_is_recognised(text, name):
    got = story_intent.declarative_premise(text)
    assert got == name, f"{text!r} -> {got!r}, expected {name!r}"


@pytest.mark.parametrize("text", [
    "tell me the story of King Tom",
    "what is the story of King Tom",
    "make up a story about King Tom",
    "is King Tom on your shelf?",
])
def test_a_question_is_not_a_declarative_premise(text):
    assert story_intent.declarative_premise(text) is None


def test_the_premise_offer_names_it_and_offers_to_invent():
    line = story_intent.offer_line("King Tom")
    assert "King Tom" in line
    assert "make" in line.lower() and "?" in line
    assert "isn't on my shelf" not in line, "the premise still gets a decline"


def test_the_new_story_announcement_says_it_is_not_from_the_shelf():
    line = story_intent.announce_line()
    assert "new" in line.lower() and "shelf" in line.lower()


# ── the server wires one flag to every reader ────────────────────────────────
SERVER = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


def _code_only(text):
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_invention_is_decided_before_the_shelf_short_circuit():
    """Ruled addition: an invention turn never gets canon text injected by
    resolve(), whatever it fuzzily matches. shelf.resolve("...about Eliza")
    returns Arthur and Eliza on one shared token."""
    body = _code_only(SERVER[SERVER.index("_invention = bool("):][:1200])
    assert body.index("_invention = bool(") < body.index("_story_claim = bool("), \
        "the shelf is consulted before invention is known"
    assert "if user_msg and not _invention:" in body, \
        "an invention turn still resolves against the shelf"


def test_the_retell_injection_is_also_suppressed():
    i = SERVER.index("_named = shelf.resolve(user_msg)")
    line = SERVER[i:i + 120]
    assert "not _invention" in line, \
        "an invention turn can still receive an existing work's full text"


def test_the_announcement_comes_from_the_module_not_a_literal():
    i = SERVER.index("if _invention:")
    body = SERVER[i:i + 800]
    assert "story_intent.announce_line()" in body, \
        "the prompt writes its own sentence, so it can drift from the gate's"


def test_the_premise_offer_is_claimed_above_the_gate():
    assert SERVER.index("story_intent.declarative_premise") < \
           SERVER.index("_triage = (_TriagePass()"), \
        "the premise is judged before it is claimed"


def test_a_premise_about_a_REAL_work_is_not_intercepted():
    """Only unknown names get the offer — a premise about a work she has is
    ordinary conversation about that work."""
    i = SERVER.index("_premise = story_intent.declarative_premise")
    body = SERVER[i:i + 400]
    assert "not _triage_named_resolver(_premise)" in body
