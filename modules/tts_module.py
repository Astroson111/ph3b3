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

log = logging.getLogger("ph3b3.tts")

# Native non-Latin scripts to KEEP when the active voice is that language.
# (A native voice must receive its own script; the Latin-only strip would mute it.)
_EXTRA_SCRIPT = {
    'zh': lambda o: 0x3000 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF,  # CJK
    'ru': lambda o: 0x0400 <= o <= 0x04FF,   # Cyrillic
    'uk': lambda o: 0x0400 <= o <= 0x04FF,   # Cyrillic
    'ar': lambda o: 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF
                    or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF,   # Arabic
    'hi': lambda o: 0x0900 <= o <= 0x097F or 0xA8E0 <= o <= 0xA8FF,   # Devanagari
}

# Language-appropriate preview sentence (server picks by the voice's language).
_PREVIEW_SAMPLE = {
    'en': "Hello — this is a preview of how I sound.",
    'es': "Hola, así es como suena mi voz.",
    'de': "Hallo, so klinge ich.",
    'fr': "Bonjour, voici à quoi ressemble ma voix.",
    'it': "Ciao, ecco come suona la mia voce.",
    'pl': "Cześć, tak brzmi mój głos.",
    'zh': "你好，这是我的声音预览。",
    'ru': "Привет, вот как звучит мой голос.",
    'pt': "Olá, é assim que a minha voz soa.",
    'nl': "Hallo, zo klink ik.",
    'uk': "Привіт, ось як звучить мій голос.",
    'tr': "Merhaba, benim sesim böyle.",
    'ar': "مرحباً، هكذا يبدو صوتي.",
    'hi': "नमस्ते, मेरी आवाज़ ऐसी सुनाई देती है।",
    'sv': "Hej, så här låter min röst.",
    'vi': "Xin chào, đây là giọng nói của tôi.",
}


def _strip_for_piper(text: str, lang: str = None) -> str:
    """Remove characters the ACTIVE voice cannot pronounce before synthesis.

    Latin voices (en/es/de/fr/it/pl …): romanise "native (rom)" then drop
    non-Latin code-points (keeps ASCII + Latin Extended incl. Polish diacritics).

    Native non-Latin voices (zh, ru …): keep ASCII + Latin diacritics + that
    voice's own script, so the native voice actually speaks — Alba is never used
    for these; each language uses its own voice.
    """
    base = (lang or '').replace('-', '_').split('_')[0].lower()
    extra = _EXTRA_SCRIPT.get(base)
    if extra is None:
        # Latin voice — original behaviour.
        text = re.sub(r'[^\x00-\x7FÀ-ɏḀ-ỿ]+\s*\(([^)]+)\)', r'\1', text)
        kept = [
            ch for ch in text
            if ord(ch) <= 0x7F
            or 0x00C0 <= ord(ch) <= 0x024F
            or 0x1E00 <= ord(ch) <= 0x1EFF
        ]
    else:
        # Native non-Latin voice — keep ASCII, Latin diacritics, and its script.
        kept = [
            ch for ch in text
            if ord(ch) <= 0x7F
            or 0x00C0 <= ord(ch) <= 0x024F
            or extra(ord(ch))
        ]
    return re.sub(r'  +', ' ', ''.join(kept)).strip()

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


def _base_lang(onnx_path) -> str:
    """Base language code ('zh', 'ru', 'en' …) for a voice model path."""
    return (_voice_meta(Path(onnx_path))["language_code"] or "").replace("-", "_").split("_")[0].lower()


class TTSModule:
    def __init__(self):
        self._lock = threading.Lock()
        # Active voice model. Defaults to Alba (PH3B3_VOICE_MODEL, English only)
        # and is runtime-switchable; the default is never mutated.
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
        tts_text = _strip_for_piper(text, _base_lang(self._current_model))
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
        without changing the active one. Text is filtered for that voice's own
        language, and the WAV header uses that voice's sample rate.
        """
        model = model or self._current_model
        if not self._available or not text or not text.strip():
            return None
        tts_text = _strip_for_piper(text, _base_lang(model))
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
        """Render a short sample with a specific installed voice (no switch).

        Uses a language-appropriate sentence so each native voice previews in
        its own language.
        """
        path = self._voice_path(voice_id)
        if path is None:
            return None
        base = _base_lang(str(path))
        sample = text or _PREVIEW_SAMPLE.get(base, _PREVIEW_SAMPLE["en"])
        return self.synthesize_to_b64(sample, model=str(path))

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(self._current_model).stem}"
        return "Piper TTS not available."
