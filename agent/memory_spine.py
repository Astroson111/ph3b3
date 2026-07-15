"""
memory_spine.py — Mnemosyne, the constellation's shared persistent memory.

Mnemosyne is the Titaness of Memory. This module is the shared, local, persistent
store the rest of Ph3b3 remembers itself by: any device or module can `remember`
a memory and `recall` the most relevant ones semantically, across devices, and
they survive restarts.

(The Mnemosyne *brand* lives here and on the /mnemosyne/* routes; the Python name
`mnemosyne` was already taken by the Jamendo karaoke provider, so the spine lives
under this filename by Astro's call — see the build brief.)

Hard constraints honoured:
  - Fully local. sqlite-vec runs in-process; embeddings run on CPU. No cloud.
  - Zero GPU load. Embeddings use all-MiniLM-L6-v2 on device='cpu' so a memory
    write never contends with Morpheus for the card or forces an Ollama reload.
  - Writes are fire-and-forget. remember() inserts the metadata row and returns
    the id immediately; the embed + vector insert happen on a single background
    worker thread, so the caller never blocks on the model.

v1 values-audit outcomes (Astro, signed off):
  - No TTL. Every memory is permanent; `expires_at` stays NULL. The column is
    kept so a forgetting policy can switch on post-v1 with no migration.
  - The content-safety floor gates *generation*, not storage. remember() stores
    what it is given. (If that reverses post-v1, the check attaches at the marked
    seam in remember().)
  - forget() is always a hard delete.
"""
import json
import logging
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sqlite_vec
from sentence_transformers import SentenceTransformer

log = logging.getLogger("ph3b3.memory_spine")

DB_PATH = Path.home() / "ph3b3_data" / "mnemosyne.db"
MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384  # all-MiniLM-L6-v2 output width; frozen — changing it changes the vec table

VALID_ROLES = {"user", "assistant", "observation"}
VALID_KINDS = {"conversation", "fact", "state", "observation"}


class MemorySpine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # One shared connection, guarded by a single lock. sqlite + the vec0
        # extension are used from both the request thread and the embed worker,
        # so every statement runs under _lock.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)
        self._init_schema()

        # The model loads lazily on a background thread so boot is not blocked by
        # the ~4s load. Embed jobs and recall() wait on _model_ready.
        self._model: SentenceTransformer | None = None
        self._model_ready = threading.Event()
        threading.Thread(target=self._load_model, daemon=True).start()

        # Single worker => embeds are serialised and CPU load stays bounded even
        # if a burst of writes lands during a Morpheus render.
        self._embed_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mnemo-embed")

        n = self._db.execute("SELECT count(*) FROM memories").fetchone()[0]
        log.info("Mnemosyne store open at %s (%d memories)", self.db_path, n)

    # ── model ────────────────────────────────────────────────────────────────

    def _load_model(self) -> None:
        try:
            t0 = time.perf_counter()
            # device='cpu' is the non-negotiable bit: keeps Mnemosyne off the GPU.
            self._model = SentenceTransformer(MODEL_NAME, device="cpu")
            log.info("Mnemosyne embed model ready: %s on CPU (%.2fs)",
                     MODEL_NAME, time.perf_counter() - t0)
        except Exception:
            log.exception("Mnemosyne embed model failed to load — recall/embeds disabled")
        finally:
            self._model_ready.set()

    def _embed(self, text: str) -> bytes:
        if not self._model_ready.wait(timeout=60) or self._model is None:
            raise RuntimeError("embed model not ready")
        vec = self._model.encode([text], normalize_embeddings=True)[0]
        return sqlite_vec.serialize_float32(vec.tolist())

    # ── schema (frozen v1) ─────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._lock:
            self._db.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0(
                    embedding float[{EMBED_DIM}] distance_metric=cosine
                )
            """)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    rowid         INTEGER PRIMARY KEY,
                    id            TEXT UNIQUE NOT NULL,
                    timestamp     TEXT NOT NULL,
                    source_device TEXT,
                    session_id    TEXT,
                    role          TEXT,
                    kind          TEXT,
                    text          TEXT NOT NULL,
                    metadata      TEXT,
                    expires_at    TEXT
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_session ON memories(session_id)")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_device ON memories(source_device)")
            self._db.commit()

    # ── remember (fire-and-forget) ─────────────────────────────────────────────

    def remember(self, text: str, source_device: str = "", session_id: str = "",
                 role: str = "user", kind: str = "conversation",
                 metadata: dict | None = None) -> str:
        """Store a memory and return its id immediately. The embedding + vector
        insert are queued on the background worker, so the caller never waits on
        the model. The memory is recallable within moments (once the embed lands).
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("cannot remember empty text")
        if role not in VALID_ROLES:
            role = "observation"
        if kind not in VALID_KINDS:
            kind = "observation"

        # --- storage-floor seam ---------------------------------------------
        # v1: the content-safety floor gates generation, not storage (Astro's
        # values-audit call). If that reverses, run the floor check here and
        # raise before the insert.
        # --------------------------------------------------------------------

        mid = str(uuid.uuid4())
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO memories (id, timestamp, source_device, session_id, "
                "role, kind, text, metadata, expires_at) VALUES (?,?,?,?,?,?,?,?,NULL)",
                (mid, ts, source_device, session_id, role, kind, text,
                 json.dumps(metadata or {})),
            )
            rowid = cur.lastrowid
            self._db.commit()

        # fire-and-forget: embed + vec insert off the request path
        self._embed_pool.submit(self._embed_and_store, rowid, text, mid)
        return mid

    def _embed_and_store(self, rowid: int, text: str, mid: str) -> None:
        try:
            emb = self._embed(text)
            with self._lock:
                self._db.execute(
                    "INSERT INTO vec_memories (rowid, embedding) VALUES (?, ?)",
                    (rowid, emb))
                self._db.commit()
        except Exception:
            # A failed embed leaves the metadata row intact but unsearchable by
            # vector; it still shows in recent()/forget(). Never crashes the write.
            log.exception("Mnemosyne embed failed for memory %s (rowid %s)", mid, rowid)

    # ── recall (semantic) ──────────────────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[dict]:
        """Semantic KNN over all memories (NOT scoped to any device — cross-device
        recall is the point), ranked by cosine similarity. Optional filters:
        {device, kind, session}. Returns the metadata + score for each hit."""
        query = (query or "").strip()
        if not query:
            return []
        filters = filters or {}
        device = filters.get("device")
        kind = filters.get("kind")
        session = filters.get("session")

        emb = self._embed(query)
        # Over-fetch so post-filtering still yields up to top_k.
        fetch_k = top_k * 5 if (device or kind or session) else top_k
        with self._lock:
            rows = self._db.execute(
                "SELECT rowid, distance FROM vec_memories "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (emb, fetch_k),
            ).fetchall()
            out: list[dict] = []
            for rowid, distance in rows:
                m = self._db.execute(
                    "SELECT id, text, timestamp, source_device, session_id, kind, "
                    "metadata FROM memories WHERE rowid = ?", (rowid,)).fetchone()
                if not m:
                    continue
                mid, text, ts, dev, sess, k, meta = m
                if device and dev != device:
                    continue
                if kind and k != kind:
                    continue
                if session and sess != session:
                    continue
                out.append({
                    "id": mid,
                    "text": text,
                    "score": round(1.0 - distance, 6),  # cosine similarity
                    "timestamp": ts,
                    "source_device": dev,
                    "kind": k,
                    "metadata": json.loads(meta or "{}"),
                })
                if len(out) >= top_k:
                    break
        return out

    # ── recent (chronological, for rebuilding a context window) ─────────────────

    def recent(self, session_id: str | None = None, device: str | None = None,
               limit: int = 20, kind: str | None = None) -> list[dict]:
        """Most recent `limit` memories in chronological order (oldest→newest), so
        a caller can rehydrate a context window. Optional session/device/kind
        filter. This is a keyed SQL read — no embedding — so it's cheap enough for
        a device to call on boot (e.g. recent(device='dio', kind='state', limit=1)
        to reload the latest story state)."""
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?"); params.append(session_id)
        if device:
            clauses.append("source_device = ?"); params.append(device)
        if kind:
            clauses.append("kind = ?"); params.append(kind)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self._lock:
            rows = self._db.execute(
                f"SELECT id, text, timestamp, source_device, session_id, role, kind, "
                f"metadata FROM memories {where} ORDER BY rowid DESC LIMIT ?", params
            ).fetchall()
        # fetched newest-first; reverse to chronological for context rebuilding
        results = [{
            "id": r[0], "text": r[1], "timestamp": r[2], "source_device": r[3],
            "session_id": r[4], "role": r[5], "kind": r[6],
            "metadata": json.loads(r[7] or "{}"),
        } for r in rows]
        results.reverse()
        return results

    # ── forget (always a hard delete) ───────────────────────────────────────────

    def forget(self, id: str | None = None, session_id: str | None = None,
               tag: str | None = None) -> int:
        """Hard-delete memories by id, session_id, or metadata tag. Removes rows
        from both the metadata and vector tables. Returns the count deleted."""
        if id:
            clause, params = "id = ?", [id]
        elif session_id:
            clause, params = "session_id = ?", [session_id]
        elif tag:
            # tag is matched against metadata.$.tag
            clause, params = "json_extract(metadata, '$.tag') = ?", [tag]
        else:
            raise ValueError("forget requires one of: id, session_id, tag")

        with self._lock:
            rowids = [r[0] for r in self._db.execute(
                f"SELECT rowid FROM memories WHERE {clause}", params).fetchall()]
            if not rowids:
                return 0
            qmarks = ",".join("?" * len(rowids))
            self._db.execute(
                f"DELETE FROM vec_memories WHERE rowid IN ({qmarks})", rowids)
            self._db.execute(
                f"DELETE FROM memories WHERE rowid IN ({qmarks})", rowids)
            self._db.commit()
        log.info("Mnemosyne forgot %d memory(ies) [%s]", len(rowids), clause)
        return len(rowids)

    # ── lifecycle ───────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._embed_pool.shutdown(wait=False)
        with self._lock:
            self._db.close()
