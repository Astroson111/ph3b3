"""Two-tier read intent: a book name is not the same kind of word twice.

`is_read_intent` required a verb AND an address, so bare "read John" fell
through — safe, and also useless, because "read Genesis" is an obvious request
she ignored. The reason it was written that way is real: scripture book names
collide with ordinary English. "read Job" is a book; "read Job's offer letter"
is a document. "read Numbers" is a book; "read the numbers" is a spreadsheet.

So the tier is decided by the NAME, deterministically. The model never chooses,
and nothing here depends on how confident a classifier feels.
"""
import sqlite3, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "modules"))

import pytest
from thoth import intent as I

DB = pathlib.Path.home() / "ph3b3_thoth" / "thoth.db"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="thoth corpus absent")


@pytest.fixture(scope="module")
def books():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT p.book FROM passages p JOIN works w ON w.id = p.work_id "
            "WHERE w.ingested = 1 AND p.book IS NOT NULL AND p.book <> ''")]
    finally:
        con.close()


# ── tier 1: unambiguous name, bare, reads from chapter 1 ────────────────────
@pytest.mark.parametrize("text,book", [
    ("read Genesis", "Genesis"),
    ("read Habakkuk", "Habakkuk"),
    ("read Isaiah", "Isaiah"),
    ("read Psalms", "Psalms"),
    ("read 1 John", "1 John"),            # longest-match beats bare "John"
    ("read Song of Solomon", "Song of Solomon"),
    ("please read Deuteronomy", "Deuteronomy"),
    ("read me Leviticus", "Leviticus"),   # filler between verb and name
])
def test_tier1_bare_book_reads_chapter_one(text, book, books):
    r = I.read_request(text, books)
    assert r is not None, f"{text!r} did not register at all"
    assert r["book"] == book and r["chapter"] == 1 and r["confirm"] is False


# ── tier 2: collision name, bare, asks first ────────────────────────────────
@pytest.mark.parametrize("text,book", [
    ("read John", "John"), ("read Job", "Job"), ("read Numbers", "Numbers"),
    ("read Mark", "Mark"), ("read Luke", "Luke"), ("read Acts", "Acts"),
    ("read James", "James"), ("read Ruth", "Ruth"), ("read Daniel", "Daniel"),
    ("read Jude", "Jude"), ("read Joel", "Joel"), ("read Amos", "Amos"),
    ("read Judges", "Judges"), ("read Revelation", "Revelation"),
])
def test_tier2_bare_collision_asks_to_confirm(text, book, books):
    r = I.read_request(text, books)
    assert r is not None and r["book"] == book
    assert r["confirm"] is True, f"{text!r} should have asked, not started"


def test_the_confirm_line_is_fixed_and_names_the_book(books):
    assert I.confirm_line("John") == "The Gospel of John?"
    assert I.confirm_line("Mark") == "The Gospel of Mark?"
    assert I.confirm_line("Job") == "The Book of Job?"
    assert I.confirm_line("Numbers") == "The Book of Numbers?"


# ── tier 2, disambiguated three ways, reads without asking ──────────────────
@pytest.mark.parametrize("text,book,chapter", [
    ("read John 3", "John", 3),
    ("read Numbers 7", "Numbers", 7),
    ("read Job chapter 38", "Job", 38),
    ("read the gospel of John", "John", 1),
    ("read the book of Job", "Job", 1),
    ("read the gospel according to Mark", "Mark", 1),
])
def test_tier2_disambiguated_does_not_ask(text, book, chapter, books):
    r = I.read_request(text, books)
    assert r is not None and r["book"] == book
    assert r["chapter"] == chapter and r["confirm"] is False


def test_surah_marker_is_its_own_address(books):
    r = I.read_request("read surah 36", books)
    assert r is not None and r.get("surah") is True and r["confirm"] is False


@pytest.mark.parametrize("text", ["read John", "read Job", "read Numbers"])
def test_thoth_active_removes_the_ambiguity(text, books):
    """Tab open or debate mode on IS the disambiguation — she is already there."""
    r = I.read_request(text, books, thoth_active=True)
    assert r is not None and r["confirm"] is False and r["chapter"] == 1


# ── must never fire ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "read my email",
    "read John's message",            # possessive => a person
    "read Job's offer letter",        # the case that makes this rule necessary
    "read Mark's reply",
    "read the numbers",               # article + lowercase => a spreadsheet
    "read the numbers again",
    "read that back to me",
    "read me the news",
    "read Acts of kindness aloud",    # trailing words, not a chapter
    "what does John say about love",  # no reading verb at all
    "I read Job last night",
])
def test_these_are_not_read_requests(text, books):
    assert I.read_request(text, books) is None, f"{text!r} fired and must not"


def test_collision_list_matches_the_corpus(books):
    """Every collision name must actually BE a book in the ingested corpus.

    A name in the list that is not in the corpus is dead weight that makes a
    confirm prompt for something she cannot read anyway.
    """
    have = {(b or "").strip().lower() for b in books}
    orphans = sorted(n for n in I.COLLISION_BOOKS if n not in have)
    assert not orphans, f"collision names not present in the corpus: {orphans}"


# ── numbered-only families: there is no bare form to read ───────────────────
# Nine families in the corpus exist ONLY numbered, so bare "read Kings" cannot
# resolve to anything. It used to do nothing at all, silently.
def test_the_numbered_only_list_comes_from_the_corpus(books):
    fams = I.numbered_families(books)
    assert set(fams) == {"Kings", "Samuel", "Chronicles", "Corinthians",
                         "Thessalonians", "Timothy", "Peter", "Esdras",
                         "Maccabees"}, sorted(fams)
    # Maccabees has FOUR parts, not two. The confirm is built from the corpus
    # rather than assuming every numbered family is a pair.
    assert fams["Maccabees"] == [1, 2, 3, 4]
    assert fams["Kings"] == [1, 2]
    # "John" is NOT here: 1/2/3 John exist AND a bare John (the Gospel) does,
    # which is why it is a collision name instead.
    assert "John" not in fams


@pytest.mark.parametrize("text,line", [
    ("read Kings", "1 Kings or 2 Kings?"),
    ("read Samuel", "1 Samuel or 2 Samuel?"),
    ("read from Chronicles", "1 Chronicles or 2 Chronicles?"),
    ("read Maccabees", "1 Maccabees, 2 Maccabees, 3 Maccabees or 4 Maccabees?"),
])
def test_bare_numbered_family_asks_which_part(text, line, books):
    r = I.read_request(text, books)
    assert r is not None and r["confirm"] is True and r.get("parts")
    assert I.numbered_confirm_line(r["stem"], r["parts"]) == line


# ── ordinal phrasings are a FULL marker: read, never ask ────────────────────
@pytest.mark.parametrize("text,book", [
    ("read from the first book of Kings", "1 Kings"),
    ("read from the second book of Kings", "2 Kings"),
    ("read the first book of Kings", "1 Kings"),
    ("read first Kings", "1 Kings"),
    ("read 1st Kings", "1 Kings"),
    ("read 1 Kings", "1 Kings"),
    ("read I Kings", "1 Kings"),
    ("read the third book of Maccabees", "3 Maccabees"),
    ("read the fourth book of Maccabees", "4 Maccabees"),
    ("read the first letter of Peter", "1 Peter"),
    ("read the second epistle to the Corinthians", "2 Corinthians"),
    ("read first epistle of John", "1 John"),        # the epistle, NOT the Gospel
    ("read the second letter of Timothy", "2 Timothy"),
])
def test_ordinal_phrase_reads_without_asking(text, book, books):
    r = I.read_request(text, books)
    assert r is not None, f"{text!r} did not register"
    assert r["book"] == book and r["confirm"] is False and r["chapter"] == 1


def test_first_epistle_of_john_is_not_the_gospel(books):
    """The one case where the same name means two different books."""
    assert I.read_request("read first epistle of John", books)["book"] == "1 John"
    assert I.read_request("read the gospel of John", books)["book"] == "John"


@pytest.mark.parametrize("text", [
    "read the third book of Kings",      # only 1 and 2 exist
    "read fourth Kings",
    "read the second book of Genesis",   # not a numbered family at all
])
def test_a_part_the_corpus_does_not_have_does_not_fire(text, books):
    assert I.read_request(text, books) is None


# ── STT singular drift, and ONLY inside an ordinal phrase ──────────────────
@pytest.mark.parametrize("text,book", [
    ("read the first book of king", "1 Kings"),
    ("read the first chronicle", "1 Chronicles"),
    ("read the second corinthian", "2 Corinthians"),
    ("read the first thessalonian", "1 Thessalonians"),
])
def test_singular_drift_tolerated_inside_an_ordinal_phrase(text, book, books):
    r = I.read_request(text, books)
    assert r is not None and r["book"] == book and r["confirm"] is False


@pytest.mark.parametrize("text", [
    "read the king's speech",        # the drift must not leak outside ordinals
    "read the king's letter",
    "read king",
    "read chronicle",
])
def test_singular_drift_never_fires_outside_an_ordinal_phrase(text, books):
    assert I.read_request(text, books) is None


# ── "read from X" is "read X" everywhere ───────────────────────────────────
@pytest.mark.parametrize("text,expect_book,expect_confirm", [
    ("read from Genesis", "Genesis", False),
    ("read from Habakkuk", "Habakkuk", False),
    ("read from John 3", "John", False),
    ("read from John", "John", True),            # collision tier still applies
    ("read from Job", "Job", True),
])
def test_read_from_is_the_same_request(text, expect_book, expect_confirm, books):
    r = I.read_request(text, books)
    assert r is not None and r["book"] == expect_book
    assert r["confirm"] is expect_confirm


# ── answers to the confirm question ────────────────────────────────────────
@pytest.mark.parametrize("answer,book", [
    ("the first one", "1 Kings"), ("first book", "1 Kings"),
    ("first", "1 Kings"), ("1", "1 Kings"), ("1st", "1 Kings"),
    ("one", "1 Kings"), ("I", "1 Kings"),
    ("second", "2 Kings"), ("2", "2 Kings"), ("the second one", "2 Kings"),
])
def test_numbered_confirm_accepts_ordinal_answers(answer, book, books):
    pending = I.read_request("read Kings", books)
    assert I.confirm_answer(answer, pending) == book


@pytest.mark.parametrize("answer", ["no thanks", "neither", "actually Genesis",
                                    "third", "yes"])
def test_numbered_confirm_rejects_non_answers(answer, books):
    """A numbered confirm needs a PART. "yes" answers nothing here, and "third"
    is a part Kings does not have."""
    pending = I.read_request("read Kings", books)
    assert I.confirm_answer(answer, pending) is None


@pytest.mark.parametrize("answer", ["yes", "yeah", "sure"])
def test_collision_confirm_accepts_a_bare_yes(answer, books):
    pending = I.read_request("read John", books)
    assert I.confirm_answer(answer, pending) == "John"


# ── the addendum's explicit never-fire list ────────────────────────────────
@pytest.mark.parametrize("text", [
    "read from the first page",
    "read the second book on my desk",
    "read me the first message",
    "read the king's letter",
    "read Peter's text",
    "read Samuel's email",
    "read from my notes",
    "read the first line again",
])
def test_addendum_must_not_fire(text, books):
    assert I.read_request(text, books) is None, f"{text!r} fired and must not"
