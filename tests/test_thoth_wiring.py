"""
Thoth — server wiring and intent routing, verify suite.

The intent tests are the ones that matter. Forced routing takes a turn away from
ordinary chat, so a false positive is a hijack: it costs Phoebe her range on a
turn that was never about scripture. The SHOULD-NOT table is therefore the real
subject here, and it is deliberately full of things this house actually says.

Run:  .venv/bin/python -m pytest tests/test_thoth_wiring.py -v
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth import intent, service                                # noqa: E402
from thoth.corpus import Corpus                                  # noqa: E402
from thoth.schema import (AddressScheme, CanonStatus, Passage,   # noqa: E402
                          Provenance, SourceSpec, Work)

SERVER = (REPO / "agent" / "server.py").read_text(encoding="utf-8")

NAMES = frozenset({"genesis", "john", "psalms", "enoch", "tobit", "revelation",
                   "bible", "quran", "jubilees"})


# ── forced routing must not steal ordinary turns ─────────────────────────────

SHOULD_ROUTE = [
    "what does the bible say about forgiveness",
    "What does scripture say about mercy?",
    "does the Quran mention Noah?",
    "quote John 3:16",
    "What is in John 3:16?",
    "Was the Book of Enoch wrongly excluded from the canon?",
    "which traditions treat Enoch as canonical",
    "what does the gospel of John say about light",
]

SHOULD_NOT_ROUTE = [
    "what's the genesis of this bug",
    "I had a revelation about the parser",
    "that's the gospel truth",
    "read my email",
    "read that back to me",
    "what does the log say about the error",
    "can you say that again",
    "what does rhea say about the backup",
    "is that the canonical implementation?",
    "what's the canonical way to do this in python",
    "tell me about the flood in 2019",
    "stop the render",
    "what's the weather today",
    "play something by King Gizzard",
]


@pytest.mark.parametrize("text", SHOULD_ROUTE)
def test_a_scripture_question_is_routed_to_the_library(text):
    assert intent.is_scripture_intent(text, NAMES), text


@pytest.mark.parametrize("text", SHOULD_NOT_ROUTE)
def test_an_ordinary_turn_is_left_alone(text):
    """A false positive here is a hijack, not a missed opportunity."""
    assert not intent.is_scripture_intent(text, NAMES), text


def test_a_canon_question_needs_a_work_it_can_name():
    """"canonical" is a software word in this house as often as a scriptural
    one, so the canon branch cannot fire without a work the corpus holds."""
    q = "which traditions treat Enoch as canonical"
    assert intent.is_scripture_intent(q, NAMES)
    assert not intent.is_scripture_intent(q, frozenset())
    assert not intent.is_scripture_intent("is that the canonical fix", NAMES)


# ── reader commands ──────────────────────────────────────────────────────────

def test_read_intent_needs_a_verb_and_something_addressable():
    for yes in ("read John 3", "read me Psalm 23", "recite Genesis 1",
                "read sura 2", "please read 1 John 1"):
        assert intent.is_read_intent(yes), yes
    for no in ("read my email", "read that back to me", "read the room",
               "what does John 3 say"):
        assert not intent.is_read_intent(no), no


def test_a_read_request_is_not_also_a_scripture_question():
    """They are different lanes and the reader must win, or "read John 3" gets
    answered in text instead of spoken."""
    assert intent.is_read_intent("read John 3")
    assert not intent.is_scripture_intent("read John 3", NAMES)


def test_stop_only_counts_while_something_is_being_read():
    assert intent.is_stop_reading("stop", reading=True)
    assert intent.is_stop_reading("stop the reading", reading=True)
    assert not intent.is_stop_reading("stop", reading=False)
    assert not intent.is_stop_reading("stop the render", reading=True), \
        "a Morpheus command was taken by the reader"


def test_resume_does_not_swallow_ordinary_conversation():
    """"Go on" and "carry on" are things people say."""
    for yes in ("keep reading", "continue reading", "pick up where you left off"):
        assert intent.is_resume_reading(yes), yes
    for no in ("go on", "carry on", "go on then", "continue", "keep going"):
        assert not intent.is_resume_reading(no), no


# ── the service degrades honestly ────────────────────────────────────────────

def test_a_broken_library_never_falls_back_to_an_unfloored_answer(monkeypatch):
    """The whole reason for forced routing is that an unfloored scripture answer
    must not happen. A store that will not open has to SAY so."""
    def boom():
        raise RuntimeError("no store")
    monkeypatch.setattr(service, "store", boom)
    out = service.answer("what does Genesis say")
    assert "library isn't open" in out
    assert "from memory" in out


def test_a_broken_library_does_not_break_ordinary_chat(monkeypatch):
    """work_names() is called on every turn to test intent. If it raises, chat
    dies — so it returns an empty set and the routing simply does not fire."""
    def boom():
        raise RuntimeError("no store")
    monkeypatch.setattr(service, "_collect_names", boom)
    monkeypatch.setattr(service, "_names", None)
    assert service.work_names() == frozenset()      # empty, and did not raise
    # A question that leans on a corpus NAME stops routing, because there are no
    # names to match. One carrying an explicit marker still routes — and then
    # answer() says the library is down rather than inventing a verse.
    assert not intent.is_scripture_intent("is Enoch canonical", frozenset())
    assert intent.is_scripture_intent("what does the bible say", frozenset())


def test_a_failing_model_call_is_reported_not_papered_over(monkeypatch, tmp_path):
    c = Corpus(db_path=tmp_path / "t.db")
    c.sync_metadata([Work(
        id="web", title="WEB", tradition="Christianity", language_of_origin="Greek",
        canonicity=(CanonStatus(tradition="Protestant Christianity", status="canonical"),),
        provenance=Provenance(license="public-domain", license_note="PD",
                              completeness="complete", vendorable=True),
        address=AddressScheme(section_label="chapter", unit_label="verse"),
        source=SourceSpec(url="https://example.invalid/x", adapter="usfm"))])
    c.replace_passages("web", [Passage(work_id="web", book="John", section=3,
                                       unit=16, text="For God so loved.", ordinal=1)])

    class Ix:
        def search(self, *a, **k): return []
        def window(self, h, **k): return []
    monkeypatch.setattr(service, "store", lambda: (c, Ix()))
    monkeypatch.setattr(service, "_generate", lambda p: (_ for _ in ()).throw(OSError("down")))
    out = service.answer("what does John say")
    # The lane catches the generator failure itself and still runs the floor.
    assert "couldn't put an answer together" in out or "from memory" in out
    c.close()


# ── the wiring in server.py ──────────────────────────────────────────────────

def test_the_server_imports_the_service():
    assert "from thoth import service as thoth_svc" in SERVER


def test_scripture_questions_are_force_routed_not_offered_as_a_tool():
    """A tool she MAY call is a floor she may skip."""
    assert "thoth_svc.intent.is_scripture_intent(user_msg" in SERVER
    assert "thoth_svc.answer" in SERVER
    # and it is not merely a tool definition she can decline to use
    assert '"name":"thoth' not in SERVER


def test_the_intercept_sits_after_the_video_grace_and_before_triage():
    """A video render evicts Ollama, so the lane cannot answer during one; and
    the routing has to precede triage or the turn is gone."""
    grace = SERVER.index("VIDEO_RENDER_GRACE")
    thoth = SERVER.index("thoth_svc.intent.is_stop_reading")
    triage = SERVER.index("Triage gate")
    assert grace < thoth < triage


def test_reader_commands_are_checked_before_the_scripture_question():
    stop = SERVER.index("thoth_svc.intent.is_stop_reading")
    read = SERVER.index("thoth_svc.intent.is_read_intent")
    ask = SERVER.index("thoth_svc.intent.is_scripture_intent")
    assert stop < read < ask


def test_the_reading_is_bound_to_the_servers_own_speaker():
    """The whole reason for wiring this in: one TTSModule means the per-unit
    speech lock actually serialises a reading against ordinary speech."""
    assert "thoth_svc.start_reading, user_msg, tts" in SERVER
    src = (REPO / "modules" / "thoth" / "service.py").read_text(encoding="utf-8")
    assert "_reading.speaker is not tts" in src, \
        "the service must rebind if handed a different speaker"


def test_debate_has_a_switch_and_the_citation_floor_does_not():
    assert "/thoth/debate" in SERVER
    for smell in ("floor=", "no_floor", "skip_floor", "verify=False"):
        assert smell not in SERVER, f"server exposes a citation-floor bypass: {smell}"
