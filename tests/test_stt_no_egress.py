"""Speech-to-text never leaves the machine (Captain's ruling, 2026-10-07).

stt_module used to fall back to speech_recognition.recognize_google() whenever
Whisper could not load — microphone audio to Google, exactly when local STT was
broken and nobody was watching. Removed. If local STT fails she fails LOUD and
nothing is sent. Two guards: the source has no outbound path, and a failing
Whisper driven through both entry points makes zero connection attempts.
"""
import re
import socket
import types
from pathlib import Path

import pytest

import modules.stt_module as stt_mod
from modules.stt_module import STTModule

SRC = Path(stt_mod.__file__).read_text(encoding="utf-8")
CODE = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith("#"))


@pytest.mark.parametrize("needle", [
    "recognize_google", "speech_recognition", "recognize_", "sr.Recognizer",
    "import requests", "import httpx", "urllib.request", "import socket",
    "http://", "https://", "googleapis",
])
def test_the_module_has_no_outbound_path(needle):
    assert needle not in CODE, f"stt_module contains {needle!r}"


@pytest.fixture
def no_network(monkeypatch):
    """Any connect attempt is recorded and refused."""
    tried = []

    def trap(self, addr, *a, **k):
        tried.append(addr)
        raise OSError("network disabled in this test")
    monkeypatch.setattr(socket.socket, "connect", trap)
    monkeypatch.setattr(socket.socket, "connect_ex", trap)
    return tried


@pytest.fixture
def broken_whisper(monkeypatch):
    def load(*_a, **_k):
        raise RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB.")
    monkeypatch.setattr(stt_mod, "WHISPER_AVAILABLE", True)
    monkeypatch.setattr(stt_mod, "whisper", types.SimpleNamespace(load_model=load))
    monkeypatch.setattr(stt_mod, "_drop_cuda_cache", lambda: 0)
    s = STTModule()
    import time
    end = time.time() + 5
    while s._loading and time.time() < end:
        time.sleep(0.01)
    return s


def test_listen_with_broken_whisper_fails_loud_and_sends_nothing(broken_whisper, no_network,
                                                                monkeypatch):
    np = pytest.importorskip("numpy")
    loud = np.full((16000, 1), 0.2, dtype="float32")   # well above the silence gate
    monkeypatch.setattr(stt_mod, "AUDIO_AVAILABLE", True)
    monkeypatch.setattr(stt_mod, "sd", types.SimpleNamespace(rec=lambda *a, **k: loud,
                                                             wait=lambda: None),
                        raising=False)
    r = broken_whisper.listen(1)
    assert r["text"] is None and r["error"], r
    assert "nothing was sent" in r["error"].lower()
    assert not no_network, f"STT tried to connect to {no_network}"


def test_transcribe_with_broken_whisper_sends_nothing(broken_whisper, no_network):
    r = broken_whisper.transcribe_file("x.wav")
    assert r["text"] is None and r["error"]
    assert not no_network, f"STT tried to connect to {no_network}"


def test_status_never_mentions_an_online_fallback(broken_whisper):
    st = broken_whisper.status().lower()
    assert "google" not in st and "fallback" not in st
    assert "not hearing" in st
