"""
thoth.sources.wlc — parse the Westminster Leningrad Codex XML from tanach.us.

The Hebrew text of the Tanakh, pointed and accented, one XML file per book:

    <c n="1">
      <v n="1">
        <w>בְּרֵאשִׁ֖ית</w> <w>בָּרָ֣א</w> <w>אֱלֹהִ֑ים</w> …
      </v>

── KETIV AND QERE ───────────────────────────────────────────────────────────
Where the received text is written one way and read another, tanach.us gives
both as siblings inside the verse:

    <k>ויאמר</k>   the ketiv  — what is WRITTEN, unpointed
    <q>וָאֹמַ֣ר</q>   the qere  — what is READ, pointed

Thoth takes the qere. This edition is pointed and accented throughout, so the
ketiv is the odd one out typographically, and the qere is what a reader
following the text aloud actually says. The choice is recorded here because it
IS a choice: a concordance would want the ketiv, and swapping it later changes
what a stored address resolves to.

── MAQQEF ───────────────────────────────────────────────────────────────────
A word ending in maqqef (U+05BE, ־) is joined to the next with no space — it is
Hebrew's hyphen and the two words are one accentual unit. Joining them with a
space instead produces text that is subtly not what the codex prints.

── NOT SCRIPTURE, DROPPED ───────────────────────────────────────────────────
<samekh/> <pe/> <s/> <reversednun/>   scribal section and paragraph markers
<x>t</x>                              editorial codes

── THE .DH FILES ARE NOT A SECOND EDITION ───────────────────────────────────
The archive ships Genesis.DH.xml beside Genesis.xml for the five books of the
Torah. DH is Documentary Hypothesis source marking after Friedman — the same
Hebrew text annotated with J/E/P/D attributions. Ingesting both would file the
Torah twice under one work, so discover() skips them.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..booknames import normalize as normalize_book

MAQQEF = "־"

# Elements inside <v> that carry scripture text.
_TEXT_TAGS = ("w", "q")
# Elements inside <v> that must not: scribal markers and editorial codes. The
# ketiv is here because the qere is taken in its place — see the module note.
_DROP_TAGS = ("k", "x", "samekh", "pe", "s", "reversednun", "n")


def is_variant_file(filename: str) -> bool:
    """True for the Documentary-Hypothesis annotated duplicates and the index
    files, none of which are a distinct text."""
    base = filename.rsplit("/", 1)[-1]
    return ".DH." in base or base.startswith("Tanach")


def book_name(root: ET.Element, fallback: str) -> str:
    """The book's English name from the TEI header, put through the shared
    normaliser so 'Samuel I' here and 'I Samuel' from Sefaria land on one key."""
    name = ""
    for t in root.iter("title"):
        if t.get("level") == "a" and t.get("type") == "main" and (t.text or "").strip():
            name = t.text.strip()
            break
    if not name:
        name = fallback.rsplit("/", 1)[-1].removesuffix(".xml")
    return normalize_book(name)


def _verse_text(v: ET.Element) -> str:
    """Join a verse's word elements, honouring maqqef."""
    words: list[str] = []
    for el in v:
        if el.tag in _DROP_TAGS:
            continue
        if el.tag not in _TEXT_TAGS:
            continue
        w = "".join(el.itertext()).strip()
        if not w:
            continue
        if words and words[-1].endswith(MAQQEF):
            words[-1] = words[-1] + w      # maqqef binds; no space
        else:
            words.append(w)
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def parse(xml_text: str, fallback_name: str) -> tuple[str, list[tuple[str, int, int, str]]]:
    """Parse one WLC book. Returns (book_name, [(book, chapter, verse, text), …])."""
    root = ET.fromstring(xml_text)
    book = book_name(root, fallback_name)
    out: list[tuple[str, int, int, str]] = []
    for c in root.iter("c"):
        try:
            chapter = int(c.get("n", ""))
        except ValueError:
            continue
        for v in c.iter("v"):
            try:
                verse = int(v.get("n", ""))
            except ValueError:
                continue
            text = _verse_text(v)
            if text:
                out.append((book, chapter, verse, text))
    return book, out
