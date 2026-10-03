"""
thoth.intent — deciding when a turn belongs to the library.

Three questions, all tuned for PRECISION the way metis.is_search_intent is: a
false negative costs an ordinary chat answer, which is the status quo, while a
false positive hijacks a turn that had nothing to do with scripture.

── WHY FORCED ROUTING AND NOT A TOOL ────────────────────────────────────────
A tool she MAY call is a floor she may skip. If "what does Genesis say about the
flood" reaches the ordinary chat path, she answers it from her own weights and
the citation floor never runs — which is exactly the failure Rung 2 caught live
and exactly what the whole module exists to prevent.

So a scripture question is force-routed server-side, the way Metis force-routes
a search: the answer comes from retrieval and the floor, or it comes back as an
honest "I don't have that", never as a fluent recollection.

── THE PRICE, STATED ────────────────────────────────────────────────────────
Everything these patterns catch loses her conversational range on that turn. She
will not muse about scripture; she will answer from the corpus or say she cannot.
That is the trade the floor is worth, and it is the reason these patterns want a
NAMED scripture marker rather than a vibe. "The genesis of the problem", "I had a
revelation", "the gospel truth" and "read my email" must all fall through.
"""
from __future__ import annotations

import re

# An explicit marker that we are talking about a sacred text. Word-start matched,
# and deliberately not including bare book names — "Genesis" alone is a common
# English word in this house ("the genesis of the bug").
_CORPUS_MARKER = re.compile(
    r"\b(?:the\s+)?(?:bible|biblical|scripture|scriptures|scriptural|"
    r"qur'?an|quran|koran|tanakh|torah|talmud|apocrypha|deuterocanon\w*|"
    r"pentateuch|septuagint|vulgate|masoretic|"
    r"new\s+testament|old\s+testament|hebrew\s+bible|"
    r"gospels?|epistles?|psalter)\b", re.I)

# A chapter-and-verse address is itself a scripture marker: "John 3:16",
# "Genesis 6-9", "2 Esdras 3:9". Requires a capitalised book-shaped word so
# "meeting 3:15" and "a 2:1 ratio" do not qualify.
_ADDRESS = re.compile(
    r"\b(?:[1-4]\s+)?[A-Z][a-zA-Z']{2,}\s+\d{1,3}\s*:\s*\d{1,3}\b")

# Asking what a text SAYS, as opposed to mentioning it in passing.
_ASKS_WHAT_IT_SAYS = re.compile(
    r"\b(?:what|where|which|does|do|is|are|how)\b.{0,60}?"
    r"\b(?:say|says|said|tell|teach|teaches|mention|mentions|record|records|"
    r"describe|describes|call|calls|state|states|read|reads|verse|verses|"
    r"passage|passages|chapter|canon|canonical)\b", re.I)

_QUOTE_ME = re.compile(
    r"\b(?:quote|cite)\b.{0,40}\b(?:bible|scripture|qur'?an|quran|verse|passage|"
    r"gospel|torah|tanakh)\b|"
    r"\b(?:quote|cite)\s+(?:me\s+)?(?:[1-4]\s+)?[A-Z][a-zA-Z']{2,}\s+\d", re.I)

# Canon questions are Thoth's whether or not a text is named to say something.
_CANON_QUESTION = re.compile(
    r"\b(?:canon|canonical|canonicity|apocryphal|deuterocanonical)\b.{0,60}?"
    r"\b(?:is|was|why|which|who|receives?|received|include[ds]?|exclude[ds]?)\b|"
    r"\b(?:is|was|why|which|who)\b.{0,60}?"
    r"\b(?:canon|canonical|canonicity|apocryphal|deuterocanonical)\b", re.I)

# Reading aloud. "read me John 3" is the lane; "read my email" is not, so a
# scripture marker or an address-shaped tail is required.
_READ_VERB = re.compile(
    r"^\s*(?:please\s+|hey\s+|could\s+you\s+|can\s+you\s+|would\s+you\s+)*"
    r"(?:read|recite)\b", re.I)
_READ_TAIL = re.compile(
    r"\b(?:[1-4]\s+)?[A-Z][a-zA-Z']{2,}\s+\d{1,3}\b|"
    r"\b(?:sura|surah)\s+\d{1,3}\b|"
    r"\bchapters?\s+\d{1,3}\b", re.I)

_STOP_READING = re.compile(
    r"\b(?:stop|quit|cancel|enough|that'?s enough|halt|pause)\b"
    r"(?:\s+(?:the\s+)?(?:reading|read|it))?\b", re.I)
_READING_WORD = re.compile(r"\b(?:reading|read|chapter|verse)\b", re.I)

# "Go on" and "carry on" are ordinary conversation and must not be taken. Resume
# has to NAME the reading, or say where it left off.
_RESUME = re.compile(
    r"\b(?:keep|continue|resume|carry on|go on)\s+(?:the\s+)?read(?:ing)?\b|"
    r"\bpick\s+up\s+where\s+you\s+left\s+off\b|"
    r"\b(?:resume|continue)\s+(?:the\s+)?(?:chapter|passage|book)\b", re.I)


def is_read_intent(text: str) -> bool:
    """True for "read John 3" — a request to hear a passage aloud.

    Requires BOTH a reading verb at the front and something address-shaped after
    it, so "read my email" and "read that back to me" fall through to whatever
    else handles them.
    """
    t = (text or "").strip()
    if not _READ_VERB.match(t):
        return False
    return bool(_READ_TAIL.search(t) or _CORPUS_MARKER.search(t))


def is_stop_reading(text: str, reading: bool) -> bool:
    """True for "stop" while something is actually being read.

    Gated on a reading being in flight: a bare "stop" means something entirely
    different when nothing is playing, and stealing it would be worse than
    missing it.
    """
    if not reading:
        return False
    t = (text or "").strip()
    if not _STOP_READING.search(t):
        return False
    # A bare "stop"/"enough" counts while reading; anything longer must name the
    # reading. Three words was too loose — "stop the render" is a Morpheus
    # command and this lane has no business taking it.
    return len(t.split()) <= 2 or bool(_READING_WORD.search(t))


def is_resume_reading(text: str) -> bool:
    return bool(_RESUME.search((text or "").strip()))


def names_a_work(text: str, names) -> bool:
    """True if `text` names a book or work the corpus actually holds.

    `names` comes from the corpus rather than a list baked in here, so a work
    added to the manifest becomes recognisable without editing this file. It is
    also what keeps canon questions honest: "is that the canonical
    implementation?" says canonical and names nothing, so it is not ours.
    """
    if not names:
        return False
    low = f" {(text or '').casefold()} "
    return any(f" {n} " in low for n in names)


def is_scripture_intent(text: str, work_names=None) -> bool:
    """True if this turn should be answered FROM THE CORPUS, under the floor.

    Deliberately narrow. It wants a named scripture marker, a real
    chapter-and-verse address, or a named work — together with some sign the
    user is asking what a text says rather than using a word that happens to be
    biblical.

    `work_names` is the corpus's own book and work names, lowercased. Without it
    the canon branch cannot fire, because "canonical" on its own is a software
    word here as often as a scriptural one.
    """
    t = (text or "").strip()
    if not t or is_read_intent(t):
        return False
    if _QUOTE_ME.search(t):
        return True
    named = names_a_work(t, work_names)
    marked = bool(_CORPUS_MARKER.search(t)) or bool(_ADDRESS.search(t)) or named
    if not marked:
        return False
    # A canon question about a work we actually hold is Thoth's whole point —
    # the canonicity table exists to answer exactly that, and it needs no verse.
    if _CANON_QUESTION.search(t) and (named or _CORPUS_MARKER.search(t)):
        return True
    return bool(_ASKS_WHAT_IT_SAYS.search(t) or _ADDRESS.search(t))


# ── Two-tier read intent (2026-10-03) ────────────────────────────────────────
#
# is_read_intent() above requires a verb AND something address-shaped, so bare
# "read John" fell through entirely. That is safe and also useless: "read
# Genesis" is an obvious request and she ignored it.
#
# The problem is that scripture book names collide with ordinary English. "read
# Job" is a book; "read Job's offer letter" is a document. "read Numbers" is a
# book; "read the numbers" is a spreadsheet. A single rule cannot serve both, so
# there are two tiers and the tier is decided by the NAME, deterministically —
# never by the model, and never by how confident anything feels.
#
#   tier 1  unambiguous name  ->  "read Habakkuk" starts chapter 1
#   tier 2  collision name    ->  needs a chapter number, an explicit marker
#                                 ("gospel of", "book of", "surah"), or the
#                                 Thoth tab / debate mode already open.
#                                 Otherwise ONE fixed confirm line.
#
# COLLISIONS, derived from the 82 book names actually present in the ingested
# corpus and filtered by two tests: is the bare word a common English word, or a
# common modern given name? Either makes "read X" plausibly about something
# else in this house. Rare biblical names (Habakkuk, Zephaniah, Obadiah) are
# effectively unambiguous and stay in tier 1 — adding them would only buy
# confirm prompts nobody needs.
_COLLISION_COMMON_WORD = frozenset({
    "acts", "job", "judges", "numbers", "proverbs", "revelation",
    "wisdom", "lamentations",
})
# "kings" was in the Captain's candidate list and is NOT here: the corpus has
# "1 Kings" and "2 Kings" and no bare "Kings", so the name could never match and
# the entry was dead weight. A test asserts every collision name is really a
# book, which is what caught it. Same class, also absent on purpose: Samuel,
# Chronicles, Corinthians, Peter, Timothy, Thessalonians, Esdras, Maccabees —
# all numbered-only. Bare "read Samuel" therefore does nothing at all, which is
# a real gap and reported rather than guessed at.
_COLLISION_GIVEN_NAME = frozenset({
    "amos", "daniel", "esther", "ezra", "hosea", "james", "joel", "john",
    "jonah", "joshua", "jude", "luke", "mark", "micah", "ruth", "titus",
})
COLLISION_BOOKS = _COLLISION_COMMON_WORD | _COLLISION_GIVEN_NAME

_GOSPELS = frozenset({"matthew", "mark", "luke", "john"})

# Explicit markers: the speaker has already disambiguated, so no confirm.
# NO ordinals here. "first book"/"second book" used to be alternatives, which
# meant "the second book of Genesis" stripped to "Genesis" and read Genesis 1 —
# silently discarding the ordinal the speaker actually said. Ordinal phrases
# belong to _ORD_PHRASE alone, where a part the corpus does not have returns
# nothing instead of quietly reading something adjacent.
_BOOK_MARKER = re.compile(
    r"^(?:the\s+)?(?:gospel|book|epistle|letter)\s+"
    r"(?:of|according\s+to)\s+", re.I)
_SURAH_MARKER = re.compile(r"^(?:the\s+)?(?:sura|surah)\b", re.I)

# Filler between the verb and the name: "read me John", "read to me Genesis".
_READ_FILLER = re.compile(r"^(?:me|us|to\s+me|to\s+us|aloud|out\s+loud)\s+", re.I)

# A possessive immediately after the name means a person, not a book:
# "read John's message", "read Job's offer letter".
_POSSESSIVE = re.compile(r"^['’]s\b", re.I)

_CHAPTER_AFTER = re.compile(r"^(?:chapter\s+|ch\.?\s*)?(\d{1,3})\b", re.I)


def _corpus_book_names(books) -> list[str]:
    """Book names longest-first, so '1 John' wins over 'John'."""
    return sorted({(b or "").strip() for b in (books or []) if (b or "").strip()},
                  key=lambda s: (-len(s), s.lower()))


def confirm_line(book: str) -> str:
    """The ONE line she says when a collision name arrives bare.

    Two templates rather than one literal string: the Captain's example is
    "The Gospel of John?", which cannot be produced for Job by a single
    template. Both are fixed strings with the name substituted — no model
    involvement, so the question is always worded the same way.
    """
    if book.strip().lower() in _GOSPELS:
        return f"The Gospel of {book}?"
    return f"The Book of {book}?"


# ── numbered families, ordinals, and STT drift ───────────────────────────────
#
# "1 Kings" is a corpus book name and matches as itself. The problem is every
# OTHER way a person says it: "the first book of Kings", "first Kings", "I
# Kings", "the second epistle to the Corinthians". An ordinal phrase is a FULL
# marker — the speaker has already said which part — so it reads immediately and
# never asks.
#
# Nine families in the ingested corpus have no bare form at all (Kings, Samuel,
# Chronicles, Corinthians, Thessalonians, Timothy, Peter, Esdras, Maccabees), so
# bare "read Kings" cannot resolve to anything and gets a confirm listing the
# parts that exist. Maccabees has FOUR, not two — the confirm is built from the
# corpus, not from an assumption about pairs.
_ORDINALS = {
    "first": 1, "1st": 1, "one": 1, "1": 1, "i": 1,
    "second": 2, "2nd": 2, "two": 2, "2": 2, "ii": 2,
    "third": 3, "3rd": 3, "three": 3, "3": 3, "iii": 3,
    "fourth": 4, "4th": 4, "four": 4, "4": 4, "iv": 4,
}
_ORD_ALT = "|".join(sorted(map(re.escape, _ORDINALS), key=len, reverse=True))

# "book of", "letter of", "epistle to the" — the connective is optional-ish but
# the SHAPE is required, which is what keeps "the second book on my desk" out.
_ORD_PHRASE = re.compile(
    r"^(?:the\s+)?(?P<ord>" + _ORD_ALT + r")\s+"
    r"(?:(?:book|letter|epistle)\s+(?:of|to)\s+(?:the\s+)?)?"
    r"(?P<stem>[A-Za-z]+)\b", re.I)
# Bare "read from X" is the same request as "read X".
_FROM = re.compile(r"^from\s+", re.I)


def numbered_families(books) -> dict[str, list[int]]:
    """{stem: [parts]} for families with NO bare form in the corpus."""
    bare = {(b or "").strip().lower() for b in (books or [])}
    fam: dict[str, set[int]] = {}
    for b in (books or []):
        m = re.match(r"^([1-4])\s+(.+)$", (b or "").strip())
        if m:
            fam.setdefault(m.group(2), set()).add(int(m.group(1)))
    return {k: sorted(v) for k, v in fam.items() if k.lower() not in bare}


def _all_families(books) -> dict[str, list[int]]:
    """Every numbered family, bare form or not — "first epistle of John" must
    resolve to 1 John even though a bare "John" also exists (the Gospel)."""
    fam: dict[str, set[int]] = {}
    for b in (books or []):
        m = re.match(r"^([1-4])\s+(.+)$", (b or "").strip())
        if m:
            fam.setdefault(m.group(2), set()).add(int(m.group(1)))
    return {k: sorted(v) for k, v in fam.items()}


def _match_stem(word: str, families: dict) -> str | None:
    """Family stem for a word, tolerating STT singular drift.

    Whisper drops the plural on these constantly: "book of king", "the first
    chronicle", "second corinthian". Accepted ONLY here, inside an ordinal
    phrase, which is why "read the king's speech" can never reach it.
    """
    w = (word or "").strip().lower()
    for stem in families:
        sl = stem.lower()
        if w == sl or (sl.endswith("s") and w == sl[:-1]):
            return stem
    return None


def numbered_confirm_line(stem: str, parts: list[int]) -> str:
    """"1 Kings or 2 Kings?" — built from the parts the corpus actually has."""
    names = [f"{n} {stem}" for n in parts]
    if len(names) == 1:
        return f"{names[0]}?"
    return f"{', '.join(names[:-1])} or {names[-1]}?"


_ANSWER_ORD = re.compile(
    r"^(?:the\s+)?(?P<ord>" + _ORD_ALT + r")(?:\s+(?:one|book|letter|epistle))?[.!]?$",
    re.I)


def confirm_answer(text: str, pending: dict) -> str | None:
    """Resolve a reply to a confirm question into a book name, or None.

    pending is what read_request returned. A collision pending takes a bare yes;
    a numbered pending takes an ordinal ("the first one", "second", "2").
    """
    t = (text or "").strip()
    if not pending:
        return None
    if pending.get("parts"):
        m = _ANSWER_ORD.match(t)
        if not m:
            return None
        n = _ORDINALS.get(m.group("ord").lower())
        if n in pending["parts"]:
            return f"{n} {pending['stem']}"
        return None
    return pending.get("book")


def read_request(text: str, books=None, thoth_active: bool = False) -> dict | None:
    """Deterministic read request, or None.

    Returns {"book", "chapter", "confirm"}:
      confirm=False -> start reading now ("chapter" defaults to 1)
      confirm=True  -> ask confirm_line(book) first; a yes starts chapter 1
    """
    t = (text or "").strip()
    if not _READ_VERB.match(t):
        return None
    tail = _READ_VERB.sub("", t, count=1).strip()
    tail = _READ_FILLER.sub("", tail, count=1).strip()
    tail = _FROM.sub("", tail, count=1).strip()     # "read from X" == "read X"
    tail = _READ_FILLER.sub("", tail, count=1).strip()
    if not tail:
        return None

    # ORDINAL PHRASE = a full marker. Tried before anything else, because
    # "the first book of Kings" is unambiguous and must never ask.
    fams_all = _all_families(books)
    om = _ORD_PHRASE.match(tail)
    if om:
        stem = _match_stem(om.group("stem"), fams_all)
        if stem:
            n = _ORDINALS[om.group("ord").lower()]
            if n in fams_all[stem]:
                rest_o = tail[om.end():].strip()
                if not rest_o or re.match(r"^(?:aloud|out\s+loud|please|to\s+me|for\s+me)\b",
                                          rest_o, re.I):
                    return {"book": f"{n} {stem}", "chapter": 1, "confirm": False}
            # Named a part the corpus does not have ("third Kings").
            return None

    marked = False
    if _BOOK_MARKER.match(tail):
        tail = _BOOK_MARKER.sub("", tail, count=1).strip()
        marked = True
    elif _SURAH_MARKER.match(tail):
        return {"book": None, "chapter": None, "confirm": False, "surah": True}

    names = _corpus_book_names(books)
    low = tail.lower()
    hit = next((n for n in names if low.startswith(n.lower())), None)
    if not hit:
        # Numbered-only family named bare: "read Kings" cannot resolve, so ask
        # which part rather than silently doing nothing.
        fams = numbered_families(books)
        for stem, parts in fams.items():
            sl = stem.lower()
            if low == sl or low.startswith(sl + " "):
                rest_n = tail[len(stem):].strip()
                if rest_n and not re.match(r"^(?:aloud|out\s+loud|please|to\s+me|for\s+me)\b",
                                           rest_n, re.I):
                    return None             # "read Peter's text" / "read Kings Road"
                return {"book": None, "stem": stem, "parts": parts,
                        "chapter": 1, "confirm": True}
        return None

    rest = tail[len(hit):]
    # "John's message" is a person. Checked BEFORE anything else, because a
    # possessive is the one signal that reliably means "not the book".
    if _POSSESSIVE.match(rest):
        return None
    rest = rest.strip()

    m = _CHAPTER_AFTER.match(rest)
    chapter = int(m.group(1)) if m else None
    if chapter is not None:
        return {"book": hit, "chapter": chapter, "confirm": False}

    # Trailing words that are not a chapter mean this was not a bare book
    # reference at all ("read Acts of kindness aloud").
    if rest and not re.match(r"^(?:aloud|out\s+loud|please|to\s+me|for\s+me)\b", rest, re.I):
        return None

    if hit.lower() in COLLISION_BOOKS and not marked and not thoth_active:
        return {"book": hit, "chapter": 1, "confirm": True}
    return {"book": hit, "chapter": 1, "confirm": False}
