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
  - Forgetting policy: `conversation` memories expire after 30 days (via
    `expires_at`); `fact`, `state`, and `observation` are permanent unless
    explicitly forgotten. Expired rows are excluded from reads and hard-deleted
    by a background purge. This bounds the deterministic per-turn auto-capture so
    Mnemosyne can't quietly grow into a permanent record of every conversation.
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

# Device-name aliases. The same physical device has been tagged under more than
# one name over time: Dio's firmware sends "stackchan" (X-Ph3b3-Device), while
# the Phase-2 boot-state design refers to it as "dio". Without this, a read like
# recent(device="dio", kind="state") never matches Dio's "stackchan"-tagged
# rows. We canonicalise on write and match the whole alias group on read, so a
# write under either name and a read by either name agree. Extend as devices
# are renamed. Canonical form is lowercased.
DEVICE_ALIASES = {
    "stackchan": "dio",
    "dio":       "dio",
}


def canon_device(name: str) -> str:
    """Map a raw device tag to its canonical name (unchanged if not aliased)."""
    n = (name or "").strip()
    return DEVICE_ALIASES.get(n.lower(), n)


def device_group(name: str) -> list[str]:
    """Every raw tag that shares `name`'s canonical device, for read filters.
    e.g. device_group("dio") == device_group("stackchan") == ["dio", "stackchan"]."""
    canon = canon_device(name)
    group = {raw for raw, c in DEVICE_ALIASES.items() if c == canon}
    group.add(canon)
    if (name or "").strip():
        group.add(name.strip())
    return sorted(group)

# Forgetting policy (v1): only `conversation` memories expire.
TTL_DAYS_BY_KIND = {"conversation": 30}


def _utc_iso(epoch: float | None = None) -> str:
    """ISO-8601 UTC (…Z). Lexical order == chronological order, so expiry can be
    compared as a plain string in SQL."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(epoch if epoch is not None else time.time()))


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
        self.purge_expired()   # drop anything already past its TTL on boot

        # The model loads lazily on a background thread so boot is not blocked by
        # the ~4s load. Embed jobs and recall() wait on _model_ready.
        self._model: SentenceTransformer | None = None
        self._model_ready = threading.Event()
        threading.Thread(target=self._load_model, daemon=True).start()

        # Single worker => embeds are serialised and CPU load stays bounded even
        # if a burst of writes lands during a Morpheus render.
        self._embed_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mnemo-embed")

        # Periodic TTL purge (conversation memories expire after 30 days).
        threading.Thread(target=self._purge_loop, daemon=True).start()

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
        source_device = canon_device(source_device)   # unify dio/stackchan et al.

        # --- storage-floor seam ---------------------------------------------
        # v1: the content-safety floor gates generation, not storage (Astro's
        # values-audit call). If that reverses, run the floor check here and
        # raise before the insert.
        # --------------------------------------------------------------------

        mid = str(uuid.uuid4())
        now = time.time()
        ts = _utc_iso(now)
        ttl_days = TTL_DAYS_BY_KIND.get(kind)
        expires_at = _utc_iso(now + ttl_days * 86400) if ttl_days else None
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO memories (id, timestamp, source_device, session_id, "
                "role, kind, text, metadata, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (mid, ts, source_device, session_id, role, kind, text,
                 json.dumps(metadata or {}), expires_at),
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
        device_grp = set(device_group(device)) if device else None  # dio+stackchan
        kind = filters.get("kind")
        session = filters.get("session")

        emb = self._embed(query)
        now = _utc_iso()
        # Over-fetch so post-filtering (incl. expiry) still yields up to top_k.
        fetch_k = top_k * 5 if (device or kind or session) else top_k * 2
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
                    "metadata, expires_at FROM memories WHERE rowid = ?", (rowid,)).fetchone()
                if not m:
                    continue
                mid, text, ts, dev, sess, k, meta, exp = m
                if exp is not None and exp <= now:
                    continue  # expired — excluded from recall (purge will delete it)
                if device_grp and dev not in device_grp:
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
                    "session_id": sess,
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
        clauses, params = ["(expires_at IS NULL OR expires_at > ?)"], [_utc_iso()]
        if session_id:
            clauses.append("session_id = ?"); params.append(session_id)
        if device:
            grp = device_group(device)   # match dio + stackchan together
            clauses.append(f"source_device IN ({','.join('?' * len(grp))})")
            params.extend(grp)
        if kind:
            clauses.append("kind = ?"); params.append(kind)
        where = "WHERE " + " AND ".join(clauses)
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

    # ── TTL purge ───────────────────────────────────────────────────────────────

    def purge_expired(self) -> int:
        """Hard-delete memories whose expires_at has passed, from both the
        metadata and vector tables. Runs on boot and every 6h thereafter. Reads
        already exclude expired rows, so this just reclaims space."""
        now = _utc_iso()
        with self._lock:
            rowids = [r[0] for r in self._db.execute(
                "SELECT rowid FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now,)).fetchall()]
            if not rowids:
                return 0
            qmarks = ",".join("?" * len(rowids))
            self._db.execute(f"DELETE FROM vec_memories WHERE rowid IN ({qmarks})", rowids)
            self._db.execute(f"DELETE FROM memories WHERE rowid IN ({qmarks})", rowids)
            self._db.commit()
        log.info("Mnemosyne purged %d expired memory(ies)", len(rowids))
        return len(rowids)

    def _purge_loop(self) -> None:
        while True:
            time.sleep(6 * 3600)
            try:
                self.purge_expired()
            except Exception:
                log.exception("Mnemosyne purge loop error")

    # ── lifecycle ───────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._embed_pool.shutdown(wait=False)
        with self._lock:
            self._db.close()
