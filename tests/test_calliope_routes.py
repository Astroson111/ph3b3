"""
Calliope HTTP surface — verify suite.

Two claims from the brief are checked here rather than asserted in prose:
the routes live under /amphion/speech/* and never collide with Amphion's own
voice profiles, and a speech render completes while the GPU is held — which is
what "in the Amphion pane but not on Amphion's queue" actually has to mean.

Run:  .venv/bin/python -m pytest tests/test_calliope_routes.py -v
"""
import base64
import io
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "modules"))

import server                                   # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402

calliope = server.calliope
client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
H = {"Authorization": f"Basic {_auth}"}


def _wav_b64(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return base64.b64encode(buf.getvalue()).decode()


class FakeTTS:
    _available = True
    last_error = None
    def synthesize_to_b64(self, text, voice=None, length_scale=None,
                          sentence_silence=None):
        return _wav_b64()


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(calliope, "SPEECH_DIR", tmp_path / "speech")
    import tts_module
    monkeypatch.setattr(tts_module, "TTSModule", lambda *a, **k: FakeTTS())
    return tmp_path


def test_the_catalogue_offers_voices_and_presets():
    j = client.get("/amphion/speech/catalogue", headers=H).json()
    assert j["default_preset"] == "narration"
    assert j["presets"]["narration"] == {"length_scale": 1.22, "sentence_silence": 0.75}
    assert any(v["code"] == "en" for v in j["voices"])


def test_the_estimate_comes_before_the_render():
    """This figure locks a music brief downstream, so it is available without
    spending a render to find it out."""
    j = client.post("/amphion/speech/estimate",
                    json={"text": " ".join(["word"] * 104), "preset": "narration"},
                    headers=H).json()
    assert j["words"] == 104
    assert abs(j["seconds"] - 40.8) < 0.5


def test_render_then_library_then_file_then_delete():
    r = client.post("/amphion/speech/render",
                    json={"text": "The water pushes back.", "title": "Water"}, headers=H)
    assert r.status_code == 200
    rec = r.json()
    assert rec["title"] == "Water" and rec["text"] == "The water pushes back."

    lib = client.get("/amphion/speech/library", headers=H).json()["speech"]
    assert [x["id"] for x in lib] == [rec["id"]]

    f = client.get(f"/amphion/speech/file/{rec['id']}", headers=H)
    assert f.status_code == 200
    assert f.content[:4] == b"RIFF"
    assert "attachment" in f.headers.get("content-disposition", "").lower()

    d = client.delete(f"/amphion/speech/{rec['id']}", headers=H)
    assert d.status_code == 200
    assert client.get("/amphion/speech/library", headers=H).json()["speech"] == []


@pytest.mark.parametrize("body,needle", [
    ({"text": ""}, "nothing to say"),
    ({"text": "hi", "preset": "breakneck"}, "breakneck"),
    ({"text": "hi", "length_scale": 9}, "pace"),
])
def test_bad_input_is_a_400_that_says_why(body, needle):
    r = client.post("/amphion/speech/render", json=body, headers=H)
    assert r.status_code == 400
    assert needle in r.json()["error"].lower()


def test_a_missing_render_is_a_404_not_a_500():
    assert client.get("/amphion/speech/file/nope", headers=H).status_code == 404
    assert client.delete("/amphion/speech/nope", headers=H).status_code == 404


def test_speech_renders_while_the_gpu_is_held():
    """'In the Amphion pane, not on Amphion's queue' has to mean this. The lock
    is HELD for the duration of the call, and the render must still finish."""
    import asyncio, morpheus
    lock = morpheus.gpu_lock

    async def hold_then_render():
        async with lock:                       # a song is rendering
            assert lock.locked()
            return await asyncio.to_thread(
                lambda: client.post("/amphion/speech/render",
                                    json={"text": "Not waiting."}, headers=H))

    r = asyncio.run(hold_then_render())
    assert r.status_code == 200, "a speech render queued behind the GPU lock"


def test_the_speech_routes_do_not_collide_with_amphion_voices():
    """/amphion/voices is ACE-Step singing descriptors and must be untouched by
    anything added here."""
    v = client.get("/amphion/voices", headers=H).json()["voices"]
    assert v and "register" in v[0]
    assert "code" not in v[0], "amphion voices grew a Calliope-shaped field"
    paths = [r.path for r in server.app.router.routes if hasattr(r, "path")]
    assert "/amphion/speech/render" in paths
    assert "/amphion/voice/render" not in paths


def test_every_speech_route_requires_a_human():
    assert client.get("/amphion/speech/catalogue").status_code in (401, 403)
    assert client.get("/amphion/speech/library").status_code in (401, 403)
    assert client.post("/amphion/speech/render",
                       json={"text": "hi"}).status_code in (401, 403)
    assert client.delete("/amphion/speech/x").status_code in (401, 403)
