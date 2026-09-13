"""
Thoth Rung 1 — schema and source-adapter verify suite.

Fast and hermetic: no network, no ~/ph3b3_thoth, no model. Every adapter case
runs against an inline fixture, which is the point of keeping the adapters pure.

Run:  .venv/bin/python -m pytest tests/test_thoth_schema.py -v
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth.schema import (AddressScheme, BookCanonicity, CanonStatus,  # noqa: E402
                          Citation, Passage, Provenance, SourceSpec,
                          Translation, Work)
from thoth.sources import sefaria as sefaria_src  # noqa: E402
from thoth.sources import tanzil as tanzil_src    # noqa: E402
from thoth.sources import usfm as usfm_src        # noqa: E402
from thoth.sources import wlc as wlc_src          # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _prov(**kw):
    base = dict(license="public-domain", license_note="PD by age",
                completeness="complete", vendorable=True)
    base.update(kw)
    return Provenance(**base)


def _work(**kw):
    base = dict(
        id="test-work", title="A Work", tradition="Testing",
        language_of_origin="English",
        canonicity=(CanonStatus(tradition="Testers", status="canonical"),),
        provenance=_prov(),
        address=AddressScheme(section_label="chapter", unit_label="verse"),
        source=SourceSpec(url="https://example.invalid/x", adapter="usfm"),
    )
    base.update(kw)
    return Work(**base)


# ── canonicity is first-class ────────────────────────────────────────────────

def test_work_without_canonicity_is_refused():
    """Silence is not a position. A work that records no tradition's view does
    not load — this is the structural half of 'canon fields are first-class'."""
    with pytest.raises(ValueError, match="canonicity"):
        _work(canonicity=())


def test_non_canonical_with_a_note_is_a_valid_position():
    w = _work(canonicity=(CanonStatus(tradition="Babylonian religion",
                                      status="non-canonical",
                                      note="Liturgical, not scriptural."),))
    assert w.traditions_receiving() == ()
    assert w.canon_status_for("babylonian religion").status == "non-canonical"


def test_canon_status_lookup_is_case_insensitive_and_absence_is_not_denial():
    w = _work(canonicity=(CanonStatus(tradition="Ethiopian Orthodox Tewahedo Church",
                                      status="canonical"),))
    assert w.canon_status_for("ETHIOPIAN ORTHODOX TEWAHEDO CHURCH").status == "canonical"
    # Unrecorded must be None, never a fabricated "not canonical".
    assert w.canon_status_for("Church of Nowhere") is None


def test_book_canonicity_overrides_the_work_default():
    """One edition, several canons: the WEB ships Genesis and 4 Maccabees."""
    w = _work(
        canonicity=(CanonStatus(tradition="Protestant Christianity", status="apocryphal"),
                    CanonStatus(tradition="Catholic Church", status="deuterocanonical")),
        book_canonicity=(
            BookCanonicity(book="4 Maccabees", canonicity=(
                CanonStatus(tradition="Georgian Orthodox Church", status="canonical"),
                CanonStatus(tradition="Catholic Church", status="apocryphal"))),))
    assert w.canon_status_for("Catholic Church").status == "deuterocanonical"
    assert w.canon_status_for("Catholic Church", book="4 Maccabees").status == "apocryphal"
    assert w.canon_status_for("Georgian Orthodox Church", book="4 Maccabees").status == "canonical"
    # A book with no override inherits the work-level position.
    assert w.canon_status_for("Catholic Church", book="Tobit").status == "deuterocanonical"


def test_empty_book_override_is_refused():
    with pytest.raises(ValueError, match="omit the override"):
        BookCanonicity(book="Tobit", canonicity=())


def test_cited_by_records_the_receipt():
    w = _work(cited_by=(Citation(source="Jude 1:14-15", note="quotes 1 Enoch 1:9"),))
    assert w.cited_by[0].source == "Jude 1:14-15"


# ── declared gaps must explain themselves ────────────────────────────────────

def test_unretrievable_work_must_say_why():
    with pytest.raises(ValueError, match="retrievable"):
        _work(retrievable=False, retrievable_note="")
    ok = _work(retrievable=False, retrievable_note="English-only encoder; see Phase 0.")
    assert not ok.retrievable


def test_incomplete_provenance_must_say_what_is_missing():
    with pytest.raises(ValueError, match="completeness_note"):
        _prov(completeness="fragmentary", completeness_note="")
    assert _prov(completeness="fragmentary",
                 completeness_note="See Lambert & Millard 1969.")


def test_license_note_is_required():
    with pytest.raises(ValueError, match="license_note"):
        _prov(license_note="  ")


# ── addressing ───────────────────────────────────────────────────────────────

def test_address_formats_books_chapters_and_tablets():
    bible = AddressScheme(section_label="chapter", unit_label="verse")
    assert bible.format("John", 3, 16) == "John 3:16"
    quran = AddressScheme(section_label="sura", unit_label="aya", has_books=False)
    assert quran.format(None, 2, 255) == "2:255"
    tablet = AddressScheme(section_label="tablet", unit_label="line",
                           has_books=False, section_style="roman")
    assert tablet.format(None, 4, 87) == "IV:87"
    assert tablet.format(None, 11, 1) == "XI:1"


def test_passage_refuses_a_zero_address_or_empty_text():
    with pytest.raises(ValueError, match="1-based"):
        Passage(work_id="w", book=None, section=0, unit=1, text="x")
    with pytest.raises(ValueError, match="no text"):
        Passage(work_id="w", book=None, section=1, unit=1, text="   ")


def test_original_language_text_has_no_translation():
    hebrew = _work(translation=None, language_of_origin="Hebrew",
                   title="Westminster Leningrad Codex")
    assert hebrew.is_original_language()
    assert hebrew.edition_label() == "Hebrew, Westminster Leningrad Codex"
    english = _work(translation=Translation(translator="Pickthall", year=1930))
    assert not english.is_original_language()
    assert english.edition_label() == "Pickthall 1930"


def test_translation_year_is_sanity_bounded():
    with pytest.raises(ValueError, match="year"):
        Translation(translator="Nobody", year=99)


# ── the naming rule, enforced ────────────────────────────────────────────────

def test_bare_canon_never_appears_as_an_identifier_in_thoth():
    """'canon' means two other things in this codebase (shelf.py's shipped
    stories and canon.py's verbatim store) and shelf.py warns in writing against
    unifying them. Thoth says canonicity/canon_status. A naming rule nobody
    checks is a naming suggestion, so this greps the package.

    Prose in docstrings and comments may say the word — the ban is on
    IDENTIFIERS, which is what would actually collide.
    """
    bare = re.compile(r"\bcanon\b")
    offenders = []
    for path in sorted((REPO / "modules" / "thoth").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        # Strip docstrings and comments; what is left is code.
        code = re.sub(r'"""..*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*", "", code)
        for i, line in enumerate(code.splitlines(), start=1):
            if bare.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}: {line.strip()}")
    assert not offenders, (
        "bare `canon` used as an identifier in thoth/ — use canonicity or "
        "canon_status:\n" + "\n".join(offenders))


# ── USFM adapter ─────────────────────────────────────────────────────────────

USFM_FIXTURE = r"""\id GEN Test
\h Genesis
\toc2 Genesis
\mt1 Genesis
\c 1
\p
\v 1 \w In|strong="H8064"\w* \w the|strong="H1254"\w* beginning\f + \fr 1:1 \ft The Hebrew here is disputed.\f*, God created.
\v 2 The earth was formless\x + \xo 1:2 \xt Job 26:7 \x* and empty.
\s1 The First Day
\p
\v 3 God said, "Let there be light."
\c 2
\q1
\v 1 \wj Thus the heavens were finished\wj*, \add and\add* the earth.
"""


def test_usfm_drops_footnotes_and_crossrefs_from_verse_text():
    rows = usfm_src.parse(USFM_FIXTURE, "Genesis")
    by = {(c, v): t for _, c, v, t in rows}
    assert by[(1, 1)] == "In the beginning, God created."
    assert "disputed" not in by[(1, 1)]
    assert by[(1, 2)] == "The earth was formless and empty."
    assert "Job 26:7" not in by[(1, 2)]


def test_usfm_section_heading_does_not_leak_into_the_previous_verse():
    """\\s1 is editorial text printed BETWEEN verses. A naive 'accumulate until
    the next \\v' loop swallows it into verse 2 — the easiest way to silently
    corrupt this corpus, and one that verbatim quoting would then propagate."""
    rows = usfm_src.parse(USFM_FIXTURE, "Genesis")
    by = {(c, v): t for _, c, v, t in rows}
    assert "The First Day" not in by[(1, 2)]
    assert not any("The First Day" in t for _, _, _, t in rows)


def test_usfm_keeps_words_of_christ_and_supplied_words():
    rows = usfm_src.parse(USFM_FIXTURE, "Genesis")
    by = {(c, v): t for _, c, v, t in rows}
    assert by[(2, 1)] == "Thus the heavens were finished, and the earth."


def test_usfm_book_name_prefers_the_short_form():
    assert usfm_src.book_name(USFM_FIXTURE, "GEN") == "Genesis"


# ── WLC adapter ──────────────────────────────────────────────────────────────

WLC_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<Tanach><teiHeader><fileDesc><titleStmt>
  <title level="a" type="main">Samuel I</title>
</titleStmt></fileDesc></teiHeader><tanach><book>
<c n="1">
  <v n="1"><w>עַל־</w><w>פְּנֵ֣י</w><w>תְה֑וֹם</w><samekh/></v>
  <v n="2"><w>וַיֹּ֥אמֶר</w><k>ויאמר</k><q>וָאֹמַ֣ר</q><x>t</x><w>אֵלָ֔יו</w></v>
</c></book></tanach></Tanach>
"""


def test_wlc_joins_maqqef_without_a_space():
    _book, rows = wlc_src.parse(WLC_FIXTURE, "Samuel_1.xml")
    text = rows[0][3]
    assert text.startswith("עַל־פְּנֵ֣י"), text
    assert "עַל־ פְּנֵ֣י" not in text


def test_wlc_takes_the_qere_and_drops_the_ketiv_and_markers():
    _book, rows = wlc_src.parse(WLC_FIXTURE, "Samuel_1.xml")
    text = rows[1][3]
    assert "וָאֹמַ֣ר" in text          # qere — what is read
    assert "ויאמר" not in text        # ketiv — what is written
    assert "t" not in text            # <x> editorial code
    assert "samekh" not in text


def test_wlc_normalises_numbered_book_names():
    book, _rows = wlc_src.parse(WLC_FIXTURE, "Samuel_1.xml")
    assert book == "1 Samuel"


def test_wlc_skips_documentary_hypothesis_duplicates():
    """Genesis.DH.xml is the same Hebrew with J/E/P/D source marking. Ingesting
    it alongside Genesis.xml would file the Torah twice under one work."""
    assert wlc_src.is_variant_file("Books/Genesis.DH.xml")
    assert wlc_src.is_variant_file("Books/TanachIndex.xml")
    assert not wlc_src.is_variant_file("Books/Genesis.xml")


# ── Tanzil adapter ───────────────────────────────────────────────────────────

TANZIL_FIXTURE = """1|1|In the name of Allah, the Beneficent, the Merciful.
1|2|Praise be to Allah, Lord of the Worlds,
bad line without pipes
2|255|Allah! There is no God save Him.
#
#  Name: Pickthall
#  Last Update: September 4, 2010
# ------------------------------------
"""


def test_tanzil_parses_sura_aya_and_skips_the_comment_block():
    rows = tanzil_src.parse(TANZIL_FIXTURE)
    assert len(rows) == 3
    assert rows[0] == (None, 1, 1, "In the name of Allah, the Beneficent, the Merciful.")
    assert rows[2] == (None, 2, 255, "Allah! There is no God save Him.")


def test_tanzil_header_note_carries_provenance():
    note = tanzil_src.header_note(TANZIL_FIXTURE)
    assert "Pickthall" in note and "September 4, 2010" in note


# ── Sefaria adapter: the version-substitution guard ──────────────────────────

def test_sefaria_refuses_a_substituted_edition():
    """Sefaria's older endpoint accepts a version parameter and ignores it. Asking
    for JPS 1917 returned the CC-BY-NC Gender-Sensitive Edition with a 200 during
    Phase 1. Storing that under a 'public domain, 1917' provenance record would be
    both a licensing error and a false citation, so the adapter refuses."""
    payload = {"versions": [{"versionTitle": "THE JPS TANAKH: Gender-Sensitive Edition",
                             "text": ["When God began to create"]}]}
    with pytest.raises(ValueError, match="Refusing"):
        sefaria_src.parse_chapter(payload, "Genesis", 1)


def test_sefaria_accepts_the_requested_edition_and_strips_footnotes():
    payload = {"versions": [{
        "versionTitle": sefaria_src.JPS_1917,
        "text": ["In the beginning God created<sup class=\"footnote-marker\">a</sup>"
                 "<i class=\"footnote\"><b>created</b> Or 'began to create'.</i>"
                 " the heaven and the earth.",
                 "Now the earth was unformed and void."]}]}
    rows = sefaria_src.parse_chapter(payload, "Genesis", 1)
    assert rows[0] == ("Genesis", 1, 1,
                       "In the beginning God created the heaven and the earth.")
    assert "began to create" not in rows[0][3]
    assert rows[1][2] == 2


def test_sefaria_refuses_an_empty_response():
    with pytest.raises(ValueError, match="no versions"):
        sefaria_src.parse_chapter({"versions": []}, "Genesis", 1)


# ── book-name normalisation ──────────────────────────────────────────────────

def test_book_names_from_three_sources_land_on_one_key():
    """tanach.us says 'Samuel I', Sefaria says 'I Samuel', eBible says
    '1 Samuel'. Left alone the store holds one book under three keys and a
    lookup against one silently misses the others."""
    from thoth.booknames import normalize
    assert normalize("Samuel I") == "1 Samuel"
    assert normalize("I Samuel") == "1 Samuel"
    assert normalize("Samuel_1") == "1 Samuel"
    assert normalize("1 Samuel") == "1 Samuel"
    assert normalize("II Chronicles") == "2 Chronicles"
    assert normalize("III John") == "3 John"


def test_normalisation_is_idempotent():
    """Adapters may each call it, and the WLC names arrive part-normalised."""
    from thoth.booknames import normalize
    for name in ("I Samuel", "Samuel I", "Genesis", "Song of Songs",
                 "Psalm 151", "4 Maccabees", "Prayer of Manasses"):
        assert normalize(normalize(name)) == normalize(name)


def test_normalisation_leaves_ordinary_titles_alone():
    from thoth.booknames import normalize
    for name in ("Genesis", "Song of Songs", "Psalm 151", "Ecclesiastes",
                 "Wisdom", "Esther (Greek)"):
        assert normalize(name) == name
