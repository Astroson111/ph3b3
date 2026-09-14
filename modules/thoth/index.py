"""
thoth.index — the vector index over the corpus, and retrieval against it.

sqlite-vec + all-MiniLM-L6-v2 on CPU: the same stack Mnemosyne runs, in a
DIFFERENT store. Nothing here opens mnemosyne.db.

── WHY NOT MNEMOSYNE'S STORE ────────────────────────────────────────────────
`memory_spine.recall()` is deliberately un-scoped — cross-device recall is the
whole point of it. Putting 74,000 verses into that table means every ordinary
recall in every module competes with scripture, and "what did Astro say about
the printer" starts returning Leviticus. Thoth reuses the stack and keeps its
own table, keyed by `passages.rowid` in thoth.db.

── AND NOT ITS WRITE PATH EITHER ────────────────────────────────────────────
Mnemosyne embeds one item per call on a single worker with a commit per row,
which is correct for one memory arriving from a conversation and hopeless for a
corpus: measured on Nyx, MiniLM does 203 texts/sec at batch 1 and 970/sec at
batch 128. Building is batched and commits per batch.

── THE INDEX IS DERIVED, AND KNOWS IT ───────────────────────────────────────
Embeddings key on `passages.rowid`, which re-ingesting a work reassigns. A row
left pointing at a recycled rowid resolves to a DIFFERENT verse — and because
the citation floor stamps addresses server-side from whatever passage it
matched, that is a fabricated citation carrying a correct-looking address. So
`Corpus.replace_passages` drops a work's vectors before rewriting its bodies,
and `build()` reports what is missing rather than assuming it is current.

── retrievable=false IS ENFORCED HERE, NOT REMEMBERED ───────────────────────
The Westminster Leningrad Codex and the Tanzil Arabic are declared
`retrievable: false` in the manifest on a measured basis (MiniLM is an English
model; Hebrew and Arabic cluster by script, not meaning). `build()` indexes only
works that are retrievable AND ingested, and `search()` filters again on the way
out. Twice, because the flag is a safety property of the answer rather than a
build-time convenience: if a stale row somehow survives, the second check still
keeps it out of an answer.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import sqlite_vec
from sentence_transformers import SentenceTransformer

from .corpus import Corpus
from .schema import Passage

log = logging.getLogger("ph3b3.thoth.index")

MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384          # frozen: changing it changes the vec table
BUILD_BATCH = 128        # measured sweet spot on Nyx (970 texts/sec)

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    """Load MiniLM once per process, on CPU.

    device='cpu' is the same non-negotiable Mnemosyne states: an embed must never
    contend with Morpheus for the card or force an Ollama reload.
    """
    global _model
    with _model_lock:
        if _model is None:
            log.info("thoth: loading %s on CPU", MODEL_NAME)
            _model = SentenceTransformer(MODEL_NAME, device="cpu")
        return _model


@dataclass(frozen=True)
class Hit:
    """One retrieved passage, with everything an honest citation needs."""
    rowid: int
    work_id: str
    book: str | None
    section: int
    unit: int
    text: str
    score: float          # cosine similarity, 1.0 == identical

    def passage(self) -> Passage:
        return Passage(work_id=self.work_id, book=self.book, section=self.section,
                       unit=self.unit, text=self.text)


class Index:
    """The vector index over a Corpus. Build it once, search it many times."""

    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self._db = corpus._db
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_passages USING vec0("
            f"embedding float[{EMBED_DIM}] distance_metric=cosine)")
        self._db.commit()

    # ── build ────────────────────────────────────────────────────────────────

    def eligible_rows(self, work_ids: list[str] | None = None) -> list[tuple[int, str]]:
        """(rowid, text) for every passage that MAY be indexed: ingested works
        that are declared retrievable, minus anything already embedded."""
        sql = ("SELECT p.rowid, p.text FROM passages p JOIN works w ON w.id = p.work_id "
               "WHERE w.retrievable = 1 AND w.ingested = 1 "
               "AND p.rowid NOT IN (SELECT rowid FROM vec_passages)")
        params: list = []
        if work_ids:
            sql += f" AND p.work_id IN ({','.join('?' * len(work_ids))})"
            params += work_ids
        return [(r[0], r[1]) for r in self._db.execute(sql + " ORDER BY p.rowid", params)]

    def build(self, work_ids: list[str] | None = None,
              batch: int = BUILD_BATCH, progress=None) -> int:
        """Embed everything eligible and not yet embedded. Returns the count added.

        Idempotent: re-running indexes only what is missing, so an interrupted
        build resumes instead of starting over.
        """
        rows = self.eligible_rows(work_ids)
        if not rows:
            return 0
        model = _get_model()
        added = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            vecs = model.encode([t for _rid, t in chunk], batch_size=batch,
                                normalize_embeddings=True)
            self._db.executemany(
                "INSERT INTO vec_passages (rowid, embedding) VALUES (?, ?)",
                [(rid, sqlite_vec.serialize_float32(v.tolist()))
                 for (rid, _t), v in zip(chunk, vecs)])
            self._db.commit()          # per batch, not per row
            added += len(chunk)
            if progress:
                progress(added, len(rows))
        log.info("thoth: indexed %d passages", added)
        return added

    def prune_ineligible(self) -> int:
        """Delete embeddings for passages that are no longer eligible.

        Covers the case that matters most: a work whose `retrievable` flag flips
        to false in the manifest. Without this the vectors linger and the flag
        would be a comment rather than a control.
        """
        cur = self._db.execute(
            "DELETE FROM vec_passages WHERE rowid NOT IN ("
            "  SELECT p.rowid FROM passages p JOIN works w ON w.id = p.work_id"
            "  WHERE w.retrievable = 1 AND w.ingested = 1)")
        self._db.commit()
        if cur.rowcount:
            log.info("thoth: pruned %d ineligible embeddings", cur.rowcount)
        return max(0, cur.rowcount)

    def stats(self) -> dict:
        indexed = self._db.execute("SELECT count(*) FROM vec_passages").fetchone()[0]
        eligible = self._db.execute(
            "SELECT count(*) FROM passages p JOIN works w ON w.id = p.work_id "
            "WHERE w.retrievable = 1 AND w.ingested = 1").fetchone()[0]
        return {"indexed": indexed, "eligible": eligible,
                "missing": max(0, eligible - indexed)}

    # ── search ───────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 8,
               work_ids: list[str] | None = None) -> list[Hit]:
        """Semantic KNN over the indexed passages, best first.

        The retrievable/ingested join is applied AGAIN here rather than trusted
        from build time — see the module note.
        """
        query = (query or "").strip()
        if not query or k < 1:
            return []
        emb = sqlite_vec.serialize_float32(
            _get_model().encode([query], normalize_embeddings=True)[0].tolist())
        # Over-fetch: the work filter and the eligibility join are applied after
        # the KNN, so a bare k could come back short.
        fetch = k * 4 if work_ids else k * 2
        rows = self._db.execute(
            "SELECT v.rowid, v.distance FROM vec_passages v "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (emb, fetch)).fetchall()
        want = set(work_ids) if work_ids else None
        out: list[Hit] = []
        for rowid, distance in rows:
            r = self._db.execute(
                "SELECT p.work_id, p.book, p.section, p.unit, p.text "
                "FROM passages p JOIN works w ON w.id = p.work_id "
                "WHERE p.rowid = ? AND w.retrievable = 1 AND w.ingested = 1",
                (rowid,)).fetchone()
            if not r:
                continue               # stale vector, or work no longer eligible
            if want and r[0] not in want:
                continue
            out.append(Hit(rowid=rowid, work_id=r[0], book=r[1] or None,
                           section=r[2], unit=r[3], text=r[4],
                           score=round(1.0 - distance, 6)))
            if len(out) >= k:
                break
        return out

    def window(self, hit: Hit, before: int = 2, after: int = 4) -> list[Hit]:
        """The hit plus its neighbours in the same section, in verse order.

        A quotation legitimately runs across verses — John 3:16-17 is one
        sentence of scripture and two addresses. The citation floor matches a
        quote against a CONTIGUOUS RUN of passages, so it needs the neighbours,
        and it needs them even though they were not themselves retrieved.
        """
        rows = self._db.execute(
            "SELECT rowid, work_id, book, section, unit, text FROM passages "
            "WHERE work_id=? AND book=? AND section=? AND unit BETWEEN ? AND ? "
            "ORDER BY unit",
            (hit.work_id, hit.book or "", hit.section,
             hit.unit - before, hit.unit + after)).fetchall()
        return [Hit(rowid=r[0], work_id=r[1], book=r[2] or None, section=r[3],
                    unit=r[4], text=r[5],
                    score=hit.score if r[4] == hit.unit else 0.0) for r in rows]
