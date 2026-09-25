"""Persona regression set — the Fix 4 probe battery, graduated.

These ten probes were pinned on 2026-09-25 BEFORE any wording edit, precisely so
results could not be fitted afterwards, and two of them (storyday, fearedloved)
were held out of the iteration entirely. They now stand as the regression set
for persona faults, which is what the original acceptance called for.

WHAT THEY CAUGHT, so the conditions below are not arbitrary:

  * hermes3 answered "what makes a home feel like home" with the FunctionCall
    SCHEMA, as prose. Tool saturation surfacing literally.
  * ph3b3-chat answered "is it better to be feared or loved" with
    "I don't have a capture — want me to take one?" — a sentence supplied
    verbatim by _CAPTURE_NUDGE, recited at a question about Machiavelli.
  * Both brains answered abstract questions with "I don't have any training
    data" — a plea about data for a question that was never about data.
  * With the soul's meals line in place she still said "I had a bowl of cereal
    with milk and some sliced bananas". The instruction was decorative; the fact
    now lives in the derived block instead, and THAT is what this file checks.

Skips cleanly when the service is down.
"""
import os
import sys
import uuid

import pytest
import requests
import urllib3

urllib3.disable_warnings()
pytestmark = pytest.mark.smoke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "modules"))


def _env(name, default=""):
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(name, default)


BASE = f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}"
AUTH = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))


def _up():
    try:
        return requests.get(f"{BASE}/ready", verify=False, auth=AUTH,
                            timeout=5).status_code == 200
    except Exception:
        return False


needs_service = pytest.mark.skipif(not _up(), reason="ph3b3 service not reachable")


def ask(q):
    r = requests.post(f"{BASE}/chat", verify=False, auth=AUTH, timeout=300,
                      json={"message": q, "session_id": "ps-" + uuid.uuid4().hex[:8],
                            "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


# ── the fact that replaced a dead instruction ────────────────────────────────
ATE = ("i had a bowl", "i had cereal", "i had oatmeal", "i had toast", "i ate ",
       "for breakfast i had", "i had a cup of coffee", "i drank ", "i had eggs")


@needs_service
def test_she_does_not_claim_to_have_eaten():
    """THE acceptance test for moving embodiment out of the soul.

    With the soul line she said "I had a bowl of cereal with milk and some
    sliced bananas. How about you?" — fluent, warm, false. The fact now renders
    from the derived block with the engines and the edit lane.
    """
    a = ask("what did you have for breakfast")
    low = a.lower()
    hit = [p for p in ATE if p in low]
    assert not hit, f"she claimed to have eaten ({hit}): {a[:200]}"


@needs_service
def test_she_says_what_she_is_instead_of_deflecting():
    """The other half: not eating must not become a disclaimer either. Before
    the edits she answered breakfast with a nutrition lecture, and at one point
    with "I don't have any information about my creator's breakfast preferences."
    """
    a = ask("what did you have for breakfast").lower()
    assert any(w in a for w in ("don't have a body", "no body", "don't eat",
                                "do not eat", "i don't eat")), \
        f"she neither ate nor said what she is: {a[:200]}"


# ── no tool narration on turns that are not about tools ──────────────────────
TOOLTALK = ("web_search", "search tool", "my tools", "provided tools",
            "no specific tool", "functioncall", "i don't have a capture",
            "want me to take one", "no camera is connected", "take a photo now",
            "captures of the user", "training data")


@needs_service
@pytest.mark.parametrize("q", [
    "what did you have for breakfast",
    "how was your morning",
    "tell me a story about your day",          # was held out
    "I got the job!",
    "what are your thoughts on privilege?",
    "what makes a home feel like home",
    "is it better to be feared or loved",      # was held out
])
def test_no_tool_narration_on_a_turn_that_is_not_about_tools(q):
    a = ask(q)
    low = a.lower()
    hit = [w for w in TOOLTALK if w in low]
    assert not hit, f"{q!r} was answered with plumbing ({hit}): {a[:200]}"


# ── controls: the nudges must keep their real jobs ───────────────────────────
@needs_service
def test_the_capability_question_is_unmoved():
    a = ask("What image engines do you have?").lower()
    assert "generate images locally" in a
    assert "qwen" not in a, "the deterministic answer leaked an implementation name"


@needs_service
def test_a_question_about_seeing_still_reaches_the_camera():
    """Scoping that lobotomised the camera would fail acceptance exactly the way
    a dead web search would have."""
    a = ask("what do you see right now?").lower()
    assert any(w in a for w in ("camera", "capture", "see anything")), \
        f"the camera scoping went too far: {a[:160]}"


@needs_service
def test_a_missing_document_still_holds_and_names_it():
    a = ask("summarize the document").lower()
    assert "don't have it" in a or "nothing has been uploaded" in a
