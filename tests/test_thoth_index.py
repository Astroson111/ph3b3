"""
Thoth Rung 2 — the vector index, verify suite.

These use a REAL index over a handful of passages: the properties under test
(eligibility, staleness, neighbour windows) are properties of sqlite-vec and the
joins around it, and a fake would only test the fake. MiniLM loads once per
session and the corpora here are a few verses each, so it stays fast.

Run:  .venv/bin/python -m pytest tests/test_thoth_index.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth.corpus import Corpus                                   # noqa: E402
from thoth.index import Index                                     # noqa: E402
from thoth.schema import (AddressScheme, CanonStatus, Passage,    # noqa: E402
                          Provenance, SourceSpec, Work)


def _work(wid, retrievable=True, note=""):
    return Work(
        id=wid, title=f"Work {wid}", tradition="Testing",
        language_of_origin="English",
        canonicity=(CanonStatus(tradition="Testers", status="canonical"),),
        provenance=Provenance(license="public-domain", license_note="PD",
                              completeness="complete", vendorable=True),
        address=AddressScheme(section_label="chapter", unit_label="verse"),
        source=SourceSpec(url="https://example.invalid/x", adapter="usfm"),
        retrievable=retrievable,
        retrievable_note=note or ("English-only encoder" if not retrievable else ""))


ENGLISH = [
    "In the beginning God created the heaven and the earth.",
    "And the earth was without form, and void.",
    "And God said, Let there be light: and there was light.",
    "And God saw the light, that it was good.",
]
HEBREW = ["בראשית ברא אלהים את השמים ואת הארץ.", "והארץ היתה תהו ובהו."]


@pytest.fixture
def store(tmp_path):
    c = Corpus(db_path=tmp_path / "t.db")
    c.sync_metadata([_work("eng"), _work("heb", retrievable=False)])
    c.replace_passages("eng", [
        Passage(work_id="eng", book="Genesis", section=1, unit=i, text=t, ordinal=i)
        for i, t in enumerate(ENGLISH, start=1)])
    c.replace_passages("heb", [
        Passage(work_id="heb", book="Genesis", section=1, unit=i, text=t, ordinal=i)
        for i, t in enumerate(HEBREW, start=1)])
    ix = Index(c)
    yield c, ix
    c.close()


# ── eligibility: retrievable=false is enforced, not remembered ───────────────

def test_an_unretrievable_work_is_never_indexed(store):
    c, ix = store
    ix.build()
    assert ix.stats() == {"indexed": len(ENGLISH), "eligible": len(ENGLISH), "missing": 0}
    rows = c._db.execute(
        "SELECT DISTINCT p.work_id FROM passages p JOIN vec_passages v ON v.rowid = p.rowid"
    ).fetchall()
    assert [r[0] for r in rows] == ["eng"]


def test_search_never_returns_an_unretrievable_work(store):
    _c, ix = store
    ix.build()
    hits = ix.search("in the beginning God created the heaven", k=10)
    assert hits
    assert all(h.work_id == "eng" for h in hits)


def test_flipping_retrievable_to_false_takes_the_vectors_out(store):
    """The flag is a control, not a comment. If the manifest turns a work off,
    its embeddings must stop being reachable."""
    c, ix = store
    ix.build()
    assert ix.stats()["indexed"] == len(ENGLISH)
    c.sync_metadata([_work("eng", retrievable=False, note="turned off"),
                     _work("heb", retrievable=False)])
    assert ix.prune_ineligible() == len(ENGLISH)
    assert ix.search("in the beginning God created", k=5) == []


# ── staleness: the trap that would fabricate a citation ──────────────────────

def test_reingesting_a_work_drops_its_vectors(store):
    """Re-ingest reassigns rowids. An embedding left pointing at a recycled rowid
    resolves to a DIFFERENT verse — and the citation floor would then stamp that
    verse's address onto it. A stale index here is a fabricated citation with a
    clean bill of health, not a degraded search."""
    c, ix = store
    ix.build()
    assert ix.stats()["indexed"] == len(ENGLISH)
    c.replace_passages("eng", [
        Passage(work_id="eng", book="Genesis", section=1, unit=1,
                text="A completely different verse now.", ordinal=1)])
    assert ix.stats()["indexed"] == 0, "vectors survived a re-ingest"
    assert ix.search("in the beginning", k=5) == []


def test_dropping_a_work_from_the_manifest_drops_its_vectors(store):
    c, ix = store
    ix.build()
    # 'eng' removed on purpose — allow_drop, per the partial-manifest guard.
    c.sync_metadata([_work("heb", retrievable=False)], allow_drop=True)
    assert ix.stats()["indexed"] == 0
    assert ix.search("in the beginning", k=5) == []


def test_search_skips_a_vector_whose_passage_vanished(store):
    """Defence in depth: even with a row the invalidation missed, an answer must
    not be built on it."""
    c, ix = store
    ix.build()
    c._db.execute("DELETE FROM passages WHERE work_id='eng' AND unit=1")
    c._db.commit()
    assert all(h.unit != 1 for h in ix.search("in the beginning God created", k=5))


# ── build behaviour ──────────────────────────────────────────────────────────

def test_build_is_resumable_and_does_not_duplicate(store):
    _c, ix = store
    first = ix.build()
    assert first == len(ENGLISH)
    assert ix.build() == 0, "a second build re-embedded work already done"
    assert ix.stats()["indexed"] == len(ENGLISH)


def test_build_can_be_scoped_to_named_works(store):
    _c, ix = store
    assert ix.build(work_ids=["heb"]) == 0      # not eligible, so nothing to do
    assert ix.build(work_ids=["eng"]) == len(ENGLISH)


def test_search_of_an_empty_index_returns_nothing_rather_than_raising(store):
    _c, ix = store
    assert ix.search("anything at all", k=5) == []


def test_blank_query_returns_nothing(store):
    _c, ix = store
    ix.build()
    assert ix.search("   ", k=5) == []


# ── windows: what makes a multi-verse quotation checkable ────────────────────

def test_window_returns_contiguous_neighbours_in_verse_order(store):
    _c, ix = store
    ix.build()
    hits = ix.search("let there be light", k=1)
    assert hits and hits[0].unit == 3
    w = ix.window(hits[0], before=2, after=1)
    assert [h.unit for h in w] == [1, 2, 3, 4]
    assert all(h.work_id == "eng" for h in w)


def test_window_does_not_cross_into_another_section(store):
    c, ix = store
    c.replace_passages("eng", [
        Passage(work_id="eng", book="Genesis", section=1, unit=1, text=ENGLISH[0], ordinal=1),
        Passage(work_id="eng", book="Genesis", section=2, unit=1,
                text="Thus the heavens and the earth were finished.", ordinal=2)])
    ix.build()
    hits = ix.search("thus the heavens were finished", k=1)
    assert hits and hits[0].section == 2
    assert all(h.section == 2 for h in ix.window(hits[0]))


def test_a_corpus_write_works_without_an_index_object_in_the_process(tmp_path):
    """Regression. Corpus must invalidate vectors on a passage write, and a vec0
    table cannot be touched from a connection without the extension loaded — so
    Corpus loads it too. Without that, `python -m thoth.ingest` died with
    "no such module: vec0" as soon as an index existed: the invalidation that
    protects against stale-rowid citations was itself breaking the write path."""
    db = tmp_path / "t.db"
    c = Corpus(db_path=db)
    c.sync_metadata([_work("eng")])
    c.replace_passages("eng", [
        Passage(work_id="eng", book="Genesis", section=1, unit=i, text=t, ordinal=i)
        for i, t in enumerate(ENGLISH, start=1)])
    Index(c).build()
    c.close()

    # A fresh process would construct Corpus alone, with no Index anywhere.
    c2 = Corpus(db_path=db)
    c2.replace_passages("eng", [
        Passage(work_id="eng", book="Genesis", section=1, unit=1,
                text="rewritten", ordinal=1)])
    assert c2._db.execute("SELECT count(*) FROM vec_passages").fetchone()[0] == 0
    c2.close()
