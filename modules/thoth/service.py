"""
thoth.service — the seam between the library and the running server.

Everything server.py needs is a function here, so wiring Thoth into a 7,600-line
file stays a handful of lines rather than a transplant.

── ONE CORPUS, ONE INDEX, LOADED LATE ───────────────────────────────────────
The embedder costs a few seconds to load and boot time is not the place to spend
it, so the corpus and index are built on FIRST USE and kept. If the store is
missing or the index was never built, retrieval simply returns nothing and the
citation floor's no-retrieval branch takes over: she argues without quoting and
says so. A library that has not been ingested yet degrades to honesty, not to an
error page.

── ONE SPEAKER, WHICH IS THE POINT OF THIS FILE ─────────────────────────────
Rung 4 shipped with a real gap: the per-unit speech lock lives on a TTSModule
INSTANCE, so `python -m thoth read` and the running service each held their own
and could talk over each other at the speaker. The fix was never a bigger lock —
it was one instance. The reading here is bound to the server's `tts` singleton,
so the per-unit lock finally means what it says and a reading interleaves with
ordinary speech instead of colliding with it.

The CLI still has its own, and still can collide with the service. That is now
the only way to reach the old behaviour, and it is documented in reader.py.

── THE MODEL CALL HAS NO TOOLS ──────────────────────────────────────────────
`_generate` posts to Ollama with no `tools` key at all — Kadmos's injection
firewall, and load-bearing here because retrieved scripture is full of
second-person imperatives. It is deliberately synchronous: `lane.ask` is a plain
function, and server.py calls the whole thing through `asyncio.to_thread`, which
keeps the async plumbing out of the lane where the floor lives.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

from . import debate, intent, lane, reader
from .corpus import Corpus, load_manifest
from .index import Index

log = logging.getLogger("ph3b3.thoth.service")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = os.getenv("PH3B3_LIGHT_MODEL", os.getenv("PH3B3_MODEL", "ph3b3-chat:latest"))

# RLock, not Lock: reading() holds it and then calls store(), which takes it
# again. With a plain Lock that is a self-deadlock on the FIRST chat turn — the
# whole server wedged, found by the chat smoke test hanging. memory_spine uses
# an RLock for exactly this shape.
_lock = threading.RLock()
_corpus: Corpus | None = None
_index: Index | None = None
_names: frozenset[str] | None = None
_reading: reader.Reading | None = None


# ── lazy singletons ──────────────────────────────────────────────────────────

def store() -> tuple[Corpus, Index]:
    global _corpus, _index
    with _lock:
        if _corpus is None:
            c = Corpus()
            works, failures = load_manifest()
            for ident, why in failures:
                log.warning("thoth: manifest entry %s rejected — %s", ident, why)
            c.sync_metadata(works, allow_drop=True)   # loads the full manifest
            _corpus, _index = c, Index(c)
            log.info("thoth: library open — %s", _index.stats())
        return _corpus, _index


def work_names() -> frozenset[str]:
    """Book and work names the corpus holds, for intent matching.

    Read from the store rather than listed here, so adding a work to the
    manifest makes it recognisable in conversation with no code change.
    """
    global _names
    if _names is None:
        try:
            _names = _collect_names()
        except Exception as e:
            # Never let a broken library break ordinary chat: with no names the
            # intent test simply does not fire and the turn goes on as before.
            log.warning("thoth: work names unavailable — %s", e)
            return frozenset()
    return _names


_books: tuple[str, ...] | None = None


def book_names() -> tuple[str, ...]:
    """Book names from the INGESTED corpus, cached per process.

    read_request() matches against this, so a name the corpus does not have
    cannot become a read request — "read Samuel" resolves to nothing because the
    corpus holds "1 Samuel" and "2 Samuel" and no bare "Samuel".
    """
    global _books
    with _lock:
        if _books is None:
            try:
                c, _ix = store()
                _books = tuple(r[0] for r in c._db.execute(
                    "SELECT DISTINCT p.book FROM passages p JOIN works w ON w.id = p.work_id "
                    "WHERE w.ingested = 1 AND p.book IS NOT NULL AND p.book <> ''"))
            except Exception as e:                     # noqa: BLE001
                log.warning("thoth: book names unavailable — %s", e)
                _books = ()
        return _books


def thoth_active(tts=None) -> bool:
    """Is she already in the library? Debate mode on, or a reading in flight.

    This is what makes a bare collision name unambiguous without a confirm:
    someone in debate mode who says "read John" means the gospel. The Thoth TAB
    being open is NOT visible here — the panel does not report focus per turn —
    so a tab-only user still gets the confirm line. Noted rather than faked.
    """
    try:
        if debate.enabled():
            return True
    except Exception:                                  # noqa: BLE001
        pass
    try:
        return bool(tts is not None and is_reading(tts))
    except Exception:                                  # noqa: BLE001
        return False


def _collect_names() -> frozenset[str]:
    c, _ix = store()
    out: set[str] = set()
    for (b,) in c._db.execute("SELECT DISTINCT book FROM passages WHERE book<>''"):
        out.add(b.casefold())
    for (t,) in c._db.execute("SELECT title FROM works"):
        for word in str(t).replace("(", " ").replace(")", " ").split():
            if len(word) > 4 and word.isalpha():
                out.add(word.casefold())
    # Short, unambiguous work nicknames the titles do not contain.
    out |= {"enoch", "jubilees", "quran", "qur'an", "koran", "bible"}
    return frozenset(out)


def available() -> bool:
    try:
        _c, ix = store()
        return ix.stats()["indexed"] > 0
    except Exception as e:
        log.warning("thoth: library unavailable — %s", e)
        return False


# ── is the index actually usable? ────────────────────────────────────────────
# The index went empty in the Sept 23 crash with every passage row intact, so
# the library LOOKED whole: works present, passages present, retrieval silently
# returning nothing. An unindexed library must be a stated condition, not an
# empty result set, because the fallback on this path is answering scripture
# from model weights — the one outcome the forced routing exists to prevent.
UNINDEXED_LINE = ("My library is unindexed at the moment — the texts are there "
                  "but the search over them isn't built, so I can't quote "
                  "chapter and verse. I'd rather tell you that than answer "
                  "about scripture from memory.")

# STRICT: every eligible passage must be embedded, or she says so.
#
# This was 0.99, which let a 128-row shortfall (one batch) read as healthy while
# Argus — alarming on unembedded > 0 — called the same state SICK. Two
# thresholds for one fact, and the looser one was the one that decided whether
# she spoke. The missing rows are not random noise either: they are specific
# verses, and a question about one of them gets a confident answer assembled
# from the verses that ARE indexed, with a correct-looking citation attached.
#
# Strict is affordable here precisely because the build is cheap and resumable:
# the whole corpus re-embeds in ~3.5 minutes and an interrupted run picks up
# where it stopped. "Refuse until it is complete" costs minutes; "answer from a
# library with holes in it" costs a wrong citation nobody can see is wrong.
INDEX_MIN_FRACTION = 1.0


def index_health() -> dict:
    """indexed / eligible / unembedded, plus whether that is good enough to use.

    `unembedded` is the number Argus alarms on. It is derived, never stored, so
    it cannot go stale the way a cached counter would.
    """
    try:
        _c, ix = store()
        st = ix.stats()
    except Exception as e:
        return {"indexed": 0, "eligible": 0, "unembedded": 0,
                "ok": False, "reason": f"store unavailable: {e}"}
    indexed, eligible = st["indexed"], st["eligible"]
    unembedded = max(0, eligible - indexed)
    if eligible == 0:
        return {**st, "unembedded": 0, "ok": False, "reason": "no eligible passages"}
    if indexed == 0:
        return {**st, "unembedded": unembedded, "ok": False, "reason": "index empty"}
    frac = indexed / eligible
    ok = frac >= INDEX_MIN_FRACTION
    return {**st, "unembedded": unembedded, "ok": ok,
            "reason": None if ok else f"index short: {indexed:,}/{eligible:,} ({frac:.1%})"}


def log_index_health() -> dict:
    """Boot check. Says the state out loud in the log either way."""
    h = index_health()
    if h["ok"]:
        log.info("thoth: index OK — %s/%s passages embedded",
                 f"{h.get('indexed',0):,}", f"{h.get('eligible',0):,}")
    else:
        log.error("thoth: INDEX NOT USABLE — %s (unembedded=%d). She will say so "
                  "rather than answer from weights.", h["reason"], h["unembedded"])
    return h


# ── the model call: NO tools key, ever ───────────────────────────────────────

def _generate(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.3}}).encode()
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r).get("response", "")


# ── answering ────────────────────────────────────────────────────────────────

def answer(query: str, session_id: str = "") -> str:
    """Answer a scripture question from the corpus, under the citation floor.

    Never raises into the caller: a library that is down returns a sentence
    saying so, because the alternative on this path is the chat falling back to
    an unfloored answer, which is the one outcome the routing exists to prevent.
    """
    try:
        c, ix = store()
    except Exception as e:
        log.warning("thoth: store unavailable — %s", e)
        return ("My library isn't open at the moment, and I'd rather say that "
                "than answer about scripture from memory.")
    # DETERMINISTIC, above the lane and above the model. An empty or short index
    # is a stated condition, not a quiet miss.
    _h = index_health()
    if not _h["ok"]:
        log.error("thoth: refusing to answer — %s (unembedded=%d)",
                  _h["reason"], _h["unembedded"])
        return UNINDEXED_LINE
    try:
        got = lane.ask(query, _generate, c, ix, session_id=session_id)
    except Exception as e:
        log.exception("thoth: lane failed")
        return ("Something went wrong reaching my library, so I'm not going to "
                f"answer that from memory. ({type(e).__name__})")
    text = got.text
    if got.ok and got.citations:
        text += "\n\nCited:\n" + "\n".join(f"  {r}" for r in got.references())
    return text


# ── reading aloud ────────────────────────────────────────────────────────────

def reading(tts) -> reader.Reading:
    """The one Reading, bound to the SERVER's TTSModule — see the module note."""
    global _reading
    with _lock:
        if _reading is None or _reading.speaker is not tts:
            c, _ix = store()
            _reading = reader.Reading(c, tts)
        return _reading


def is_reading(tts) -> bool:
    """Cheap by design: consulted on EVERY chat turn.

    Never constructs the Reading and never opens the store — if nothing has
    started a reading in this process the answer is no, and there is nothing to
    look up. Opening a corpus to discover that would put a database read on the
    hot path of every sentence anyone says to her.
    """
    r = _reading
    try:
        return bool(r is not None and r.speaker is tts and r.is_running())
    except Exception:
        return False


def start_reading(text: str, tts) -> str:
    """Resolve "read John 3" and start it. Returns what to say back."""
    try:
        c, _ix = store()
    except Exception:
        return "My library isn't open, so there's nothing for me to read from."
    r = reading(tts)
    if r.is_running():
        return "I'm already reading. Say stop and I'll put it down."
    res = reader.resolve(text, c, tts)
    if res.question:
        return res.question
    if not res.ok:
        return res.refusal
    if not tts.available():
        return "I've found it, but I've no voice to read it with."
    r.start(res.reference, from_unit=0)
    where = res.reference.spoken()
    edition = f", in the {res.note}" if res.note else ""
    return f"Reading {where}{edition}. Say stop whenever you want me to put it down."


def resume_reading(tts) -> str:
    try:
        c, _ix = store()
    except Exception:
        return "My library isn't open."
    pos = reader.load_position(c)
    if not pos:
        return "I haven't got a reading to pick back up."
    r = reading(tts)
    if r.is_running():
        return "I'm already reading."
    row = c._db.execute("SELECT title FROM works WHERE id=?", (pos.work_id,)).fetchone()
    ref = reader.Reference(work_id=pos.work_id,
                           work_title=row[0] if row else pos.work_id,
                           book=pos.book, section=pos.section)
    r.start(ref, from_unit=pos.unit)
    return f"Picking up from {pos.spoken()}."


def stop_reading(tts) -> str:
    r = reading(tts)
    if not r.is_running():
        return "I wasn't reading."
    pos = r.stop()
    return (f"Stopped at {pos.spoken()}. Say keep reading and I'll go on."
            if pos else "Stopped.")


# ── status, for the panel/route ──────────────────────────────────────────────

def status(tts=None) -> dict:
    out: dict = {"debate": debate.enabled(), "reading": False, "position": None,
                 "indexed": 0, "eligible": 0, "works": 0, "passages": 0,
                 "continue_after_chapters": reader.continue_after_chapters()}
    try:
        c, ix = store()
        out.update(ix.stats())
        _h = index_health()
        out["unembedded"] = _h["unembedded"]      # Argus alarms on this
        out["index_ok"] = _h["ok"]
        out["index_reason"] = _h["reason"]
        row = c._db.execute(
            "SELECT count(*), coalesce(sum(passage_count),0) FROM works "
            "WHERE ingested=1").fetchone()
        out["works"], out["passages"] = row[0], row[1]
        pos = reader.load_position(c)
        out["position"] = pos.spoken() if pos else None
    except Exception as e:
        out["error"] = str(e)
    if tts is not None:
        out["reading"] = is_reading(tts)
    return out


__all__ = ["answer", "available", "index_health", "log_index_health",
           "UNINDEXED_LINE", "intent", "is_reading", "reading",
           "resume_reading", "start_reading", "status", "stop_reading",
           "store", "work_names"]
