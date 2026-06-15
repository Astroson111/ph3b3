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
    """Resolve the TTS playback device, PipeWire-native where possible.

    Resolution order:
      1. PH3B3_AUDIO_DEVICE env var — used verbatim if set.
      2. pactl list short sinks — find the first sink whose name contains
         'USB_Audio' (the stable fragment in PipeWire sink names for Generic
         USB Audio devices) while excluding 'fifine' / 'Microphone' entries.
         Pins it as the PipeWire session default via `pactl set-default-sink`
         so every subsequent `aplay -D default` call routes there automatically.
         Returns 'default' (ALSA default device → PipeWire default sink).
      3. aplay -l scan — legacy ALSA fallback when pactl is absent.
         Matches card long-name 'USB Audio', device 1.
      4. fallback ('default') — let the system decide; logs a warning.
    """
    explicit = os.getenv("PH3B3_AUDIO_DEVICE")
    if explicit:
        log.info(f"TTS audio: {explicit!r} (PH3B3_AUDIO_DEVICE override)")
        return explicit

    # ── PipeWire-native: stable sink name, survives card-index renumbers ──
    try:
        out = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            # format: "<idx>\t<name>\t<driver>\t<sample_spec>\t<state>"
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if "USB_Audio" in name and "fifine" not in name.lower() and "Microphone" not in name:
                subprocess.run(
                    ["pactl", "set-default-sink", name],
                    capture_output=True, timeout=5,
                )
                log.info(f"TTS audio: default → PipeWire sink {name!r}")
                return "default"
    except Exception:
        pass

    # ── Legacy ALSA fallback: scan aplay -l by card long-name ─────────────
    try:
        out = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            # "card N: ShortName [Long Name], device D: ..."
            m = re.match(r"card (\d+):[^[]+\[([^\]]+)\],\s*device 1:", line)
            if m and m.group(2) == "USB Audio":
                dev = f"plughw:{m.group(1)},1"
                log.info(f"TTS audio: {dev!r} (ALSA scan fallback)")
                return dev
    except Exception:
        pass

    log.warning(f"TTS audio: {fallback!r} (system default — USB sink not found)")
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