"""
thoth.sources.tanzil — parse Tanzil.net Quran text and translation files.

All three Quran texts in the v1 corpus arrive in the same pipe-delimited shape,
which is why one adapter serves the Arabic and both English translations:

    1|1|بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ
    1|1|In the name of Allah, the Beneficent, the Merciful.

sura | aya | text, one per line, followed by a trailing block of '#' comment
lines carrying the edition's own provenance (translator, last update, source).

── ADDRESSING ───────────────────────────────────────────────────────────────
Sura and aya map onto section and unit; there is no book level, so the address
scheme for these works sets has_books=False and a reference renders as "2:255".

Verse breaks follow the Kufan count that Tanzil publishes. Other counts exist
and divide some ayat differently. Per the v1 versification rule this is stored
as printed, with no attempt to reconcile it against another count.

── THE COMMENT BLOCK IS PROVENANCE, NOT TEXT ────────────────────────────────
The trailing '#' lines are the only machine-readable record of which revision of
a translation this is. parse() skips them for the body and header_note() returns
them, so ingest can pin the edition rather than silently accept whatever the URL
served that day.
"""
from __future__ import annotations

import re


def parse(text: str) -> list[tuple[None, int, int, str]]:
    """Parse pipe-delimited Quran text into (book=None, sura, aya, text) tuples.

    A malformed line is skipped rather than guessed at: a partial verse stored
    under a real address is worse than a missing one, because Rung 2 would quote
    it verbatim and cite it correctly.
    """
    out: list[tuple[None, int, int, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sura, aya, body = parts
        if not (sura.isdigit() and aya.isdigit()):
            continue
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            continue
        out.append((None, int(sura), int(aya), body))
    return out


def header_note(text: str) -> str:
    """The trailing '#' provenance block, comment markers stripped."""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
            if s and not set(s) <= {"-"}:
                lines.append(s)
    return " | ".join(lines)
