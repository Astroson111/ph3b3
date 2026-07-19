import base64
import io
import json
import os
import logging
import re
import subprocess
import threading
import wave
from pathlib import Path


def _strip_for_piper(text: str) -> str:
    """Remove characters Piper/Alba cannot pronounce before synthesis.

    Two-pass approach:
      1. Replace "native_script (romanisation)" → "romanisation" so that
         e.g. "你好 (nǐ hǎo)" becomes "nǐ hǎo" rather than going silent.
      2. Drop any remaining code-points outside Piper's Latin/ASCII range.

    Characters kept:
      - ASCII (U+0000–U+007F)
      - Latin Extended A/B and IPA (U+00C0–U+024F) — covers diacritics used in
        pinyin (ǐ ǎ ō …), Cyrillic romanisations, etc.
      - Latin Extended Additional (U+1E00–U+1EFF) — covers Vietnamese tones
        and other precomposed Latin forms.
    """
    # Pass 1: "non-Latin-word (romanisation)" → "romanisation"
    text = re.sub(
        r'[^\x00-\x7FÀ-ɏḀ-ỿ]+\s*\(([^)]+)\)',
        r'\1',
        text,
    )
    # Pass 2: drop remaining non-speakable code-points
    kept = [
        ch for ch in text
        if ord(ch) <= 0x7F
        or 0x00C0 <= ord(ch) <= 0x024F
        or 0x1E00 <= ord(ch) <= 0x1EFF
    ]
    return re.sub(r'  +', ' ', ''.join(kept)).strip()

log = logging.getLogger("ph3b3.tts")

VOICE_DIR   = Path.home() / "ph3b3_data" / "voices"
VOICE_MODEL = os.getenv("PH3B3_VOICE_MODEL", str(VOICE_DIR / "en_GB-alba-medium.onnx"))
# Command that plays raw s16le/22050/mono PCM on stdin. Default is aplay (ALSA,
# unchanged for Nyx). Athena has no ALSA device but a WSLg PulseAudio bridge, so
# it sets PH3B3_AUDIO_PLAYER=paplay ... in .env. The "22050" token below is
# rewritten per-voice when a voice uses a different sample rate (e.g. x_low=16k).
AUDIO_PLAYER = os.getenv("PH3B3_AUDIO_PLAYER", "aplay -r 22050 -f S16_LE -c 1 -t raw")


def _voice_cfg(onnx_path) -> dict:
    """Load the sibling <name>.onnx.json Piper config, or {} on failure."""
    try:
        with open(str(onnx_path) + ".json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _rate_for(onnx_path) -> int:
    """Piper output sample rate for a model (default 22050)."""
    try:
        return int((_voice_cfg(onnx_path).get("audio") or {}).get("sample_rate") or 22050)
    except Exception:
        return 22050


def _voice_meta(onnx_path: Path) -> dict:
    """Best-effort language/quality/name metadata for one .onnx voice."""
    cfg = _voice_cfg(onnx_path)
    lang = cfg.get("language") or {}
    stem = onnx_path.stem
    parts = stem.split("-")
    code = lang.get("code") or lang.get("family") or (parts[0] if parts else stem)
    name = lang.get("name_english") or lang.get("name_native") or code
    quality = (cfg.get("audio") or {}).get("quality") or (parts[2] if len(parts) >= 3 else "")
    dataset = cfg.get("dataset") or (parts[1] if len(parts) >= 2 else stem)
    return {"language_code": code, "language": name, "quality": quality, "dataset": dataset}


class TTSModule:
    def __init__(self):
        self._lock = threading.Lock()
        # Active voice model. Defaults to Alba (PH3B3_VOICE_MODEL) and is
        # runtime-switchable via set_voice(); the default is never mutated, so
        # the Alba config and boot greeting are unchanged.
        self._current_model = VOICE_MODEL
        self._available = self._any_voice_available()
        if Path(self._current_model).exists():
            log.info(f"Piper TTS ready: {Path(self._current_model).stem}")
        else:
            log.warning(f"Voice model not found at {self._current_model}")

    def _any_voice_available(self) -> bool:
        if Path(self._current_model).exists():
            return True
        try:
            return any(VOICE_DIR.glob("*.onnx"))
        except Exception:
            return False

    # ── Voice registry (server owns this; the web client stays thin) ─────────
    def list_voices(self) -> list:
        """Every installed Piper voice, with the active one flagged."""
        cur = Path(self._current_model).stem
        out = []
        try:
            for onnx in sorted(VOICE_DIR.glob("*.onnx")):
                m = _voice_meta(onnx)
                vid = onnx.stem
                ds = (m["dataset"] or vid).replace("_", " ").title()
                q = m["quality"] or ""
                label = f"{ds} — {m['language']}" + (f" ({q})" if q else "")
                out.append({
                    "id": vid,
                    "label": label,
                    "language": m["language"],
                    "language_code": m["language_code"],
                    "quality": q,
                    "current": vid == cur,
                })
        except Exception as e:
            log.error(f"list_voices error: {e}")
        return out

    def current_voice_id(self) -> str:
        return Path(self._current_model).stem

    def _voice_path(self, voice_id: str):
        """Resolve a voice id to a real .onnx inside VOICE_DIR, or None. Path-safe."""
        if not voice_id or "/" in voice_id or "\\" in voice_id or ".." in voice_id:
            return None
        path = VOICE_DIR / f"{voice_id}.onnx"
        return path if path.exists() else None

    def set_voice(self, voice_id: str) -> bool:
        """Switch the active voice by id (filename stem). Alba stays the default."""
        path = self._voice_path(voice_id)
        if path is None:
            return False
        with self._lock:
            self._current_model = str(path)
        log.info(f"Voice switched to {voice_id}")
        return True

    # ── Speech ───────────────────────────────────────────────────────────────
    def speak(self, text, blocking=True):
        if not self._available:
            log.info(f"[TTS silent] {text[:80]}")
            return "TTS not available."
        if not text or not text.strip():
            return "Nothing to say."
        tts_text = _strip_for_piper(text)
        if not tts_text:
            return "Nothing to say."
        if blocking:
            self._speak_now(tts_text)
        else:
            t = threading.Thread(target=self._speak_now, args=(tts_text,), daemon=True)
            t.start()
        return f"Speaking: {text[:60]}"

    def _speak_now(self, text, model=None):
        model = model or self._current_model
        # Match the player's sample rate to the voice (x_low voices are 16 kHz).
        player = re.sub(r'\b22050\b', str(_rate_for(model)), AUDIO_PLAYER)
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([text])} | piper --model {model} --output-raw | {player}'
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                log.error(f"TTS error: {e}")

    def synthesize_to_b64(self, text: str, model: str | None = None) -> str | None:
        """Run Piper and return base64-encoded WAV, or None if unavailable.

        `model` lets callers (e.g. voice preview) render with a specific voice
        without changing the active one. The WAV header uses that voice's own
        sample rate, so non-22050 voices (x_low = 16 kHz) play at correct pitch.
        """
        model = model or self._current_model
        if not self._available or not text or not text.strip():
            return None
        tts_text = _strip_for_piper(text)
        if not tts_text:
            return None
        rate = _rate_for(model)
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([tts_text])} | piper --model {model} --output-raw'
                proc = subprocess.run(cmd, shell=True, capture_output=True)
                raw_pcm = proc.stdout
                if not raw_pcm:
                    return None
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(rate)
                    wf.writeframes(raw_pcm)
                return base64.b64encode(buf.getvalue()).decode('ascii')
            except Exception as e:
                log.error(f"TTS synthesize error: {e}")
                return None

    def preview_b64(self, voice_id: str, text: str | None = None) -> str | None:
        """Render a short sample with a specific installed voice (no switch)."""
        path = self._voice_path(voice_id)
        if path is None:
            return None
        sample = text or "Hello — this is a preview of how I sound."
        return self.synthesize_to_b64(sample, model=str(path))

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(self._current_model).stem}"
        return "Piper TTS not available."
