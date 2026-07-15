"""Tier 1 — Mnemosyne correctness suite.

Deterministic, isolated (temp DB per test), no production impact. Proves the
store's behavioural contract: fire-and-forget writes, recall ranking + filters,
recent ordering, forget across both tables, and the 30-day conversation TTL
(expiry-filtered reads + purge).
"""
import calendar
import time


def _ttl_days(expires_at):
    epoch = calendar.timegm(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ"))
    return (epoch - time.time()) / 86400


def test_remember_is_nonblocking_then_recallable(spine, wait_vec):
    # Metadata row is written synchronously (visible immediately via recent),
    # while the embedding lands asynchronously.
    mid = spine.remember("The captain takes his coffee black.", "iris", "s1", kind="fact")
    assert isinstance(mid, str) and len(mid) == 36
    assert any(m["id"] == mid for m in spine.recent(limit=10)), "metadata not written synchronously"
    # ...and becomes semantically recallable once the embed lands.
    assert wait_vec(spine, 1)
    hits = spine.recall("what does he drink?", top_k=3)
    assert hits and hits[0]["id"] == mid


def test_recall_ranks_relevant_first_cross_device(spine, wait_vec):
    spine.remember("The captain prefers black coffee, no sugar.", "iris", "s1", kind="fact")
    spine.remember("Morpheus finished the moon-dish render.", "nyx", "s2", kind="observation")
    spine.remember("The villain is a jealous constellation.", "dio", "s3", kind="conversation")
    assert wait_vec(spine, 3)
    # Query from no particular device — cross-device recall is the point.
    hits = spine.recall("what beverage does the captain like?", top_k=3)
    assert "coffee" in hits[0]["text"].lower()
    assert hits[0]["score"] > hits[-1]["score"]          # ranked by similarity
    assert hits[0]["source_device"] == "iris"            # surfaced across devices


def test_recall_filters(spine, wait_vec):
    spine.remember("story state chapter three", "dio", "story", kind="state")
    spine.remember("story chatter about the hero", "iris", "chat", kind="conversation")
    spine.remember("a dio observation", "dio", "obs", kind="observation")
    assert wait_vec(spine, 3)
    # kind filter
    r = spine.recall("story", top_k=5, filters={"kind": "state"})
    assert r and all(h["kind"] == "state" for h in r)
    # device filter
    r = spine.recall("anything", top_k=5, filters={"device": "iris"})
    assert all(h["source_device"] == "iris" for h in r)
    # session filter
    r = spine.recall("story", top_k=5, filters={"session": "story"})
    assert all(h["id"] for h in r) and r[0]["kind"] == "state"


def test_recent_is_chronological_with_kind_filter(spine, wait_vec):
    for i in range(4):
        spine.remember(f"turn {i}", "dio", "s", kind="conversation")
    spine.remember("story checkpoint", "dio", "s", kind="state")
    assert wait_vec(spine, 5)
    rec = spine.recent(device="dio", limit=10)
    texts = [r["text"] for r in rec]
    assert texts == sorted(texts, key=lambda t: rec[texts.index(t)]["timestamp"])  # oldest->newest
    # kind filter isolates the state checkpoint (Dio's "read on boot" path)
    st = spine.recent(device="dio", kind="state", limit=1)
    assert len(st) == 1 and st[0]["text"] == "story checkpoint"


def test_forget_removes_from_both_tables(spine, wait_vec):
    a = spine.remember("delete me by id", "iris", "sX", kind="fact", metadata={"tag": "t1"})
    spine.remember("delete me by session", "iris", "sKILL", kind="fact")
    spine.remember("delete me by tag", "iris", "sY", kind="fact", metadata={"tag": "sweep"})
    assert wait_vec(spine, 3)

    def counts():
        with spine._lock:
            m = spine._db.execute("SELECT count(*) FROM memories").fetchone()[0]
            v = spine._db.execute("SELECT count(*) FROM vec_memories").fetchone()[0]
        return m, v

    assert counts() == (3, 3)
    assert spine.forget(id=a) == 1
    assert spine.forget(session_id="sKILL") == 1
    assert spine.forget(tag="sweep") == 1
    assert counts() == (0, 0)              # both tables emptied, no orphan vectors


def test_conversation_gets_30d_ttl_others_permanent(spine):
    cid = spine.remember("a chat turn", "iris", "s", kind="conversation")
    fid = spine.remember("a stable fact", "iris", "s", kind="fact")
    sid = spine.remember("story state", "dio", "s", kind="state")
    oid = spine.remember("an observation", "nyx", "s", kind="observation")
    exp = {r[0]: r[1] for r in spine._db.execute(
        "SELECT id, expires_at FROM memories").fetchall()}
    assert exp[cid] is not None and 29 < _ttl_days(exp[cid]) < 31   # ~30 days
    assert exp[fid] is None and exp[sid] is None and exp[oid] is None  # permanent


def test_expired_excluded_from_reads_and_purged(spine, wait_vec):
    fresh = spine.remember("fresh conversation about the festival", "iris", "s", kind="conversation")
    assert wait_vec(spine, 1)
    # Inject an already-expired row directly (past expires_at) + its vector.
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 86400))
    with spine._lock:
        cur = spine._db.execute(
            "INSERT INTO memories (id,timestamp,source_device,session_id,role,kind,text,metadata,expires_at)"
            " VALUES ('stale','2020-01-01T00:00:00Z','iris','s','user','conversation','stale festival note','{}',?)",
            (past,))
        rid = cur.lastrowid
        spine._db.execute("INSERT INTO vec_memories (rowid, embedding) VALUES (?,?)",
                          (rid, spine._embed("stale festival note")))
        spine._db.commit()

    # Reads must never surface the expired row...
    assert all(h["id"] != "stale" for h in spine.recall("festival", top_k=10))
    assert all(r["id"] != "stale" for r in spine.recent(limit=50))
    # ...and purge hard-deletes it from BOTH tables, leaving the fresh one.
    assert spine.purge_expired() == 1
    with spine._lock:
        assert spine._db.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
        assert spine._db.execute("SELECT count(*) FROM vec_memories").fetchone()[0] == 1
    assert spine.recall("festival", top_k=3)[0]["id"] == fresh
