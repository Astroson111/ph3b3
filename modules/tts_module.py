import base64
import io
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


def _resolve_audio_device(fallback: str = "default") -> str:
    """Resolve the TTS playback device.

    Resolution order:
      1. PH3B3_AUDIO_DEVICE env var — used verbatim if set.
      2. PipeWire default sink — trust WirePlumber's configured default
         (HDMI locked at priority 1300 via /etc/wireplumber/main.lua.d/).
         aplay -D default routes there automatically.
      3. fallback ('default') — should never reach here under normal operation.
    """
    explicit = os.getenv("PH3B3_AUDIO_DEVICE")
    if explicit:
        log.info(f"TTS audio: {explicit!r} (PH3B3_AUDIO_DEVICE override)")
        return explicit

    # ── Trust WirePlumber's default — HDMI is locked at high priority ──
    try:
        sink = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if sink:
            log.info(f"TTS audio: default → PipeWire default sink ({sink!r})")
            return "default"
    except Exception:
        pass

    log.warning(f"TTS audio: {fallback!r} (pactl unavailable — using system default)")
    return fallback


AUDIO_DEVICE = _resolve_audio_device()


class TTSModule:
    def __init__(self):
        self._lock      = threading.Lock()
        self._available = Path(VOICE_MODEL).exists()
        if self._available:
            log.info(f"Piper TTS ready: {Path(VOICE_MODEL).stem}")
        else:
            log.warning(f"Voice model not found at {VOICE_MODEL}")

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

    def _speak_now(self, text):
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([text])} | piper --model {VOICE_MODEL} --output-raw | aplay -r 22050 -f S16_LE -c 1 -t raw -D {AUDIO_DEVICE}'
                subprocess.run(cmd, shell=True, check=True, timeout=30)
            except subprocess.TimeoutExpired:
                log.warning("TTS timed out after 30 s — audio device may not be ready")
            except Exception as e:
                log.error(f"TTS error: {e}")

    def synthesize_to_b64(self, text: str) -> str | None:
        """Run Piper and return base64-encoded WAV, or None if unavailable."""
        if not self._available or not text or not text.strip():
            return None
        tts_text = _strip_for_piper(text)
        if not tts_text:
            return None
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([tts_text])} | piper --model {VOICE_MODEL} --output-raw'
                proc = subprocess.run(cmd, shell=True, capture_output=True)
                raw_pcm = proc.stdout
                if not raw_pcm:
                    return None
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(22050)
                    wf.writeframes(raw_pcm)
                return base64.b64encode(buf.getvalue()).decode('ascii')
            except Exception as e:
                log.error(f"TTS synthesize error: {e}")
                return None

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(VOICE_MODEL).stem}"
        return "Piper TTS not available."