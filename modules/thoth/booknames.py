"""
thoth.booknames — one spelling for a book, across every edition that holds it.

The sources disagree about how to write a numbered book:

    tanach.us   "Samuel I"      (Roman numeral, trailing)
    Sefaria     "I Samuel"      (Roman numeral, leading)
    eBible/WEB  "1 Samuel"      (Arabic numeral, leading)

All three mean the same book. Left alone, the store ends up holding "1 Samuel"
under the WEB and "I Samuel" under JPS 1917, and a lookup that resolves against
one silently misses the other — so "read 1 Samuel 3 in the JPS" returns nothing
and looks like a corpus gap rather than a spelling mismatch.

This is NOT the versification question. Astro's v1 ruling is that verse NUMBERS
are per-edition as printed and nothing reconciles them: the WLC really does have
a Numbers 25:19 that JPS prints as 26:1a, and that divergence is preserved. A
book's NAME is not a scholarly claim about the text, it is the key you look it up
by, and having two keys for one book is a bug in the index.

Canonical form: Arabic numeral, leading, single space. "1 Samuel".
"""
from __future__ import annotations

import re

_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}

# "I Samuel" / "II Kings" — Roman numeral leading.
_LEADING = re.compile(r"^(I{1,3}|IV|V)\s+(.+)$")
# "Samuel I" / "Chronicles II" — Roman numeral trailing.
_TRAILING = re.compile(r"^(.+?)\s+(I{1,3}|IV|V)$")
# "Samuel_1" / "Kings 2" — Arabic numeral trailing.
_TRAILING_ARABIC = re.compile(r"^(.+?)[ _](\d)$")


def normalize(name: str) -> str:
    """Return the canonical spelling of a book name.

    Idempotent: normalize(normalize(x)) == normalize(x), which matters because
    adapters may each call it and the WLC files already arrive part-normalised.
    """
    n = re.sub(r"\s+", " ", (name or "").replace("_", " ")).strip()
    if not n:
        return n

    m = _LEADING.match(n)
    if m:
        return f"{_ROMAN[m.group(1).lower()]} {m.group(2).strip()}"

    m = _TRAILING.match(n)
    if m:
        # Guard the real titles that simply END in a Roman-looking word. "Psalm
        # 151" is safe (digit), but a book called "... V" would be mangled, so
        # only fold when the stem is a known multi-part book.
        stem = m.group(1).strip()
        if stem.lower() in _MULTIPART:
            return f"{_ROMAN[m.group(2).lower()]} {stem}"

    m = _TRAILING_ARABIC.match(n)
    if m and m.group(1).strip().lower() in _MULTIPART:
        return f"{m.group(2)} {m.group(1).strip()}"

    return n


# Books that genuinely come in numbered parts. Used to avoid folding a title
# that merely ends in something that looks like a Roman numeral.
_MULTIPART = frozenset({
    "samuel", "kings", "chronicles", "esdras", "maccabees",
    "corinthians", "thessalonians", "timothy", "peter", "john",
})
