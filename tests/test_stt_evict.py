"""STTModule gives the card back — and refuses to do it unsafely.

Measured 2026-09-22: a Qwen render peaks at 14,467 MiB of a 16,380 MiB card with
this module stopped, and Whisper medium holds ~4.5 GB from boot. They cannot both
hold the card, so release() is what makes a text-render lane possible at all.

These assert CAPABILITY, not prose: the checks are AST-level or behavioural, so
renaming a docstring cannot turn them green.
"""
import ast
import threading
import time
import types

import pytest

import modules.stt_module as stt_mod
from modules.stt_module import STTModule, STTBusy

SRC = ast.parse(open(stt_mod.__file__).read())


def _cls():
    return next(n for n in SRC.body
                if isinstance(n, ast.ClassDef) and n.name == "STTModule")


def _method(name):
    return next((n for n in _cls().body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


def _calls(node):
    return {n.func.attr for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


# ---------- shape ---------------------------------------------------------
def test_release_and_ensure_loaded_exist():
    assert _method("release") is not None, "no way to hand the card back"
    assert _method("ensure_loaded") is not None, "no way to get it back"


def test_boot_load_is_still_eager(monkeypatch):
    """Lazy-on-first-listen would cost ~15s on her first word after every boot.
    The whole point of this design is that normal operation is unchanged.

    Asserted BEHAVIOURALLY, not by looking for the call in the AST: a mutation
    that left `_begin_load()` textually present but unreachable (`if False:`)
    sailed past the AST version of this test. The model must actually become
    resident without anyone calling listen().
    """
    sentinel = object()
    monkeypatch.setattr(stt_mod, "WHISPER_AVAILABLE", True)
    monkeypatch.setattr(stt_mod, "whisper",
                        types.SimpleNamespace(load_model=lambda *a, **k: sentinel))
    s = STTModule()
    deadline = time.time() + 5
    while s._model is None and time.time() < deadline:
        time.sleep(0.01)
    assert s._model is sentinel, \
        "construction did not start a load — that is the lazy regression"


def test_transcribe_paths_reload_and_guard():
    for name in ("_listen_whisper", "transcribe_file"):
        called = _calls(_method(name))
        assert "ensure_loaded" in called, f"{name} cannot recover a released model"
        assert "_using" in called, f"{name} does not mark itself in-flight"


def test_recording_happens_before_the_reload():
    """Reloading before recording would close the mic for ~15s and lose the words."""
    body = _method("_listen_whisper").body
    src = ast.dump(ast.Module(body=body, type_ignores=[]))
    assert src.index("'rec'") < src.index("'ensure_loaded'"), \
        "ensure_loaded runs before sd.rec — the reload would eat the audio"


# ---------- behaviour ------------------------------------------------------
@pytest.fixture
def stt(monkeypatch):
    """An instance with no real Whisper, so nothing touches the GPU."""
    monkeypatch.setattr(stt_mod, "WHISPER_AVAILABLE", False)
    s = STTModule()
    monkeypatch.setattr(stt_mod, "WHISPER_AVAILABLE", True)
    return s


def test_release_refuses_while_transcribing(stt):
    stt._model, stt._available = object(), True
    with stt._using():
        with pytest.raises(STTBusy):
            stt.release("qwen render")
    assert stt._model is not None, "model was dropped despite the refusal"


def test_release_refuses_mid_load(stt):
    stt._model, stt._loading = None, True
    with pytest.raises(STTBusy):
        stt.release()


def test_release_when_not_loaded_is_not_an_error(stt):
    assert stt.release()["released"] is False


def test_release_then_reload(stt, monkeypatch):
    stt._model, stt._available = object(), True
    assert stt.release("making room")["released"] is True
    assert stt._model is None and stt._released is True

    sentinel = object()
    monkeypatch.setattr(stt_mod, "whisper",
                        types.SimpleNamespace(load_model=lambda *a, **k: sentinel))
    assert stt.ensure_loaded(timeout=10) is True
    assert stt._model is sentinel and stt._released is False


def test_status_names_the_released_state(stt):
    stt._model, stt._available, stt._released = None, False, True
    assert "released" in stt.status().lower()


def test_listen_does_not_refuse_a_released_model(stt, monkeypatch):
    """A released model must not surface as 'still loading' — it must reload."""
    stt._released, stt._loading, stt._available = True, True, False
    monkeypatch.setattr(stt_mod, "AUDIO_AVAILABLE", False)
    r = stt.listen(1)
    assert "still loading" not in (r.get("error") or ""), \
        "a released model is being reported as a boot-time load"


def test_in_use_survives_an_exception(stt):
    stt._model = object()
    with pytest.raises(ValueError):
        with stt._using():
            raise ValueError("boom")
    assert stt._in_use == 0, "_using leaked a reference on the error path"
    stt.release()          # would raise STTBusy if the counter had leaked


def test_concurrent_release_and_use_do_not_race(stt):
    stt._model, stt._available = object(), True
    hit = []

    def worker():
        with stt._using():
            threading.Event().wait(0.15)

    t = threading.Thread(target=worker); t.start()
    threading.Event().wait(0.02)
    try:
        stt.release()
    except STTBusy:
        hit.append("refused")
    t.join()
    assert hit == ["refused"], "release slipped through while a transcription ran"


# ---------- the weld: no HTTP surface ---------------------------------------
def test_evict_api_has_no_http_surface():
    """release()/ensure_loaded() are method-only and must stay that way.

    Gate condition for merging this branch (ruling 2026-09-22): the evict API
    must be unreachable from the portal or the Tailscale Funnel. Rung 2 gives
    Herakles the authority to call it; until then nothing calls it at all, and
    even after, it should be reached through Herakles rather than a route of
    its own. This test is the weld, so the property cannot lapse silently.
    """
    import pathlib
    server = pathlib.Path(__file__).resolve().parents[1] / "agent" / "server.py"
    tree = ast.parse(server.read_text())

    reached = [
        (ast.unparse(n.func.value), n.func.attr, n.lineno)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("release", "ensure_loaded")
        and ast.unparse(n.func.value) == "stt"
    ]
    assert not reached, (
        f"the STT evict API is now reachable from server.py at {reached} — "
        f"route it through Herakles, not an HTTP endpoint")
