"""
Thoth Rung 1 — manifest and store verify suite.

Hermetic: every Corpus here is a fresh temp DB. Nothing touches
~/ph3b3_thoth/thoth.db and nothing reaches the network. The one shared resource
is the real config/thoth_corpus.yaml, which is in-repo and is the artifact under
test in the manifest cases.

Run:  .venv/bin/python -m pytest tests/test_thoth_corpus.py -v
"""
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth.corpus import Corpus, load_manifest  # noqa: E402
from thoth.schema import Passage                # noqa: E402

MANIFEST = REPO / "config" / "thoth_corpus.yaml"


@pytest.fixture
def corpus(tmp_path):
    c = Corpus(db_path=tmp_path / "thoth.db")
    yield c
    c.close()


@pytest.fixture(scope="module")
def works():
    w, failures = load_manifest(MANIFEST)
    assert not failures, f"manifest entries rejected: {failures}"
    return w


# ── the shipped manifest ─────────────────────────────────────────────────────

def test_shipped_manifest_loads_with_no_rejected_entries(works):
    assert len(works) >= 15
    ids = {w.id for w in works}
    for expected in ("web", "web-apocrypha", "jps1917", "wlc", "quran-ar",
                     "quran-pickthall", "quran-yusufali", "enoch1", "jubilees",
                     "enuma-elish", "gilgamesh", "atrahasis", "etcsl",
                     "book-of-the-dead", "memphite-theology"):
        assert expected in ids, f"{expected} missing from the manifest"


def test_a_work_with_no_public_domain_english_edition_is_not_listed(works):
    """Astro's ruling, 2026-09-13: the manifest describes the corpus that
    EXISTS. A work with no PD/open English translation is dropped entirely —
    not carried as a gap, a placeholder or a pending download.

    The Pyramid Texts are the case that produced the rule: Mercer 1952 is in
    copyright, Sethe is German, and the public-domain English material is a 1916
    monograph about the corpus rather than a translation of it.
    """
    assert "pyramid-texts" not in {w.id for w in works}


def test_every_work_declares_a_position_from_some_tradition(works):
    for w in works:
        assert w.canonicity, w.id


def test_hebrew_and_arabic_source_texts_are_out_of_the_retrieval_index(works):
    """The Phase 0 measurement, encoded as policy rather than remembered."""
    by_id = {w.id: w for w in works}
    for wid in ("wlc", "quran-ar"):
        assert not by_id[wid].retrievable, wid
        assert "MiniLM" in by_id[wid].retrievable_note or \
               "English" in by_id[wid].retrievable_note
    # The English translations of the same scriptures stay retrievable.
    for wid in ("quran-pickthall", "quran-yusufali", "web", "jps1917"):
        assert by_id[wid].retrievable, wid


def test_etcsl_is_marked_unvendorable(works):
    """© Oxford. cite-don't-vendor is enforced at ingest, and this is the flag it
    reads. If this ever flips to true, ETCSL text could be committed to the repo."""
    etcsl = next(w for w in works if w.id == "etcsl")
    assert etcsl.provenance.vendorable is False
    assert etcsl.provenance.license == "scholarly-restricted"


def test_budge_carries_the_dated_scholarship_flag(works):
    bod = next(w for w in works if w.id == "book-of-the-dead")
    assert "DATED" in bod.scholarship_note


def test_atrahasis_points_at_the_fuller_edition(works):
    """A fragmentary text must say where the complete one is, or a reader takes
    the fragments for the whole."""
    atra = next(w for w in works if w.id == "atrahasis")
    assert atra.provenance.completeness == "fragmentary"
    assert "Lambert" in atra.provenance.completeness_note


def test_enoch_records_the_citation_that_makes_it_interesting(works):
    enoch = next(w for w in works if w.id == "enoch1")
    assert any("Jude" in c.source for c in enoch.cited_by)
    receiving = {t.lower() for t in enoch.traditions_receiving()}
    assert any("ethiopian" in t for t in receiving)
    assert enoch.canon_status_for("Protestant Christianity").status == "excluded"


def test_uningested_works_say_why(works):
    for w in works:
        if not w.ingested and w.source.adapter == "prose":
            assert w.ingest_note.strip(), f"{w.id} is not ingested and does not say why"


# ── manifest robustness ──────────────────────────────────────────────────────

def _write(tmp_path, body):
    p = tmp_path / "m.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


_GOOD_ENTRY = """
  - id: good
    title: Good Work
    tradition: Testing
    language_of_origin: English
    address: {section_label: chapter, unit_label: verse}
    provenance: {license: public-domain, license_note: PD, completeness: complete,
                 vendorable: true}
    source: {url: "https://example.invalid/a", adapter: usfm}
    canonicity:
      - {tradition: Testers, status: canonical}
"""


def test_one_bad_entry_does_not_take_the_library_down(tmp_path):
    """shelf.py's rule: a broken pack disables itself and nothing else."""
    p = _write(tmp_path, "works:\n" + _GOOD_ENTRY + """
  - id: bad
    title: Bad Work
    tradition: Testing
    language_of_origin: English
    address: {section_label: chapter, unit_label: verse}
    provenance: {license: public-domain, license_note: PD, completeness: complete,
                 vendorable: true}
    source: {url: "https://example.invalid/b", adapter: usfm}
    canonicity: []
""")
    works, failures = load_manifest(p)
    assert [w.id for w in works] == ["good"]
    assert len(failures) == 1 and failures[0][0] == "bad"
    assert "canonicity" in failures[0][1]


def test_duplicate_ids_are_rejected_not_silently_merged(tmp_path):
    p = _write(tmp_path, "works:\n" + _GOOD_ENTRY + _GOOD_ENTRY)
    works, failures = load_manifest(p)
    assert len(works) == 1
    assert "duplicate" in failures[0][1]


# ── the store ────────────────────────────────────────────────────────────────

def test_passages_round_trip_by_address(corpus, works):
    corpus.sync_metadata(works)
    corpus.replace_passages("web", [
        Passage(work_id="web", book="John", section=3, unit=16,
                text="For God so loved the world", ordinal=1),
        Passage(work_id="web", book="John", section=3, unit=17,
                text="For God didn't send his Son", ordinal=2),
    ])
    got = corpus.passage("web", 3, 16, book="John")
    assert got is not None and got.text.startswith("For God so loved")
    assert corpus.passage("web", 3, 99, book="John") is None
    assert [p.unit for p in corpus.passage_range("web", 3, book="John")] == [16, 17]


def test_replace_passages_is_a_replacement_not_an_append(corpus, works):
    corpus.sync_metadata(works)
    p = [Passage(work_id="web", book="John", section=1, unit=1, text="a", ordinal=1)]
    corpus.replace_passages("web", p)
    corpus.replace_passages("web", p)
    assert corpus.summary()[[r["id"] for r in corpus.summary()].index("web")]["passage_count"] == 1


def test_sync_metadata_does_not_clobber_ingested_bodies(corpus, works):
    """Correcting a canonicity row is a text edit and a re-sync. It must never
    cost a re-download of the Bible."""
    corpus.sync_metadata(works)
    corpus.replace_passages("web", [
        Passage(work_id="web", book="John", section=1, unit=1, text="a", ordinal=1)])
    corpus.sync_metadata(works)          # second pass, as after a manifest edit
    assert corpus.passage("web", 1, 1, book="John") is not None
    row = next(r for r in corpus.summary() if r["id"] == "web")
    assert row["ingested"] and row["passage_count"] == 1


# ── canonicity as a query, which is the whole point of the table ─────────────

def test_canonicity_is_queryable_across_traditions(corpus, works):
    corpus.sync_metadata(works)
    ethiopian = dict((w, s) for w, _b, s in
                     corpus.works_received_by("Ethiopian Orthodox Tewahedo Church"))
    assert ethiopian.get("enoch1") == "canonical"
    assert ethiopian.get("jubilees") == "canonical"
    assert "enoch1" not in dict(
        (w, s) for w, _b, s in corpus.works_received_by("Protestant Christianity"))


def test_book_level_override_is_stored_and_beats_the_work_default(corpus, works):
    corpus.sync_metadata(works)
    default = dict((t, s) for t, s, _n in corpus.canonicity_of("web-apocrypha"))
    assert default["Eastern Orthodox Church"] == "canonical"
    fourth = dict((t, s) for t, s, _n
                  in corpus.canonicity_of("web-apocrypha", book="4 Maccabees"))
    assert fourth["Georgian Orthodox Church"] == "canonical"
    assert fourth["Eastern Orthodox Church"] == "apocryphal"
    # A book with no override falls back to the work-level rows.
    tobit = dict((t, s) for t, s, _n
                 in corpus.canonicity_of("web-apocrypha", book="Tobit"))
    assert tobit["Eastern Orthodox Church"] == "canonical"


def test_canonicity_rows_are_replaced_not_duplicated_on_resync(corpus, works):
    corpus.sync_metadata(works)
    first = len(corpus.canonicity_of("enoch1"))
    corpus.sync_metadata(works)
    assert len(corpus.canonicity_of("enoch1")) == first


def test_retrievable_index_excludes_declared_gaps_and_uningested_works(corpus, works):
    corpus.sync_metadata(works)
    for wid in ("web", "wlc", "quran-ar", "quran-pickthall"):
        corpus.replace_passages(wid, [
            Passage(work_id=wid, book="B", section=1, unit=1, text="x", ordinal=1)])
    eligible = set(corpus.retrievable_work_ids())
    assert "web" in eligible and "quran-pickthall" in eligible
    assert "wlc" not in eligible, "Hebrew source text must stay out of the index"
    assert "quran-ar" not in eligible, "Arabic source text must stay out of the index"
    # Never ingested, so nothing to index even though retrievable=true.
    assert "gilgamesh" not in eligible


def test_web_subset_is_declared_not_inferred_from_the_work_id(works):
    """One archive, two works. If the selector were sniffed from the id, renaming
    'web-apocrypha' would silently change which books it ingests."""
    by_id = {w.id: w for w in works}
    assert by_id["web"].source.subset == "protocanon"
    assert by_id["web-apocrypha"].source.subset == "deuterocanon"
    assert by_id["web"].source.url == by_id["web-apocrypha"].source.url


def test_source_hash_is_recorded_for_provenance(corpus, works):
    corpus.sync_metadata(works)
    corpus.set_source_hash("web", "a" * 64)
    got = corpus._db.execute(
        "SELECT source_sha256 FROM works WHERE id='web'").fetchone()[0]
    assert got == "a" * 64


def test_a_work_removed_from_the_manifest_is_dropped_from_the_store(corpus, works):
    """The manifest is authoritative, not merely additive. A work deleted from
    it must stop answering queries — otherwise 'the manifest describes the
    corpus that exists' is false the moment anything is removed, and a dropped
    work goes on being citable out of the DB."""
    corpus.sync_metadata(works)
    corpus.replace_passages("gilgamesh", [
        Passage(work_id="gilgamesh", book=None, section=11, unit=1,
                text="Gilgamesh spoke to him, to Utnapishtim the far-away",
                ordinal=1)])
    assert corpus.passage("gilgamesh", 11, 1) is not None
    assert corpus.canonicity_of("gilgamesh")

    # allow_drop: this test IS the deliberate-removal case the flag exists for.
    # Without it the partial-manifest guard refuses, which is the point of the
    # guard — a caller that means to drop a work has to say so.
    corpus.sync_metadata([w for w in works if w.id != "gilgamesh"],
                         allow_drop=True)

    assert corpus.passage("gilgamesh", 11, 1) is None
    assert corpus.canonicity_of("gilgamesh") == []
    assert "gilgamesh" not in {r["id"] for r in corpus.summary()}
    # Everything else survives untouched.
    assert "web" in {r["id"] for r in corpus.summary()}
