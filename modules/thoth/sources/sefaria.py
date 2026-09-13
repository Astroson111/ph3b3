"""
thoth.sources.sefaria — pull the JPS 1917 Tanakh from Sefaria's v3 text API.

── THE VERSION TRAP, AND WHY parse() REFUSES ────────────────────────────────
Sefaria hosts several JPS editions under similar names. Exactly one of them is
the 1917 translation this corpus wants, and exactly one is public domain:

    The Holy Scriptures: A New Translation (JPS 1917)   Public Domain   ← this
    Tanakh: The Holy Scriptures, published by JPS       CC-BY-NC
    THE JPS TANAKH: Gender-Sensitive Edition            CC-BY-NC

The older /api/texts/ endpoint accepts a `version=` parameter and then IGNORES
it, returning whichever edition is default. Asking it for JPS 1917 during Phase
1 returned the Gender-Sensitive Edition — different words, different century,
and a non-commercial licence — with a 200 and no warning. Ingesting that would
have written a CC-BY-NC text into the corpus under a "public domain, 1917"
provenance record: a licensing error and a false citation in one step.

Two defences, both required:
  1. Use /api/v3/texts/ with `version=english|<exact title>`, which honours it.
  2. parse() checks the versionTitle that came BACK and raises if it is not the
     one asked for. A silent substitution upstream then fails the ingest loudly
     instead of quietly changing what the library holds.

── FOOTNOTES ────────────────────────────────────────────────────────────────
Sefaria returns verse text as HTML. Footnotes ride inline:

    When God began to create<sup class="footnote-marker">a</sup>
    <i class="footnote"><b>When God began…</b>In contrast to others…</i> heaven

The <i class="footnote"> content is apparatus, not scripture, and is dropped
whole before any other tag stripping — the same rule the USFM adapter applies to
\\f notes, and for the same reason: it would otherwise be quoted verbatim under a
real address.
"""
from __future__ import annotations

import html
import re

from ..booknames import normalize as normalize_book

JPS_1917 = "The Holy Scriptures: A New Translation (JPS 1917)"

# Apparatus that must be removed with its content, before generic tag stripping.
_FOOTNOTE = re.compile(
    r"<i[^>]*class=[\"']?footnote[\"']?[^>]*>.*?</i>|"
    r"<sup[^>]*class=[\"']?footnote-marker[\"']?[^>]*>.*?</sup>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def clean_text(raw: str) -> str:
    """Strip Sefaria's inline HTML, dropping footnote apparatus entirely."""
    s = _FOOTNOTE.sub("", raw or "")
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_chapter(payload: dict, book: str, chapter: int,
                  expected_version: str = JPS_1917) -> list[tuple[str, int, int, str]]:
    """Turn one /api/v3/texts/ response into (book, chapter, verse, text) tuples.

    Raises ValueError if the response carries a different edition than the one
    requested — see the module note. This is the guard, not a sanity check.
    """
    versions = payload.get("versions") or []
    if not versions:
        raise ValueError(f"Sefaria returned no versions for {book} {chapter}")
    got = versions[0].get("versionTitle") or ""
    if got.strip() != expected_version.strip():
        raise ValueError(
            f"Sefaria served {got!r} when {expected_version!r} was requested "
            f"({book} {chapter}). Refusing: the provenance record in the manifest "
            f"would describe a different edition and licence than the stored text.")
    out: list[tuple[str, int, int, str]] = []
    book = normalize_book(book)     # "I Samuel" -> "1 Samuel"; see thoth.booknames
    for i, raw in enumerate(versions[0].get("text") or [], start=1):
        if isinstance(raw, list):          # nested verse fragments
            raw = " ".join(str(x) for x in raw)
        text = clean_text(str(raw))
        if text:
            out.append((book, chapter, i, text))
    return out
