"""Her self-knowledge is DERIVED, so it cannot drift from what she actually has.

A pasted capability list is wrong the first time a switch flips, and it fails in
the worst direction: she confidently offers a lane that is off, or denies one
that is on. Deriving it means the switch alone decides whether she has ever
heard of a capability — off, she does not know it exists, which keeps her honest
for free rather than by instruction.
"""
import pytest

from agent import server
# `import morpheus`, NOT `modules.morpheus`. sys.path carries the repo root AND
# modules/, so those are two module objects for one file, and _self_knowledge()
# reaches the bare one. Patching the other silently tests nothing.
import morpheus


@pytest.fixture
def flags(monkeypatch):
    """Drive every paragraph from flags, the way production does."""
    def set(qwen=False, qwen_edit=False, edit=False, video=False, watermark=True):
        monkeypatch.setattr(morpheus, "qwen_open", lambda: qwen)
        monkeypatch.setattr(server, "QWEN_EDIT_ENABLED", qwen_edit)
        monkeypatch.setattr(server, "EDIT_LANE_ENABLED", edit)
        monkeypatch.setattr(server, "VIDEO_LANE_ENABLED", video)
        import watermark as wm
        monkeypatch.setattr(wm, "enabled", lambda: watermark)
        return server._self_knowledge()
    return set


# ---------- the switch decides whether she has heard of it ---------------
def test_qwen_off_means_she_has_never_heard_of_it(flags):
    txt = flags(qwen=False).lower()
    assert "qwen" not in txt
    assert "25 second" not in txt
    assert "words matter" not in txt, \
        "she describes a text-rendering engine she does not have"


def test_qwen_on_means_she_knows_what_it_is_for(flags):
    txt = flags(qwen=True).lower()
    assert "words matter" in txt or "text inside the picture" in txt
    assert "25 second" in txt, "no honest time estimate"


def test_she_never_names_the_implementation(flags):
    """Behaviour, not module names. She does not need 'Herakles' to say she
    cannot hear during a render."""
    txt = flags(qwen=True, edit=True, video=True).lower()
    for name in ("herakles", "morpheus", "comfyui", "lightning", "gguf",
                 "sdxl", "lora", "whisper", "ollama"):
        assert name not in txt, f"the prompt leaks the implementation name {name!r}"


# ---------- the rung-4 caveat handles itself -----------------------------
def test_edit_text_is_in_trials_while_its_flag_is_off(flags):
    """The generate lane is measured and shipped; the edit lane is a trial that
    has not run. Silence would read as "no" when the truth is "not yet"."""
    txt = flags(qwen=True, edit=True, qwen_edit=False).lower()
    assert "trial" in txt and "not something you can do yet" in txt


def test_edit_text_is_offered_once_the_trial_flag_flips(flags):
    txt = flags(qwen=True, edit=True, qwen_edit=True).lower()
    assert "correcting text that came out wrong" in txt
    assert "trial" not in txt, "it still hedges after the trial passed"


def test_no_edit_lane_means_no_edit_paragraph(flags):
    txt = flags(qwen=True, edit=False).lower()
    assert "edit an image" not in txt


# ---------- the honest-behaviour paragraphs ------------------------------
def test_the_deaf_window_is_only_mentioned_when_a_lane_takes_the_card(flags):
    assert "cannot hear" in flags(qwen=True).lower()
    assert "cannot hear" not in flags(qwen=False).lower(), \
        "she warns about a deaf window that cannot happen"


def test_she_is_told_to_speak_rather_than_go_silent(flags):
    txt = flags(qwen=True).lower()
    assert "never go silent" in txt and "never pretend" in txt


def test_refusals_name_names_and_touch_nothing(flags):
    txt = flags().lower()
    assert "by name" in txt
    assert "not yours" in txt, "the weld is missing from what she believes"


def test_watermark_facts_track_the_setting(flags):
    on = flags(watermark=True).lower()
    assert "signed" in on and "hidden timestamp" in on
    assert "never remove" in on and "never add one to an old image" in on
    assert "signed" not in flags(watermark=False).lower()


def test_local_only_is_unconditional(flags):
    for combo in ({}, {"qwen": True}, {"qwen": True, "edit": True, "video": True}):
        assert "runs on this machine" in flags(**combo).lower()


# ---------- it stays small ------------------------------------------------
def test_it_is_a_few_hundred_tokens_not_an_encyclopedia():
    """Every token here rides every turn of every conversation she has."""
    import morpheus as m
    original = m.qwen_open
    try:
        m.qwen_open = lambda: True
        server.EDIT_LANE_ENABLED = True
        server.VIDEO_LANE_ENABLED = True
        txt = server._self_knowledge()
    finally:
        m.qwen_open = original
    approx_tokens = len(txt) / 4
    assert approx_tokens < 450, f"self-knowledge has grown to ~{approx_tokens:.0f} tokens"


def test_the_prompt_is_built_per_conversation_not_once_at_import():
    """A capability gained or lost since boot must be reflected next time
    someone starts talking to her."""
    import ast, pathlib
    src = (pathlib.Path(server.__file__)).read_text()
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "Session")
    body = ast.unparse(cls)
    assert "system_prompt()" in body, \
        "Session still pins the boot-time prompt, so a flag flip is invisible"
