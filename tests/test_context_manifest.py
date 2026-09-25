"""The triage manifest is DERIVED from the same stores as the injections it
describes — so the guard cannot be told about something she does not have.

The defect: triage judges answerability against a context that has not been
assembled yet, so anything answered by an assembly-time injection reads as
"missing" and gets held. Four one-off bypasses had accumulated above the gate
for four instances of it. This is the general mechanism.

THE INVARIANT these tests exist to hold, restated for the two-author design:

    Every manifest heading derives from the same store as the injection it
    describes. No heading is hand-written prose, and the drift test covers
    every author — not just the block.

"One renderer" was the original mechanism and could not survive contact with
four subject classes (capabilities from the self-knowledge block; stories from
canon and shelf; documents from kadmos). What matters is not that one function
renders them, but that no heading can exist unless the thing it names actually
rendered — which is what test_no_heading_outlives_its_section proves, per
author.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import context_manifest as cm          # noqa: E402
import triage                          # noqa: E402
from agent import server               # noqa: E402
import morpheus                        # noqa: E402  (bare name — see conftest)


# ── the flag matrix every section is driven from ─────────────────────────────
_COMBOS = [
    dict(qwen=False, qwen_edit=False, edit=False, video=False, watermark=False),
    dict(qwen=True,  qwen_edit=False, edit=False, video=False, watermark=False),
    dict(qwen=True,  qwen_edit=False, edit=True,  video=False, watermark=True),
    dict(qwen=True,  qwen_edit=True,  edit=True,  video=True,  watermark=True),
    dict(qwen=False, qwen_edit=False, edit=True,  video=True,  watermark=True),
]


@pytest.fixture
def at_flags(monkeypatch):
    """Render the sections under a given switch state, the way production does."""
    def _set(qwen=False, qwen_edit=False, edit=False, video=False, watermark=True):
        monkeypatch.setattr(morpheus, "qwen_open", lambda: qwen)
        monkeypatch.setattr(server, "QWEN_EDIT_ENABLED", qwen_edit)
        monkeypatch.setattr(server, "EDIT_LANE_ENABLED", edit)
        monkeypatch.setattr(server, "VIDEO_LANE_ENABLED", video)
        import watermark as wm
        monkeypatch.setattr(wm, "enabled", lambda: watermark)
        return server._self_knowledge_sections()
    return _set


# ── the refactor changed nothing she reads ───────────────────────────────────
def test_the_block_is_still_the_join_of_its_sections(at_flags):
    """_self_knowledge() gained a second reader, not a second behaviour."""
    for combo in _COMBOS:
        sections = at_flags(**combo)
        assert server._self_knowledge() == "\n- ".join(t for _k, _t, t, _a in sections)


# ── author 1: capabilities ───────────────────────────────────────────────────
# Every section, and the ruling on what it IS. A SUBJECT is something a user
# asks after, so it reaches the guard; CONDUCT is how she behaves while doing
# it, which nobody opens a turn with.
#
# This table is the lock, and it is deliberately not derived from the code it
# checks — pinning only the section KEYS was not enough. Re-classifying
# watermark from SUBJECT to CONDUCT deletes its heading from the guard while
# the paragraph still renders to her, which is precisely the drift this file
# exists to catch, and the key-only version of this test passed that mutation.
_CLASS = {
    "preamble":    "conduct",   # an instruction about the section, not a subject
    "images":      "subject",
    "edit":        "subject",
    "video":       "subject",
    "watermark":   "subject",   # "did you sign that?" is a real question
    "embodiment":  "subject",   # "what did you have for breakfast?" is a real question
    "deaf_window": "conduct",
    "card_full":   "conduct",
    "local":       "subject",   # "does any of this leave the machine?"
}


def test_every_section_is_classified_and_stays_classified(at_flags):
    """A new paragraph cannot slip in without someone ruling SUBJECT vs CONDUCT,
    and an existing one cannot be quietly reclassified out of the guard."""
    seen = set()
    for combo in _COMBOS:
        for key, topics, text, answer in at_flags(**combo):
            seen.add(key)
            assert isinstance(topics, tuple), f"{key}: topics must be a tuple"
            assert text.strip(), f"{key}: rendered an empty section"
            assert key in _CLASS, (
                f"section {key!r} renders but is unclassified. Decide whether it "
                "is a SUBJECT (give it a manifest topic) or CONDUCT (topics=()), "
                "then record it in _CLASS.")
            actual = "subject" if topics else "conduct"
            # A SUBJECT must be answerable in the first person, because the
            # capability question is now ANSWERED from this list rather than
            # asked of a model. A subject with no answer would be a capability
            # she is told about but cannot state when asked.
            if actual == "subject":
                assert answer, f"section {key!r} is a SUBJECT with no first-person answer"
            else:
                assert answer is None, \
                    f"section {key!r} is CONDUCT but carries an answer"
            assert actual == _CLASS[key], (
                f"section {key!r} is classified {_CLASS[key]} but rendered as "
                f"{actual}. A SUBJECT that became CONDUCT vanishes from the "
                "guard while she still reads the paragraph — that is drift.")
    missing = set(_CLASS) - seen
    assert not missing, f"_CLASS names {missing}, which no flag combination renders"


def test_no_heading_outlives_its_section(at_flags):
    """THE INVARIANT. A topic may appear in the manifest only when the section
    that owns it actually rendered — so a switched-off capability is invisible
    to the guard, exactly as it is invisible to her."""
    all_topics = set()
    for combo in _COMBOS:
        for _k, topics, _t, _a in at_flags(**combo):
            all_topics.update(topics)

    for combo in _COMBOS:
        sections = at_flags(**combo)
        live = {t for _k, topics, _t, _a in sections for t in topics}
        manifest = cm.build(capability_topics=server._manifest_capability_topics())
        for topic in live:
            assert topic in manifest, f"{topic!r} rendered but never reached the guard"
        for topic in all_topics - live:
            assert topic not in manifest, (
                f"the guard is told about {topic!r} under flags {combo}, but the "
                "section that owns it did not render")


def test_the_text_engine_heading_tracks_its_switch(at_flags):
    """The concrete case the whole thing was built for."""
    at_flags(qwen=True, edit=True)
    on = cm.build(capability_topics=server._manifest_capability_topics())
    assert "readable text" in on

    at_flags(qwen=False, edit=True)
    off = cm.build(capability_topics=server._manifest_capability_topics())
    assert "readable text" not in off, \
        "the guard is told she can render readable text with the engine switched off"


def test_the_edit_heading_is_present_in_both_trial_states(at_flags):
    """'Can you fix the text in an existing image?' must REACH her whether the
    answer is yes or not-yet — saying which is her job, and a heading that
    appeared only once the trial flag flipped would hold the turn during exactly
    the window when the honest answer was 'not yet'."""
    for qwen_edit in (False, True):
        at_flags(qwen=True, edit=True, qwen_edit=qwen_edit)
        m = cm.build(capability_topics=server._manifest_capability_topics())
        assert "editing an image you were given" in m


# ── authors 2 and 3: stories, documents ──────────────────────────────────────
def test_stories_are_never_named_in_the_manifest():
    """A LOCK, not an omission.

    The story clause was built to retire the named-story bypass, and it made the
    gate credulous about story-shaped turns instead of about those titles:
    "tell me <unfiled title> again" went from held 0/10 to passed 6/6, and on
    the live verify she answered one with a complete invented story. Stories
    have a deterministic resolver (shelf/canon resolve() above the gate) which
    cannot pass a title that does not exist; the manifest covers only what has
    no such resolver. Putting titles back re-opens a fabrication route.
    """
    m = cm.build(capability_topics=["making images"],
                 story_titles=["Arthur and Eliza", "Esmeralda's Garden"])
    assert "Arthur and Eliza" not in m
    assert "Esmeralda" not in m
    assert "stories" not in m.lower()
    assert "stories" not in cm.CONTRIBUTORS


def test_the_server_does_not_pass_story_titles_to_the_manifest():
    """The lock above only holds if the call site agrees with it."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("context_manifest.build(")
    call = src[i:src.index(")", src.index("document_loaded", i))]
    assert "story_titles" not in call, \
        "the server is naming stories in the manifest again — see _clause_stories"


def test_the_story_bypass_is_still_what_carries_a_named_story():
    """Retiring it was the brief's goal and the measurement refused it: the
    bypass is a directory lookup that cannot flap, and at baseline the gate's
    verdict on "What is Arthur and Eliza about?" was answerable 4/5 where all
    four were TIMEOUTS — the one run that completed held it."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "_early_claim or _story_claim" in src
    assert src.index("_story_claim = False") < src.index("_triage = (_TriagePass()")


def test_no_document_loaded_means_no_document_clause():
    """'Summarize the PDF I uploaded' with nothing uploaded must still hold, and
    it does because there is no heading for it to match."""
    assert "document" not in cm.build(capability_topics=["making images"],
                                      document_loaded=False)
    assert "document" in cm.build(capability_topics=["making images"],
                                  document_loaded=True)


def test_nothing_at_all_renders_an_empty_manifest():
    """Not a stub sentence — an empty string. A manifest listing nothing would
    still nudge the gate, and there is nothing for it to be right about."""
    assert cm.build() == ""
    assert cm.build(capability_topics=[], story_titles=[], document_loaded=False) == ""


def test_the_manifest_states_the_rule_in_both_directions():
    """One-sided ('do not hold these') would buy the positive cases by making
    the guard credulous. The second half is what keeps absent things absent."""
    m = cm.build(capability_topics=["making images"])
    assert "do not hold it" in m
    assert "still absent" in m and "still holds" in m


# ── the guard itself is untouched for everyone else ──────────────────────────
def test_a_caller_without_a_manifest_gets_the_byte_identical_old_prompt():
    """Out of scope: any change to what triage holds for. Every existing caller
    and every existing test must be on the exact prompt they were on."""
    assert triage._system_for(None) == triage._SYSTEM
    assert triage._system_for("") == triage._SYSTEM
    assert triage._system_for("   ") == triage._SYSTEM
    assert triage._SYSTEM == triage._SYSTEM_HEAD + triage._SYSTEM_TAIL


def test_the_manifest_sits_before_the_output_contract():
    """After the rule about absent artifacts, which it qualifies — not after
    'Nothing else.', where it reads as an afterthought to the JSON contract."""
    s = triage._system_for("MANIFEST_MARKER.")
    assert s.index("MANIFEST_MARKER") < s.index("Return strict JSON")
    assert s.index("absent from the context") < s.index("MANIFEST_MARKER")


def test_triage_gate_still_accepts_two_positional_arguments():
    """modules/triage.py is shared plumbing. The manifest is a defaulted keyword
    so nothing that called it before has to change."""
    import inspect
    p = inspect.signature(triage.triage_gate).parameters
    assert list(p) == ["user_text", "context", "manifest"]
    assert p["manifest"].default is None


def test_a_manifest_fault_cannot_gate_a_turn():
    """Building it reads three stores. If any of them throws, the turn proceeds
    with an unqualified gate rather than dying."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("context_manifest.build(")
    window = src[i - 400:i + 700]
    assert "except Exception" in window and '_manifest = ""' in window, \
        "the manifest build is not wrapped — a store fault would break /chat"


def test_the_manifest_is_built_before_the_gate_runs():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.index("context_manifest.build(") < \
           src.index("_triage = (_TriagePass()"), \
        "the manifest is built after triage has already ruled"
