"""canon — the verbatim store for stories Ph3b3 wrote, and its lookup.

Two things this locks down. First that canon is REACHABLE: it was committed,
tested and imported by nothing, so the store worked perfectly and no
conversation could ever get at it — the same fault as the shelf's missing tool,
found by the same audit.

Second that the lookup cannot dead-end. Every failure names what does exist.

Write tests redirect CANON_DIR into tmp_path and pass deep=False. None of these
may touch ~/ph3b3_data/stories/canon — a test run must not file, alter or delete
a real story.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import canon  # noqa: E402


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(canon, "CANON_DIR", tmp_path / "canon")
    return tmp_path / "canon"


def _file(title, text="Once there was a garden, and it whispered."):
    return canon.save(title, text, deep=False)


# ── Reachability: the bug this file exists for ───────────────────────────────
def test_canon_is_imported_by_the_server():
    """It was orphaned — committed and tested, reachable by nothing."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "import canon" in src, "canon is unreachable at runtime again"


def test_chat_tools_exist_and_dispatch():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    for tool in ("file_story", "retell_story"):
        assert f'"name":"{tool}"' in src, f"{tool} is not registered as a tool"
        assert f'elif name == "{tool}"' in src, f"{tool} is declared but never dispatched"


def test_the_write_tool_runs_off_the_event_loop():
    """canon.save pays for a semantic floor pass — a model call. Awaiting it
    inline would stall the loop mid-turn."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread(_tool_file_story" in src


def test_the_filed_text_is_put_in_front_of_her():
    """Registering the tool was not enough — asked to retell Esmeralda's Garden
    she wrote a NEW story about the same character. A filed story coming back as
    a different story is the exact failure canon exists to prevent, so the text
    is injected rather than offered."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    start = src.index("async def _run_chat_pipeline(")
    body = src[start:src.index("async def ", start + 10)]
    assert "canon.resolve(user_msg)" in body, "the turn is never checked for a filed story"
    assert "canon.fenced(" in body, "the story is injected unfenced, or not at all"
    assert "canon.describe(" in body, "the filed inventory is never stated"
    assert "CANON_INLINE_MAX_WORDS" in body, "no size guard on the inline injection"


def test_only_one_story_is_inlined_per_turn():
    """A shelved work runs to 3,000 words and a filed one to 2,000. Injecting
    both would evict the history the context window was raised to protect."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "_story_inlined" in src
    assert "not _story_inlined" in src, "canon can inline on top of a shelved work"


def test_canon_inlines_lower_than_the_shelf():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert 'PH3B3_CANON_INLINE_MAX_WORDS", "2000"' in src
    assert 'PH3B3_SHELF_INLINE_MAX_WORDS", "3000"' in src


def test_free_retelling_is_still_permitted_when_inlined():
    """canon's rule is "store exact, speak freely" — the injection must not
    quietly turn a filed story into something she has to quote verbatim. What it
    forbids is inventing a different story, not paraphrasing this one."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("a story you ")
    window = src[i:i + 400]
    assert "your own" in window, "the injection removed free retelling"
    assert "quote exactly" not in window, "canon was pinned to verbatim like the shelf"


def test_the_real_filed_story_fits_under_the_cap():
    """If it did not fit, the injection would silently never fire for it."""
    s = canon.load("esmeraldas-garden")
    if s and s.get("ok"):
        assert len(s["text"].split()) <= 2000


# ── Verbatim storage ─────────────────────────────────────────────────────────
def test_stored_and_read_back_exactly(scratch):
    text = "Line one.\n\n   Indented line.\nAnd a last one."
    assert _file("Test Tale", text)["ok"]
    got = canon.load("test-tale")
    assert got["ok"] and got["text"] == text, "text was reflowed on the round trip"


def test_apostrophes_do_not_mint_a_second_file(scratch):
    """"Esmeralda's Garden" must slug to one name, or saving it twice leaves two
    files that drift apart."""
    assert canon.slugify("Esmeralda's Garden") == "esmeraldas-garden"
    assert canon.slugify("Esmeralda’s Garden") == "esmeraldas-garden"


# ── Lookup: fuzzy, and never a bare miss ─────────────────────────────────────
@pytest.mark.parametrize("q", [
    "Esmeralda's Garden", "esmeralda's garden", "ESMERALDA'S GARDEN",
    "the Esmeralda's Garden one", "esmeraldas garden",
])
def test_loose_titles_resolve(scratch, q):
    _file("Esmeralda's Garden")
    assert canon.resolve(q)["ok"], f"{q!r} did not resolve"


def test_unknown_name_returns_candidates(scratch):
    _file("Esmeralda's Garden")
    r = canon.resolve("a story about penguins")
    assert not r["ok"] and r["reason"] == "unknown"
    assert r["candidates"], "a miss returned no candidates — a dead-end lookup"


def test_empty_query_returns_candidates(scratch):
    _file("Esmeralda's Garden")
    r = canon.resolve("   ")
    assert not r["ok"] and r["candidates"]


def test_empty_store_says_so(scratch):
    r = canon.resolve("anything")
    assert not r["ok"] and r["reason"] == "empty" and r["candidates"] == []
    assert "haven't filed any" in canon.describe()


# ── The list is BOUNDED — canon grows, the shelf does not ────────────────────
def test_describe_truncates_and_counts_the_rest(scratch):
    for i in range(12):
        _file(f"Story Number {i}")
    d = canon.describe()
    assert d.count("“") == canon.DESCRIBE_MAX, "the list was not truncated"
    assert "and 4 more" in d, f"the remainder was not counted: {d}"


def test_resolve_caps_its_candidate_list(scratch):
    for i in range(12):
        _file(f"Story Number {i}")
    r = canon.resolve("nothing like this")
    assert len(r["candidates"]) == canon.DESCRIBE_MAX
    assert r["total"] == 12


# ── A refusal is not a miss ──────────────────────────────────────────────────
def test_a_floor_refusal_is_reported_as_itself(scratch, monkeypatch):
    """The story IS filed; the floor just will not replay it. Reporting that as
    'not found' would be a lie, and would send the user hunting for a title that
    is sitting right there."""
    _file("Ordinary Tale")
    monkeypatch.setattr(canon, "_floor_reason", lambda *a, **k: "minor-sexual")
    r = canon.resolve("Ordinary Tale")
    assert not r["ok"] and r["reason"] == "refused"
    assert r["detail"] == canon.REFUSAL_READ


# ── Path safety ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["../secrets", "../../etc/passwd", "/etc/passwd", "a/b", "..", ""])
def test_traversal_slugs_are_refused(scratch, bad):
    assert canon.load(bad) is None


# ── Fencing, and the difference from the shelf ───────────────────────────────
def test_retold_text_is_fenced_but_not_pinned_to_verbatim():
    """canon's premise is "store exact, speak freely": the original is safe on
    disk, so she may retell it in her own words. The shelf holds someone else's
    authored work and is the opposite case — that one must be quoted exactly."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    start = src.index("def _tool_retell_story(")
    body = src[start:src.index("def _tool_read_shelf_story(")]
    assert "canon.fenced(" in body, "canon text enters a prompt unfenced"
    assert "your own" in body, "the retell tool does not permit free retelling"
    assert "shelf.for_telling" not in body, "canon must not use the shelf's verbatim recital"
