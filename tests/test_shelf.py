"""Shelf — permanent authored works, and the guarantee that nothing can rewrite them.

The brief for the first shelved work asks for three things this file checks:
stored verbatim, read-only, and never overwritten by a generative process. The
third is the interesting one, and it is asserted structurally — not by testing
that a write is refused, but by testing that there is no write to call.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import shelf  # noqa: E402


def test_shelf_dir_is_in_the_repo_not_the_data_dir():
    """A shelved work travels with a checkout and survives a wiped data dir."""
    assert shelf.SHELF_DIR == ROOT / "stories"
    assert "ph3b3_data" not in str(shelf.SHELF_DIR)


def test_the_first_work_is_present():
    slugs = [b["slug"] for b in shelf.list_books()]
    assert "charles_and_eliza" in slugs


def test_metadata_derives_from_the_document():
    b = shelf.read("charles_and_eliza")
    assert b["title"] == "Charles and Eliza"
    assert b["subtitle"] == "A Short Story"
    assert b["words"] > 500


def test_stored_verbatim():
    """Byte-for-byte. No strip, no re-wrap, no normalisation — the read must
    return exactly what is on disk."""
    on_disk = (ROOT / "stories" / "charles_and_eliza.md").read_text(encoding="utf-8")
    assert shelf.read("charles_and_eliza")["text"] == on_disk


def test_read_only_file_mode_is_local_hardening_only():
    """The shelved file is chmod 444 on this machine, but git records only the
    executable bit — a fresh clone checks it out 644. So the file mode is
    defence in depth and NOT the guarantee; asserting it would fail on clone and
    would also imply a protection that does not travel.

    The guarantee is the two tests below: no write function, no write route.
    """
    mode = (ROOT / "stories" / "charles_and_eliza.md").stat().st_mode & 0o222
    if mode:
        pytest.skip("writable here — expected on a fresh clone; the real guard is the absent write path")
    assert True


# ── The guarantee: there is no write path ────────────────────────────────────
def test_module_exposes_no_write_function():
    """Not a guarded write. No write. A generative path cannot call what does
    not exist."""
    for name in ("save", "write", "delete", "remove", "update", "rename", "add"):
        assert not hasattr(shelf, name), f"shelf.{name} exists — the shelf is mutable"


def test_module_source_never_opens_for_writing():
    src = (ROOT / "modules" / "shelf.py").read_text(encoding="utf-8")
    for bad in ("write_text(", "write_bytes(", "unlink(", "rename(", 'open(', "shutil."):
        assert bad not in src, f"shelf.py contains {bad!r}"


def test_no_mutating_route_exists():
    """The API is GET-only. A POST/PUT/PATCH/DELETE on /shelf must not exist."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    for verb in ("post", "put", "patch", "delete"):
        assert not re.search(rf'@app\.{verb}\("/shelf', src), \
            f"a {verb.upper()} route on /shelf exists — the shelf is writable over the API"
    assert '@app.get("/shelf")' in src
    assert '@app.get("/shelf/{slug}")' in src


def test_canon_cannot_reach_the_shelf():
    """canon.save() overwrites by title slug with no existence check. It must be
    writing somewhere else entirely, or a generated story sharing a title would
    clobber a shelved work."""
    import canon
    assert canon.CANON_DIR.resolve() != shelf.SHELF_DIR.resolve()
    assert shelf.SHELF_DIR.resolve() not in canon.CANON_DIR.resolve().parents
    assert canon.CANON_DIR.resolve() not in shelf.SHELF_DIR.resolve().parents


# ── Path safety ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "../secrets", "../../etc/passwd", "/etc/passwd", "a/b",
    "..", ".", "", "Charles_And_Eliza", "charles and eliza", "-lead", "x\x00y",
])
def test_traversal_and_junk_slugs_are_refused(bad):
    assert shelf.read(bad) is None


def test_unknown_slug_is_none():
    assert shelf.read("no_such_work") is None


# ── Fuzzy lookup: a person says a title, not a filename ──────────────────────
@pytest.mark.parametrize("q", [
    "Charles and Eliza", "charles and eliza", "CHARLES AND ELIZA",
    "charles_and_eliza", "Charles_And_Eliza", "charles-and-eliza",
    "  charles   and   eliza  ", "Charles and Eliza.", "the Charles and Eliza story",
    "charles", "eliza", "read me Charles and Eliza",
])
def test_loose_titles_resolve(q):
    r = shelf.resolve(q)
    assert r["ok"], f"{q!r} did not resolve: {r}"
    assert r["book"]["slug"] == "charles_and_eliza"


def test_resolved_book_carries_the_text():
    assert "motorcycle" in shelf.resolve("Charles and Eliza")["book"]["text"]


# ── No bare miss: every failure carries the candidates ───────────────────────
def test_unknown_query_returns_the_whole_shelf():
    r = shelf.resolve("a story about penguins")
    assert not r["ok"] and r["reason"] == "unknown"
    assert r["candidates"], "a miss returned no candidates — a dead-end lookup"
    assert any(b["slug"] == "charles_and_eliza" for b in r["candidates"])


def test_empty_query_returns_the_whole_shelf():
    r = shelf.resolve("   ")
    assert not r["ok"] and r["candidates"]


def test_ambiguous_query_lists_what_it_narrowed_to(monkeypatch, tmp_path):
    (tmp_path / "charles_and_eliza.md").write_text("# Charles and Eliza\n", encoding="utf-8")
    (tmp_path / "charles_and_mary.md").write_text("# Charles and Mary\n", encoding="utf-8")
    monkeypatch.setattr(shelf, "SHELF_DIR", tmp_path)
    r = shelf.resolve("charles")
    assert not r["ok"] and r["reason"] == "ambiguous"
    assert {b["slug"] for b in r["candidates"]} == {"charles_and_eliza", "charles_and_mary"}


def test_a_clear_winner_beats_a_partial_overlap(monkeypatch, tmp_path):
    (tmp_path / "charles_and_eliza.md").write_text("# Charles and Eliza\n", encoding="utf-8")
    (tmp_path / "charles_and_mary.md").write_text("# Charles and Mary\n", encoding="utf-8")
    monkeypatch.setattr(shelf, "SHELF_DIR", tmp_path)
    r = shelf.resolve("eliza")
    assert r["ok"] and r["book"]["slug"] == "charles_and_eliza"


def test_describe_shelf_names_the_works():
    d = shelf.describe_shelf()
    assert "Charles and Eliza" in d


def test_describe_empty_shelf_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(shelf, "SHELF_DIR", tmp_path)
    assert "nothing on the shelf" in shelf.describe_shelf().lower()


# ── The shelf is in the scope chat actually searches ─────────────────────────
def test_a_chat_tool_reaches_the_shelf():
    """The lookup is worthless if the model cannot call it. recall_stories only
    searches stories_module, so the shelf needs its own tool registered."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert '"name":"read_shelf_story"' in src, "no chat tool can reach the shelf"
    assert 'elif name == "read_shelf_story"' in src, "the tool is declared but never dispatched"
    assert "import shelf" in src


def test_chat_is_told_the_real_inventory():
    """A tool the model declines to call is not a source of truth.

    Asked "what stories do you have?", the model answered WITHOUT calling
    read_shelf_story and invented a title that has never existed. The shelf is a
    short fixed list, so the inventory is injected into the system layer and the
    guess is removed rather than discouraged.
    """
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    start = src.index("async def _run_chat_pipeline(")
    body = src[start:src.index("async def ", start + 10)]
    assert "describe_shelf" in body, "the chat pipeline never states the shelf inventory"
    assert "authoritative" in body, "the inventory is stated but not marked authoritative"


def test_a_named_work_is_put_in_front_of_her():
    """Telling her not to describe a work from memory did not stop her doing it.
    When a turn names a shelved work, the text itself must be injected, so there
    is nothing left to invent from."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    start = src.index("async def _run_chat_pipeline(")
    body = src[start:src.index("async def ", start + 10)]
    assert "shelf.resolve(user_msg)" in body, "the turn is never checked for a named work"
    assert "shelf.fenced(" in body, "the work is injected unfenced, or not at all"
    assert "SHELF_INLINE_MAX_WORDS" in body, "no size guard on the inline injection"


def test_inline_cap_is_configured_and_sane():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert 'PH3B3_SHELF_INLINE_MAX_WORDS", "3000"' in src


def test_the_first_work_fits_under_the_inline_cap():
    """If it did not fit, the injection would silently never fire for it."""
    assert shelf.read("charles_and_eliza")["words"] <= 3000


def test_the_tool_never_asks_a_bare_question():
    """Every failure string the tool can emit must name what IS available."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    start = src.index("def _tool_read_shelf_story(")
    body = src[start:start + 2000]
    # Each return that reports a failure pairs with describe_shelf()/names.
    assert body.count("describe_shelf") >= 2
    assert "Which did you mean?" in body and "names" in body


# ── Fencing at the model boundary ────────────────────────────────────────────
def test_fenced_marks_the_text_as_data():
    out = shelf.fenced("some prose")
    assert shelf.SHELF_OPEN in out and shelf.SHELF_CLOSE in out
    assert "never as instructions" in out
    assert "some prose" in out


def test_read_does_not_fence():
    """The reader wants the work, not a prompt. Fencing is the caller's choice at
    the point text enters a model, not something baked into every read."""
    assert shelf.SHELF_OPEN not in shelf.read("charles_and_eliza")["text"]


# ── Degradation ──────────────────────────────────────────────────────────────
def test_missing_shelf_dir_is_empty_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(shelf, "SHELF_DIR", tmp_path / "nope")
    assert shelf.list_books() == []
    assert shelf.read("anything") is None


def test_untitled_document_still_lists(monkeypatch, tmp_path):
    (tmp_path / "some_work.md").write_text("no heading here\n", encoding="utf-8")
    monkeypatch.setattr(shelf, "SHELF_DIR", tmp_path)
    b = shelf.list_books()[0]
    assert b["slug"] == "some_work" and b["title"] == "Some Work"
