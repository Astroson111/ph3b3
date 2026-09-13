"""
thoth.sources.usfm — parse USFM scripture into addressed passages.

Used for the World English Bible (and its Apocrypha), which eBible.org ships as
one USFM file per book inside eng-web_usfm.zip.

── WHAT MUST NOT END UP IN A VERSE ──────────────────────────────────────────
This parser exists to produce text that Rung 2 can quote VERBATIM against an
address. That makes every stray character a correctness bug, not a cosmetic one:
a footnote spliced into John 3:16 becomes a fabricated citation the moment she
quotes it, and the citation floor cannot catch it because the corrupted text IS
what the store holds.

Three kinds of content sit inside a USFM verse and must be dropped whole:

  \\f + \\fr 1:1 \\ft The Hebrew word rendered "God" ... \\f*   translator footnote
  \\x + \\xo 3:16 \\xt John 1:1 \\x*                          cross-reference
  \\s1 The Creation                                       section heading

The first two are editorial apparatus printed at the foot of the page. The third
is an editorial heading printed BETWEEN verses and belongs to no verse at all —
and because it is a line of plain text sitting between \\v markers, a naive
"accumulate until the next \\v" loop swallows it into the preceding verse. It is
the easiest way to silently corrupt this corpus, so headings terminate the
current verse rather than extending it.

── WHAT MUST BE KEPT ────────────────────────────────────────────────────────
Character-level markup wraps real scripture text and only the MARKUP comes off:

  \\w created|strong="H1254"\\w*   →  created     (word with a Strong's number)
  \\wj Truly I say\\wj*            →  Truly I say (words of Christ)
  \\add of them\\add*              →  of them     (supplied for English sense)
  \\nd Lord\\nd*                   →  Lord        (divine name)

\\add is deliberately kept. The words are italicised in print because they have
no counterpart in the source language, but they are part of what this edition
prints at that address, and "as printed" is the versification rule Astro set.
"""
from __future__ import annotations

import re
import unicodedata

from ..booknames import normalize as normalize_book

# Footnotes and cross-references, including the nested \+xx forms that appear
# inside them. Non-greedy to the matching closer; DOTALL because either can wrap
# across lines in the eBible releases.
_NOTE = re.compile(r"\\(f|fe|x)\s.*?\\\1\*", re.S)

# \w gloss|strong="H1254" ... \w*  →  gloss.   The attribute list after '|' is
# metadata (Strong's numbers, lemmas) and is never printed.
_ATTRIB = re.compile(r"\\\+?(w|rb|fig)\s+([^|\\]*?)(?:\|[^\\]*?)?\\\+?\1\*")

# Any remaining paired character marker: keep the content, drop the wrapper.
_CHARPAIR = re.compile(r"\\\+?([a-z]{1,5}\d?)\s?(.*?)\\\+?\1\*", re.S)

# A leftover standalone marker (\p, \b, \qs …) with no closer.
_LONE = re.compile(r"\\\+?[a-z]{1,5}\d?\*?")

_VERSE = re.compile(r"\\v\s+(\d+)(?:[-–](\d+))?\s?(.*)", re.S)
_CHAPTER = re.compile(r"\\c\s+(\d+)")

# Markers whose line carries editorial text that belongs to NO verse. Hitting one
# closes the verse in progress; its own text is discarded.
_HEADING_MARKERS = frozenset({
    "s", "s1", "s2", "s3", "s4", "ms", "ms1", "ms2", "mr", "sr", "r",
    "d", "sp", "cl", "cp", "qa", "mt", "mt1", "mt2", "mt3", "mte",
    "h", "id", "ide", "toc1", "toc2", "toc3", "rem", "sts", "iex",
    "imt", "imt1", "is", "is1", "ip", "ipi", "im", "io", "io1", "io2",
})

# Markers that continue the verse in progress (poetry lines, paragraph breaks).
# Their own text, if any, is part of the current verse.
_CONTINUATION_MARKERS = frozenset({
    "p", "m", "pi", "pi1", "pi2", "pc", "pr", "q", "q1", "q2", "q3", "q4",
    "qc", "qr", "qm", "qm1", "qm2", "b", "nb", "li", "li1", "li2", "li3",
    "lh", "lf", "lim", "lim1", "tr", "th", "thr", "tc", "tcr", "cls", "po",
})


def clean_text(raw: str) -> str:
    """Strip USFM markup from a verse body, dropping apparatus and keeping text."""
    s = _NOTE.sub(" ", raw)
    # Attribute-bearing markers first: \w gloss|strong=... \w* must yield the
    # gloss, not the attribute list. Repeat because they nest.
    for _ in range(6):
        s, n = _ATTRIB.subn(r"\2", s)
        if not n:
            break
    for _ in range(6):
        s, n = _CHARPAIR.subn(r"\2", s)
        if not n:
            break
    s = _LONE.sub(" ", s)
    s = s.replace("|", " ")
    # NBSP and friends read as speech-relevant whitespace, not as characters.
    s = "".join(" " if unicodedata.category(c) == "Zs" else c for c in s)
    s = re.sub(r"\s+", " ", s)
    # A dropped note leaves its space behind: "beginning\f…\f*," becomes
    # "beginning ," once the note is gone. Close that up, or every verse with a
    # footnote before punctuation is stored one character off from what the
    # edition prints — and stored text is what verbatim quoting reproduces.
    s = re.sub(r"\s+([,.;:!?»”’)\]])", r"\1", s)
    s = re.sub(r"([(\[«“‘])\s+", r"\1", s)
    return s.strip()


def book_name(usfm: str, fallback: str) -> str:
    """The book's printed name: \\toc2 (short form) then \\h, else the fallback.

    \\toc2 is preferred over \\toc1 because \\toc1 is the long form ("The First
    Book of Moses, Commonly Called Genesis") and an address should read
    "Genesis 1:1".
    """
    for marker in ("toc2", "h", "toc1"):
        m = re.search(rf"\\{marker}\s+(.+)", usfm)
        if m:
            name = clean_text(m.group(1))
            if name:
                return normalize_book(name)
    return normalize_book(fallback)


def parse(usfm: str, book: str) -> list[tuple[str, int, int, str]]:
    """Parse one USFM book into (book, chapter, verse, text) tuples.

    A verse range marker (\\v 3-4) is stored under its FIRST number with the
    whole shared text, which is what the edition prints — there is no separate
    verse 4 on the page to address.
    """
    out: list[tuple[str, int, int, str]] = []
    chapter = 0
    verse = 0
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, verse
        if verse and buf:
            text = clean_text(" ".join(buf))
            if text:
                out.append((book, chapter, verse, text))
        buf = []
        verse = 0

    for line in usfm.splitlines():
        line = line.strip()
        if not line:
            continue

        if not line.startswith("\\"):
            # Bare continuation of the previous marker's text.
            if verse:
                buf.append(line)
            continue

        marker = re.match(r"\\\+?([a-z]{1,5}\d?)\*?", line)
        tag = marker.group(1) if marker else ""

        if tag == "c":
            flush()
            m = _CHAPTER.match(line)
            if m:
                chapter = int(m.group(1))
            continue

        if tag == "v":
            flush()
            m = _VERSE.match(line)
            if m:
                verse = int(m.group(1))
                buf = [m.group(3) or ""]
            continue

        if tag in _HEADING_MARKERS:
            # Editorial text belonging to no verse — close the verse, drop the line.
            flush()
            continue

        if tag in _CONTINUATION_MARKERS:
            if verse:
                buf.append(re.sub(r"^\\\+?[a-z]{1,5}\d?\*?\s?", "", line))
            continue

        # Unknown marker: treat as continuation rather than lose scripture, but
        # only while a verse is open. Outside a verse it is front matter.
        if verse:
            buf.append(line)

    flush()
    return out
