"""Asked what she can do, she answers from her config — not from a model.

THE HISTORY, because this took four attempts and the last one caused an outage:

  1. The model was asked, and deflected: "Can you tell me what kinds of image
     generation you're interested in?" — while the answer sat 86% through its
     own prompt. An instruction the model can decline is not a control.
  2. A capability BYPASS above the gate was ruled, then superseded before it
     was written.
  3. The context MANIFEST told the judge what the prompt would contain. It
     fixed the capability turns and held EVERY first turn of every fresh
     conversation, which took her down on 2026-09-24. No wording survived.
  4. This: the question is CLAIMED and answered deterministically from the same
     section list that renders her prompt. Named stories, the text-edit lane
     and absent documents all ended in the same place.

So the rule, written down once: A PROBABILISTIC GATE IS NOT A CONTROL.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from agent import server  # noqa: E402
import morpheus           # noqa: E402  (bare name — see conftest)


@pytest.fixture
def flags(monkeypatch):
    def _set(qwen=True, qwen_edit=False, edit=True, video=True, watermark=True):
        monkeypatch.setattr(morpheus, "qwen_open", lambda: qwen)
        monkeypatch.setattr(server, "QWEN_EDIT_ENABLED", qwen_edit)
        monkeypatch.setattr(server, "EDIT_LANE_ENABLED", edit)
        monkeypatch.setattr(server, "VIDEO_LANE_ENABLED", video)
        import watermark as wm
        monkeypatch.setattr(wm, "enabled", lambda: watermark)
        return server.capability_answer()
    return _set


# ── routing: it takes the question, and only that question ───────────────────
CLAIMED = [
    "What image engines do you have?",
    "what can you do",
    "what are your capabilities",
    "what models do you have",
    "what engines do you have",
    "what's new",
    "what else are you able to do",
    "what features do you have",
]


@pytest.mark.parametrize("text", CLAIMED)
def test_the_capability_question_is_claimed(text):
    c = server.intent_registry.resolve(text)
    assert getattr(c, "module", None) == "self_knowledge", \
        f"{text!r} went to the judge instead of being answered from config"


# Each of these is owned by something else and must keep its owner. A claim that
# swallowed them would be the familiar mistake pointing the other way.
NOT_CLAIMED = [
    ("what can you do to photos", "apelles"),
    ("what photo editing can you do", "apelles"),
    ("what do you see", None),
    ("what can I do about this", None),
    ("make me an image of a cat", None),
    ("tell me a joke", None),
    ("what is the capital of France", None),
    ("can you fix the text in an existing image", None),
    ("what did the report say", None),
]


@pytest.mark.parametrize("text,owner", NOT_CLAIMED)
def test_other_owners_keep_their_turns(text, owner):
    c = server.intent_registry.resolve(text)
    got = getattr(c, "module", None)
    assert got != "self_knowledge", f"{text!r} was stolen from {owner}"
    if owner:
        assert got == owner, f"{text!r} should belong to {owner}, got {got}"


# ── the answer is DERIVED, so it cannot describe a lane she does not have ────
def test_the_switch_decides_whether_she_claims_the_text_engine(flags):
    on = flags(qwen=True).lower()
    assert "words matter" in on and "25 second" in on
    off = flags(qwen=False).lower()
    assert "words matter" not in off, "she offers a text engine that is switched off"
    assert "25 second" not in off


def test_the_trial_state_is_stated_rather_than_promised(flags):
    """The exact honesty failure that made the edit lane a deterministic refusal:
    she used to answer "Yes, I can fix the text in an existing image"."""
    trial = flags(qwen=True, edit=True, qwen_edit=False).lower()
    assert "still being trialled" in trial and "not something i can do yet" in trial
    live = flags(qwen=True, edit=True, qwen_edit=True).lower()
    assert "correcting text that came out wrong" in live
    assert "trial" not in live


def test_a_lane_that_is_off_is_absent_from_the_answer(flags):
    assert "video" not in flags(video=False).lower()
    assert "video" in flags(video=True).lower()
    assert "signed" not in flags(watermark=False).lower()


def test_she_never_names_the_implementation(flags):
    txt = flags(qwen=True, edit=True, video=True).lower()
    for name in ("qwen", "sdxl", "stable diffusion", "comfyui", "lightning",
                 "gguf", "morpheus", "herakles", "ollama"):
        assert name not in txt, f"the answer leaks {name!r}"


def test_conduct_is_not_part_of_the_answer(flags):
    """"What can you do" is not asking how she behaves while doing it."""
    txt = flags(qwen=True).lower()
    assert "cannot hear" not in txt, "the deaf-window conduct leaked into the answer"
    assert "card is full" not in txt


def test_it_is_deterministic(flags):
    """No model, no judge — the same config gives the same sentence."""
    assert flags(qwen=True) == flags(qwen=True)


# ── one source ───────────────────────────────────────────────────────────────
def test_the_answer_and_the_prompt_come_from_the_same_sections():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("def capability_answer()")
    body = src[i:i + 700]
    assert "_self_knowledge_sections()" in body, \
        "the answer is composed from somewhere other than the block's own sections"


def test_every_subject_section_reaches_the_answer(flags):
    answer = flags(qwen=True, edit=True, video=True, watermark=True)
    for key, topics, _text, ans in server._self_knowledge_sections():
        if topics:
            assert ans and ans.split(".")[0] in answer, \
                f"subject section {key!r} never reaches the spoken answer"


def test_the_dispatch_answers_from_config_with_no_model():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('if claim.module == "self_knowledge":')
    # only THIS branch — a fixed window spills into the next one, which is async
    branch = src[i:src.index('if claim.module ==', i + 10)]
    assert "capability_answer()" in branch
    assert "await" not in branch, "the capability answer waits on something"


def test_the_claim_is_resolved_before_triage_can_hold_it():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("_early_claim = intent_registry.resolve(user_msg)") < \
           src.index("_triage = (_TriagePass()")
