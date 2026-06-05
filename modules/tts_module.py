import base64
import io
import os
import logging
import subprocess
import threading
import wave
from pathlib import Path

log = logging.getLogger("ph3b3.tts")

VOICE_DIR   = Path.home() / "ph3b3_data" / "voices"
VOICE_MODEL = os.getenv("PH3B3_VOICE_MODEL", str(VOICE_DIR / "en_GB-alba-medium.onnx"))

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
        if blocking:
            self._speak_now(text)
        else:
            t = threading.Thread(target=self._speak_now, args=(text,), daemon=True)
            t.start()
        return f"Speaking: {text[:60]}"

    def _speak_now(self, text):
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([text])} | piper --model {VOICE_MODEL} --output-raw | aplay -r 22050 -f S16_LE -c 1 -t raw'
                subprocess.run(cmd, shell=True, check=True)
            except Exception as e:
                log.error(f"TTS error: {e}")

    def synthesize_to_b64(self, text: str) -> str | None:
        """Run Piper and return base64-encoded WAV, or None if unavailable."""
        if not self._available or not text or not text.strip():
            return None
        with self._lock:
            try:
                cmd = f'echo {subprocess.list2cmdline([text])} | piper --model {VOICE_MODEL} --output-raw'
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