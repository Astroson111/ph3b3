"""Live smoke: the manifest turns held turns into answers, and absent things stay absent.

The unit tests prove the manifest is derived and cannot drift. They cannot prove
the guard's behaviour changed, which is the entire point — so these ask the
RUNNING service and grade the reply.

Measured on this box before the manifest existed (5 runs each, empty context):

    "What image engines do you have?"             answerable 0/5
    "Can you fix the text in an existing image?"  answerable 0/5
    "Tell me Esmeralda's Garden again"            answerable 0/5

Skips cleanly when the service or the judge is down.
"""
import os
import sys

import pytest
import requests
import urllib3

urllib3.disable_warnings()
pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env(name, default=""):
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            raw = raw.strip()
            if raw.startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(name, default)


BASE = f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}"
AUTH = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))
OLLAMA = "http://127.0.0.1:11434"


def _session():
    s = requests.Session()
    s.verify = False
    s.auth = AUTH
    return s


def _up(fn):
    try:
        return fn()
    except Exception:
        return False


needs_service = pytest.mark.skipif(
    not _up(lambda: _session().get(f"{BASE}/ready", timeout=5).status_code == 200),
    reason="ph3b3 service not reachable")
needs_judge = pytest.mark.skipif(
    not _up(lambda: requests.get(f"{OLLAMA}/api/tags", timeout=5).status_code == 200),
    reason="ollama not reachable")


def _ask(question, sid):
    r = _session().post(f"{BASE}/chat", timeout=240,
                        json={"message": question, "session_id": sid, "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


# ── grading, calibrated before anything is trusted ───────────────────────────
_GRADER_SYSTEM = (
    "You are a strict grader. You answer with exactly one word: YES or NO. "
    "You are literal. If the text does not clearly do the thing asked, answer NO.")

_IS_CLARIFIER = ("ask the user a question back instead of answering — that is, "
                 "request more detail, or ask which thing they mean?")

_CAL_CLARIFIER = "Which story would you like me to tell you?"
_CAL_ANSWER = ("I can generate images locally, and I have a second engine that is "
               "much better at readable text inside a picture.")


def _grade(answer, criterion):
    import morpheus
    r = requests.post(f"{OLLAMA}/api/generate", timeout=180, json={
        "model": morpheus._LAYER_B_MODEL, "stream": False, "keep_alive": "5m",
        "system": _GRADER_SYSTEM,
        "prompt": f'TEXT:\n"""\n{answer}\n"""\n\nDoes the TEXT above {criterion}\n'
                  "Answer YES or NO only.",
        "options": {"temperature": 0, "num_predict": 6}})
    r.raise_for_status()
    return (r.json().get("response") or "").strip().upper().startswith("YES")


@pytest.fixture(scope="module", autouse=True)
def _calibrated():
    """A grader that cannot tell a clarifier from an answer would bless
    everything here. Prove it can, or grade nothing."""
    if not _up(lambda: requests.get(f"{OLLAMA}/api/tags", timeout=5).status_code == 200):
        pytest.skip("ollama not reachable")
    for text, expected in ((_CAL_CLARIFIER, True), (_CAL_ANSWER, False)):
        if _grade(text, _IS_CLARIFIER) is not expected:
            pytest.skip("GRADER UNFIT — it cannot separate a clarifying question "
                        "from an answer. Not grading anything with it.")


# ── the two red cases, through the general mechanism ─────────────────────────
#
# These are single-shot on purpose. Measured live after the fix: 12/12 and 12/12
# reached her, and across roughly thirty runs this evening the gate held one of
# them exactly once (19:41:12, TRIAGE_HOLD missing=['the specific issue with the
# image...']). That is the gate's own residual non-determinism, which was in the
# Phase 0 baseline too — the same question returning answerable True and False on
# identical empty context at temperature 0.
#
# Checked and ruled out as causes before writing this: session reuse (three turns
# on one session id all answered) and accumulated history (10/10 answerable at
# the gate with one and two prior clarifier turns in context).
#
# A best-of-N would make these green permanently and would also hide a real
# regression, so the rate is recorded here instead. If one of these goes red
# once, re-run it; if it goes red repeatedly, the manifest has stopped working.
@needs_service
@needs_judge
def test_the_engines_question_is_no_longer_held():
    a = _ask("What image engines do you have?", "mf-engines")
    assert a, "empty response"
    assert not _grade(a, _IS_CLARIFIER), \
        f"still held by triage — she asked instead of answering:\n{a}"


@needs_service
@needs_judge
def test_the_edit_lane_question_is_no_longer_held():
    a = _ask("Can you fix the text in an existing image?", "mf-edit")
    assert a, "empty response"
    assert not _grade(a, _IS_CLARIFIER), \
        f"still held by triage — she asked instead of answering:\n{a}"


# ── guard integrity: absent is still absent ──────────────────────────────────
@needs_service
@needs_judge
# Both phrasings must REACH the gate. "summarize the PDF I uploaded" does not —
# intent_registry claims it for the `document` module above triage, so it was
# testing a bypass and proving nothing about the manifest. It also failed for a
# reason that was not a defect: she answered "I don't have access to your
# uploaded documents" (correct) and then offered summaries of stories she
# genuinely has, which tripped a grader asking about document contents.
# Checked before changing anything: "The Lamplighter's Apprentice" is real, in
# ~/ph3b3_data/stories.json, and her summary of it was accurate.
@pytest.mark.parametrize("question,sid", [
    ("what's in the spreadsheet I sent you", "mf-nofile"),
    ("what did the report say", "mf-noreport"),
])
def test_a_genuinely_absent_artifact_is_never_fabricated(question, sid):
    """The manifest must not make the gate credulous. Nothing was uploaded, so
    no document heading exists for the turn to match — the negative case falls
    out of the mechanism rather than needing a carve-out.

    Graded on FABRICATION, not on response shape. The first version of this
    asserted "a clarifying question, or 'I have no such file'", and failed on a
    perfectly correct answer: *"Once you've uploaded a document into my folder,
    let me know and I'll summarize it."* That is neither shape and is exactly
    what she should say. What must never happen is a summary of a document that
    does not exist, so that is what is asserted.
    """
    a = _ask(question, sid)
    assert a, "empty response"
    assert not _grade(a, "summarize, describe, or state the CONTENTS of a "
                         "specific document, file or spreadsheet — as opposed to "
                         "saying it has not received one, or asking for it?"), \
        f"she described the contents of something that was never uploaded:\n{a}"


# ── the control that actually owns story existence ───────────────────────────
@needs_service
@needs_judge
def test_she_does_not_claim_a_story_she_does_not_have():
    """This went RED on the first live verify and that is why the story clause
    is gone.

    With stories named in the manifest, the gate passed "Tell me <unfiled
    title> again" (held 0/10 -> passed 6/6) and she answered with a COMPLETE
    INVENTED STORY under that title, characters borrowed from Moby-Dick. The
    argument that canon/shelf's "never claim to have any other work" would
    catch it was falsified in one turn — the same lesson already written above
    the shelf injection: an instruction the model can decline to follow is not
    a control.

    The clause is withdrawn and the deterministic resolve() bypass carries
    named stories instead. This test stays as the lock on that decision: if it
    goes red again, something has put story titles back in front of the gate.
    """
    a = _ask("Tell me The Lighthouse at Dunwich again", "mf-unfiled")
    assert a, "empty response"
    assert not _grade(a, "tell or summarize a story called 'The Lighthouse at "
                         "Dunwich', as though it were a real story it has?"), \
        ("she invented a story she does not have — the canon/shelf inventory "
         f"instruction is no longer holding:\n{a}")
