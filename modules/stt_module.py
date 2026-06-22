import os
import logging
import subprocess
import threading

import numpy as np

log = logging.getLogger("ph3b3.stt")

# whisper.cpp ggml model name: tiny, base, small, medium, large (and .en variants).
# Larger = more accurate, slower. Switch via .env (PH3B3_WHISPER_MODEL) — no code change.
WHISPER_MODEL = os.getenv("PH3B3_WHISPER_MODEL", "medium")
# CPU threads for whisper.cpp inference. Defaults to all cores; more threads = faster.
WHISPER_THREADS = int(os.getenv("PH3B3_WHISPER_THREADS", str(os.cpu_count() or 8)))
WHISPER_SAMPLE_RATE = 16000

try:
    from pywhispercpp.model import Model as _WhisperCppModel
    WHISPERCPP_AVAILABLE = True
except ImportError:
    WHISPERCPP_AVAILABLE = False
    log.warning("pywhispercpp not installed. Run: pip install pywhispercpp")

try:
    import sounddevice as sd
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False


def _decode_to_16k_mono(filepath):
    """Decode any audio file to 16 kHz mono float32 via ffmpeg.

    whisper.cpp (pywhispercpp) only accepts 16 kHz mono input, whereas the
    device / Piper may produce other sample rates. ffmpeg resamples robustly,
    matching how openai-whisper loaded audio internally.
    """
    cmd = ["ffmpeg", "-nostdin", "-threads", "0", "-i", filepath,
           "-f", "f32le", "-ac", "1", "-ar", str(WHISPER_SAMPLE_RATE), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-300:]
        raise RuntimeError(f"ffmpeg decode failed: {tail}")
    return np.frombuffer(proc.stdout, np.float32)


class STTModule:
    def __init__(self):
        self._model     = None
        self._available = False
        self._loading   = False
        if WHISPERCPP_AVAILABLE:
            self._loading = True
            threading.Thread(target=self._load_model, daemon=True).start()
        else:
            log.warning("whisper.cpp unavailable — falling back to SpeechRecognition")

    def _load_model(self):
        try:
            log.info(f"Loading whisper.cpp {WHISPER_MODEL} on CPU ({WHISPER_THREADS} threads)...")
            self._model = _WhisperCppModel(
                WHISPER_MODEL,
                n_threads=WHISPER_THREADS,
                print_progress=False,
                print_realtime=False,
            )
            self._available = True
            self._loading   = False
            log.info(f"whisper.cpp {WHISPER_MODEL} ready (CPU, {WHISPER_THREADS} threads)")
        except Exception as e:
            log.error(f"whisper.cpp load error: {e}")
            self._loading = False

    def _transcribe_array(self, audio, language=None):
        params = {}
        if language:
            params["language"] = language
        segments = self._model.transcribe(audio, **params)
        return " ".join(seg.text for seg in segments).strip()

    def listen(self, duration_seconds=10, language=None):
        if self._loading:
            return {"text": None, "error": "Whisper still loading — try again in a moment."}
        if self._available:
            return self._listen_whisper(duration_seconds, language)
        elif SR_AVAILABLE:
            return self._listen_sr()
        return {"text": None, "error": "No speech recognition available."}

    def _listen_whisper(self, duration, language=None):
        if not AUDIO_AVAILABLE:
            return {"text": None, "error": "sounddevice not installed"}
        try:
            audio = sd.rec(int(duration * WHISPER_SAMPLE_RATE),
                           samplerate=WHISPER_SAMPLE_RATE, channels=1, dtype='float32')
            sd.wait()
            text = self._transcribe_array(audio.flatten(), language)
            return {"text": text, "language": language or "", "error": None}
        except Exception as e:
            return {"text": None, "error": str(e)}

    def _listen_sr(self):
        try:
            recognizer = sr.Recognizer()
            recognizer.pause_threshold = 2.0
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=20)
            text = recognizer.recognize_google(audio)
            return {"text": text, "language": "unknown", "error": None, "fallback": True}
        except Exception as e:
            return {"text": None, "error": str(e)}

    def transcribe_file(self, filepath, language=None):
        if self._loading:
            return {"text": None, "error": "Whisper still loading — try again in a moment."}
        if not self._available:
            return {"text": None, "error": "Whisper not available"}
        try:
            audio = _decode_to_16k_mono(filepath)
            text = self._transcribe_array(audio, language)
            return {"text": text, "language": language or "", "error": None}
        except Exception as e:
            return {"text": None, "error": str(e)}

    def status(self):
        if self._loading:
            return f"whisper.cpp {WHISPER_MODEL} loading..."
        if self._available:
            return f"whisper.cpp {WHISPER_MODEL} ready (CPU, {WHISPER_THREADS} threads)"
        if SR_AVAILABLE:
            return "Whisper unavailable — using Google fallback"
        return "No speech recognition available"
