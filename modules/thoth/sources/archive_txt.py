"""
archive.org _djvu.txt — OCR'd scans of printed books.

HOW THIS DIFFERS FROM THE OTHER ADAPTERS, and why it addresses coarsely.

USFM, Tanzil and Sefaria ship STRUCTURE: the verse boundaries are in the data,
so a verse address is a fact the source asserts. A djvu.txt has none of that. It
is one long stream of machine-read page images, and any chapter-and-verse
addressing derived from it would be this parser's guess dressed up as the
edition's own numbering — which is exactly the kind of confident wrongness the
citation floor exists to stop.

So passages here are addressed by PAGE and PARAGRAPH, which the scan can
actually support: archive.org's djvu text separates pages with a form feed or,
failing that, with the page-break markers the OCR leaves behind. An address like
"p. 438, para 2" is a smaller claim than "XIII.13", and it is a true one.

Where a work has real internal structure that survives OCR — Euclid's BOOK and
PROPOSITION headings, Agrippa's CHAPTER — that is captured as the `book` field
so retrieval can still say which book a passage sits in, while the numbers stay
honest about being page positions.
"""
from __future__ import annotations

import re

# The boilerplate Google and the Archive wrap around scans. Removing it is not
# editing the text: it was never part of the book.
_FRONT = re.compile(
    r"^.*?(?:About Google Book Search|this project is to make|"
    r"Google Book Search has digitized)[^\n]*\n", re.S | re.I)
_NOISE = (
    re.compile(r"Hosted by\s*(?:Google|the Internet Archive)[^\n]*", re.I),
    re.compile(r"Digitized by\s*(?:Google|VjOOQ|the Internet Archive)[^\n]*", re.I),
    re.compile(r"^\s*\d{1,4}\s*$", re.M),          # bare page numbers on their own line
    # The Google Books footer, which OCR renders a dozen different ways —
    # "qooqle", "gooole", "Coogle". Matched loosely because the point is the URL
    # shape, not the spelling of a word the scanner never read correctly.
    re.compile(r"\bat\s*j?https?\s*:\s*//\s*books\s*\.\s*\w+\s*\.\s*com/?", re.I),
    re.compile(r"https?\s*:\s*//\s*books\s*\.\s*\w+\s*\.\s*com\S*", re.I),
)

# KNOWN AND MEASURED LOSS. Ingesting a scan is lossy at the margins and this
# adapter does not pretend otherwise: on Mead's Hermetica, 4 of the 5 occurrences
# of "Poemandres" survive the parse. The fifth sits in a footnote that the page
# splitter merges away. That is the honest cost of turning a photograph into
# addressed passages, it is why every Rung 5 work is flagged text_source: ocr,
# and it is why fixtures assert a FLOOR ("at least N") rather than an exact
# count — an exact count would fail on a re-scan for no useful reason.

# Structure that survives OCR well enough to trust as a LABEL (not as numbering).
_BOOK = re.compile(r"^\s*BOOK\s+([IVXL]+|ONE|TWO|THREE|\d+)\b[.\s]*$", re.M | re.I)
_CHAP = re.compile(r"^\s*CHAPTER\s+([IVXL]+|\d+)\b[.\s]*$", re.M | re.I)

_PAGE_SPLIT = re.compile(r"\f|\n{3,}")


def clean_text(raw: str) -> str:
    """Strip scanner furniture. Never alters the book's own words."""
    t = raw.replace("\r\n", "\n")
    t = _FRONT.sub("", t, count=1)
    for pat in _NOISE:
        t = pat.sub("", t)
    return t


_WORD = re.compile(r"[A-Za-z]{2,}")


def _is_text(s: str) -> bool:
    """Keep a paragraph if it reads as language, drop it if it reads as noise.

    A flat length floor was the first attempt and it was too blunt in both
    directions: at 40 characters it discarded 2,653 fragments from Mead alone,
    nearly all of it genuine scanner debris — "at jhttp : //books . qooqle .
    com/", "nvnf", "X'dMXA^Autf" — but it also took short real lines with it,
    and a measured fixture caught one going missing.

    So the test is what the fragment IS rather than how long it is: enough real
    words, and mostly letters rather than symbols. Long fragments still pass on
    length alone, because a long line of garbage is rare and a long line of text
    is common.
    """
    if len(s) >= 40:
        return True
    words = _WORD.findall(s)
    if len(words) < 3:
        return False
    # Mostly letters and spaces? OCR debris is dense with punctuation and marks.
    letters = sum(c.isalpha() or c.isspace() for c in s)
    return letters / max(1, len(s)) >= 0.75


def _paras(page: str) -> list[str]:
    out = []
    for chunk in re.split(r"\n\s*\n", page):
        # Rejoin OCR's hard-wrapped lines, and heal end-of-line hyphenation,
        # which is a typesetting artifact rather than the author's spelling.
        s = re.sub(r"(\w)-\n(\w)", r"\1\2", chunk)
        s = " ".join(s.split())
        if _is_text(s):
            out.append(s)
    return out


def parse(raw: str, fallback_book: str = "") -> list[tuple[str, int, int, str]]:
    """-> [(book_label, page, paragraph, text)] in reading order."""
    text = clean_text(raw)
    rows: list[tuple[str, int, int, str]] = []
    label = fallback_book
    for page_no, page in enumerate(_PAGE_SPLIT.split(text), start=1):
        m = _BOOK.search(page)
        if m:
            label = f"Book {m.group(1).upper()}"
        else:
            c = _CHAP.search(page)
            if c and label:
                label = re.sub(r",? ch\. .*$", "", label) + f", ch. {c.group(1).upper()}"
        for i, para in enumerate(_paras(page), start=1):
            rows.append((label or fallback_book, page_no, i, para))
    return rows
