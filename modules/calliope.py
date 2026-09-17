"""
Calliope — text in, a spoken WAV out, and you can find it again afterwards.

WHY THIS EXISTS. On 2026-09-17 Alba read a 104-word script to a WAV in 3.9
seconds, and it then took ten minutes to locate, because nothing indexed it: the
file went straight to disk through the TTS module and no surface lists that
folder. The Amphion track from the same session was findable at once, because
Amphion registers its renders where the panel can read them. So the library is
the feature here, not a convenience bolted on afterwards — a render box without
one rebuilds the same dead end.

THE GATE. Astro's ruling, 2026-09-17: ungated with logging. This is the first
path in the system that speaks arbitrary text — everything before it renders
either Phoebe's own reply, which the floor has already seen, or a fixed registry
sample (/voice/preview refuses client-supplied text outright). That constraint is
lifted here deliberately, so the trade is made honestly: nothing is refused, and
nothing is forgotten either. Every render writes its FULL text into a durable
sidecar next to the audio. The record is the file, not a log line that rotates
away — you can always answer "what did it say" for anything that was ever spoken.

NO CARD, NO QUEUE. Piper is a CPU subprocess. Nothing here imports morpheus or
amphion, touches gpu_lock, or waits on the render queue, even though the tab
lives in the Amphion pane — a speech render must complete while a song is
rendering, and that is tested rather than assumed.

NAMING. The tab reads "Speech", and the routes are /amphion/speech/*, because
/amphion/voices already means something else entirely: ACE-Step singing
descriptors, no audio. Two meanings of "voice" one click apart is the `canon`
collision from Thoth, and it is avoided here by not reusing the word.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
import wave
from pathlib import Path

from paths import PH3B3_DATA

log = logging.getLogger("ph3b3")

SPEECH_DIR = PH3B3_DATA / "speech"

# Piper's duration multiplier and inter-sentence pause. Presets rather than raw
# numbers in the UI, because "1.22" means nothing to a person choosing a pace.
# "narration" is the pair used for Motivation_voice.wav — it is the reason this
# module exists, so it is the default.
PRESETS: dict[str, tuple[float, float]] = {
    "natural":   (1.00, 0.30),
    "narration": (1.22, 0.75),
    "slow":      (1.40, 0.95),
}
DEFAULT_PRESET = "narration"

MAX_CHARS = 20_000          # ~2.5 hours of speech; a guard, not a feature
TITLE_MAX = 80

# Measured on Nyx, Alba (en_GB-alba-medium): 104 words of script at
# length_scale 1.22 came out at 40.8s. That is the figure the estimate is built
# from, and it is what locks a music brief downstream, so it is stated rather
# than guessed.
_SECONDS_PER_WORD_AT_1X = (40.8 / 104) / 1.22


class CalliopeError(ValueError):
    """Something this module will not render."""


def _dir() -> Path:
    SPEECH_DIR.mkdir(parents=True, exist_ok=True)
    return SPEECH_DIR


def estimate_seconds(text: str, length_scale: float = 1.0) -> float:
    """Roughly how long this will take to say, before committing to it."""
    words = len((text or "").split())
    return round(words * _SECONDS_PER_WORD_AT_1X * max(0.1, float(length_scale)), 1)


def resolve_pace(preset: str | None, length_scale=None, sentence_silence=None):
    """Preset name, or explicit values, or the default. Explicit wins."""
    if preset is not None and preset not in PRESETS:
        raise CalliopeError(
            f"'{preset}' isn't a pace I have — try: {', '.join(PRESETS)}")
    base = PRESETS[preset or DEFAULT_PRESET]
    ls = base[0] if length_scale is None else float(length_scale)
    ss = base[1] if sentence_silence is None else float(sentence_silence)
    if not (0.5 <= ls <= 2.5):
        raise CalliopeError("pace (length_scale) must be between 0.5 and 2.5")
    if not (0.0 <= ss <= 3.0):
        raise CalliopeError("sentence gap must be between 0 and 3 seconds")
    return ls, ss


def _slug(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (title or "").strip()).strip("_")
    return (s[:40] or "speech")


def _title_from(text: str) -> str:
    first = (text or "").strip().split("\n")[0]
    return (first[:TITLE_MAX].rstrip() or "Untitled")


def render(text: str, voice: str | None = None, preset: str | None = None,
           length_scale=None, sentence_silence=None, title: str | None = None,
           tts=None) -> dict:
    """Speak `text`, store the WAV and its record, return the record.

    `tts` is injectable so the tests never shell out to Piper.
    """
    text = (text or "").strip()
    if not text:
        raise CalliopeError("There's nothing to say — the script is empty.")
    if len(text) > MAX_CHARS:
        raise CalliopeError(
            f"That script is {len(text):,} characters; the limit is {MAX_CHARS:,}.")
    ls, ss = resolve_pace(preset, length_scale, sentence_silence)

    if tts is None:
        import tts_module
        tts = tts_module.TTSModule()
    if not getattr(tts, "_available", False) and not hasattr(tts, "_piper_raw"):
        raise CalliopeError("Piper isn't available, so I can't render speech.")

    t0 = time.time()
    b64 = tts.synthesize_to_b64(text, voice, ls, ss)
    took = time.time() - t0
    if not b64:
        # Never return silence as success — the failure this whole lane guards.
        why = getattr(tts, "last_error", None) or "synthesis produced no audio"
        raise CalliopeError(f"The voice didn't render: {why}")

    import base64
    raw = base64.b64decode(b64)
    sid = uuid.uuid4().hex[:12]
    stem = f"{sid}_{_slug(title or _title_from(text))}"
    wav = _dir() / f"{stem}.wav"
    wav.write_bytes(raw)

    dur = _wav_seconds(wav)
    rec = {
        "id": sid,
        "title": (title or _title_from(text))[:TITLE_MAX],
        "voice": voice or _selected_code(),
        "voice_name": _display_name(voice),
        "preset": preset or DEFAULT_PRESET,
        "length_scale": ls,
        "sentence_silence": ss,
        "seconds": dur,
        "words": len(text.split()),
        "chars": len(text),
        "synth_seconds": round(took, 2),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "file": wav.name,
        # THE LOG. Ungated means the record has to be complete: the full script
        # lives here, beside the audio, for as long as the audio does.
        "text": text,
    }
    wav.with_suffix(".json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    log.info("[calliope] spoke %s (%s) %.1fs from %d words in %.1fs — %r",
             sid, rec["voice_name"], dur, rec["words"], took, text[:60])
    return rec


def _selected_code() -> str:
    """The voice code actually in effect when no explicit voice is given."""
    try:
        import voices
        return (voices.get_setting() or {}).get("voice") or "en"
    except Exception:
        return "en"


def _display_name(code: str | None) -> str:
    """Who actually spoke — never blank, and never the word "default".

    display_name_for(None) returns "", so a record rendered with the default
    voice used to name nobody. That is not cosmetic: the selected voice is a
    SETTING (currently en_cori, not the registry's Alba), so "default" in a
    record is a promise to be wrong the next time the setting changes. Resolve
    it to the voice that really ran, at render time.
    """
    try:
        import voices
        return voices.display_name_for(code) or voices.current_display_name()
    except Exception:
        return code or "unknown voice"


def _wav_seconds(p: Path) -> float:
    try:
        with wave.open(str(p)) as w:
            return round(w.getnframes() / float(w.getframerate() or 1), 1)
    except Exception:
        return 0.0


def library(limit: int = 50) -> list[dict]:
    """Newest first. The script is included — re-rendering with edited wording
    is the normal way this gets used, so the text has to come back with it."""
    out = []
    for j in sorted(_dir().glob("*.json"),
                    key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            rec = json.loads(j.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (_dir() / rec.get("file", "")).exists():
            out.append(rec)
    return out


def get(speech_id: str) -> dict | None:
    for rec in library(limit=10_000):
        if rec.get("id") == speech_id:
            return rec
    return None


def wav_path(speech_id: str) -> Path | None:
    rec = get(speech_id)
    if not rec:
        return None
    p = _dir() / rec["file"]
    return p if p.exists() else None


def delete(speech_id: str) -> bool:
    """Remove the audio and its record together.

    Deleting one and leaving the other is how orphans appear in a listing
    pretending to be renders — the same trap amphion.delete_song() documents.
    """
    rec = get(speech_id)
    if not rec:
        return False
    p = _dir() / rec["file"]
    if p.parent != _dir():                 # never follow a name out of the dir
        return False
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)
    log.info("[calliope] deleted %s (%s)", speech_id, rec.get("title"))
    return True


def roster() -> list[dict]:
    """Approved, installed English voices — the same list the picker shows."""
    import voices
    return [{"code": c, "name": voices.display_name_for(c)}
            for c in voices.approved_voices_for("en")]
