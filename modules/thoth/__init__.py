"""
thoth — Ph3b3's comparative sacred-text library.

Named for the Egyptian god of writing, measure and the adjudication of disputes,
which is the job: hold several traditions' scriptures at verse-level addresses,
say honestly what each tradition makes of each text, and never invent a citation.

Rung 1 (this): the corpus and its schema.
    schema.py   what a work must declare; the address and passage model
    corpus.py   the manifest loader and the sqlite passage store
    sources/    per-format adapters (usfm, wlc, tanzil, sefaria)
    ingest.py   fetch, parse, store

Later rungs build on the addresses this rung establishes:
    Rung 2  retrieval + the verbatim-or-silence citation floor
    Rung 3  debate mode
    Rung 4  the reader lane
"""
from .schema import (AddressScheme, BookCanonicity, CanonStatus, Citation,
                     Passage, Provenance, SourceSpec, Translation, Work)

__all__ = ["AddressScheme", "BookCanonicity", "CanonStatus", "Citation",
           "Passage", "Provenance", "SourceSpec", "Translation", "Work"]
