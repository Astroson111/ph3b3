import os
import logging
import threading

log = logging.getLogger("ph3b3.stt")

WHISPER_MODEL = os.getenv("PH3B3_WHISPER_MODEL", "medium")

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    log.warning("openai-whisper not installed. Run: pip install openai-whisper")

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

class STTModule:
    def __init__(self):
        self._model     = None
        self._available = False
        self._loading   = False
        if WHISPER_AVAILABLE:
            self._loading = True
            threading.Thread(target=self._load_model, daemon=True).start()
        else:
            log.warning("Whisper unavailable — falling back to SpeechRecognition")

    def _load_model(self):
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            log.info(f"Loading Whisper {WHISPER_MODEL} on {device}...")
            self._model     = whisper.load_model(WHISPER_MODEL, device=device)
            self._available = True
            self._loading   = False
            log.info(f"Whisper {WHISPER_MODEL} ready on {device}")
        except Exception as e:
            log.error(f"Whisper load error: {e}")
            self._loading = False

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
            sample_rate = 16000
            audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
            sd.wait()
            audio_flat = audio.flatten()
            options = {}
            if language:
                options["language"] = language
            result = self._model.transcribe(audio_flat, **options)
            return {"text": result.get("text","").strip(), "language": result.get("language",""), "error": None}
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
        options = {}
        if language:
            options["language"] = language
        try:
            result = self._model.transcribe(filepath, **options)
            return {"text": result.get("text","").strip(), "language": result.get("language",""), "error": None}
        except Exception as e:
            if "CUDA" in str(e) and self._model is not None:
                log.warning("CUDA error in transcription — falling back to CPU")
                try:
                    self._model = self._model.to("cpu")
                    result = self._model.transcribe(filepath, **options)
                    return {"text": result.get("text","").strip(), "language": result.get("language",""), "error": None}
                except Exception as cpu_e:
                    return {"text": None, "error": f"Transcription error (CPU fallback): {cpu_e}"}
            return {"text": None, "error": str(e)}

    def status(self):
        if self._loading: return f"Whisper {WHISPER_MODEL} loading..."
        if self._available:
            import torch
            return f"Whisper {WHISPER_MODEL} ready on {'cuda' if torch.cuda.is_available() else 'cpu'}"
        if SR_AVAILABLE: return "Whisper unavailable — using Google fallback"
        return "No speech recognition available"
