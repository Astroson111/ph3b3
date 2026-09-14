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
