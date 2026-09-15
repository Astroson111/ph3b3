"""
Voice roster + fail-loud fallback — verify suite.

The fallback tests are the point. A voice that will not load used to fall back
to Alba with nothing but a log line, which means a person who chose Cori and
heard Alba was told something false about what they were listening to. Worse,
a voice whose files were PRESENT but unusable produced no audio at all: the
caller skipped every failed chunk and the result was dead air that looked like
a successful reply.

Run:  .venv/bin/python -m pytest tests/test_voice_roster.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import tts_module                       # noqa: E402
import voices                           # noqa: E402
from tts_module import TTSModule, _resolve_voice, unavailable_line  # noqa: E402

REGISTRY = voices.load_registry().get("voices") or {}


# ── the roster ───────────────────────────────────────────────────────────────

def test_cori_is_registered_and_installed():
    assert "en_cori" in REGISTRY
    v = voices.resolve_voice("en_cori")
    assert v, "Cori is in the registry but her model did not resolve"
    assert v["model_path"].endswith("en_GB-cori-high.onnx")


def test_cori_ships_unreviewed_because_approving_is_done_by_ear():
    """The registry's own rule: a new voice reaches the picker only after the
    Captain has heard it. Tooling does not get to set that."""
    assert REGISTRY["en_cori"]["status"] == "unreviewed"


def test_cori_carries_the_fields_the_install_check_demands():
    assert voices.voices_missing_required() == {}
    e = REGISTRY["en_cori"]
    assert e["display_name"] and e["sample_text"]
    assert e["script"] == "latin" and e["lang"] == "en"


def test_the_two_restrictively_licensed_voices_were_not_installed():
    """amy's provenance points at a repo that does not contain it (CC BY-SA at
    root); alan's source dataset is "Copyright 2022 Mycroft AI / All Rights
    Reserved". Astro's call: public domain only."""
    assert "en_amy" not in REGISTRY and "en_alan" not in REGISTRY
    vdir = Path(voices.VOICE_DIR)
    assert not list(vdir.glob("*amy*")), "amy was installed despite the licence call"
    assert not list(vdir.glob("*alan*")), "alan was installed despite the licence call"


# ── Alba is welded ───────────────────────────────────────────────────────────

def test_alba_remains_the_default_and_her_config_is_untouched():
    reg = voices.load_registry()
    assert reg["default"] == "en"
    assert reg["voices"]["en"]["model"] == "en_GB-alba-medium.onnx"
    assert reg["voices"]["en"]["status"] == "approved"


def test_alba_is_still_english_primary_after_the_addition():
    """approved_voices_for puts the voice whose code == lang first. Adding
    another English voice must not unseat her."""
    approved = voices.approved_voices_for("en")
    assert approved and approved[0] == "en"


def test_adding_an_english_voice_did_not_touch_other_languages():
    for lang, primary in (("es", "es"), ("de", "de"), ("fr", "fr"), ("zh", "zh")):
        got = voices.approved_voices_for(lang)
        assert got and got[0] == primary, (lang, got)


# ── resolution requires BOTH files Piper needs ───────────────────────────────

def test_a_voice_missing_its_json_sidecar_does_not_resolve(tmp_path, monkeypatch):
    """Checking only the .onnx let a half-installed voice resolve cleanly and
    then fail as SILENCE at synth time."""
    monkeypatch.setattr(voices, "VOICE_DIR", tmp_path)
    (tmp_path / "x-medium.onnx").write_bytes(b"weights")
    monkeypatch.setattr(voices, "load_registry", lambda: {
        "default": "en", "voices": {"x": {"model": "x-medium.onnx", "lang": "en",
                                          "display_name": "X — Test",
                                          "sample_text": "hi", "status": "approved"}}})
    assert voices.resolve_voice("x") is None
    (tmp_path / "x-medium.onnx.json").write_text("{}")
    assert voices.resolve_voice("x") is not None


# ── fail loud ────────────────────────────────────────────────────────────────

def test_a_missing_voice_is_named_not_swallowed(monkeypatch):
    monkeypatch.setattr(voices, "resolve_voice", lambda c: None)
    monkeypatch.setattr(voices, "display_name_for", lambda c: "Cori — English (Great Britain)")
    model, script, unavailable = _resolve_voice("en_cori")
    assert model.endswith("en_GB-alba-medium.onnx")
    assert unavailable == "Cori — English (Great Britain)"


def test_the_announcement_names_the_voice_and_says_what_happened():
    line = unavailable_line("Cori — English (Great Britain)")
    assert "Cori" in line
    assert "Alba" in line
    assert "unreadable" in line or "missing" in line


def test_selecting_alba_herself_announces_nothing():
    """The default path must stay byte-identical — no note, no change."""
    _m, _s, unavailable = _resolve_voice("en")
    assert unavailable == ""


def test_corrupt_weights_retry_on_alba_and_announce(monkeypatch):
    """Files present, model unusable. The old path returned None and every
    caller rendered that as dead air."""
    t = TTSModule()
    t._available = True
    seen = []

    def fake_raw(text, model=None, length_scale=None, sentence_silence=None):
        seen.append((text, model))
        return None if "cori" in str(model) else b"\x00\x01" * 100

    monkeypatch.setattr(t, "_piper_raw", fake_raw)
    monkeypatch.setattr(tts_module, "_resolve_voice",
                        lambda c=None: ("/voices/en_GB-cori-high.onnx", "latin", ""))
    monkeypatch.setattr(voices, "display_name_for", lambda c: "Cori")
    pcm = t.synth_pcm("The library is open.", voice="en_cori")
    assert pcm, "corrupt voice produced no audio at all"
    assert any("Cori" in txt and "Alba" in txt for txt, _m in seen), \
        "fell back without announcing which voice failed"


def test_the_speaker_path_also_falls_back_mid_stream(monkeypatch):
    """_speak_now synthesises chunk by chunk and used to `continue` past every
    failure — a whole reading that plays as silence."""
    t = TTSModule()
    t._available = True
    played, synthed = [], []

    def fake_raw(text, model=None, length_scale=None, sentence_silence=None):
        synthed.append((text, model))
        return None if "broken" in str(model) else b"\x00\x01" * 100

    monkeypatch.setattr(t, "_piper_raw", fake_raw)
    monkeypatch.setattr(t, "_play_pcm", lambda pcm: (played.append(len(pcm)), True)[1])
    monkeypatch.setattr(voices, "display_name_for", lambda c: "BrokenVoice")
    t._speak_now("One sentence. And a second one, for good measure.",
                 "/voices/broken.onnx", voice="en_broken")
    assert played, "the speaker path went silent instead of falling back"
    assert any("BrokenVoice" in txt and "Alba" in txt for txt, _m in synthed)


def test_the_fallback_is_not_a_setting():
    """No flag turns the announcement off — a silent fallback is the bug."""
    src = (REPO / "modules" / "tts_module.py").read_text(encoding="utf-8")
    for smell in ("announce=", "silent_fallback", "quiet_fallback", "notify="):
        assert smell not in src, f"tts_module exposes a way to mute the fallback: {smell}"
