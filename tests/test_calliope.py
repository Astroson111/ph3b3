"""
Calliope — speech renders, verify suite.

THE REGRESSION THAT CAUSED THE MODULE. A WAV was rendered in 3.9 seconds and
then took ten minutes to find, because nothing indexed it. So the first test
below is not about audio at all — it is that a render is findable afterwards.

THE GATE. Astro ruled ungated-with-logging on 2026-09-17. Ungated is easy to
build and easy to get wrong in one specific way: if the log is partial, the
trade that justified being ungated has not actually been made. So the record is
tested for completeness, not merely for existence.

Run:  .venv/bin/python -m pytest tests/test_calliope.py -v
"""
import base64
import io
import json
import sys
import wave
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import calliope  # noqa: E402


def _wav_b64(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return base64.b64encode(buf.getvalue()).decode()


class FakeTTS:
    """Piper stands still for the tests. Never shells out."""
    _available = True

    def __init__(self, seconds=1.0, fail=False):
        self.seconds, self.fail, self.calls = seconds, fail, []
        self.last_error = None

    def synthesize_to_b64(self, text, voice=None, length_scale=None,
                          sentence_silence=None):
        self.calls.append({"text": text, "voice": voice,
                           "length_scale": length_scale,
                           "sentence_silence": sentence_silence})
        if self.fail:
            self.last_error = "piper exited 1"
            return None
        return _wav_b64(self.seconds)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Never write into the real speech directory."""
    monkeypatch.setattr(calliope, "SPEECH_DIR", tmp_path / "speech")
    return tmp_path


# ── the regression: a render must be findable ────────────────────────────────

def test_a_render_is_in_the_library_immediately():
    """The whole reason this module exists. A WAV that only the renderer knows
    the path to is the bug, not the feature."""
    rec = calliope.render("Hello there.", tts=FakeTTS(), title="Greeting")
    lib = calliope.library()
    assert [r["id"] for r in lib] == [rec["id"]]
    assert lib[0]["title"] == "Greeting"
    assert calliope.wav_path(rec["id"]).exists()


def test_the_library_returns_the_script_so_it_can_be_re_rendered():
    """Wording gets iterated. If the text does not come back with the record,
    every edit means retyping the script."""
    rec = calliope.render("One. Two. Three.", tts=FakeTTS())
    assert calliope.library()[0]["text"] == "One. Two. Three."


def test_newest_first():
    import time
    a = calliope.render("First.", tts=FakeTTS())
    time.sleep(0.01)
    b = calliope.render("Second.", tts=FakeTTS())
    assert [r["id"] for r in calliope.library()] == [b["id"], a["id"]]


# ── the gate: ungated, but the record must be complete ───────────────────────

def test_arbitrary_text_renders_with_no_gate():
    """Astro's ruling. Nothing here refuses text on content grounds."""
    for t in ("Buy my product now!", "A political opinion.", "asdf qwer zxcv"):
        assert calliope.render(t, tts=FakeTTS())["id"]


def test_the_full_script_is_stored_beside_the_audio_not_truncated():
    """Ungated is only defensible if the record is complete. A truncated log is
    the failure mode that quietly withdraws the trade."""
    long_text = "Sentence number {}. ".format(1) + " ".join(
        f"This is sentence {i}." for i in range(2, 200))
    rec = calliope.render(long_text, tts=FakeTTS())
    side = json.loads((calliope._dir() / f"{Path(rec['file']).stem}.json")
                      .read_text(encoding="utf-8"))
    assert side["text"] == long_text
    assert len(side["text"]) == len(long_text)


def test_the_record_names_who_actually_spoke():
    """voice_name used to come back empty for the default voice, because
    display_name_for(None) returns "". The selected voice is a SETTING — it is
    currently Cori, not the registry's Alba — so a record saying "default"
    is a promise to be wrong later."""
    rec = calliope.render("Who is speaking?", tts=FakeTTS())
    assert rec["voice_name"] and rec["voice_name"] != "default"
    assert rec["voice"] and rec["voice"] != "default"


def test_the_record_carries_what_a_person_would_ask_later():
    rec = calliope.render("A line.", tts=FakeTTS(seconds=2.5), title="T")
    for field in ("id", "title", "voice", "voice_name", "preset", "length_scale",
                  "sentence_silence", "seconds", "words", "chars",
                  "synth_seconds", "created_at", "file", "text"):
        assert field in rec, f"record is missing {field}"
    assert rec["seconds"] == 2.5


# ── pace ─────────────────────────────────────────────────────────────────────

def test_the_narration_preset_is_the_pair_that_produced_the_original():
    """1.22 / 0.75 rendered Motivation_voice.wav. It is the reason this module
    exists, so it is the default and it is pinned."""
    assert calliope.PRESETS["narration"] == (1.22, 0.75)
    assert calliope.DEFAULT_PRESET == "narration"


def test_the_preset_reaches_piper():
    t = FakeTTS()
    calliope.render("A line.", preset="slow", tts=t)
    assert t.calls[0]["length_scale"] == 1.40
    assert t.calls[0]["sentence_silence"] == 0.95


def test_explicit_values_beat_the_preset():
    t = FakeTTS()
    calliope.render("A line.", preset="natural", length_scale=1.9, tts=t)
    assert t.calls[0]["length_scale"] == 1.9
    assert t.calls[0]["sentence_silence"] == 0.30      # preset still supplies this


@pytest.mark.parametrize("kw,needle", [
    ({"preset": "breakneck"}, "breakneck"),
    ({"length_scale": 9.0}, "pace"),
    ({"sentence_silence": 99}, "sentence gap"),
])
def test_bad_pace_is_refused_by_name(kw, needle):
    with pytest.raises(calliope.CalliopeError) as e:
        calliope.render("A line.", tts=FakeTTS(), **kw)
    assert needle in str(e.value)


# ── the estimate locks the music brief ───────────────────────────────────────

def test_the_estimate_matches_the_measured_render():
    """104 words at length_scale 1.22 came out at 40.8s on Nyx. That figure is
    what a music duration gets built from, so drift here is not cosmetic."""
    est = calliope.estimate_seconds(" ".join(["word"] * 104), 1.22)
    assert abs(est - 40.8) < 0.5


def test_the_estimate_scales_with_pace():
    words = " ".join(["word"] * 100)
    assert calliope.estimate_seconds(words, 1.4) > calliope.estimate_seconds(words, 1.0)


# ── failure is never silence ─────────────────────────────────────────────────

def test_a_failed_render_raises_and_writes_nothing():
    """Returning an empty success is the failure mode the TTS lane keeps hitting.
    No file, no orphan record, and the reason is carried out."""
    with pytest.raises(calliope.CalliopeError) as e:
        calliope.render("A line.", tts=FakeTTS(fail=True))
    assert "piper exited 1" in str(e.value)
    assert calliope.library() == []
    assert not list(calliope._dir().glob("*"))


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_an_empty_script_is_refused(text):
    with pytest.raises(calliope.CalliopeError) as e:
        calliope.render(text, tts=FakeTTS())
    assert "nothing to say" in str(e.value).lower()


def test_an_overlong_script_is_refused_with_the_limit_named():
    with pytest.raises(calliope.CalliopeError) as e:
        calliope.render("x" * (calliope.MAX_CHARS + 1), tts=FakeTTS())
    assert f"{calliope.MAX_CHARS:,}" in str(e.value)


# ── delete takes both halves ─────────────────────────────────────────────────

def test_delete_removes_the_audio_and_the_record_together():
    """Leaving one behind is how an orphan turns up in a listing pretending to
    be a render — the trap amphion.delete_song() documents."""
    rec = calliope.render("Delete me.", tts=FakeTTS())
    stem = Path(rec["file"]).stem
    assert calliope.delete(rec["id"]) is True
    assert not (calliope._dir() / f"{stem}.wav").exists()
    assert not (calliope._dir() / f"{stem}.json").exists()
    assert calliope.library() == []


def test_deleting_something_that_is_not_there_is_false_not_an_error():
    assert calliope.delete("nope") is False


def test_a_record_whose_audio_vanished_is_not_listed():
    """A sidecar with no WAV is exactly the orphan shape. It must not appear as
    a render you can play."""
    rec = calliope.render("Ghost.", tts=FakeTTS())
    (calliope._dir() / rec["file"]).unlink()
    assert calliope.library() == []


# ── no GPU, no queue ─────────────────────────────────────────────────────────

def test_calliope_never_touches_the_gpu_lock(monkeypatch):
    """Instrumented. The tab lives in the Amphion pane, so the temptation to
    borrow Amphion's queue is real — this fails the moment anything tries."""
    import morpheus

    class Tripwire:
        def locked(self): raise AssertionError("Calliope inspected the GPU lock")
        async def __aenter__(self): raise AssertionError("Calliope took the GPU lock")
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(morpheus, "gpu_lock", Tripwire())
    rec = calliope.render("No card needed.", tts=FakeTTS())
    calliope.library(); calliope.wav_path(rec["id"]); calliope.delete(rec["id"])


def test_the_module_does_not_reach_the_gpu_stack():
    """AST, not grep — the docstring names gpu_lock while explaining it is never
    touched, and a text search would trip on its own documentation."""
    import ast
    tree = ast.parse((REPO / "modules" / "calliope.py").read_text(encoding="utf-8"))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            b = getattr(n, "body", None)
            if (b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant)
                    and isinstance(b[0].value.value, str)):
                docs.add(id(b[0].value))
    banned = {"morpheus", "amphion", "torch", "comfy"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                assert a.name.split(".")[0] not in banned, f"imports {a.name}"
        elif isinstance(n, ast.ImportFrom):
            assert (n.module or "").split(".")[0] not in banned
        elif isinstance(n, ast.Attribute):
            assert n.attr not in ("gpu_lock", "comfy_free", "evict_hermes")


def test_amphions_own_voice_profiles_are_a_different_thing_entirely():
    """The naming collision this module was renamed to avoid. amphion's
    'voices' are singing descriptors with no audio; Calliope's are Piper codes.
    If these ever merge, something has gone wrong."""
    import amphion
    amphion_fields = set(amphion._VOICE_FIELDS)
    assert "register" in amphion_fields and "seed" in amphion_fields
    ours = calliope.roster()
    assert ours and set(ours[0]) == {"code", "name"}
    assert not (amphion_fields & {"code"}), "the two voice concepts have collided"
