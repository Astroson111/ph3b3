"""
thoth.corpus — the manifest loader and the passage store.

TWO SOURCES OF TRUTH, DELIBERATELY SPLIT.

    config/thoth_corpus.yaml    the WORKS: metadata, canonicity, provenance.
                                Authored by hand. This is the library's
                                scholarship and the part worth backing up.
    THOTH_DATA/thoth.db         the BODIES: every addressed passage, plus a
                                materialised copy of the metadata for querying.
                                Rebuildable from the manifest and the network.

The manifest wins on every metadata conflict. `sync_metadata()` re-materialises
works, canonicity and citations from the YAML without touching a single passage,
so correcting a canonicity row is a text edit and a re-sync, never a re-download
of the Bible.

── WHY CANONICITY IS A TABLE AND NOT A JSON COLUMN ─────────────────────────
Astro's rule is that canon fields are first-class, not notes. A JSON blob in a
column technically stores the same bytes and quietly fails the rule: "which
traditions receive 1 Enoch as scripture" stops being a query and becomes a
program that parses every row. As tables, the interesting questions are SQL:

    SELECT work_id FROM canonicity WHERE tradition=? AND status='canonical'

A `book` of NULL is the work-level position; a row with a book overrides it for
that book, which is how one WEB release holds Genesis and 4 Maccabees honestly.

── ONE BAD ENTRY MUST NOT TAKE THE LIBRARY DOWN ────────────────────────────
load_manifest() validates each work independently and collects failures instead
of raising on the first. A typo in the Atrahasis provenance disables Atrahasis
and nothing else — the same rule shelf.py applies to a broken pack manifest, for
the same reason: a library that refuses to open because one shelf is wrong is
worse than a library with one shelf missing and a note saying so.

── WHERE THE DATA LIVES, AND WHY IT IS NOT UNDER ph3b3_data ────────────────
THOTH_DATA defaults to ~/ph3b3_thoth, OUTSIDE both of Rhea's backup roots.

The corpus and its embeddings are re-downloadable bulk — the same policy class
as the Piper voice models and the RecipeNLG dataset, both of which Rhea excludes
by name. Astro's call in Phase 0 was that they are excluded by design.

Placing them outside the backup roots achieves that structurally and today, with
no edit to Rhea (which this brief forbids). The alternative — living under
ph3b3_data and relying on an exclude line — was measured during Phase 0 and is
worse than it looks: Rhea's `--exclude "$DATA_DIR"/'*.db'` glob does not descend
into subdirectories, so a DB at ph3b3_data/thoth/thoth.db is NOT excluded. It
would be copied live, mid-write, by a backup whose entire step 2 exists to stop
exactly that.

The manifest is a different matter and stays in the repo at config/, which Rhea
already backs up in full.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from .schema import (AddressScheme, BookCanonicity, CanonStatus, Citation,
                     Passage, Provenance, SourceSpec, Translation, Work)

log = logging.getLogger("ph3b3.thoth.corpus")

try:                                              # server: modules/ on sys.path
    from paths import PH3B3_HOME
except ImportError:                               # tests / standalone
    from modules.paths import PH3B3_HOME

THOTH_DATA = Path(os.getenv("PH3B3_THOTH_DATA", str(Path.home() / "ph3b3_thoth")))
CACHE_DIR = THOTH_DATA / "cache"
DB_PATH = THOTH_DATA / "thoth.db"
MANIFEST_PATH = Path(PH3B3_HOME) / "config" / "thoth_corpus.yaml"


# ── Manifest ─────────────────────────────────────────────────────────────────

def _canon_rows(raw: list | None, where: str) -> tuple[CanonStatus, ...]:
    out = []
    for r in raw or []:
        out.append(CanonStatus(tradition=str(r["tradition"]),
                               status=str(r["status"]),
                               note=str(r.get("note", ""))))
    if not out:
        raise ValueError(f"{where}: no canonicity rows")
    return tuple(out)


def _work_from_dict(d: dict) -> Work:
    """Build one validated Work from a manifest entry. Raises on anything the
    schema refuses — the caller isolates the failure."""
    wid = str(d.get("id", "")).strip()
    tr = d.get("translation")
    translation = None
    if tr:
        translation = Translation(translator=str(tr["translator"]),
                                  year=int(tr["year"]),
                                  title=str(tr.get("title", "")))
    prov = d["provenance"]
    addr = d["address"]
    src = d["source"]
    return Work(
        id=wid,
        title=str(d["title"]),
        tradition=str(d["tradition"]),
        language_of_origin=str(d["language_of_origin"]),
        canonicity=_canon_rows(d.get("canonicity"), f"work {wid!r}"),
        book_canonicity=tuple(
            BookCanonicity(book=str(b["book"]),
                           canonicity=_canon_rows(
                               b.get("canonicity"),
                               f"work {wid!r} book {b.get('book')!r}"))
            for b in d.get("book_canonicity") or []),
        provenance=Provenance(
            license=str(prov["license"]),
            license_note=str(prov["license_note"]),
            completeness=str(prov["completeness"]),
            vendorable=bool(prov["vendorable"]),
            completeness_note=str(prov.get("completeness_note", ""))),
        address=AddressScheme(
            section_label=str(addr["section_label"]),
            unit_label=str(addr["unit_label"]),
            has_books=bool(addr.get("has_books", True)),
            section_style=str(addr.get("section_style", "arabic"))),
        source=SourceSpec(url=str(src["url"]), adapter=str(src["adapter"]),
                          sha256=str(src.get("sha256", "")),
                          note=str(src.get("note", "")),
                          subset=str(src.get("subset", ""))),
        translation=translation,
        cited_by=tuple(Citation(source=str(c["source"]), note=str(c.get("note", "")))
                       for c in d.get("cited_by") or []),
        retrievable=bool(d.get("retrievable", True)),
        retrievable_note=str(d.get("retrievable_note", "")),
        scholarship_note=str(d.get("scholarship_note", "")),
        ingested=bool(d.get("ingested", False)),
        ingest_note=str(d.get("ingest_note", "")),
    )


def load_manifest(path: Path | None = None) -> tuple[list[Work], list[tuple[str, str]]]:
    """Parse the corpus manifest.

    Returns (works, failures) where failures is [(work_id_or_index, reason)].
    Never raises for a bad entry — only for an unreadable or malformed FILE,
    which is a different kind of broken.
    """
    import yaml
    p = Path(path or MANIFEST_PATH)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = doc.get("works")
    if not isinstance(entries, list):
        raise ValueError(f"{p}: manifest has no 'works' list")

    works: list[Work] = []
    failures: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, d in enumerate(entries):
        ident = str((d or {}).get("id", f"#{i}"))
        try:
            w = _work_from_dict(d)
            if w.id in seen:
                raise ValueError(f"duplicate work id {w.id!r}")
            seen.add(w.id)
            works.append(w)
        except Exception as e:
            failures.append((ident, str(e)))
            log.warning("thoth: manifest entry %s rejected — %s", ident, e)
    return works, failures


# ── Store ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    id                 TEXT PRIMARY KEY,
    title              TEXT NOT NULL,
    tradition          TEXT NOT NULL,
    language_of_origin TEXT NOT NULL,
    translator         TEXT,
    translation_year   INTEGER,
    translation_title  TEXT,
    license            TEXT NOT NULL,
    license_note       TEXT NOT NULL,
    vendorable         INTEGER NOT NULL,
    completeness       TEXT NOT NULL,
    completeness_note  TEXT,
    retrievable        INTEGER NOT NULL,
    retrievable_note   TEXT,
    scholarship_note   TEXT,
    section_label      TEXT NOT NULL,
    unit_label         TEXT NOT NULL,
    has_books          INTEGER NOT NULL,
    section_style      TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    source_adapter     TEXT NOT NULL,
    source_sha256      TEXT,
    ingested           INTEGER NOT NULL DEFAULT 0,
    ingest_note        TEXT,
    passage_count      INTEGER NOT NULL DEFAULT 0
);

-- book IS NULL  => the work-level position.
-- book NOT NULL => overrides the work-level position for that book only.
CREATE TABLE IF NOT EXISTS canonicity (
    work_id   TEXT NOT NULL,
    book      TEXT,
    tradition TEXT NOT NULL,
    status    TEXT NOT NULL,
    note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_canon_work ON canonicity(work_id);
CREATE INDEX IF NOT EXISTS idx_canon_trad ON canonicity(tradition, status);

CREATE TABLE IF NOT EXISTS citations (
    work_id TEXT NOT NULL,
    source  TEXT NOT NULL,
    note    TEXT
);
CREATE INDEX IF NOT EXISTS idx_cite_work ON citations(work_id);

CREATE TABLE IF NOT EXISTS passages (
    work_id TEXT NOT NULL,
    book    TEXT NOT NULL DEFAULT '',
    section INTEGER NOT NULL,
    unit    INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    text    TEXT NOT NULL,
    PRIMARY KEY (work_id, book, section, unit)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_pass_order ON passages(work_id, ordinal);
"""


class Corpus:
    """The Thoth store. Metadata is materialised from the manifest; passages are
    written by ingest and read by everything downstream."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # ── metadata ─────────────────────────────────────────────────────────────

    def sync_metadata(self, works: list[Work]) -> int:
        """Materialise work metadata from the manifest. Passages of works that
        are STILL in the manifest are untouched.

        Existing passage_count and ingested state are preserved for those: they
        describe what is in the DB, which the manifest does not know and must not
        clobber.

        A work that has been REMOVED from the manifest is dropped from the store
        entirely — metadata, canonicity, citations and passages. Astro's ruling
        of 2026-09-13 is that the manifest describes the corpus that exists, and
        a work deleted from the manifest but still answering queries out of the
        DB would make that false. Deleting the row is what makes the manifest
        authoritative rather than merely additive.
        """
        cur = self._db.cursor()
        keep = {w.id for w in works}
        stale = [r[0] for r in cur.execute("SELECT id FROM works").fetchall()
                 if r[0] not in keep]
        for wid in stale:
            for table in ("passages", "canonicity", "citations", "works"):
                col = "id" if table == "works" else "work_id"
                cur.execute(f"DELETE FROM {table} WHERE {col}=?", (wid,))
            log.info("thoth: dropped %s — no longer in the manifest", wid)
        for w in works:
            prior = cur.execute(
                "SELECT ingested, passage_count FROM works WHERE id=?", (w.id,)
            ).fetchone()
            ingested, count = (prior if prior else (int(w.ingested), 0))
            cur.execute("""
                INSERT INTO works (id, title, tradition, language_of_origin,
                    translator, translation_year, translation_title,
                    license, license_note, vendorable, completeness,
                    completeness_note, retrievable, retrievable_note,
                    scholarship_note, section_label, unit_label, has_books,
                    section_style, source_url, source_adapter, source_sha256,
                    ingested, ingest_note, passage_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, tradition=excluded.tradition,
                    language_of_origin=excluded.language_of_origin,
                    translator=excluded.translator,
                    translation_year=excluded.translation_year,
                    translation_title=excluded.translation_title,
                    license=excluded.license, license_note=excluded.license_note,
                    vendorable=excluded.vendorable,
                    completeness=excluded.completeness,
                    completeness_note=excluded.completeness_note,
                    retrievable=excluded.retrievable,
                    retrievable_note=excluded.retrievable_note,
                    scholarship_note=excluded.scholarship_note,
                    section_label=excluded.section_label,
                    unit_label=excluded.unit_label,
                    has_books=excluded.has_books,
                    section_style=excluded.section_style,
                    source_url=excluded.source_url,
                    source_adapter=excluded.source_adapter,
                    source_sha256=excluded.source_sha256,
                    ingest_note=excluded.ingest_note
            """, (
                w.id, w.title, w.tradition, w.language_of_origin,
                w.translation.translator if w.translation else None,
                w.translation.year if w.translation else None,
                w.translation.title if w.translation else None,
                w.provenance.license, w.provenance.license_note,
                int(w.provenance.vendorable), w.provenance.completeness,
                w.provenance.completeness_note, int(w.retrievable),
                w.retrievable_note, w.scholarship_note,
                w.address.section_label, w.address.unit_label,
                int(w.address.has_books), w.address.section_style,
                w.source.url, w.source.adapter, w.source.sha256,
                ingested, w.ingest_note, count,
            ))
            # Canonicity and citations are fully replaced: the manifest is the
            # only author of these rows, so a deleted entry must disappear.
            cur.execute("DELETE FROM canonicity WHERE work_id=?", (w.id,))
            cur.executemany(
                "INSERT INTO canonicity (work_id, book, tradition, status, note) "
                "VALUES (?,?,?,?,?)",
                [(w.id, None, c.tradition, c.status, c.note) for c in w.canonicity]
                + [(w.id, bc.book, c.tradition, c.status, c.note)
                   for bc in w.book_canonicity for c in bc.canonicity])
            cur.execute("DELETE FROM citations WHERE work_id=?", (w.id,))
            cur.executemany(
                "INSERT INTO citations (work_id, source, note) VALUES (?,?,?)",
                [(w.id, c.source, c.note) for c in w.cited_by])
        self._db.commit()
        return len(works)

    # ── passages ─────────────────────────────────────────────────────────────

    def replace_passages(self, work_id: str, passages: list[Passage]) -> int:
        """Write a work's body, replacing whatever was there.

        One transaction and one executemany — NOT the per-row insert-and-commit
        pattern Mnemosyne uses for single memories, which fsyncs once per verse
        and turns a 31,000-verse Bible into an afternoon.
        """
        cur = self._db.cursor()
        cur.execute("DELETE FROM passages WHERE work_id=?", (work_id,))
        cur.executemany(
            "INSERT INTO passages (work_id, book, section, unit, ordinal, text) "
            "VALUES (?,?,?,?,?,?)",
            [(p.work_id, p.book or "", p.section, p.unit, p.ordinal, p.text)
             for p in passages])
        cur.execute(
            "UPDATE works SET passage_count=?, ingested=1 WHERE id=?",
            (len(passages), work_id))
        self._db.commit()
        return len(passages)

    def set_source_hash(self, work_id: str, sha256: str) -> None:
        """Record the sha256 of the bytes actually parsed into this work, so
        'which revision is in the store' has an answer a re-download can be
        compared against."""
        self._db.execute("UPDATE works SET source_sha256=? WHERE id=?",
                         (sha256, work_id))
        self._db.commit()

    def passage(self, work_id: str, section: int, unit: int,
                book: str | None = None) -> Passage | None:
        row = self._db.execute(
            "SELECT work_id, book, section, unit, text, ordinal FROM passages "
            "WHERE work_id=? AND book=? AND section=? AND unit=?",
            (work_id, book or "", section, unit)).fetchone()
        if not row:
            return None
        return Passage(work_id=row[0], book=row[1] or None, section=row[2],
                       unit=row[3], text=row[4], ordinal=row[5])

    def passage_range(self, work_id: str, section: int,
                      book: str | None = None) -> list[Passage]:
        """Every passage in one section (a chapter, a tablet), in order."""
        rows = self._db.execute(
            "SELECT work_id, book, section, unit, text, ordinal FROM passages "
            "WHERE work_id=? AND book=? AND section=? ORDER BY unit",
            (work_id, book or "", section)).fetchall()
        return [Passage(work_id=r[0], book=r[1] or None, section=r[2],
                        unit=r[3], text=r[4], ordinal=r[5]) for r in rows]

    def books(self, work_id: str) -> list[str]:
        return [r[0] for r in self._db.execute(
            "SELECT DISTINCT book FROM passages WHERE work_id=? AND book<>'' "
            "ORDER BY ordinal", (work_id,)).fetchall()]

    # ── canonicity queries — the point of the table ──────────────────────────

    def works_received_by(self, tradition: str) -> list[tuple[str, str | None, str]]:
        """(work_id, book, status) for everything `tradition` receives as
        scripture at any stratum."""
        return [tuple(r) for r in self._db.execute(
            "SELECT work_id, book, status FROM canonicity "
            "WHERE lower(tradition)=lower(?) AND status IN "
            "('canonical','deuterocanonical') ORDER BY work_id, book", (tradition,))]

    def canonicity_of(self, work_id: str,
                      book: str | None = None) -> list[tuple[str, str, str]]:
        """(tradition, status, note) governing a work or one of its books."""
        rows = self._db.execute(
            "SELECT tradition, status, note FROM canonicity "
            "WHERE work_id=? AND book IS ? ORDER BY tradition",
            (work_id, book)).fetchall()
        if not rows and book is not None:
            rows = self._db.execute(
                "SELECT tradition, status, note FROM canonicity "
                "WHERE work_id=? AND book IS NULL ORDER BY tradition",
                (work_id,)).fetchall()
        return [tuple(r) for r in rows]

    def retrievable_work_ids(self) -> list[str]:
        """Works eligible for the Rung 2 retrieval index. Honours the declared
        `retrievable` flag, which is how WLC and the Arabic Quran stay out of an
        English-model index without anyone having to remember why."""
        return [r[0] for r in self._db.execute(
            "SELECT id FROM works WHERE retrievable=1 AND ingested=1 ORDER BY id")]

    def summary(self) -> list[dict]:
        cols = ("id", "title", "tradition", "license", "completeness",
                "retrievable", "ingested", "passage_count")
        return [dict(zip(cols, r)) for r in self._db.execute(
            f"SELECT {','.join(cols)} FROM works ORDER BY id")]
