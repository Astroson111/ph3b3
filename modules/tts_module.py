import base64
import io
import os
import logging
import re
import subprocess
import sys
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

AUDIO_DEVICE = os.getenv("PH3B3_AUDIO_DEVICE", "default")

_VENV_BIN   = Path(sys.executable).parent
_PIPER_VENV = str(_VENV_BIN / "piper")
PIPER_BIN   = os.getenv("PIPER_BIN") or (_PIPER_VENV if Path(_PIPER_VENV).exists() else "piper")

# Stable node.name for the intended TTS output — used only for sink-mismatch warnings.
_EXPECTED_SINK = "alsa_output.pci-0000_01_00.1.hdmi-stereo"

log.info(f"TTS audio device: {AUDIO_DEVICE!r}  piper: {PIPER_BIN!r}")


def _warn_if_sink_wrong() -> None:
    """Log a warning if WirePlumber's default sink is not the expected HDMI output."""
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=2,
            env={**os.environ, "XDG_RUNTIME_DIR": os.getenv("XDG_RUNTIME_DIR", "/run/user/1000")},
        )
        current = result.stdout.strip()
        if current and current != _EXPECTED_SINK:
            log.warning(
                f"TTS sink mismatch — expected {_EXPECTED_SINK!r}, "
                f"got {current!r}. Audio will go to the wrong output."
            )
    except Exception:
        pass


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
        _warn_if_sink_wrong()
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([text])} | {PIPER_BIN} --model {VOICE_MODEL} --output-raw | aplay -r 22050 -f S16_LE -c 1 -t raw -D {AUDIO_DEVICE}'
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
                cmd = f'echo {subprocess.list2cmdline([tts_text])} | {PIPER_BIN} --model {VOICE_MODEL} --output-raw'
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

    def soul_line(self):
        self.speak("Made with Soul, baby.", blocking=False)

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(VOICE_MODEL).stem}"
        return "Piper TTS not available."