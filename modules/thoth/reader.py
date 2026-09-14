"""
thoth.reader — "read John 3" out loud, on the Nyx speaker.

Two halves. RESOLUTION turns a spoken phrase into one address in one edition,
asking a single question when it genuinely cannot tell. READING walks the book
from there, synthesising ahead of playback and keeping a stop/resume marker at
verse granularity.

── ONE QUESTION, NOT A GUESS ────────────────────────────────────────────────
"John" names five books in this corpus: John, 1 John, 2 John, 3 John, and
Revelation, which the tradition calls the Revelation of John. Picking the Gospel
silently is right most of the time and wrong invisibly the rest, so an ambiguous
name asks — once, with the candidates listed. This is the same shape Astro chose
for versification divergence: a question the user can answer beats a table that
quietly picks for them.

The EDITION is not asked about. Genesis 1 exists in three works here, and making
someone choose between the World English Bible and JPS 1917 before hearing a
word is a worse experience than telling them which one they got. So the edition
is chosen by a stated preference order and ANNOUNCED aloud before the reading
starts. Naming one ("read Genesis 1 in the JPS") overrides it.

── SILENCE IS NOT AN ANSWER ─────────────────────────────────────────────────
The Westminster Leningrad Codex and the Tanzil Arabic are in this corpus and
Alba cannot pronounce either. `_strip_for_piper` drops every non-Latin codepoint,
so asking Piper for Hebrew returns an empty string and the lane would "read" a
chapter as nothing at all — the failure looks exactly like success. Speakability
is therefore checked BEFORE a reading starts, against the actual text, and an
unspeakable edition is refused out loud with the reason.

── THE SPEECH LOCK IS TAKEN PER UNIT, NEVER PER READING ─────────────────────
Astro's ruling. `TTSModule._speak_now` holds a module-wide lock for a whole
utterance, which is right for a reply and wrong for a chapter: a reading would
own the speaker for minutes and every other thing Phoebe says would queue behind
it. This lane takes the same lock around ONE synthesis unit at a time, so an
ordinary reply interleaves between verses after a second or two rather than
waiting for Leviticus to finish.

── IT KEEPS GOING, AND THAT IS THE POINT ────────────────────────────────────
"Read John 3" starts at chapter 3 and reads ON through the book, announcing each
chapter as it arrives. That follows from the brief asking for chapter
announcements at boundaries and a continue-prompt after four or five chapters:
both only mean something if the reading does not stop at one chapter.

It is worth knowing what that implies. "Read Psalm 117" — two verses — will run
on to Psalm 150 unless stopped, which is about an hour of speech, and Psalm 119
alone is 176 verses. Nothing is wrong when that happens. Stop it, or set a
chapter limit, or say the whole reference you want.

── WHY NOT PRE-RENDER ───────────────────────────────────────────────────────
A 200-character unit is roughly twelve seconds of speech, and twelve seconds of
22 kHz mono PCM is about half a megabyte. A chapter is tens of units and a book
is hundreds, so rendering ahead without a bound turns a reading into hundreds of
megabytes of audio nobody has heard yet.

The two pipelines therefore run at different depths. TEXT is fetched and packed
one chapter at a time, as the producer reaches it — a millisecond of SQL, so it
needs no buffer of its own and the next chapter is always ready before its first
unit is synthesised. AUDIO is queued four units ahead, which is about
three-quarters of a minute of speech: enough that playback never waits on Piper,
bounded enough that memory stays flat however long the reading runs.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from tts_chunker import pack_units

log = logging.getLogger("ph3b3.thoth.reader")

try:
    from paths import PH3B3_DATA
except ImportError:                               # tests / standalone
    from modules.paths import PH3B3_DATA

SETTING_PATH = Path(PH3B3_DATA) / "thoth_reader.json"

# Piper's comfort, measured: TTSModule uses 200 chars for its own speaker path
# because that synthesises in well under a second and plays for ~12 s, which
# keeps the pipeline full without making any single job long.
UNIT_MAX_CHARS = 200

# Delivery for a reading. Shelf's values, for the same reason: this is a work
# being read aloud, not a reply. Both change DELIVERY and never the text.
READ_PACE = 1.12          # Piper --length-scale; larger is slower
READ_SILENCE = 0.45       # seconds after each sentence

# The only buffer that needs a size. Text is fetched and packed one chapter at a
# time as the producer reaches it, which is a millisecond of SQL and needs no
# depth of its own; AUDIO is the expensive thing and this bounds it.
SYNTH_QUEUE_DEPTH = 4         # ~48 s of speech, ~2 MB of PCM in flight

# Preference order when the user does not name an edition. English translations
# first: the original-language texts cannot be spoken at all.
EDITION_PREFERENCE = ("web", "web-apocrypha", "jps1917",
                      "quran-pickthall", "quran-yusufali")

# Spoken names for editions a user is likely to ask for by shorthand.
_EDITION_ALIASES = {
    "web": "web", "world english bible": "web", "world english": "web",
    "jps": "jps1917", "jps1917": "jps1917", "jps 1917": "jps1917",
    "masoretic": "jps1917", "tanakh": "jps1917",
    "pickthall": "quran-pickthall", "yusuf ali": "quran-yusufali",
    "yusufali": "quran-yusufali",
    "hebrew": "wlc", "leningrad": "wlc", "wlc": "wlc",
    "arabic": "quran-ar", "tanzil": "quran-ar",
}

# Books a bare name should offer alongside the exact match. Revelation is here
# because the tradition names it for John and a person asking for "John" may
# well mean it — Astro's brief lists it among the things to disambiguate.
_ALSO_OFFER = {"john": ("1 John", "2 John", "3 John", "Revelation")}

_READ_VERB = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you\s+)?(?:read|recite|say|speak)"
    r"(?:\s+me)?(?:\s+out)?(?:\s+aloud)?(?:\s+from)?\s+", re.I)
_EDITION_IN = re.compile(r"\s+(?:in|from)\s+the\s+([A-Za-z0-9 ']+?)\s*$", re.I)
_TRAILING_NUM = re.compile(r"^(.*?)[\s:]*(\d{1,3})\s*$")
_LEADING_NUM_OF = re.compile(r"^(\d{1,3})\s+of\s+(.+)$", re.I)
_CHAPTER_WORD = re.compile(r"\bchapters?\b", re.I)
_SURA_WORD = re.compile(r"\b(?:sura|surah)\b", re.I)


# ── settings ─────────────────────────────────────────────────────────────────

def continue_after_chapters() -> int:
    """How many chapters to read before asking whether to go on. 0 = never ask.

    Default 0, per the brief: no "continue?" prompt unless it is configured.
    Fail-closed on a broken file means the DEFAULT behaviour, which here is not
    asking — a reading that stops to ask when it was told not to is the annoying
    failure, not the dangerous one.
    """
    try:
        n = int(json.loads(SETTING_PATH.read_text()).get("continue_after_chapters", 0))
        return max(0, min(50, n))
    except Exception:
        return 0


def set_continue_after_chapters(n: int) -> dict:
    SETTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    n = max(0, min(50, int(n)))
    SETTING_PATH.write_text(json.dumps({"continue_after_chapters": n}))
    return {"continue_after_chapters": n}


# ── resolution ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reference:
    work_id: str
    work_title: str
    book: str | None
    section: int

    def spoken(self) -> str:
        head = f"{self.book} " if self.book else ""
        return f"{head}chapter {self.section}"


@dataclass(frozen=True)
class Resolution:
    ok: bool
    reference: Reference | None = None
    question: str = ""              # the ONE disambiguating question
    options: tuple[str, ...] = ()
    refusal: str = ""               # spoken/printed reason; never silence
    note: str = ""                  # e.g. which edition was chosen for you


def _books_of(corpus) -> list[str]:
    return [r[0] for r in corpus._db.execute(
        "SELECT DISTINCT book FROM passages WHERE book <> '' ORDER BY book")]


def _works_holding(corpus, book: str | None, section: int) -> list[tuple[str, str]]:
    rows = corpus._db.execute(
        "SELECT DISTINCT p.work_id, w.title FROM passages p JOIN works w ON w.id=p.work_id "
        "WHERE p.book=? AND p.section=? ORDER BY p.work_id", (book or "", section))
    return [(r[0], r[1]) for r in rows]


def parse(text: str) -> tuple[str, int | None, str | None, bool]:
    """Split a request into (book_phrase, chapter, edition_hint, genre_named)."""
    s = _READ_VERB.sub("", (text or "").strip())
    edition = None
    m = _EDITION_IN.search(s)
    if m:
        edition = m.group(1).strip().casefold()
        s = s[:m.start()].strip()
    s = _CHAPTER_WORD.sub(" ", s)
    is_sura = bool(_SURA_WORD.search(s))
    s = _SURA_WORD.sub(" ", s)
    s = re.sub(r"^(?:the|a)\s+", "", s.strip(), flags=re.I)
    # "the Gospel of John" is a person being explicit, not ambiguous. Naming the
    # genre resolves the John family on its own, so record that it was named.
    s, named_genre = re.subn(r"^(?:gospel|book|epistle|letter)\s+of\s+", "", s,
                             flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,.:;")
    chapter = None
    # "chapter 4 of Psalms" — the number leads and the book follows. Natural to
    # say, and invisible to a trailing-number match.
    m = _LEADING_NUM_OF.match(s)
    if m:
        return (re.sub(r"^(?:the|a)\s+", "", m.group(2).strip(), flags=re.I),
                int(m.group(1)), edition, bool(named_genre))
    m = _TRAILING_NUM.match(s)
    if m:
        s, chapter = m.group(1).strip(" ,.:;"), int(m.group(2))
    if is_sura and not s:
        s = "__quran__"
    return s, chapter, edition, bool(named_genre)


def resolve(text: str, corpus, speaker=None) -> Resolution:
    """Turn "read John 3" into one address in one edition, or one question."""
    phrase, chapter, edition_hint, genre_named = parse(text)
    section = chapter or 1

    wanted_work = _EDITION_ALIASES.get(edition_hint or "", None)

    # Qur'an: no book level, addressed by sura.
    if phrase.casefold() in ("__quran__", "quran", "qur'an", "koran"):
        work = wanted_work or "quran-pickthall"
        return _finish(corpus, work, None, section, speaker,
                       note="" if wanted_work else "Pickthall's translation")

    if not phrase:
        return Resolution(ok=False, refusal="Tell me what to read — a book and a "
                                            "chapter, like 'read John 3'.")

    books = _books_of(corpus)
    folded = {b.casefold(): b for b in books}
    exact = folded.get(phrase.casefold())

    # Ambiguity by name: "John" is five books here.
    also = () if genre_named else _ALSO_OFFER.get(phrase.casefold(), ())
    candidates = ([exact] if exact else []) + [b for b in also if b in books]
    if not exact:
        loose = [b for b in books if phrase.casefold() in b.casefold()]
        candidates = loose or candidates
    candidates = list(dict.fromkeys(c for c in candidates if c))

    # A singular/plural near-miss is not a real ambiguity. "Psalm 23" pulled in
    # both "Psalms" and the apocryphal "Psalm 151" by substring, and asking
    # which one someone meant by "Psalm 23" is the machine being obtuse rather
    # than careful. Only the genuinely ambiguous names (the John family) ask.
    if len(candidates) > 1 and (genre_named or phrase.casefold() not in _ALSO_OFFER):
        near = [b for b in candidates
                if b.casefold() in (phrase.casefold(), phrase.casefold() + "s")]
        if len(near) == 1:
            candidates = near

    if not candidates:
        return Resolution(ok=False, refusal=(
            f"I don't have a book called \"{phrase}\". I can read from the Bible, "
            f"the Apocrypha, the Tanakh in JPS 1917, or the Qur'an."))
    if len(candidates) > 1:
        listed = ", ".join(candidates[:-1]) + f", or {candidates[-1]}"
        return Resolution(ok=False, options=tuple(candidates), question=(
            f"Which {phrase} did you mean — {listed}?"))

    return _finish(corpus, wanted_work, candidates[0], section, speaker)


def _finish(corpus, wanted_work, book, section, speaker, note: str = "") -> Resolution:
    holders = _works_holding(corpus, book, section)
    if not holders:
        where = f"{book} " if book else ""
        return Resolution(ok=False, refusal=(
            f"I don't have {where}chapter {section} — that chapter isn't in what I hold."))

    by_id = dict(holders)
    if wanted_work:
        if wanted_work not in by_id:
            return Resolution(ok=False, refusal=(
                f"I don't have that passage in that edition."))
        work_id = wanted_work
    else:
        work_id = next((w for w in EDITION_PREFERENCE if w in by_id), holders[0][0])
        if len(holders) > 1 and not note:
            note = by_id[work_id]

    ref = Reference(work_id=work_id, work_title=by_id[work_id], book=book,
                    section=section)

    # Speakability, checked against the real text before anything starts.
    if speaker is not None:
        sample = corpus._db.execute(
            "SELECT text FROM passages WHERE work_id=? AND book=? AND section=? "
            "ORDER BY unit LIMIT 1", (work_id, book or "", section)).fetchone()
        if sample and not speaker.can_speak(sample[0]):
            return Resolution(ok=False, refusal=(
                f"I can't read {by_id[work_id]} aloud — it's not in a script Alba "
                f"can pronounce, and I'd rather say so than play you silence. I can "
                f"show you the text, or read an English translation instead."))
    return Resolution(ok=True, reference=ref, note=note)


# ── position ─────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reading_position (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    work_id    TEXT NOT NULL,
    book       TEXT NOT NULL DEFAULT '',
    section    INTEGER NOT NULL,
    unit       INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Position:
    work_id: str
    book: str | None
    section: int
    unit: int

    def spoken(self) -> str:
        head = f"{self.book} " if self.book else ""
        return f"{head}{self.section}:{self.unit}"


def ensure_schema(corpus) -> None:
    corpus._db.executescript(_SCHEMA)
    corpus._db.commit()


def save_position(corpus, pos: Position) -> None:
    """Record the last verse actually SPOKEN. Written after playback, never
    after synthesis — resuming from a verse that was rendered but never heard
    would silently skip it."""
    ensure_schema(corpus)
    corpus._db.execute(
        "INSERT INTO reading_position (id, work_id, book, section, unit, updated_at) "
        "VALUES (1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET work_id=excluded.work_id, "
        "book=excluded.book, section=excluded.section, unit=excluded.unit, "
        "updated_at=excluded.updated_at",
        (pos.work_id, pos.book or "", pos.section, pos.unit, time.time()))
    corpus._db.commit()


def load_position(corpus) -> Position | None:
    ensure_schema(corpus)
    r = corpus._db.execute(
        "SELECT work_id, book, section, unit FROM reading_position WHERE id=1").fetchone()
    return Position(work_id=r[0], book=r[1] or None, section=r[2], unit=r[3]) if r else None


def clear_position(corpus) -> None:
    ensure_schema(corpus)
    corpus._db.execute("DELETE FROM reading_position WHERE id=1")
    corpus._db.commit()


# ── the reading ──────────────────────────────────────────────────────────────

@dataclass
class _Unit:
    """One synthesis unit: the text to speak and the verses it covers."""
    text: str
    section: int
    first_unit: int
    last_unit: int
    announcement: bool = False


def chapter_units(corpus, ref: Reference, section: int,
                  from_unit: int = 0) -> list[_Unit]:
    """Pack one chapter into synthesis units, verse boundaries respected.

    The atoms are VERSES and the packer is the shared one in tts_chunker, so the
    rule that packs a spoken reply packs a chapter too — and because that packer
    reports which atoms landed in each chunk, every unit knows the verses it
    covers and the position marker can stay at verse granularity.
    """
    rows = corpus._db.execute(
        "SELECT unit, text FROM passages WHERE work_id=? AND book=? AND section=? "
        "AND unit > ? ORDER BY unit",
        (ref.work_id, ref.book or "", section, from_unit)).fetchall()
    if not rows:
        return []
    verses = [r[1] for r in rows]
    numbers = [r[0] for r in rows]
    return [_Unit(text=chunk, section=section,
                  first_unit=numbers[a], last_unit=numbers[b])
            for chunk, a, b in pack_units(verses, UNIT_MAX_CHARS)]


def chapters_of(corpus, ref: Reference) -> list[int]:
    return [r[0] for r in corpus._db.execute(
        "SELECT DISTINCT section FROM passages WHERE work_id=? AND book=? "
        "ORDER BY section", (ref.work_id, ref.book or ""))]


class Reading:
    """One reading in flight. Start it, stop it, ask where it got to."""

    def __init__(self, corpus, speaker, on_event=None):
        self.corpus = corpus
        self.speaker = speaker
        self.on_event = on_event or (lambda kind, detail: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._position: Position | None = None
        self._lock = threading.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, ref: Reference, from_unit: int = 0, block: bool = False,
              continue_after: int | None = None) -> bool:
        """Begin reading. `continue_after` overrides the persisted setting for
        THIS reading only — a per-invocation choice should not quietly rewrite
        the configured default."""
        if self.is_running():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(ref, from_unit, continue_after), daemon=True,
            name="thoth-reader")
        self._thread.start()
        if block:
            self._thread.join()
        return True

    def stop(self, timeout: float = 5.0) -> Position | None:
        """Stop after the unit in flight. The marker is already saved per unit,
        so where it stops is where it resumes."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        return self.position()

    def position(self) -> Position | None:
        with self._lock:
            return self._position

    # ── the pipeline ─────────────────────────────────────────────────────────

    def _run(self, ref: Reference, from_unit: int,
             continue_after: int | None = None) -> None:
        sections = [s for s in chapters_of(self.corpus, ref) if s >= ref.section]
        if not sections:
            self.on_event("error", "nothing to read there")
            return

        q: queue.Queue = queue.Queue(maxsize=SYNTH_QUEUE_DEPTH)
        DONE = object()
        limit = (continue_after_chapters() if continue_after is None
                 else max(0, int(continue_after)))

        def producer() -> None:
            """Prepare text a couple of chapters ahead; synthesise a few units
            ahead. Two different depths, for two different costs — see the
            module note on why nothing pre-renders a book."""
            try:
                read_chapters = 0
                for idx, section in enumerate(sections):
                    if self._stop.is_set():
                        break
                    if limit and read_chapters >= limit:
                        q.put((_Unit(text=("That's %d chapters. Say 'keep reading' "
                                           "and I'll go on." % read_chapters),
                                     section=section, first_unit=0, last_unit=0,
                                     announcement=True), None))
                        break
                    start_at = from_unit if idx == 0 else 0
                    units = chapter_units(self.corpus, ref, section, start_at)
                    if not units:
                        continue
                    if start_at == 0:
                        units.insert(0, _Unit(text=f"Chapter {section}.",
                                              section=section, first_unit=0,
                                              last_unit=0, announcement=True))
                    for u in units:
                        if self._stop.is_set():
                            break
                        pcm = self.speaker.synth_pcm(
                            u.text, length_scale=READ_PACE,
                            sentence_silence=READ_SILENCE)
                        if not pcm:
                            # Never skip silently: a unit that will not speak is
                            # reported. This is the shape the whole lane guards
                            # against — a reading that produces nothing and looks
                            # like it worked.
                            self.on_event("unspoken", f"{section}:{u.first_unit}")
                            continue
                        while not self._stop.is_set():
                            try:
                                q.put((u, pcm), timeout=0.5)
                                break
                            except queue.Full:
                                continue
                    read_chapters += 1
            except Exception as e:                      # pragma: no cover
                log.exception("thoth reader: producer failed")
                self.on_event("error", str(e))
            finally:
                q.put(DONE)

        prod = threading.Thread(target=producer, daemon=True, name="thoth-synth")
        prod.start()
        self.on_event("start", f"{ref.spoken()} — {ref.work_title}")
        try:
            while True:
                item = q.get()
                if item is DONE:
                    break
                unit, pcm = item
                if self._stop.is_set():
                    break
                if pcm is None:                        # the continue prompt
                    pcm = self.speaker.synth_pcm(unit.text, length_scale=READ_PACE)
                    if not pcm:
                        continue
                # The lock is taken HERE, around one unit, and released before
                # the next. A reply Phoebe needs to make interleaves after a
                # second or two instead of waiting out the chapter.
                with self.speaker.speech_lock:
                    if self._stop.is_set():
                        break
                    self.speaker.play_pcm(pcm)
                if not unit.announcement:
                    pos = Position(work_id=ref.work_id, book=ref.book,
                                   section=unit.section, unit=unit.last_unit)
                    with self._lock:
                        self._position = pos
                    save_position(self.corpus, pos)     # after PLAYBACK, not synth
                    self.on_event("verse", pos.spoken())
        finally:
            self._stop.set()
            try:
                while q.get_nowait() is not DONE:
                    pass
            except queue.Empty:
                pass
            prod.join(timeout=2)
            self.on_event("stop", self.position().spoken() if self.position() else "")
