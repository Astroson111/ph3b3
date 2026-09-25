"""The gate may only hold what a hold can fix.

A hold's one legitimate theory is "the user can supply or point to the missing
thing". When the judge held "what did you have for breakfast?" with
missing=['your breakfast'], it was not making that claim — it had mistaken a
noun it did not know for a dependency it could be handed.

THE LOOP THAT MADE THIS AN OUTAGE, reproduced 2026-09-25 at 09:04 and 10:37:
with the model seated, a hold means the brain is never invoked, AND the verdict
itself refreshes the model's keep_alive lease (observed: expiry 10:37:03 ->
10:37:06 across one verdict). So nothing evicts it and every clarification the
user offers re-arms the trap. Breaking it needs a deterministic check, not a
prompt: the judge keeps its vote and loses its veto over anything a user could
not hand it.

Note the mechanism is single-model. brain, triage judge and Layer-B judge all
resolve to ph3b3-chat:latest on this box; every hermes3 reference in the tree is
a fallback default for PH3B3_HEAVY_MODEL, which .env overrides. There is no
model evicting another model here.
"""
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import triage  # noqa: E402


def _held(missing, question="Which one?"):
    return triage.TriageResult(answerable=False, missing=list(missing), question=question)


@pytest.fixture
def caplogs():
    got = []

    class _Cap(logging.Handler):
        def emit(self, r):
            got.append((r.levelno, r.getMessage()))

    h = _Cap()
    triage.log.addHandler(h)
    old = triage.log.level
    triage.log.setLevel(logging.DEBUG)
    yield got
    triage.log.removeHandler(h)
    triage.log.setLevel(old)


# ── what must be overruled ───────────────────────────────────────────────────
SOCIAL = [
    ["your breakfast"], ["breakfast"], ["thoughts", "opinions"],
    ["your personal views or opinions"], ["your morning"],
    ["the user's mood"], ["how you are feeling"], ["your day"],
]


@pytest.mark.parametrize("missing", SOCIAL)
def test_a_hold_the_user_cannot_fix_is_overruled(missing, caplogs):
    r = triage.enforce_fetchable(_held(missing))
    assert r.answerable is True, f"{missing} still held the turn"
    assert r.missing == [] and r.question is None
    assert any(lv >= logging.WARNING and "TRIAGE_HOLD_OVERRULED" in m
               for lv, m in caplogs), "the override was silent"


def test_an_empty_missing_list_is_LEFT_ALONE():
    """A hold with no itemised missing is the PROSE FALLBACK — the judge was
    confident but the parser could not extract items. That is a parse
    degradation, not a garbage verdict. An earlier version of this file
    overruled it and silently discarded real holds; test_triage_gate caught it."""
    assert triage.enforce_fetchable(_held([])).answerable is False


def test_any_unfetchable_item_overrules_the_whole_hold():
    """A verdict reasoning from 'breakfast' is not made sound by also naming a
    document — the reasoning is what is contaminated."""
    assert triage.enforce_fetchable(_held(["the report", "breakfast"])).answerable is True


# ── what must still hold ─────────────────────────────────────────────────────
FETCHABLE = [
    ["the document"], ["the PDF"], ["the spreadsheet"], ["the uploaded file"],
    ["the report"], ["which image"], ["the render job"], ["the song"],
    ["the screenshot"], ["the transcript"], ["a link"], ["the story"],
]


@pytest.mark.parametrize("missing", FETCHABLE)
def test_a_genuinely_fetchable_hold_survives(missing):
    r = triage.enforce_fetchable(_held(missing))
    assert r.answerable is False, f"{missing} was overruled but the user CAN supply it"
    assert r.missing == missing


def test_manifest_subjects_count_as_fetchable():
    """Manifest subjects come from the caller's manifest string, so there is no
    second place deciding what the prompt contains."""
    man = ("The context will also contain: what it can do — making images; "
           "your image engines, and readable text inside a picture.")
    subs = triage._subjects_from(man)
    assert subs, "no subjects parsed from the manifest"
    r = triage.enforce_fetchable(_held(["your image engines"]), subs)
    assert r.answerable is False, "a manifest subject was treated as unfetchable"


def test_no_manifest_means_no_subjects_and_nothing_breaks():
    assert triage._subjects_from(None) == ()
    assert triage._subjects_from("") == ()


# ── the clarifying question must name the fetchable thing ────────────────────
def test_the_question_names_what_is_missing():
    q = triage._clarifying(["the document"], "summarize it",
                           "Could you tell me more about your day?")
    assert "document" in q.lower(), \
        "the clarifier ignored the missing item and asked about something else"


def test_a_question_that_already_names_it_is_kept():
    q = triage._clarifying(["the document"], "summarize it",
                           "Which document did you mean, the invoice or the contract?")
    assert q.startswith("Which document")


def test_the_breakfast_parrot_is_impossible_now():
    """The anti-example: "Could you please tell me what you had for breakfast
    today?" asked back at someone who just told you they were talking about
    breakfast. That verdict no longer survives to reach a clarifier at all."""
    r = triage.enforce_fetchable(
        _held(["your breakfast"], "Could you please tell me what you had for breakfast today?"))
    assert r.answerable is True and r.question is None


# ── wiring ───────────────────────────────────────────────────────────────────
def test_the_check_runs_before_the_clarifier_is_built():
    src = (ROOT / "modules" / "triage.py").read_text(encoding="utf-8")
    assert src.index("enforce_fetchable(result, _subjects_from(manifest)") < \
           src.index("result.question = _clarifying(")


def test_the_override_is_counted():
    before = triage.HOLD_OVERRULED_COUNT[0]
    triage.enforce_fetchable(_held(["breakfast"]))
    assert triage.HOLD_OVERRULED_COUNT[0] == before + 1


# ── THREE OUTCOMES, added 2026-09-25 after the repair ────────────────────────
# The first version of _fetchable() recognised category NOUNS and never proper
# names, so "The Lighthouse at Dunwich" — a title the shelf does not have — read
# as unfetchable, lost its veto, and she invented a 2015 horror film, then a
# public-domain summary, then a 1930s radio serial. Three fabrications, three
# different lies, produced by a check written to make her more honest.
#
# Fetchability is now RESOLVED against the stores, not inferred from vocabulary.

_FILED = ["Esmeralda's Garden", "Arthur and Eliza", "The Crooked Man of Flintstone"]


def _fake_resolver(text):
    return any(t.lower() in text.lower() for t in _FILED)


@pytest.mark.parametrize("title", _FILED)
def test_a_filed_title_resolves_and_the_hold_stands(title):
    """She is held to recall a real thing properly rather than improvise it."""
    assert triage.classify(title, (), _fake_resolver) == "hold"
    r = triage.enforce_fetchable(_held([title]), (), _fake_resolver)
    assert r.answerable is False


def test_an_absent_named_work_is_DECLINED_not_overruled():
    """The trap. Overruling hands it to the brain to imagine; holding asks the
    user to supply a story she cannot be given. The third answer is the truth."""
    assert triage.classify("The Lighthouse at Dunwich", (), _fake_resolver) == "decline"
    r = triage.enforce_fetchable(_held(["The Lighthouse at Dunwich"]), (), _fake_resolver)
    assert r.answerable is False, "an absent named work was overruled into invention"
    assert "don't have anything called" in r.question
    assert "The Lighthouse at Dunwich" in r.question
    assert "make one up" in r.question


def test_decline_beats_overrule_when_a_turn_has_both():
    """A turn naming an absent work must never reach the brain, even if it also
    mentions something social."""
    r = triage.enforce_fetchable(
        _held(["The Lighthouse at Dunwich", "your breakfast"]), (), _fake_resolver)
    assert r.answerable is False
    assert "don't have anything called" in r.question


@pytest.mark.parametrize("item", ["your breakfast", "your morning", "thoughts",
                                  "your personal views or opinions",
                                  "a brief description of what happened in my day"])
def test_the_social_path_is_untouched(item):
    """Her own interiority is the ONLY tier that strips a veto."""
    assert triage.classify(item, (), _fake_resolver) == "overrule"
    assert triage.enforce_fetchable(_held([item]), (), _fake_resolver).answerable is True


@pytest.mark.parametrize("item", ["company name", "today's date", "the document",
                                  "the uploaded file", "which spreadsheet"])
def test_user_suppliable_specifics_now_hold_legitimately(item):
    """These were being overruled by accident — 'company name' 11 times in one
    day. A clarifying question is exactly what they are for. Defaulting to hold
    is the conservative direction: the cost is a question, where the cost of
    over-overruling is an invented answer."""
    assert triage.classify(item, (), _fake_resolver) == "hold"
    assert triage.enforce_fetchable(_held([item]), (), _fake_resolver).answerable is False


def test_a_resolver_fault_never_gates_a_turn():
    def _boom(text):
        raise RuntimeError("shelf on fire")
    assert triage.classify("your breakfast", (), _boom) == "overrule"


def test_the_server_injects_a_store_backed_resolver():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("def _triage_named_resolver(")
    body = src[i:i + 400]
    assert "shelf.resolve(" in body and "canon.resolve(" in body
    assert "named_resolver = _triage_named_resolver" in src


def test_the_fuzzy_resolver_is_only_asked_about_title_shaped_items():
    """shelf.resolve() is a good TITLE matcher and a bad general oracle.

    Measured 2026-09-25: shelf.resolve("the user's mood") returns True. An
    earlier ordering consulted it first, for every missing item, so a social
    hold came back 'hold' and the livelock returned for that phrasing — caught
    only because the full suite polluted these unit tests with the live
    resolver, which is the sort of accident that usually hides a bug instead of
    exposing one.
    """
    def _says_yes_to_everything(text):
        return True

    # Not title-shaped: the resolver must never be consulted, so interiority wins.
    assert triage.classify("the user's mood", (), _says_yes_to_everything) == "overrule"
    assert triage.classify("your breakfast", (), _says_yes_to_everything) == "overrule"
    # Title-shaped: now it is consulted, and it decides.
    assert triage.classify("The Lighthouse at Dunwich", (), _says_yes_to_everything) == "hold"

    def _says_no_to_everything(text):
        return False
    assert triage.classify("The Lighthouse at Dunwich", (), _says_no_to_everything) == "decline"


def test_the_ordering_is_stated_in_the_source():
    src = (ROOT / "modules" / "triage.py").read_text(encoding="utf-8")
    body = src[src.index("def classify("):src.index("def _fetchable(")]
    assert body.index("_NAMED_RE.search(text)") < body.index("_INTERIORITY_RE.search(text)"), \
        "interiority is being tested before the named-work branch"
    assert "FUZZY" in body, "the reason the resolver is gated is not recorded"
