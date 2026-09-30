"""A turn that carries its content cannot be missing it.

MEASURED LIVE, 2026-09-25, six self-contained text-edit requests through the real
chat path. Four were held, and the gate asked for text the message supplied:

  "fix the wording in this paragraph: the quick brown fox jumped over a lazy
   dogs."                           TRIAGE_HOLD missing=['paragraph to fix']
  "proofread this for me: their going to the store tommorow"
                                    TRIAGE_HOLD missing=['going','store','tomorrow']
  'Rewrite this sentence so it reads better: "The report was wrote by the team
   which they finished it late."'    TRIAGE_HOLD missing=['sentence to rewrite']
  "Here is a paragraph. Please tighten it.\n\nWe have decided that the meeting
   which was scheduled for Tuesday..."          TRIAGE_HOLD missing=['paragraph']

The second row is the diagnosis: the judge listed the WORDS OF THE SUPPLIED
SENTENCE as missing subjects.

WHAT THIS IS NOT. It is not a missing-input bug. triage_gate has always sent
`REQUEST:\n{user_text}` in full — the judge had every one of those payloads in
front of it and held anyway. Giving it the text again fixes nothing; the guard is
deterministic and lives in enforce_fetchable, where the verdict is enforced.

The missing lists in _ROWS are the REAL ones from that run's journal, not
invented — so this file is a regression table against measured behaviour rather
than against a guess about what the judge might say.
"""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import triage  # noqa: E402


def _held(missing, question="Which one did you mean?"):
    return triage.TriageResult(answerable=False, missing=list(missing),
                               question=question)


# ── the six rows, verbatim, with their measured verdicts ─────────────────────
WRONG_HOLDS = [
    ("fix the wording in this paragraph: the quick brown fox jumped over a lazy dogs.",
     ["paragraph to fix"]),
    ("proofread this for me: their going to the store tommorow",
     ["going", "store", "tomorrow"]),
    ('Rewrite this sentence so it reads better: "The report was wrote by the team '
     'which they finished it late."',
     ["sentence to rewrite"]),
    ("Here is a paragraph. Please tighten it.\n\nWe have decided that the meeting "
     "which was scheduled for Tuesday will now be held on Thursday, due to the "
     "fact that several people are unavailable.",
     ["paragraph"]),
]

# Held in the same run, and RIGHT to hold: the words it asks for appear nowhere
# in the message, so the veto must abstain and the question must stand.
CORRECT_HOLD = (
    "make me a poster with readable text",
    ["specific details about the desired poster content, such as the main message "
     "or theme, colors to use, and any other relevant information"])

# Answered correctly in the same run — the judge passed them. They still carry a
# payload, so if it ever holds one of them the veto covers it.
PASSED_ANYWAY = [
    "fix the wording: the quick brown fox jumped over a lazy dogs.",
    "tighten this up: We have decided that the meeting scheduled for Tuesday will "
    "now be held on Thursday because several people are unavailable.",
]


@pytest.mark.parametrize("text,missing", WRONG_HOLDS)
def test_the_four_wrong_holds_invert(text, missing):
    r = triage.enforce_fetchable(_held(missing), (), None, text=text)
    assert r.answerable is True, \
        f"still held, asking for content the turn carries: {missing}"
    assert r.missing == []
    assert r.question is None


def test_the_correct_hold_survives():
    """The veto abstains where the ask is real. A veto that fired here would be
    the familiar mistake pointing the other way: she would guess at a poster."""
    text, missing = CORRECT_HOLD
    r = triage.enforce_fetchable(_held(missing), (), None, text=text)
    assert r.answerable is False, "a legitimate clarifying question was overruled"
    assert r.missing == missing


@pytest.mark.parametrize("text", PASSED_ANYWAY)
def test_the_turns_that_passed_carry_a_payload_too(text):
    assert triage.payload_segment(text), \
        "a turn the judge happened to pass would not be covered if it stopped"


def test_an_answerable_result_is_never_touched():
    r = triage.TriageResult(answerable=True, missing=[], question=None)
    out = triage.enforce_fetchable(r, (), None, text=PASSED_ANYWAY[0])
    assert out.answerable is True and out.missing == []


# ── part 1 of the check: no payload, no veto ──────────────────────────────────
NO_PAYLOAD = [
    "summarize the document",
    "what did the report say",
    "make me a poster with readable text",
    "fix the typo",
    "remind me about the thing at 3:30",          # a clock is not a payload
    "have a look at https://example.com/page",     # nor is a URL scheme
    'he called it "brilliant" and left',           # nor a scare-quoted word
]


@pytest.mark.parametrize("text", NO_PAYLOAD)
def test_a_turn_with_no_payload_is_left_alone(text):
    assert triage.payload_segment(text) is None, \
        f"{text!r} was read as carrying pasted content"


def test_summarize_the_document_still_holds():
    """The hold this module exists for must survive the veto."""
    r = triage.enforce_fetchable(_held(["document"]), (), None,
                                 text="summarize the document")
    assert r.answerable is False
    assert r.question == "Which one did you mean?"


HAS_PAYLOAD = [
    "fix this: the quick brown fox jumped over a lazy dogs",
    'rewrite this: "the report was wrote by the team late"',
    "tighten this up\n\nWe have decided that the meeting is moved to Thursday",
]


@pytest.mark.parametrize("text", HAS_PAYLOAD)
def test_the_three_payload_shapes_are_detected(text):
    assert triage.payload_segment(text)


# ── part 2: the item's words must actually be in the turn ─────────────────────
def test_an_item_the_turn_does_not_name_keeps_its_hold():
    """A payload does not blanket-overrule. 'the API key' is genuinely absent
    from a turn that pasted a paragraph about meetings."""
    text = ("deploy this for me\n\nWe have decided that the meeting scheduled for "
            "Tuesday is moved to Thursday")
    r = triage.enforce_fetchable(_held(["the API key"]), (), None, text=text)
    assert r.answerable is False


def test_an_article_alone_never_carries_the_veto():
    """Stop-filtered, same as _names_any. 'the' appearing in a paste is not the
    user having supplied 'the document'."""
    text = "fix this: the meeting is on the Thursday after the holiday weekend"
    assert triage.supplied_in_turn(["the"], text) == []
    assert triage.supplied_in_turn(["a specific"], text) == []


def test_it_reports_which_items_were_supplied():
    text = "proofread this for me: their going to the store tommorow"
    got = triage.supplied_in_turn(["going", "store", "tomorrow"], text)
    assert "going" in got and "store" in got
    assert "tomorrow" not in got, \
        "the turn misspells it as 'tommorow' — word matching must be literal"


# ── precedence: decline still wins ───────────────────────────────────────────
def test_a_named_absent_work_declines_even_with_a_payload():
    """Never hand a named work this box does not have to the brain to imagine,
    whatever else the turn carries."""
    text = ('tell me about The Lighthouse at Dunwich: it is the one about the '
            'keeper and the storm')
    r = triage.enforce_fetchable(_held(["The Lighthouse at Dunwich"]), (),
                                 lambda t: False, text=text)
    assert r.answerable is False, "a fabrication route was opened by the veto"
    assert "isn't on my shelf" in r.question


def test_interiority_still_overrules_without_a_payload():
    r = triage.enforce_fetchable(_held(["your feelings"]), (), None, text="how are you")
    assert r.answerable is True


# ── the log line and the counter ─────────────────────────────────────────────
def test_the_veto_logs_and_counts(caplog):
    before = triage.PAYLOAD_OVERRULED_COUNT[0]
    with caplog.at_level(logging.WARNING, logger=triage.log.name):
        triage.enforce_fetchable(_held(["paragraph to fix"]), (), None,
                                 text=WRONG_HOLDS[0][0])
    assert triage.PAYLOAD_OVERRULED_COUNT[0] == before + 1
    assert any("TRIAGE_HOLD_OVERRULED — content present in turn" in r.message
               for r in caplog.records), \
        "the veto fired silently — an invisible overrule cannot be audited"


def test_the_two_overrule_paths_count_separately():
    """Interiority and payload are different faults and must not share a tally,
    or the Argus wiring cannot tell a greeting from a paste."""
    a, b = triage.HOLD_OVERRULED_COUNT[0], triage.PAYLOAD_OVERRULED_COUNT[0]
    triage.enforce_fetchable(_held(["your mood"]), (), None, text="how are you")
    assert triage.HOLD_OVERRULED_COUNT[0] == a + 1
    assert triage.PAYLOAD_OVERRULED_COUNT[0] == b


# ── the judge's half of the prompt is bounded ────────────────────────────────
def test_a_long_paste_is_capped_for_the_judge():
    long = "x" * 40 + " ".join(f"word{i}" for i in range(4000))
    out = triage._bounded_request(long)
    assert len(out) < len(long)
    assert len(out) <= triage._MAX_REQUEST_CHARS + 120
    assert "content continues" in out


def test_a_short_turn_is_passed_through_untouched():
    t = "fix this: the quick brown fox jumped over a lazy dogs"
    assert triage._bounded_request(t) == t


def test_the_gate_caps_the_request_but_the_veto_sees_everything():
    """The cap protects the 6s budget; it must never narrow the veto. If the veto
    read the capped text, a paste longer than the cap could be held for content
    sitting at character 5,000."""
    src = (ROOT / "modules" / "triage.py").read_text(encoding="utf-8")
    assert "_bounded_request(user_text)" in src, "the judge prompt is not bounded"
    assert "text=user_text" in src, "the veto is not given the full turn"
    i = src.index("enforce_fetchable(result, _subjects_from(manifest)")
    call = src[i:src.index(")", src.index("text=", i))]
    assert "_bounded_request" not in call, "the veto was handed the capped text"


def test_the_veto_fires_on_content_past_the_cap():
    filler = " ".join(f"word{i}" for i in range(500))      # well over 1200 chars
    text = f"proofread this for me: {filler} and their going to the store"
    assert len(text) > triage._MAX_REQUEST_CHARS
    r = triage.enforce_fetchable(_held(["going", "store"]), (), None, text=text)
    assert r.answerable is True, "the veto only read the capped prefix"


# ── teeth: the payload gate is load-bearing ──────────────────────────────────
def test_without_the_payload_gate_the_document_hold_would_break(monkeypatch):
    """Mutation. Make payload_segment always claim a payload and confirm
    "summarize the document" then gets wrongly overruled — which is what part 1
    of the check exists to prevent. If this passes with the real gate in place,
    part 1 is doing nothing."""
    monkeypatch.setattr(triage, "payload_segment", lambda t: "pretend content")
    r = triage.enforce_fetchable(_held(["document"]), (), None,
                                 text="summarize the document")
    assert r.answerable is True, \
        "the mutation changed nothing, so the payload gate is not what holds this"


def test_the_default_keeps_every_existing_caller_unchanged():
    """73 tests in test_triage_fetchable.py call this with no text. Without the
    turn, the veto cannot fire — and must not."""
    r = triage.enforce_fetchable(_held(["paragraph to fix"]))
    assert r.answerable is False
