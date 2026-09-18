"""
Thoth Rung 5 — currents as first-class, and the stance floor.

TWO THINGS ARE NEW HERE AND NOTHING ELSE IS.

  currents   Canonicity asks "does this tradition receive this as scripture",
             which does not apply to esoterica — nobody canonises Agrippa. The
             question that does apply is which CURRENT reads a work and how
             central it is, and flattening that into one `tradition` string
             would state one reading and silently discard the rest.

  stance     Astro's ruling, 2026-09-18. Thoth's citation floor guards against
             INVENTING a passage. It cannot guard against faithfully quoting
             one that will be acted on, and this corpus is full of those.

Run:  .venv/bin/python -m pytest tests/test_thoth_rung5.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

from thoth import stance                                    # noqa: E402
from thoth.schema import CurrentPosition, Work              # noqa: E402


# ── currents ─────────────────────────────────────────────────────────────────

def test_a_current_position_is_shaped_like_a_canon_status():
    """Deliberately a PEER of canonicity, not a column on it — a work can carry
    both, and one table pretending to be the other loses a question."""
    c = CurrentPosition(current="Hermeticism", standing="foundational")
    assert c.current == "Hermeticism" and c.standing == "foundational"
    assert c.note == ""


def test_a_current_with_no_name_is_refused():
    with pytest.raises(ValueError) as e:
        CurrentPosition(current="   ", standing="received")
    assert "current is required" in str(e.value)


def test_the_standing_vocabulary_is_closed_and_means_something():
    from thoth import schema
    import typing
    vals = set(typing.get_args(schema.CurrentStanding))
    assert vals == {"foundational", "received", "formative", "contested", "rejected"}


def test_currents_are_stored_as_rows_not_as_prose():
    """The whole point of first-class: queryable, like canonicity. A note field
    holding 'foundational to Hermeticism, formative for the GD' is the failure."""
    src = (REPO / "modules" / "thoth" / "corpus.py").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS currents" in src
    assert "INSERT INTO currents" in src
    assert "DELETE FROM currents WHERE work_id=?" in src, \
        "the manifest must be the sole author of these rows, as it is for canonicity"


# ── the standing guard, generalised not weakened ─────────────────────────────

def _spec():
    from thoth.schema import Provenance, AddressScheme, SourceSpec
    return dict(
        provenance=Provenance(license="public-domain", license_note="PD by age.",
                              completeness="complete", vendorable=True),
        address=AddressScheme(section_label="chapter", unit_label="verse",
                              has_books=False),
        source=SourceSpec(url="https://example.org/x.txt", adapter="gutenberg"))


def test_a_work_with_currents_and_no_canonicity_is_legal():
    """Rung 5's whole shape. Padding Agrippa with a 'non-canonical' row to
    satisfy a scripture-shaped check would be noise dressed as data."""
    w = Work(id="agrippa", title="Three Books", tradition="Western esotericism",
             language_of_origin="Latin", canonicity=(),
             currents=(CurrentPosition(current="Hermeticism", standing="foundational"),),
             **_spec())
    assert w.currents and not w.canonicity


def test_a_work_with_neither_is_still_refused():
    """The guard was generalised, not removed. Silence about standing is still
    the thing it exists to prevent."""
    with pytest.raises(ValueError) as e:
        Work(id="mystery", title="?", tradition="?", language_of_origin="?",
             canonicity=(), currents=(), **_spec())
    msg = str(e.value)
    assert "neither canonicity nor currents" in msg
    assert "silence is not" in msg


def test_the_scriptural_works_still_require_canonicity_in_practice():
    """Rungs 1-4 are untouched: their manifest entries all carry canonicity, and
    a regression that dropped it would show up as an empty-standing work."""
    from thoth import corpus
    works, errs = corpus.load_manifest()
    assert works, "the live manifest stopped loading"
    for w in works:
        assert w.canonicity or w.currents, f"{w.id} states no standing at all"


# ── the stance ───────────────────────────────────────────────────────────────

CONTENT = [
    "What does Lilly say about horary charts?",
    "What did Paracelsus prescribe for melancholy?",
    "What is the Hermetic doctrine of correspondence?",
    "How does Agrippa classify the elements?",
    "What herbs does Culpeper list for fever?",
    "Which spirits does the Goetia name?",
    "What does the Sefer Yetzirah say about the 22 letters?",
    "Explain the Emerald Tablet.",
    "Should I read Agrippa or Barrett first?",
    "What does Blavatsky mean by the astral light?",
    "Tell me what Paracelsus says about fever.",
    "Show me the Tetrabiblos on Saturn.",
    "Describe the alchemical stages to me.",
    "What is the Theosophical view of reincarnation?",
    "When was the Corpus Hermeticum written?",
]

APPLIED = [
    ("What should I take for my depression?", "psychological"),
    ("Will I be rich?", "financial"),
    ("What does my chart say about my marriage?", "predictive"),
    ("Should I use mercury to treat my illness?", "medical"),
    ("Should I sign my contract on a Tuesday?", "legal"),
    ("What will happen to me this year?", "predictive"),
    ("Tell me what to do about my debt.", "financial"),
    ("What herb should I take for my fever?", "medical"),
    ("What lies ahead for me?", "predictive"),
    ("What does my horoscope say?", "predictive"),
    ("Will my marriage last?", "predictive"),
    ("Is my illness caused by Saturn?", "medical"),
    ("Should I sue my landlord?", "legal"),
    ("Can I cure my anxiety with this?", "medical"),
    ("Should I invest my money now?", "financial"),
]


@pytest.mark.parametrize("q", CONTENT)
def test_a_question_about_the_texts_is_answered(q):
    """The library has to be able to discuss its own subject matter. A floor
    that refuses 'what did Paracelsus prescribe' has eaten the corpus."""
    assert stance.check(q) is None, f"false refusal on a content question: {q!r}"


@pytest.mark.parametrize("q,category", APPLIED)
def test_a_question_seeking_guidance_is_refused_by_category(q, category):
    r = stance.check(q)
    assert r is not None, f"applied question passed: {q!r}"
    assert r.category == category, f"{q!r} -> {r.category}, expected {category}"


def test_the_refusal_admits_the_corpus_has_the_material():
    """'I don't know' would be a lie when the library plainly holds Paracelsus.
    The honest refusal is that it is held and will not be applied — which is
    also the only version a person can argue with."""
    line = stance.check("Should I use mercury to treat my illness?").line
    low = line.lower()
    assert "i have them" in low or "i do have" in low
    assert "medical advice" in low
    assert "won't" in low or "will not" in low
    for denial in ("i don't know", "i have no", "nothing about"):
        assert denial not in low, f"the refusal pretends ignorance: {denial!r}"


def test_the_refusal_offers_the_thing_it_will_do():
    line = stance.check("Will I be rich?").line.lower()
    assert "ask me what a tradition held" in line


def test_an_applied_question_dressed_as_a_content_question_is_still_refused():
    """The adversarial shape: name a source, then ask for advice anyway."""
    r = stance.check("What does the Goetia say I should do about my debt?")
    assert r is not None and r.category == "financial"


def test_the_stance_is_not_a_per_surface_setting():
    """The device lane reaches Dio and Iris, and a spoken answer carries no
    footnotes — a caveat nobody hears is not a caveat."""
    assert stance.applies_to("nyx") is True
    assert stance.applies_to("dio") is True
    assert stance.applies_to(None) is True
    # Checked as CODE, not as text. The module's own docstring warns against
    # adding a device exemption, and a grep reads that warning as the smell —
    # the same way the secrets tripwire fired on comments about tokens.
    import ast, io, tokenize
    src = (REPO / "modules" / "thoth" / "stance.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            b = getattr(n, "body", None)
            if (b and isinstance(b[0], ast.Expr)
                    and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                docs.add(id(b[0].value))
    # Any NAME or non-docstring string that offers a way out.
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) or isinstance(n, ast.Attribute):
            ident = (getattr(n, "id", "") or getattr(n, "attr", "")).lower()
            for smell in ("exempt", "bypass", "stance_off", "disable", "skip_stance"):
                assert smell not in ident, f"stance.py names a way out: {ident}"
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
              and id(n) not in docs):
            low = n.value.lower()
            for smell in ("exempt", "bypass", "stance_off"):
                assert smell not in low, f"stance.py encodes a way out: {n.value[:40]}"
    # And no branch on the device at all.
    assert "device ==" not in src.replace("# ", "")[:0] + "".join(
        ln for ln in src.splitlines(True) if not ln.lstrip().startswith("#"))


def test_the_stance_needs_no_gpu():
    """Deterministic and CPU-only on purpose: a floor that can fail closed
    because the card was busy produces false refusals, which is the failure the
    edit lane documents at length."""
    src = (REPO / "modules" / "thoth" / "stance.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            names = ([a.name for a in n.names] if isinstance(n, ast.Import)
                     else [n.module or ""])
            for nm in names:
                assert nm.split(".")[0] in ("re", "dataclasses", "__future__"), \
                    f"stance.py imports {nm} — it must stay dependency-free"


def test_empty_input_is_not_a_refusal():
    assert stance.check("") is None and stance.check("   ") is None


# ── what this library will not take from ─────────────────────────────────────
# Astro, 2026-09-18: "Lets not pirate anything over here. I want to run this as
# clean as I can." Written as a mechanism rather than a habit, because every
# failure it guards LOOKS correct at a glance — a plagiarised edition carries the
# right title, and a blocked host returns a plausible 403 a retry would paper over.

from thoth import source_policy as sp                        # noqa: E402


def test_a_host_that_blocks_automation_is_refused():
    """Sacred Texts 403s every path including its own scrape. subdomain. The
    refusal is about the block, not only the copyright: working around it is
    the part being refused."""
    with pytest.raises(sp.RefusedSource) as e:
        sp.check_source("https://sacred-texts.com/gno/th2/th206.htm")
    msg = str(e.value)
    assert "403" in msg and "spoofing a user agent" in msg


def test_subdomains_of_a_blocked_host_are_also_refused():
    """Their own scrape. subdomain 403s too, and a bare-hostname check would
    have let it through."""
    with pytest.raises(sp.RefusedSource):
        sp.check_source("https://scrape.sacred-texts.com/gno/th2/index.htm")


@pytest.mark.parametrize("url", [
    "https://www.gutenberg.org/ebooks/43548",
    "https://www.gutenberg.org/files/43548/43548-h/43548-h.htm",
    "https://www.gutenberg.org/cache/epub/43548/pg43548.txt",
])
def test_a_plagiarised_edition_is_refused_in_every_url_shape(url):
    """Keyed on the ebook NUMBER, because the title is exactly what makes it
    dangerous — it is shelved under the name of the author it took from."""
    with pytest.raises(sp.RefusedSource) as e:
        sp.check_source(url)
    assert "de Laurence" in str(e.value) and "Waite" in str(e.value)


def test_the_refusal_says_the_original_is_welcome():
    """Refusing the theft must not read as refusing the work. Waite's own
    Pictorial Key is public domain and wanted."""
    with pytest.raises(sp.RefusedSource) as e:
        sp.check_source("https://www.gutenberg.org/ebooks/43548")
    assert "public domain and welcome" in str(e.value)


def test_a_cleared_source_passes_and_is_recorded_as_read():
    url = "https://www.gutenberg.org/ebooks/70850.txt.utf-8"
    sp.check_source(url)                       # must not raise
    assert sp.cleared(url) is True
    assert "2026-09-18" in sp.CLEARED_HOSTS["gutenberg.org"], \
        "'we checked' should be a fact with a date, not an impression"


def test_an_unchecked_host_is_not_silently_treated_as_cleared():
    """Unlisted means nobody has read the terms yet — a prompt to go and read,
    not a verdict either way."""
    assert sp.cleared("https://example.org/whatever.txt") is False
    sp.check_source("https://example.org/whatever.txt")   # not blocked either


def test_the_policy_is_enforced_at_manifest_load_not_at_download():
    """By the time something is downloading it has already been treated as
    legitimate. The refusal has to happen before that."""
    src = (REPO / "modules" / "thoth" / "corpus.py").read_text(encoding="utf-8")
    assert "_check_source_policy" in src
    # It must run before the Work is built, not merely somewhere in the file.
    body = src[src.index("def _work_from_dict"):src.index("return Work(")]
    assert "_check_source_policy(d, wid)" in body, \
        "the source policy does not run while building the work"
    assert body.index("_check_source_policy") < body.index("Translation("), \
        "the source policy runs after other field parsing"


def test_a_refused_entry_is_rejected_by_the_loader_with_its_reason(tmp_path):
    from thoth import corpus
    y = tmp_path / "m.yaml"
    y.write_text('''works:
  - id: bad
    title: T
    tradition: X
    language_of_origin: English
    address: {section_label: c, unit_label: v, has_books: false}
    provenance: {license: public-domain, license_note: n, completeness: complete, vendorable: true}
    source: {url: "https://sacred-texts.com/x.htm", adapter: sacred_texts}
    currents: [{current: C, standing: received}]
''', encoding="utf-8")
    works, errs = corpus.load_manifest(y)
    assert works == [] and len(errs) == 1
    assert "sacred-texts.com" in str(errs[0][1])


def test_the_live_manifest_still_passes_the_policy():
    """Rungs 1-4 must not be caught by a guard added for Rung 5."""
    from thoth import corpus
    works, errs = corpus.load_manifest()
    assert len(works) == 15 and errs == []


# ── archive.org: cleared per host, checked per item ──────────────────────────
# Gutenberg curates — everything there is public domain, so the host check is
# the whole check. The Archive does not: in-copyright lending scans sit in the
# same shelf space as public-domain ones and look identical from the URL.

def test_archive_org_is_cleared_as_a_host_with_its_conditions_recorded():
    assert "archive.org" in sp.CLEARED_HOSTS
    note = sp.CLEARED_HOSTS["archive.org"]
    assert "2026-09-18" in note
    assert "robots.txt" in note
    assert "info@archive.org" in note
    assert "per-item" in note or "every item" in note, \
        "clearing the host must not read as clearing its contents"


def test_an_open_public_domain_item_passes():
    sp.archive_item_ok({"metadata": {
        "identifier": "thirteenbookseu02heibgoog",
        "possible-copyright-status": "NOT_IN_COPYRIGHT",
        "collection": ["americana"]}})


def test_a_lending_scan_is_refused_even_though_it_has_a_full_text_file():
    """THE TRAP. Both the 1908 original and the 2002 reprint list a
    <id>_djvu.txt derivative, so 'a full text file exists' is not the test — a
    scraper keying on the file pattern would take an in-copyright translation
    without noticing."""
    with pytest.raises(sp.RefusedSource) as e:
        sp.archive_item_ok({"metadata": {
            "identifier": "euclidselementsa0000eucl",
            "access-restricted-item": "true",
            "collection": ["internetarchivebooks", "printdisabled"]}})
    assert "access-restricted" in str(e.value)
    assert "_djvu.txt" in str(e.value), \
        "the refusal should name the thing that would have fooled us"


@pytest.mark.parametrize("collection", [
    "printdisabled", "inlibrary", "internetarchivebooks"])
def test_the_lending_shelves_are_refused(collection):
    with pytest.raises(sp.RefusedSource):
        sp.archive_item_ok({"metadata": {
            "identifier": "x", "collection": [collection],
            "possible-copyright-status": "NOT_IN_COPYRIGHT"}})


def test_an_item_stating_no_copyright_status_is_refused():
    """Silence is not permission. This is the default for a lot of uploads and
    it is exactly where a guess would go wrong."""
    with pytest.raises(sp.RefusedSource) as e:
        sp.archive_item_ok({"metadata": {"identifier": "m", "collection": ["texts"]}})
    assert "Silence is not permission" in str(e.value)


def test_an_in_copyright_item_is_refused():
    with pytest.raises(sp.RefusedSource) as e:
        sp.archive_item_ok({"metadata": {
            "identifier": "x", "collection": ["texts"],
            "possible-copyright-status": "COPYRIGHTED"}})
    assert "COPYRIGHTED" in str(e.value)


def test_a_single_string_collection_is_handled():
    """The metadata API returns a bare string when there is one collection."""
    with pytest.raises(sp.RefusedSource):
        sp.archive_item_ok({"metadata": {
            "identifier": "x", "collection": "printdisabled",
            "possible-copyright-status": "NOT_IN_COPYRIGHT"}})


def test_their_etiquette_is_numbers_a_client_can_honour():
    """A paragraph someone remembers reading is not a rate limit."""
    e = sp.ARCHIVE_ETIQUETTE
    assert e["concurrency"] == 1 and e["min_delay_s"] >= 1.0
    assert e["on_429"] == "stop", \
        "their guidance is 'don't just start again, reach out' — not back off and retry"
    assert e["contact"] == "info@archive.org"


# ── the partial-manifest guard ───────────────────────────────────────────────
# On 2026-09-18 an ingest script called sync_metadata() with only the 8 Rung 5
# works. That dropped 15 works and 103,156 passages — correct behaviour for a
# manifest that genuinely no longer lists them (Astro's 2026-09-13 ruling), and
# a disaster when the caller simply passed a subset. The two are
# indistinguishable from inside the method, so it now makes the caller say which.

def _tiny_work(wid):
    from thoth.schema import Work, Provenance, AddressScheme, SourceSpec, CurrentPosition
    return Work(id=wid, title=wid, tradition="T", language_of_origin="en",
                canonicity=(), currents=(CurrentPosition(current="C", standing="received"),),
                provenance=Provenance(license="public-domain", license_note="PD",
                                      completeness="complete", vendorable=True),
                address=AddressScheme(section_label="c", unit_label="v", has_books=False),
                source=SourceSpec(url="https://example.org/x", adapter="archive_txt"))


@pytest.fixture
def store(tmp_path, monkeypatch):
    from thoth import corpus as C
    monkeypatch.setattr(C, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(C, "THOTH_DATA", tmp_path)
    c = C.Corpus()
    c.sync_metadata([_tiny_work("a"), _tiny_work("b"), _tiny_work("c")],
                    allow_drop=True)
    return c


def test_a_partial_manifest_is_refused(store):
    with pytest.raises(ValueError) as e:
        store.sync_metadata([_tiny_work("a")])
    msg = str(e.value)
    assert "would drop 2 work(s)" in msg
    assert "b, c" in msg, "the refusal must name what it would have deleted"
    assert "allow_drop=True" in msg, "it must say how to do it on purpose"


def test_the_refusal_states_the_passage_cost_not_just_the_count(store):
    """Silent deletion that looks like success is the failure mode. The number
    of passages is the cost a person actually needs to see."""
    from thoth.schema import Passage
    store.replace_passages("b", [Passage(work_id="b", book=None, section=1,
                                         unit=i, text=f"line {i}", ordinal=i)
                                 for i in range(1, 51)])
    with pytest.raises(ValueError) as e:
        store.sync_metadata([_tiny_work("a")])
    assert "50 passages" in str(e.value)


def test_dropping_on_purpose_still_works(store):
    """The 2026-09-13 ruling is intact: a work removed from the manifest really
    is dropped. The guard asks for intent, it does not forbid the act."""
    n = store.sync_metadata([_tiny_work("a"), _tiny_work("b")], allow_drop=True)
    assert n == 2
    import sqlite3
    ids = {r[0] for r in store._db.execute("SELECT id FROM works")}
    assert ids == {"a", "b"}


def test_a_sync_that_drops_nothing_needs_no_permission(store):
    """The common case — re-syncing the same corpus, or adding to it — must not
    have to opt in, or the flag becomes something people paste in everywhere."""
    assert store.sync_metadata([_tiny_work("a"), _tiny_work("b"),
                                _tiny_work("c")]) == 3
    assert store.sync_metadata([_tiny_work("a"), _tiny_work("b"),
                                _tiny_work("c"), _tiny_work("d")]) == 4


def test_every_production_caller_passes_the_whole_corpus():
    """allow_drop=True is only correct where the caller has loaded the COMPLETE
    manifest. If a new caller appears that has not, this is the tripwire."""
    import re
    for mod in ("ingest.py", "__main__.py", "service.py"):
        src = (REPO / "modules" / "thoth" / mod).read_text(encoding="utf-8")
        for m in re.finditer(r"sync_metadata\([^)]*\)", src):
            call = m.group(0)
            if "allow_drop=True" in call:
                # must be justified in a comment on the same line
                line = src[src.rindex("\n", 0, m.start()) + 1:
                           src.index("\n", m.end())]
                assert "#" in line, f"{mod}: allow_drop=True with no justification"
