"""Her hearing is claimed only after a transcript proves it (Captain's ruling,
2026-10-07: "claim follows proof, never precedes it").

WHY. On 2026-10-07 /ready said "Whisper medium on hold — palamedes has the card,
ears back in ~40s" for over an hour. A reload at lease end had OOM'd, the hold
was never cleared, and the ETA was a number computed once at hold time. The
string was a prediction, and nothing ever checked it.

So: loaded is not hearing. Only an accepted transcript since the last load is.
Behavioural, with a fake whisper — nothing here touches the card.
"""
import re
import time
import types

import pytest

import modules.stt_module as stt_mod
from modules.stt_module import STTModule

GOOD = {"text": "hello there phoebe",
        "segments": [{"no_speech_prob": 0.01, "avg_logprob": -0.2}]}
PHANTOM = {"text": "Thank you.",
           "segments": [{"no_speech_prob": 0.95, "avg_logprob": -1.5}]}

# Anything that promises the future rather than reporting the present.
PROMISE = re.compile(r"ears (are )?back|back in|in ~|in about|\bshortly\b|"
                     r"will be|seconds", re.I)


class _FakeModel:
    def __init__(self, result):
        self.result = result

    def transcribe(self, *_a, **_k):
        return self.result


def _wait(pred, s=5.0):
    end = time.time() + s
    while not pred() and time.time() < end:
        time.sleep(0.01)
    assert pred()


@pytest.fixture
def make(monkeypatch):
    def _make(result=GOOD, fail=None):
        def load(*_a, **_k):
            if fail:
                raise RuntimeError(fail)
            return _FakeModel(result)
        monkeypatch.setattr(stt_mod, "WHISPER_AVAILABLE", True)
        monkeypatch.setattr(stt_mod, "whisper", types.SimpleNamespace(load_model=load))
        s = STTModule()
        _wait(lambda: not s._loading)
        return s
    return _make


def test_loaded_is_not_hearing(make):
    s = make()
    assert s._model is not None
    assert not s.hearing_confirmed()
    assert "no live transcript since it loaded" in s.status()


def test_an_accepted_transcript_is_what_confirms_it(make):
    s = make()
    assert s.transcribe_file("x.wav")["text"] == "hello there phoebe"
    assert s.hearing_confirmed()
    assert "hearing confirmed by a transcript at" in s.status()


def test_a_gated_phantom_does_not_confirm_hearing(make):
    s = make(result=PHANTOM)
    assert s.transcribe_file("x.wav")["text"] is None
    assert not s.hearing_confirmed()


def test_a_reload_resets_the_proof(make):
    """Proof from BEFORE a release says nothing about the model loaded after it."""
    s = make()
    s.transcribe_file("x.wav")
    assert s.hearing_confirmed()
    s.hold("palamedes", eta_s=40)
    assert not s.hearing_confirmed()
    time.sleep(0.01)
    assert s.resume(reload=True)
    assert not s.hearing_confirmed(), "a fresh load inherited the old transcript"
    s.transcribe_file("x.wav")
    assert s.hearing_confirmed()


def test_hold_states_the_present_and_promises_nothing(make):
    s = make()
    s.hold("palamedes", eta_s=40)
    st, line = s.status(), s._hold_line()
    assert "not hearing" in st and "since" in st
    assert not PROMISE.search(st), st
    assert not PROMISE.search(line), line


def test_a_failed_load_says_so_with_its_reason(make):
    """The 15:04:29 case: CUDA OOM on reload. It must not read as ready, released
    'for now', or coming back."""
    s = make(fail="CUDA out of memory. Tried to allocate 20.00 MiB.")
    st = s.status()
    assert "last load failed at" in st and "CUDA out of memory" in st
    assert "not hearing" in st
    assert not PROMISE.search(st), st


def test_no_status_anywhere_makes_a_promise(make):
    s = make()
    seen = [s.status()]
    s.transcribe_file("x.wav"); seen.append(s.status())
    s.hold("palamedes", eta_s=40); seen.append(s.status())
    s.resume(reload=False); seen.append(s.status())
    for st in seen:
        assert not PROMISE.search(st), st


# ── C1 memory: nothing left orphaned ─────────────────────────────────────────
def test_a_failed_load_hands_its_memory_back(make, monkeypatch):
    """15:04:29 on 2026-10-07: a reload OOM'd and ~3.8 GB stayed reserved in the
    process with _model None. The failure path must return it."""
    dropped = []
    monkeypatch.setattr(stt_mod, "_drop_cuda_cache", lambda: dropped.append(1) or 3800)
    make(fail="CUDA out of memory. Tried to allocate 20.00 MiB.")
    assert dropped, "a failed load left its partial weights reserved"


def test_release_when_not_loaded_still_recovers_an_orphan(make, monkeypatch):
    s = make(fail="CUDA out of memory.")
    monkeypatch.setattr(stt_mod, "_drop_cuda_cache", lambda: 3800)
    r = s.release("palamedes")
    assert r["released"] is False and r["freed_mb"] == 3800, \
        "'not loaded' returned without giving the orphaned memory back"


# ── restore verification ─────────────────────────────────────────────────────
def test_self_test_passes_on_the_known_clip_words(make):
    s = make(result={"text": "The quick brown fox jumps over the lazy dog.",
                     "segments": [{"no_speech_prob": 0.01, "avg_logprob": -0.1}]})
    r = s.self_test()
    assert r["ok"]
    assert "self-test transcript passed at" in s.status()
    assert not s.hearing_confirmed(), "a self-test is not a live transcript"


def test_self_test_fails_on_the_wrong_words(make):
    s = make(result={"text": "Thank you.", "segments": []})
    assert s.self_test()["ok"] is False


def test_self_test_refuses_while_held(make):
    s = make()
    s.hold("palamedes")
    assert s.self_test()["ok"] is False


def test_the_self_test_clip_exists():
    assert stt_mod.os.path.exists(stt_mod._SELFTEST_WAV), stt_mod._SELFTEST_WAV
