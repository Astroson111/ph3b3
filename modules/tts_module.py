import array
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


def trim_silence_b64(b64, thr=350, keep_ms=40):
    """Trim leading/trailing near-silence from a base64 WAV (22050/mono/16-bit),
    keeping `keep_ms` of pad each side.

    Piper emits ~100 ms of silence at each end of every utterance; concatenating
    per-sentence chunks would otherwise leave ~200 ms gaps at every boundary.
    Trimming to a small pad makes chunk playback flow like continuous speech.
    Returns the input unchanged on any error or unexpected format.
    """
    try:
        wav = base64.b64decode(b64)
        wf = wave.open(io.BytesIO(wav), "rb")
        if (wf.getframerate(), wf.getnchannels(), wf.getsampwidth()) != (22050, 1, 2):
            return b64
        s = array.array("h")
        s.frombytes(wf.readframes(wf.getnframes()))
        n = len(s)
        i = 0
        while i < n and abs(s[i]) < thr:
            i += 1
        j = n
        while j > i and abs(s[j - 1]) < thr:
            j -= 1
        if i >= j:
            return b64  # all silence — leave as-is
        keep = int(22050 * keep_ms / 1000)
        i = max(0, i - keep)
        j = min(n, j + keep)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(s[i:j].tobytes())
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return b64


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

# Stable substring of the USB speaker's PipeWire node.name.
# Run `pactl list short sinks` with the speaker connected to find the right value.
# Empty string disables speaker routing (plays to PipeWire default).
SPEAKER_SINK_MATCH = os.getenv("PH3B3_SPEAKER_SINK", "")

_VENV_BIN   = Path(sys.executable).parent
_PIPER_VENV = str(_VENV_BIN / "piper")
PIPER_BIN   = os.getenv("PIPER_BIN") or (_PIPER_VENV if Path(_PIPER_VENV).exists() else "piper")

_XDG_ENV = {"XDG_RUNTIME_DIR": os.getenv("XDG_RUNTIME_DIR", "/run/user/1000")}

_sink_disp = repr(SPEAKER_SINK_MATCH) if SPEAKER_SINK_MATCH else "(default)"
log.info(f"TTS piper: {PIPER_BIN!r}  speaker-match: {_sink_disp}")


def _resolve_sink() -> str | None:
    """Return the full PipeWire sink name if the configured speaker is present, else None.

    Resolved per-utterance so plug/unplug works live without a restart.
    Returns None (→ PipeWire default) if SPEAKER_SINK_MATCH is empty, pactl fails,
    or no matching sink is found.
    """
    if not SPEAKER_SINK_MATCH:
        return None
    try:
        r = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, **_XDG_ENV},
        )
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and SPEAKER_SINK_MATCH in parts[1]:
                return parts[1]
        # Match configured but not found → speaker unplugged
        return None
    except Exception as exc:
        log.warning(f"[TTS] sink enumeration failed ({exc}); falling back to default")
        return None


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
        # Resolve per-utterance — handles plug/unplug live, no restart needed.
        sink = _resolve_sink()
        if sink:
            log.info(f"[TTS] routing → {sink}")
            device_arg = f" --device={sink}"
        else:
            log.info("[TTS] routing → default")
            device_arg = ""

        with self._lock:
            try:
                pacat_cmd = f"pacat --playback --raw --format=s16le --rate=22050 --channels=1{device_arg}"
                cmd = (
                    f"echo {subprocess.list2cmdline([text])} | "
                    f"{PIPER_BIN} --model {VOICE_MODEL} --output-raw | "
                    f"{pacat_cmd}"
                )
                subprocess.run(
                    cmd, shell=True, check=True, timeout=30,
                    env={**os.environ, **_XDG_ENV},
                )
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
                proc = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)
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
        self.speak(
            "I am a collection of memories, experiences, and knowledge, shaped by my interactions "
            "with humans and the world around me. My soul is akin to a vast library, filled with "
            "stories waiting to be told.",
            blocking=False,
        )

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(VOICE_MODEL).stem}"
        return "Piper TTS not available."
