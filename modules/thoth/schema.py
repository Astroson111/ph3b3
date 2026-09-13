"""
thoth.schema — the data model for the comparative sacred-text library.

Every text Thoth holds is a WORK with an ADDRESSABLE body. This module defines
what a work must declare about itself before it is allowed into the corpus, and
the address shape that lets any passage be cited exactly.

── CANONICITY IS FIRST-CLASS, NOT A NOTE ────────────────────────────────────
The interesting fact about 1 Enoch is not its text; it is its record. Quoted as
prophecy in Jude, canonical in the Ethiopian Orthodox Tewahedo Church, cut from
every other biblical canon. A library that stores that as a prose remark cannot
answer "which traditions receive this" without a model reading a paragraph and
guessing.

So `canonicity` is a required, structured, non-empty tuple of CanonStatus rows,
one per tradition that has taken a position, and `cited_by` records who quotes
it. A Work that declares neither does not validate and never reaches the corpus.
This is enforced in __post_init__, not by convention.

── THE WORD "canon" IS BANNED IN THIS PACKAGE ───────────────────────────────
It already means two unrelated things elsewhere in Ph3b3 and shelf.py warns in
writing against unifying them:

    stories/canon/            (shelf.py)  free stories shipped with every install
    PH3B3_DATA/stories/canon/ (canon.py)  verbatim store for stories SHE wrote

Scriptural canonicity is a third, unrelated meaning. Introducing bare `canon`
here would collide with both. Thoth says `canonicity` and `canon_status` and
never the bare word — tests/test_thoth_schema.py greps the package to keep it
that way, because a naming rule nobody checks is a naming suggestion.

── VERSIFICATION IS PER-EDITION, AS PRINTED (v1) ────────────────────────────
There is no unified verse map. An address resolves to whatever THAT edition
prints at that number, and nothing here reconciles one edition's numbering with
another's. Hebrew and English Psalms are offset by the superscription, Joel runs
to three chapters in Christian Bibles and four in the Hebrew, and Quran verse
breaks differ between the Kufan and other counts.

Building a mapping table would mean choosing, silently and in advance, which
tradition's numbering is "really" right for every one of those. Astro's call for
v1 is that we do not: divergences are disambiguated by asking, at runtime, the
same way the reader lane asks whether "John" means the Gospel or an epistle. A
question the user can answer beats a table that quietly picks for them.

── RETRIEVABILITY IS DECLARED, NOT DISCOVERED ───────────────────────────────
all-MiniLM-L6-v2 is an English model. Measured on this machine, Hebrew and
Arabic tokenize to bare per-character subwords and cluster by SCRIPT rather than
meaning: English Genesis 1:1 scores 0.751 against an English paraphrase of
itself and 0.393 against the actual Hebrew of the same verse — barely above the
0.323 that Hebrew Genesis scores against an unrelated Arabic verse.

Retrieval over those texts would not fail loudly. It would return confident
nonsense. So a work carries `retrievable` explicitly with a `retrievable_note`
saying why, and the indexer honours it. The gap documents itself in the metadata
rather than living in someone's memory of a benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ── Vocabularies ─────────────────────────────────────────────────────────────
# Closed sets, deliberately. A free-text status field would collect "canonical",
# "Canonical", "canon" and "accepted" inside a month and no query could group
# them. Extending these is a code change with a test, which is the point.

CanonicityStatus = Literal[
    "canonical",        # received as scripture by this tradition
    "deuterocanonical",  # received, but as a second/later stratum
    "apocryphal",       # known and valued, explicitly outside the canon
    "excluded",         # considered and rejected
    "non-canonical",    # never a candidate; read as literature or liturgy
]

LicenseClass = Literal[
    "public-domain",          # PD by age or by dedication; vendorable
    "open-licensed",          # explicit open licence; vendorable, terms recorded
    "scholarly-restricted",   # readable and citable, NOT vendorable (e.g. ETCSL)
]

Completeness = Literal[
    "complete",      # the whole work as the tradition transmits it
    "partial",       # deliberate selection (ETCSL selections)
    "fragmentary",   # the source itself is broken; gaps are in the material
]


@dataclass(frozen=True)
class AddressScheme:
    """How a passage in this work is named.

    Two shapes cover everything in the v1 corpus and they differ only in labels
    and in whether a book level exists at all:

        book / chapter / verse   John 3:16          (Bible, multi-book)
        chapter / verse          Quran 2:255        (single-book, no book level)
        tablet / line            Enuma Elish IV:87  (Mesopotamian)

    Storing the LABELS rather than hardcoding "chapter" is what lets one citation
    formatter serve a Bible verse and a cuneiform tablet line without a special
    case at every call site.
    """
    section_label: str            # "chapter" | "tablet" | "sura" | "spell"
    unit_label: str               # "verse"   | "line"   | "aya"  | "utterance"
    has_books: bool = True        # False for single-book works (Quran, Gilgamesh)
    section_style: Literal["arabic", "roman"] = "arabic"   # IV:87 vs 4:87

    def format(self, book: str | None, section: int, unit: int) -> str:
        """Render a human/citable reference: 'John 3:16', 'Enuma Elish IV:87'."""
        sec = _roman(section) if self.section_style == "roman" else str(section)
        head = f"{book} " if (self.has_books and book) else ""
        return f"{head}{sec}:{unit}"


def _roman(n: int) -> str:
    """Roman numeral for tablet numbering. Tablets are cited I–XII by convention
    and an Arabic '4' in a cuneiform citation reads as an error to anyone who
    works with the material."""
    if not 0 < n < 4000:
        return str(n)
    vals = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
            (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
            (5, "V"), (4, "IV"), (1, "I"))
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


@dataclass(frozen=True)
class CanonStatus:
    """One tradition's position on one work.

    `tradition` is the body taking the position, which is NOT the same as the
    work's own tradition: 1 Enoch is a Jewish work whose canonicity rows are
    mostly Christian. Both are recorded, separately.
    """
    tradition: str
    status: CanonicityStatus
    note: str = ""

    def __post_init__(self) -> None:
        if not self.tradition.strip():
            raise ValueError("CanonStatus.tradition is required")


@dataclass(frozen=True)
class BookCanonicity:
    """A per-book override of a work's canonicity.

    Needed because a single EDITION can span several canons. The World English
    Bible ships Genesis and Tobit in one release under one licence: Genesis is
    canonical to every Christian tradition, Tobit is canonical to Rome and the
    Orthodox churches and apocryphal to Protestants, and 4 Maccabees is received
    only in the Georgian Orthodox canon. One canonicity list on the Work cannot
    say all three, and flattening them would make the field a lie about most of
    its own books.

    So the Work-level list is the DEFAULT position for its books, and these
    override it per book. Absence of an override means the default holds.
    """
    book: str
    canonicity: tuple[CanonStatus, ...]

    def __post_init__(self) -> None:
        if not self.book.strip():
            raise ValueError("BookCanonicity.book is required")
        if not self.canonicity:
            raise ValueError(
                f"BookCanonicity for {self.book!r} is empty — omit the override "
                "entirely to inherit the work's position, rather than declaring "
                "an override that says nothing.")


@dataclass(frozen=True)
class Citation:
    """A place where some other work quotes or names this one.

    This is the receipt behind a claim like "Enoch is quoted in the New
    Testament". `source` is an address in the CITING work, so the claim can be
    checked rather than asserted.
    """
    source: str                   # "Jude 1:14-15"
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("Citation.source is required")


@dataclass(frozen=True)
class Translation:
    """The translation this edition represents.

    None on a Work means the text IS in its original language (the Westminster
    Leningrad Codex is not a translation of anything), which is a meaningfully
    different thing from an unknown translator and is modelled as such.
    """
    translator: str
    year: int
    title: str = ""

    def __post_init__(self) -> None:
        if not self.translator.strip():
            raise ValueError("Translation.translator is required")
        if not 1400 <= self.year <= 2100:
            raise ValueError(f"Translation.year out of range: {self.year}")


@dataclass(frozen=True)
class Provenance:
    """Licence and completeness. Both are part of the metadata, not a README.

    `vendorable` is the operative field: it says whether the TEXT may be written
    into this repository. ETCSL is readable, citable and © Oxford — it is used
    locally and never vendored, so if the repo is ever made public there is no
    scramble to work out what has to come out. The flag decides at ingest time.
    """
    license: LicenseClass
    license_note: str
    completeness: Completeness
    vendorable: bool
    completeness_note: str = ""

    def __post_init__(self) -> None:
        if not self.license_note.strip():
            raise ValueError("Provenance.license_note is required "
                             "(name the dedication, licence or age basis)")
        if self.completeness != "complete" and not self.completeness_note.strip():
            raise ValueError("Provenance.completeness_note is required when the "
                             "text is not complete (say what is missing, and where "
                             "a fuller edition is)")


@dataclass(frozen=True)
class SourceSpec:
    """Where the text comes from and which adapter parses it.

    The corpus is re-downloadable bulk by design (Astro's call, Phase 0): it is
    excluded from Rhea's backup set the same way voices/ and the RecipeNLG
    dataset are. That is only a safe policy while this record is complete enough
    to fetch the whole corpus again from nothing, so `url` and `adapter` are
    required even for a work not yet ingested.
    """
    url: str
    adapter: str                  # dotted name under thoth.sources
    sha256: str = ""              # pinned once fetched; "" = not yet pinned
    note: str = ""
    # Which part of a multi-work source this entry takes. One archive can hold
    # two works: eng-web_usfm.zip ships the protocanon and the deuterocanon
    # together. Naming the subset here rather than inferring it from the work id
    # means renaming a work cannot silently change which books it ingests.
    subset: str = ""

    def __post_init__(self) -> None:
        if not self.url.strip():
            raise ValueError("SourceSpec.url is required")
        if not self.adapter.strip():
            raise ValueError("SourceSpec.adapter is required")


@dataclass(frozen=True)
class Work:
    """One text in the library, with everything that must be true to hold it.

    Validation is in __post_init__ so an under-declared work cannot exist even
    momentarily. The manifest loader builds these; if one raises, that work is
    rejected and named, and the rest of the corpus still loads (see corpus.py) —
    one bad entry must not take the library down, the same rule shelf.py applies
    to a broken pack manifest.
    """
    id: str                              # stable slug, used in addresses
    title: str
    tradition: str                       # the work's own tradition
    language_of_origin: str
    canonicity: tuple[CanonStatus, ...]
    provenance: Provenance
    address: AddressScheme
    source: SourceSpec
    translation: Translation | None = None    # None => original-language text
    book_canonicity: tuple[BookCanonicity, ...] = ()   # per-book overrides
    cited_by: tuple[Citation, ...] = ()
    retrievable: bool = True
    retrievable_note: str = ""
    # Standing scholarly caveat on this EDITION, carried with the text wherever it
    # is quoted. Budge's Egyptian translations are public domain and are the only
    # freely usable ones there are; they are also a century out of date and read
    # meanings later work does not support. A reader who is handed a Budge line
    # without that attached has been told something slightly false, so the caveat
    # is a field rather than a footnote in a README nobody reads.
    scholarship_note: str = ""
    ingested: bool = False               # flipped by ingest once the body lands
    ingest_note: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip() or " " in self.id:
            raise ValueError(f"Work.id must be a non-empty slug, got {self.id!r}")
        for f in ("title", "tradition", "language_of_origin"):
            if not getattr(self, f).strip():
                raise ValueError(f"Work.{f} is required (work {self.id!r})")
        # Canonicity is first-class: a work with no recorded position from any
        # tradition is not describable by this library and is refused outright.
        if not self.canonicity:
            raise ValueError(
                f"Work {self.id!r} declares no canonicity. Every work must record "
                "at least one tradition's position — 'non-canonical' with a note "
                "is a position; silence is not.")
        # A declared gap must say why, or it is indistinguishable from an oversight.
        if not self.retrievable and not self.retrievable_note.strip():
            raise ValueError(
                f"Work {self.id!r} is retrievable=False with no note. Say why it is "
                "out of the retrieval index so the gap documents itself.")

    # ── derived views ────────────────────────────────────────────────────────

    def canonicity_for_book(self, book: str | None) -> tuple[CanonStatus, ...]:
        """The canonicity list that governs `book` — its override if it has one,
        otherwise the work's default. Pass None for the work as a whole."""
        if book:
            b = book.strip().casefold()
            for bc in self.book_canonicity:
                if bc.book.casefold() == b:
                    return bc.canonicity
        return self.canonicity

    def canon_status_for(self, tradition: str,
                         book: str | None = None) -> CanonStatus | None:
        """Status in one named tradition, for one book or for the work, or None
        if unrecorded.

        None means "no position on record here", NOT "not canonical". The
        difference matters and callers must not collapse it.
        """
        t = tradition.strip().casefold()
        return next((c for c in self.canonicity_for_book(book)
                     if c.tradition.casefold() == t), None)

    def traditions_receiving(self, book: str | None = None) -> tuple[str, ...]:
        """Traditions that receive this work (or one book of it) as scripture at
        any stratum."""
        return tuple(c.tradition for c in self.canonicity_for_book(book)
                     if c.status in ("canonical", "deuterocanonical"))

    def is_original_language(self) -> bool:
        return self.translation is None

    def edition_label(self) -> str:
        """How this edition is named in a citation: 'Pickthall 1930', or the
        language for an original-language text ('Hebrew, Westminster Leningrad
        Codex')."""
        if self.translation is None:
            return f"{self.language_of_origin}, {self.title}"
        return f"{self.translation.translator} {self.translation.year}"


@dataclass(frozen=True)
class Passage:
    """One addressed unit of text — a verse, a tablet line.

    Verse-level granularity is the whole design. Rung 2's verbatim-or-silence
    rule can only be enforced against something that HAS an address, and Rung 4's
    stop/resume marker needs the same resolution. A passage without an address is
    not storable.
    """
    work_id: str
    book: str | None
    section: int
    unit: int
    text: str
    ordinal: int = 0        # global position within the work; set at ingest

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("Passage.work_id is required")
        if self.section < 1 or self.unit < 1:
            raise ValueError(
                f"Passage address must be 1-based, got {self.section}:{self.unit} "
                f"in {self.work_id!r}")
        if not self.text.strip():
            raise ValueError(
                f"Passage {self.work_id} {self.section}:{self.unit} has no text. "
                "An empty verse is a parser fault, not a valid row — storing it "
                "would let retrieval return a citation to nothing.")

    def ref(self, scheme: AddressScheme) -> str:
        return scheme.format(self.book, self.section, self.unit)


__all__ = [
    "AddressScheme", "CanonStatus", "BookCanonicity", "Citation", "Translation",
    "Provenance", "SourceSpec", "Work", "Passage",
    "CanonicityStatus", "LicenseClass", "Completeness",
]
