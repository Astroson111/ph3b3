"""Translation never leaves the machine (Captain's ruling, 2026-10-07).

WHY. translate_text used deep_translator's GoogleTranslator. After tool_groups
put it on every turn (2026-10-04), "say thank you for the support on TikTok"
called it five times, and skill_log.jsonl holds 43 calls with 35 HTTP-429
answers — text Google received — through 2026-10-07. The replacement is Argos,
and Argos is NOT offline by default: under strace its first translation reached
raw.githubusercontent.com and a CDN, because it builds stanza.Pipeline without
download_method=None. These tests pin both halves: no Google path exists, and
the Argos path cannot fetch.

No server import (that would load Whisper onto the card); the tool table is read
the way test_tool_exposure reads it.
"""
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "tests"))
import tool_groups as tg                                    # noqa: E402
from test_tool_exposure import _tools                       # noqa: E402

TM_SRC = (ROOT / "modules" / "translation_module.py").read_text(encoding="utf-8")
SERVER_SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Source with comment lines dropped — the history is told in comments."""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


# ── no Google path exists ────────────────────────────────────────────────────
@pytest.mark.parametrize("needle", ["deep_translator", "GoogleTranslator",
                                    "recognize_google", "speech_recognition",
                                    "translate.google", "googleapis"])
def test_translation_module_has_no_google_path(needle):
    assert needle not in _code(TM_SRC)


def test_translate_text_is_not_advertised():
    names = {t["function"]["name"] for t in _tools()}
    assert "translate_text" not in names
    assert "translate_offline" in names


def test_a_stale_translate_text_call_is_refused_without_calling_anything():
    i = SERVER_SRC.index('elif name == "translate_text":')
    branch = SERVER_SRC[i:SERVER_SRC.index("elif name ==", i + 10)]
    assert "translation." not in _code(branch)
    assert "removed" in branch


def test_translate_offline_is_one_shot():
    line = next(l for l in SERVER_SRC.splitlines() if l.startswith("ONE_SHOT_TOOLS"))
    assert '"translate_offline"' in line


# ── exposure: asked for, never ambient ───────────────────────────────────────
def test_translation_is_not_in_core():
    assert not {"translate_text", "translate_offline"} & tg.CORE


@pytest.mark.parametrize("text", [
    "translate thank you into Spanish",
    "how do you say good morning in French",
    "can you say that in Japanese?",
    "what's the translation of gracias",
])
def test_an_explicit_ask_loads_translation(text):
    assert "translate_offline" in tg.exposed_names(
        {t["function"]["name"] for t in _tools()}, text)


@pytest.mark.parametrize("text", [
    # The turn that sent text to Google.
    "Phoebe, can you say thank you for all the support on TikTok?",
    "say thank you to Ben Kenobi",
    "what makes a home feel like home?",
    "I translated that letter yesterday",          # narration, not a request
])
def test_ordinary_talk_does_not_load_translation(text):
    assert "translate_offline" not in tg.exposed_names(
        {t["function"]["name"] for t in _tools()}, text)


# ── the Argos path cannot fetch ──────────────────────────────────────────────
def test_stanza_pipelines_are_pinned_offline():
    import translation_module  # noqa: F401  — the import installs the pin
    stanza = pytest.importorskip("stanza")
    assert getattr(stanza.Pipeline, "_ph3b3_offline", False)
    # Run the override's __init__ against a stubbed parent, so no real pipeline
    # (and no download attempt) is ever built by this test.
    parent = stanza.Pipeline.__mro__[1]
    seen = {}
    orig = parent.__init__
    try:
        parent.__init__ = lambda self, *a, **kw: seen.update(kw)
        stanza.Pipeline(lang="es", download_method="DOWNLOAD_RESOURCES")
    finally:
        parent.__init__ = orig
    assert "download_method" in seen and seen["download_method"] is None


def test_the_local_splitter_reaches_through_cache_and_pivot():
    import translation_module as tm
    leaf1 = types.SimpleNamespace(sentencizer="stanza")
    leaf2 = types.SimpleNamespace(sentencizer="stanza")
    pivot = types.SimpleNamespace(t1=leaf1, t2=leaf2)
    cached = types.SimpleNamespace(underlying=pivot)
    tm._pin_local_splitter(cached)
    assert isinstance(leaf1.sentencizer, tm._LocalSplitter)
    assert isinstance(leaf2.sentencizer, tm._LocalSplitter)


def test_local_splitter_splits_without_a_model():
    import translation_module as tm
    s = tm._LocalSplitter().split_sentences("Hola. ¿Qué tal? ¡Muy bien!")
    assert s == ["Hola.", "¿Qué tal?", "¡Muy bien!"]


def test_a_missing_pack_is_refused_locally():
    import translation_module as tm
    if not tm.TRANSLATOR_AVAILABLE:
        pytest.skip("argostranslate not installed")
    r = tm.TranslationModule().translate("hello", "zu")      # no Zulu pack
    assert r["error"] and "nothing was sent" in r["error"]
