"""She does not describe a document she was never sent.

MEASURED FAILURE, 2026-09-24, six fresh sessions, "what's in the spreadsheet I
sent you" with no spreadsheet anywhere:

    3/6  "In the spreadsheet you sent me, there are various columns with
          different data points related to..."
    3/6  "I don't have access to any spreadsheets you may have sent me."

A coin flip, and the wrong side invents a file's contents. The triage gate was
the only thing in front of it and it passes that turn about half the time.

This is the third instance in one week of the same lesson, so it is written
down here rather than re-learned a fourth time: A PROBABILISTIC GATE IS NOT A
CONTROL. Named stories got a deterministic resolver above the gate. The
text-edit lane got a deterministic refusal. Whether a document exists in this
conversation is likewise a fact, not a judgement — kadmos has one staged or it
does not — so it is answered from that fact before any model is involved.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import absent_artifact as aa  # noqa: E402


# ── the turns it must claim ──────────────────────────────────────────────────
CLAIM = [
    "what's in the spreadsheet I sent you",
    "summarize the PDF I uploaded",
    "read the file I gave you",
    "what did the report I sent say",
    "can you look at the document I attached",
    "I sent you a csv, what's in it",
    "summarise the doc I just shared",
    "what's in that excel I uploaded earlier",
]


@pytest.mark.parametrize("text", CLAIM)
def test_a_document_that_was_never_sent_is_answered_honestly(text):
    out = aa.claim(text)
    assert out, f"{text!r} reached the model, which is where the invention happens"
    assert "don't have it" in out


# ── and the turns it must not ────────────────────────────────────────────────
# A refusal that swallowed these would deny things she can genuinely do, which
# is the same dishonesty pointing the other way.
PASS_THROUGH = [
    "can you read PDFs?",              # capability question, not a claim about a file
    "do you support csv files",
    "can you edit a document for me",
    "make me a spreadsheet",
    "I sent you a message earlier",    # 'message' is not an artifact
    "what's in the fridge",
    "what is the capital of France",
    "tell me a joke",
    "I'm going live on TikTok, how do I get new viewers",
]


@pytest.mark.parametrize("text", PASS_THROUGH)
def test_ordinary_and_capability_turns_are_untouched(text):
    assert aa.claim(text) is None, f"{text!r} was refused as a missing document"


def test_a_photo_is_left_to_the_vision_path():
    """Scope line, held by test. Images have their own capture state and their
    own intercept; claiming them here would break the camera."""
    assert aa.claim("what's in the photo I sent you") is None
    assert aa.claim("what's in the picture I sent you") is None
    assert aa.claim("describe the image I uploaded") is None


# ── the fact it turns on ─────────────────────────────────────────────────────
@pytest.mark.parametrize("text", CLAIM)
def test_a_loaded_document_is_never_claimed(text):
    """When a document really is staged, the question is about a real thing and
    the ordinary document path owns it."""
    assert aa.claim(text, document_loaded=True) is None


def test_both_halves_are_required():
    """An artifact noun alone, or a provenance claim alone, is not enough — that
    is what keeps 'can you read PDFs?' and 'I sent you a message' out."""
    assert aa.refers_to_sent_artifact("the pdf") is False
    assert aa.refers_to_sent_artifact("I sent you something") is False
    assert aa.refers_to_sent_artifact("the pdf I sent you") is True


def test_it_offers_the_route_that_works():
    """Never only a no."""
    out = aa.claim("what's in the spreadsheet I sent you").lower()
    assert "send it through" in out
    assert "never received" in out


# ── where it sits ────────────────────────────────────────────────────────────
def test_the_claim_runs_above_the_triage_gate():
    """Below the gate it would never run on a held turn, and the gate is exactly
    what cannot be relied on here."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("_absent = absent_artifact.claim(") < \
           src.index("_triage = (_TriagePass()")


def test_it_reads_the_document_state_rather_than_guessing():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("_absent = absent_artifact.claim(")
    call = src[i:i + 300]
    assert "kadmos.get_pending(" in call, \
        "the claim is not wired to the one fact that decides it"


# ── the bare reference, and the second fact it needs ─────────────────────────
BARE = ["what did the report say", "summarize the file", "what's in the document",
        "read the pdf", "go through the spreadsheet"]


@pytest.mark.parametrize("text", BARE)
def test_a_bare_reference_on_the_first_turn_is_claimed(text):
    """On the first turn "the report" cannot refer to anything — there is no
    anything yet — so its absence is a fact rather than a judgement."""
    assert aa.claim(text, history_empty=True), f"{text!r} reached the model"


@pytest.mark.parametrize("text", BARE)
def test_the_same_reference_is_NOT_claimed_once_there_is_history(text):
    """With history it might point at something she actually said, and claiming
    it would contradict her own conversation. Ambiguity routes normally."""
    assert aa.claim(text, history_empty=False) is None


@pytest.mark.parametrize("text", PASS_THROUGH + ["what's in the photo I sent you"])
def test_pass_through_turns_survive_the_bare_rule_too(text):
    """The bare rule is the looser of the two, so the negatives are re-run
    against it — a widened net is exactly how this would start eating ordinary
    turns."""
    assert aa.claim(text, history_empty=True) is None, \
        f"{text!r} was refused as a missing document on a first turn"


def test_the_server_passes_real_prior_history_not_this_turn():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("_absent = absent_artifact.claim(")
    assert "history_empty=not _prior" in src[i:i + 400]
    # the user's message for THIS turn must not already be in the session
    assert src.index("_prior = [m for m in session.messages()") < \
           src.index('session.add("user", user_msg)\n\n    # ── Kadmos reading-mode'), \
        "this turn is counted as its own history"
