"""The suite must not touch the physical world.

Several test files drive real FastAPI routes through TestClient, and some of
those routes do things outside the process. /kadmos/upload speaks its
confirmation prompt aloud on Nyx, so `pytest tests/` announced "That's g.pdf —
PDF, 2 pages…" through the HDMI sink on every run, once per upload — audible in
the room, and absent from the service journal because it is the test process
talking rather than the service.

conftest.py mutes TTS at the class level before any test module imports server.
These guard that, because the failure mode is not a red test — it is a machine
talking to an empty room, which nothing in CI would ever catch.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import tts_module


def test_tts_is_muted_for_the_whole_session():
    """The patch is on the CLASS, so every instance — including the one server
    builds at import time — is already mute."""
    inst = tts_module.TTSModule.__new__(tts_module.TTSModule)
    assert tts_module.TTSModule.speak(inst, "this must not be audible") is None


def test_the_real_speak_is_kept_not_destroyed():
    """Muted for the suite, not monkeypatched into oblivion — the real one is
    held so the patch stays reversible and reviewable."""
    import conftest
    assert callable(conftest._real_speak)
    assert conftest._real_speak is not tts_module.TTSModule.speak


def test_servers_tts_instance_is_mute_if_server_was_imported():
    """Free check: other test modules import server during collection, so by the
    time this runs it is usually in sys.modules already. If it is, its live tts
    object must be the muted one — patching the class after the instance existed
    would still work, but patching a copy would not."""
    server = sys.modules.get("server")
    if server is None:
        return                          # nothing imported it this run; nothing to assert
    assert server.tts.speak("silence") is None


def test_conftest_mutes_before_importing_server():
    """Ordering matters: server builds `tts = TTSModule()` at import. Muting the
    class first is what makes that instance mute. A conftest that imported server
    before patching would leave a live speaker behind."""
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "tts_module.TTSModule.speak = " in src
    assert "import server" not in src, \
        "conftest must not import server — mute the class first, let test modules import it"
