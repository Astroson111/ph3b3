"""Kadmos file release — the door out.

A document had a door in and no door out: reading mode could be switched off, but
the document stayed staged server-side with its extracted text and would capture
the next turn again the moment the switch went back on.

These test the SOURCE of that capture — kadmos._pending — not the UI. The chip is
cosmetic; if _pending survives a release, the panel is a chip-less UI still
whispering the document into every turn, which is the bug.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

from kadmos_module import KadmosModule


@pytest.fixture
def kad():
    return KadmosModule()


def _stage(kad, sid="s1", doc_id="d1", name="brief.pdf"):
    """Stage a document and confirm it, i.e. the state a release has to clear."""
    kad.set_pending(sid, doc_id, name, "PDF", kind="pdf", size=1234, pages=3)
    kad.confirm(sid, lane="read")
    st = kad.get_pending(sid)
    st["full_text"] = "SECRET DOCUMENT BODY"
    st["rolling_summary"] = "a summary of the document"
    return st


# ── the capture condition ────────────────────────────────────────────────────

def test_capture_requires_both_reading_mode_and_a_document(kad):
    """server.py routes a turn to the document only when BOTH are true. Release
    works by removing the second, which is the half the user could not reach."""
    def captures(sid):
        return bool(kad.get_reading(sid).get("mode") and kad.get_pending(sid))

    _stage(kad, "s1")
    kad.set_reading("s1", True)
    assert captures("s1")

    kad.clear_pending("s1")
    assert not captures("s1"), "a released document must not capture the turn"


def test_reading_mode_alone_does_not_capture_after_release(kad):
    """The switch may stay on. With no document there is nothing to answer through,
    so the turn falls through to normal chat."""
    _stage(kad, "s1")
    kad.set_reading("s1", True)
    kad.clear_pending("s1")
    assert kad.get_reading("s1")["mode"] is True     # user's switch, untouched
    assert kad.get_pending("s1") is None


# ── what release must drop ───────────────────────────────────────────────────

def test_release_drops_extracted_text_and_summary(kad):
    """Acceptance 2(d): cached extraction is dropped from working state. The whole
    point — a chip-less UI that still holds full_text is the failure mode."""
    st = _stage(kad, "s1")
    assert st["full_text"]

    kad.clear_pending("s1")

    assert kad.get_pending("s1") is None
    fresh = kad.get_pending("s1")
    assert fresh is None or not fresh.get("full_text")


def test_release_is_idempotent(kad):
    """A double-click, or a stale chip against a server that already forgot,
    must be a no-op rather than an error."""
    _stage(kad, "s1")
    kad.clear_pending("s1")
    kad.clear_pending("s1")          # must not raise
    assert kad.get_pending("s1") is None


def test_release_of_nothing_is_harmless(kad):
    kad.clear_pending("never-loaded")
    assert kad.get_pending("never-loaded") is None


# ── isolation ────────────────────────────────────────────────────────────────

def test_release_is_scoped_to_its_session(kad):
    """Two sessions, one release. The other session keeps its document."""
    _stage(kad, "s1", "d1", "one.pdf")
    _stage(kad, "s2", "d2", "two.pdf")

    kad.clear_pending("s1")

    assert kad.get_pending("s1") is None
    assert kad.get_pending("s2") is not None
    assert kad.get_pending("s2")["filename"] == "two.pdf"


def test_no_bleed_from_released_document_to_the_next_one(kad):
    """Acceptance 4: load → release → load a different file → the new document is
    the only one present, carrying none of the old one's extraction."""
    _stage(kad, "s1", "d1", "old.pdf")
    kad.clear_pending("s1")

    kad.set_pending("s1", "d2", "new.pdf", "PDF", kind="pdf")
    st = kad.get_pending("s1")

    assert st["filename"] == "new.pdf"
    assert st["doc_id"] == "d2"
    assert not st.get("full_text"), "the new document must start with no extraction"
    assert not st.get("rolling_summary")
    assert st["confirmed"] is False, "a fresh document re-enters the confirmation gate"


# ── the keep-it path is unchanged (acceptance 5) ─────────────────────────────

def test_not_releasing_changes_nothing(kad):
    """Release is opt-in. A session that never dismisses behaves exactly as before."""
    st = _stage(kad, "s1")
    kad.set_reading("s1", True)

    assert kad.get_pending("s1") is st
    assert st["confirmed"] is True
    assert st["full_text"] == "SECRET DOCUMENT BODY"
    assert kad.get_reading("s1")["mode"] is True
