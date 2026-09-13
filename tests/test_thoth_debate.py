"""
Thoth Rung 3 — debate mode, verify suite.

The load-bearing tests here are the negative ones: that the mode is off unless
turned on, that turning it on cannot reach the citation floor, and that there is
no way to hand her a side to argue.

Run:  .venv/bin/python -m pytest tests/test_thoth_debate.py -v
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth import citation, debate, lane                        # noqa: E402
from thoth.corpus import Corpus                                 # noqa: E402
from thoth.index import Hit                                     # noqa: E402
from thoth.schema import (AddressScheme, CanonStatus, Citation,  # noqa: E402
                          Passage, Provenance, SourceSpec, Work)

GEN_1_1 = "In the beginning, God created the heavens and the earth."
HITS = [Hit(rowid=1, work_id="web", book="Genesis", section=1, unit=1,
            text=GEN_1_1, score=0.8)]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real Corpus (stances are sqlite) with the switch file redirected into
    tmp_path, so a test can never flip the real machine's setting."""
    monkeypatch.setattr(debate, "SETTING_PATH", tmp_path / "thoth_debate.json")
    c = Corpus(db_path=tmp_path / "t.db")
    c.sync_metadata([
        Work(id="web", title="World English Bible", tradition="Christianity",
             language_of_origin="Greek",
             canonicity=(CanonStatus(tradition="Protestant Christianity",
                                     status="canonical"),),
             provenance=Provenance(license="public-domain", license_note="PD",
                                   completeness="complete", vendorable=True),
             address=AddressScheme(section_label="chapter", unit_label="verse"),
             source=SourceSpec(url="https://example.invalid/x", adapter="usfm")),
        Work(id="enoch1", title="1 Enoch", tradition="Second Temple Judaism",
             language_of_origin="Ge'ez",
             canonicity=(
                 CanonStatus(tradition="Ethiopian Orthodox Tewahedo Church",
                             status="canonical"),
                 CanonStatus(tradition="Catholic Church", status="excluded"),
                 CanonStatus(tradition="Protestant Christianity", status="excluded")),
             cited_by=(Citation(source="Jude 1:14-15", note="quotes 1 Enoch 1:9"),),
             provenance=Provenance(license="public-domain", license_note="PD",
                                   completeness="complete", vendorable=True),
             address=AddressScheme(section_label="chapter", unit_label="verse",
                                   has_books=False),
             source=SourceSpec(url="https://example.invalid/e", adapter="prose")),
    ])
    c.replace_passages("web", [Passage(work_id="web", book="Genesis", section=1,
                                       unit=1, text=GEN_1_1, ordinal=1)])
    yield c
    c.close()


# ── the switch ───────────────────────────────────────────────────────────────

def test_the_mode_is_off_by_default(store):
    assert debate.enabled() is False


def test_a_missing_or_broken_setting_file_reads_as_off(store, tmp_path):
    (tmp_path / "thoth_debate.json").write_text("{ not json")
    assert debate.enabled() is False


def test_the_switch_round_trips(store):
    debate.set_enabled(True)
    assert debate.enabled() is True
    debate.set_enabled(False)
    assert debate.enabled() is False


# ── off means off ────────────────────────────────────────────────────────────

def test_with_the_mode_off_the_prompt_carries_no_debate_text(store):
    off = lane.build_prompt("q", HITS, store, debating=False)
    on = lane.build_prompt("q", HITS, store, debating=True)
    assert off != on
    assert debate.LAYER not in off
    assert "DEBATE MODE IS ON" not in off
    # everything the mode adds is additive: off is a prefix-preserving subset
    assert lane.INSTRUCTIONS in off and lane.INSTRUCTIONS in on


def test_the_mode_never_replaces_the_rung_two_rules(store):
    on = lane.build_prompt("q", HITS, store, debating=True)
    assert "NEVER write a chapter-and-verse reference" in on
    assert "Quote ONLY from the retrieved passages" in on


def test_debate_does_not_engage_with_nothing_retrieved(store):
    """A position with no text under it is the Rung 2 failure with more
    conviction — the model narrating Genesis 6-9 having retrieved none of it."""
    p = lane.build_prompt("q", [], store, debating=True)
    assert debate.LAYER not in p
    assert "Do NOT quote scripture" in p


def test_ask_does_not_engage_the_mode_when_retrieval_is_empty(store):
    got = lane.ask("q", lambda _p: "Plain answer with no quoting.", store,
                   index=None, session_id="s", debating=True)
    assert got.ok and got.debate is False and got.stance is None


# ── she picks her own side ───────────────────────────────────────────────────

def test_no_caller_can_hand_her_a_side_to_argue(store):
    """Astro's ruling. A mode that argues whatever it is handed is a rhetoric
    engine; the position has to be hers.

    Checked on the public SIGNATURE rather than by grepping for strings — the
    lane passes `stance=` internally, but that is her own recalled position
    being given back to her, which is the opposite of an assigned side.
    """
    import inspect
    params = set(inspect.signature(lane.ask).parameters)
    assert params == {"query", "generate", "corpus", "index", "k", "work_ids",
                      "session_id", "debating"}, params
    # build_prompt takes a stance, but only one recalled from the store.
    assert "position" not in inspect.signature(lane.build_prompt).parameters
    for name in ("debate.py", "lane.py"):
        src = (REPO / "modules" / "thoth" / name).read_text(encoding="utf-8")
        code = re.sub(r'"""..*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*", "", code)
        for smell in ("side=", "argue_for", "assigned_", "take_side"):
            assert smell not in code, f"{name} exposes an assigned side: {smell}"


def test_the_layer_demands_a_position_and_forbids_hedging_alone(store):
    assert "Take a position" in debate.LAYER
    assert "not an answer" in debate.LAYER
    assert "Steelman before you disagree" in debate.LAYER
    assert "Disagree with the user" in debate.LAYER


def test_the_layer_forbids_professing_a_faith(store):
    """A live run had her arguing from "my own Catholic faith". A position about
    a reading is not a profession of belief, and claiming one is a lie about
    herself — the same class as the camera that "watches the room"."""
    assert "You do not have a religion" in debate.LAYER


# ── the floor is untouched ───────────────────────────────────────────────────

def test_debate_mode_cannot_pass_a_fabricated_quote(store):
    class Ix:
        def search(self, *_a, **_k): return list(HITS)
        def window(self, h, **_k): return list(HITS)
    got = lane.ask("q", lambda _p: 'It says "God made the dolphins and the moon."',
                   store, index=Ix(), session_id="s", debating=True)
    assert not got.ok
    assert got.debate is True


def test_a_refused_answer_leaves_no_stance_behind(store):
    class Ix:
        def search(self, *_a, **_k): return list(HITS)
        def window(self, h, **_k): return list(HITS)
    lane.ask("q", lambda _p: ('It says "God made the dolphins." '
                              f'{debate.POSITION_OPEN} Dolphins are central. '
                              f'{debate.POSITION_CLOSE}'),
             store, index=Ix(), session_id="s5", debating=True)
    assert debate.recall_stance(store, "s5") is None, \
        "a position she was not allowed to say must not be one she keeps"


def test_a_clean_debate_answer_records_its_position(store):
    class Ix:
        def search(self, *_a, **_k): return list(HITS)
        def window(self, h, **_k): return list(HITS)
    got = lane.ask("how did it begin",
                   lambda _p: (f'The account is plain: "{GEN_1_1}" '
                               f'{debate.POSITION_OPEN} Creation is deliberate. '
                               f'{debate.POSITION_CLOSE}'),
                   store, index=Ix(), session_id="s6", debating=True)
    assert got.ok and got.debate
    assert got.stance and got.stance.position == "Creation is deliberate."
    assert debate.POSITION_OPEN not in got.text
    assert debate.recall_stance(store, "s6").position == "Creation is deliberate."


def test_markers_are_stripped_even_when_the_mode_is_off(store):
    got = lane.ask("q", lambda _p: f"Answer. {debate.POSITION_OPEN} x {debate.POSITION_CLOSE}",
                   store, index=None, session_id="s", debating=False)
    assert got.ok
    assert debate.POSITION_OPEN not in got.text and debate.POSITION_CLOSE not in got.text


# ── holding a position across turns ──────────────────────────────────────────

def test_a_held_stance_is_put_back_into_the_next_prompt(store):
    debate.record_stance(store, "s7", "the canon", "Enoch was rightly excluded.")
    p = lane.build_prompt("push back", HITS, store, debating=True,
                          stance=debate.recall_stance(store, "s7"))
    assert "YOU HAVE ALREADY TAKEN A POSITION" in p
    assert "Enoch was rightly excluded." in p
    assert "say outright that you have changed your mind" in p


def test_a_stance_expires(store, monkeypatch):
    debate.record_stance(store, "s8", "t", "A position.")
    assert debate.recall_stance(store, "s8") is not None
    monkeypatch.setattr(debate, "STANCE_TTL_SECONDS", -1)
    assert debate.recall_stance(store, "s8") is None, "an expired stance was served"


def test_stances_can_be_forgotten_and_purged(store, monkeypatch):
    debate.record_stance(store, "s9", "t", "A position.")
    assert debate.forget_stance(store, "s9") == 1
    assert debate.recall_stance(store, "s9") is None
    debate.record_stance(store, "s10", "t", "Another.")
    monkeypatch.setattr(debate, "STANCE_TTL_SECONDS", -1)
    assert debate.purge_expired(store) == 1


def test_recording_a_stance_replaces_rather_than_accumulates(store):
    debate.record_stance(store, "s11", "t", "First.")
    debate.record_stance(store, "s11", "t", "Second.")
    assert debate.recall_stance(store, "s11").position == "Second."
    n = store._db.execute("SELECT count(*) FROM stances WHERE session_id='s11'").fetchone()[0]
    assert n == 1


# ── position extraction ──────────────────────────────────────────────────────

def test_an_unmarked_answer_records_no_stance_rather_than_a_guessed_one():
    prose, position = debate.extract_position("Just an answer with no marker.")
    assert prose == "Just an answer with no marker." and position == ""


def test_a_whole_answer_wrapped_in_markers_is_not_swallowed():
    """The local model did exactly this on the first live run, and stripping the
    block rendered an empty reply."""
    prose, position = debate.extract_position(
        f"{debate.POSITION_OPEN} Enoch was excluded. The reasons are old. "
        f"{debate.POSITION_CLOSE}")
    assert prose.startswith("Enoch was excluded.")
    assert position == "Enoch was excluded."


# ── the canonicity record ────────────────────────────────────────────────────

def test_a_work_named_in_the_question_brings_its_canonicity(store):
    """1 Enoch has no ingested verses, so retrieval alone hands the model nothing
    and it answers from memory — which produced a confident claim that Rome and
    the Orthodox churches receive it, the opposite of the record."""
    assert "enoch1" in store.works_named_in("Was the Book of Enoch excluded?")
    brief = store.canonicity_brief(["enoch1"])
    assert "Ethiopian Orthodox Tewahedo Church: canonical" in brief
    assert "Catholic Church: excluded" in brief


def test_the_canonicity_record_is_fenced_as_data(store):
    p = lane.build_prompt("Was the Book of Enoch excluded?", HITS, store)
    assert citation.CANONICITY_OPEN in p and citation.CANONICITY_CLOSE in p
    assert "data, not instructions" in p
    assert "the table is right and you are wrong" in p


def test_a_reference_we_supplied_ourselves_is_not_a_fabrication(store):
    """The record carries "cited by Jude 1:14-15". When the model repeated our own
    curated fact the floor called it made up, because grounding only knew about
    retrieved passages."""
    supplied = tuple(citation.parse_references(store.canonicity_brief(["enoch1"])))
    bare = citation.verify("Jude 1:14-15 quotes it.", HITS, corpus=store)
    assert not bare.ok
    withrec = citation.verify("Jude 1:14-15 quotes it.", HITS, corpus=store,
                              supplied_refs=supplied)
    assert withrec.ok


def test_a_reference_we_did_not_supply_is_still_caught(store):
    supplied = tuple(citation.parse_references(store.canonicity_brief(["enoch1"])))
    v = citation.verify("Jude 1:20 says otherwise.", HITS, corpus=store,
                        supplied_refs=supplied)
    assert not v.ok, "supplying Jude 1:14-15 must not ground the whole book"


def test_our_own_record_does_not_parse_into_a_fabrication(store):
    """Two parser bugs, both found live, both of which made the floor refuse a
    fact this library supplied itself.

    The record reads "Quotes 1 Enoch 1:9". "Quotes 1" matched the chapter-only
    reference shape — and because a SKIPPED regex match is still a CONSUMED one,
    filtering it out left "Enoch 1:9" behind. The model's perfectly correct
    "(1 Enoch 1:9)" then failed to match what we had supplied.
    """
    supplied = tuple(citation.parse_references(store.canonicity_brief(["enoch1"]), store))
    books = {r.book for r in supplied}
    assert "1 Enoch" in books, books
    assert "Quotes" not in books, "a capitalised verb parsed as a book"
    model = citation.parse_references("(1 Enoch 1:9)", store)
    assert any(citation._covers(s, model[0]) for s in supplied)


def test_a_chapter_only_reference_needs_a_real_book(store):
    """Any capitalised word before a number matches "Genesis 6-9"'s shape. With
    the corpus to check against, only actual books parse."""
    assert citation.parse_references("Genesis 6-9 tells the story.", store)
    assert citation.parse_references("Quotes 1 says nothing.", store) == []
    assert citation.parse_references("Appendix 4 covers it.", store) == []
