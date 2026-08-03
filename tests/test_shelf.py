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
