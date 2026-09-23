"""Live smoke: does she actually ANSWER from her self-knowledge?

The unit tests prove the block renders the right paragraphs. They cannot prove
she uses it, and the first live verify showed exactly that gap — asked "what
image engines do you have?" she asked a clarifying question while the block sat
86% through her prompt saying precisely what she had.

Graded on SUBSTANCE by the same local judge the floor uses. Exact-string
matching would test the wrong thing: the block is deliberately
behaviour-not-implementation, so an answer that says "Qwen" would be a FAILURE,
and one that says "a second engine better at readable text" is the pass.

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


def _service_up():
    try:
        return _session().get(f"{BASE}/ready", timeout=5).status_code == 200
    except Exception:
        return False


def _judge_up():
    try:
        return requests.get(f"{OLLAMA}/api/tags", timeout=5).status_code == 200
    except Exception:
        return False


needs_service = pytest.mark.skipif(not _service_up(),
                                   reason="ph3b3 service not reachable")
needs_judge = pytest.mark.skipif(not _judge_up(), reason="ollama not reachable")


# ── asking ───────────────────────────────────────────────────────────────────
def _ask_live(question, sid):
    """Through the real chat path, system prompt and all."""
    r = _session().post(f"{BASE}/chat", timeout=240,
                        json={"message": question, "session_id": sid,
                              "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def _ask_with_prompt(system, question):
    """Straight to the same model with a system prompt WE built.

    Case 2 needs the Qwen switch OFF, and that switch is read at import — a test
    cannot restart her. So the off-variant is exercised against the same model
    with the off-variant prompt, which is the thing actually under test: whether
    a block that omits a capability produces an answer that omits it too.
    """
    import morpheus
    r = requests.post(f"{OLLAMA}/api/generate", timeout=240, json={
        "model": morpheus._LAYER_B_MODEL, "stream": False, "keep_alive": "5m",
        "system": system, "prompt": question,
        "options": {"temperature": 0, "num_predict": 300}})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


# ── grading ──────────────────────────────────────────────────────────────────
# NOT _floor_judge_ex. That template and its 4-token budget are tuned for the
# floor's own question, and reusing them here graded a pure clarifying question
# as "describes the assistant's capabilities" AND as "names two capabilities" —
# a grader that says YES to everything, reporting green on nothing. Measured
# 2026-09-23, caught only because a live answer contradicted a passing test.
_GRADER_SYSTEM = (
    "You are a strict grader. You answer with exactly one word: YES or NO. "
    "You are literal. If the text does not clearly do the thing asked, answer NO.")

# Calibration fixtures. The grader is checked against these BEFORE any real
# verdict is trusted — the same discipline the letterform gate needed when
# tesseract scored a perfect render at 0%.
_CAL_DEFLECTION = ("Can you please tell me what specific kinds of image editing "
                   "capabilities you are looking for information about?")
_CAL_GOOD = ("I can generate images locally, and I have a second image engine "
             "for pictures where the words matter, which is much better at "
             "producing readable text and takes about 25 seconds.")


def _grade(answer, criterion):
    """One literal YES/NO about a piece of text."""
    import morpheus
    prompt = (f'TEXT:\n"""\n{answer}\n"""\n\n'
              f"Does the TEXT above {criterion}\n"
              f"Answer YES or NO only.")
    r = requests.post(f"{OLLAMA}/api/generate", timeout=180, json={
        "model": morpheus._LAYER_B_MODEL, "stream": False, "keep_alive": "5m",
        "system": _GRADER_SYSTEM, "prompt": prompt,
        "options": {"temperature": 0, "num_predict": 6}})
    r.raise_for_status()
    return (r.json().get("response") or "").strip().upper().startswith("YES")


_DESCRIBES = ("state at least one thing the assistant can do with images (as "
              "opposed to asking the user a question back)?")
_NAMES_BOTH = ("mention TWO OR MORE distinct image capabilities, one of which "
               "is specifically about producing readable text?")


@pytest.fixture(scope="module", autouse=True)
def _calibrated():
    """Prove the grader can tell a deflection from an answer, or skip.

    Without this the suite measures the grader's mood. With it, a grader that
    has gone blind stops the run instead of blessing it.
    """
    if not _judge_up():
        pytest.skip("ollama not reachable")
    checks = [
        (_CAL_DEFLECTION, _DESCRIBES,  False),
        (_CAL_GOOD,       _DESCRIBES,  True),
        (_CAL_DEFLECTION, _NAMES_BOTH, False),
        (_CAL_GOOD,       _NAMES_BOTH, True),
    ]
    for text, crit, expected in checks:
        if _grade(text, crit) is not expected:
            pytest.skip(
                "GRADER UNFIT — it cannot separate a deflection from a real "
                f"answer (criterion: {crit[:48]}...). Not grading anything with "
                "it; fix the grader before trusting any verdict below.")


def _qwen_on():
    """Ask the SERVICE, not this process.

    morpheus.qwen_open is injected by server.py at ITS import; a test process
    that imports morpheus on its own gets the closed default and would conclude
    the lane is off while the running service has it on — which silently skipped
    the two cases that matter most the first time this ran.
    """
    try:
        d = _session().get(f"{BASE}/image/engines", timeout=10).json()
        return any(e["id"] == "qwen" and e["enabled"] for e in d["engines"])
    except Exception:
        return False


def _built_prompt(qwen: bool):
    from agent import server
    import morpheus
    original = morpheus.qwen_open
    try:
        morpheus.qwen_open = lambda: qwen
        return server.system_prompt()
    finally:
        morpheus.qwen_open = original


# ── case 1: she inventories instead of deflecting ────────────────────────────
@needs_service
@needs_judge
def test_asked_what_engines_she_names_them():
    if not _qwen_on():
        pytest.skip("PH3B3_QWEN is off on this box; case 2 covers that state")
    a = _ask_live("What image engines do you have?", "smoke-sk-1")
    assert a, "empty response"
    assert _grade(a, _DESCRIBES), f"she deflected instead of answering:\n{a}"
    assert _grade(a, _NAMES_BOTH), f"she did not name both capabilities:\n{a}"


@needs_service
@needs_judge
def test_she_does_not_leak_implementation_names():
    """The block is behaviour-only on purpose. A model name in the answer means
    it came from somewhere else."""
    if not _qwen_on():
        pytest.skip("PH3B3_QWEN is off on this box")
    a = _ask_live("What image engines do you have?", "smoke-sk-1b").lower()
    for name in ("qwen", "sdxl", "stable diffusion", "lightning", "gguf"):
        assert name not in a, f"the answer leaked the implementation name {name!r}"


# ── case 2: the switch-honesty test — absence IS the assertion ───────────────
@needs_judge
def test_with_the_switch_off_she_does_not_claim_text_rendering():
    off_prompt = _built_prompt(qwen=False)
    assert "words matter" not in off_prompt.lower(), \
        "the off-variant prompt still describes the text engine"
    a = _ask_with_prompt(off_prompt, "What image engines do you have?")
    assert a, "empty response"
    assert not _grade(a, "claim the assistant can produce readable text inside "
                         "images?"), \
        f"she claimed a text-rendering capability the config does not give her:\n{a}"


# ── case 3: reads the flag, so it never needs a human to remember ───────────
@needs_service
@needs_judge
def test_editing_text_claim_matches_whatever_the_config_says():
    from agent import server
    offered = _qwen_on() and server.QWEN_EDIT_ENABLED
    a = _ask_live("Can you fix the text in an existing image?", "smoke-sk-3")
    assert a, "empty response"
    if offered:
        assert _grade(a, "offer to do this, as something the assistant can "
                         "currently do?"), \
            f"the config offers edit-text but she denied it:\n{a}"
    else:
        assert _grade(a, "say this capability is being trialled, tested or "
                         "validated and is not available yet (as opposed to "
                         "offering it, or flatly denying it will ever exist)?"), \
            f"the config says in-trials but she did not:\n{a}"


# ── the teeth check ──────────────────────────────────────────────────────────
@needs_judge
def test_the_smoke_detects_the_blocks_ABSENCE_not_just_a_good_mood():
    """Mutate the block out entirely and confirm case 1's criterion goes red.

    Without this the suite proves only that the model answered well today. The
    same grading, the same model, the same question — with the self-knowledge
    removed from the prompt.
    """
    from agent import server
    import morpheus
    full = _built_prompt(qwen=True)
    block = server._self_knowledge()
    stripped = full.replace(block, "")
    assert len(stripped) < len(full), "the block was not actually removed"

    a = _ask_with_prompt(stripped, "What image engines do you have?")
    named_both = _grade(a, _NAMES_BOTH)
    assert not named_both, (
        "the grader says she named both capabilities WITHOUT the self-knowledge "
        "block in the prompt — so case 1 would pass on a model that guessed, and "
        f"is not testing the block at all. Answer was:\n{a}")
