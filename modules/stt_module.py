import os
import re
import logging
import threading

log = logging.getLogger("ph3b3.stt")

WHISPER_MODEL = os.getenv("PH3B3_WHISPER_MODEL", "medium")
STT_LANGUAGE  = "en"
# ── Hallucination gate thresholds (post-Whisper) ─────────────────────────────
# Whisper invents fluent phrases from silence/noise. It also reports its own
# confidence per segment: no_speech_prob (↑ = probably not speech) and
# avg_logprob (↓ = low-confidence decode). Drop on either, plus known boilerplate
# ("thanks for watching", "ready to board") when the decode isn't confident.
NO_SPEECH_MAX     = float(os.getenv("PH3B3_STT_NO_SPEECH_MAX", "0.6"))   # avg no_speech_prob above → drop
AVG_LOGPROB_MIN   = float(os.getenv("PH3B3_STT_LOGPROB_MIN",  "-1.0"))   # avg_logprob below → drop
BOILERPLATE_LOGPROB_MIN = float(os.getenv("PH3B3_STT_BOILERPLATE_LOGPROB", "-0.55"))  # boilerplate kept only above this
# Normalised (lowercase, letters+spaces only) phrases Whisper emits from silence.
# Kept ONLY when the decode is confident (avg_logprob ≥ BOILERPLATE_LOGPROB_MIN),
# so a real, clearly-spoken "thank you" survives but a mumbled phantom does not.
_BOILERPLATE = {
    "thank you", "thanks for watching", "thank you for watching",
    "thanks for watching everyone", "thank you very much", "thank you so much",
    "please subscribe", "subscribe", "like and subscribe", "see you next time",
    "you", "bye", "bye bye", "okay", "ok", "so", "the",
    "ready to board take off", "ready to board", "take off",
    "new york city", "i'm not sure", "i don't know",
}
# under a forced-English lock, any CJK/Cyrillic/Greek/Hebrew/Arabic output is a hallucination
_NON_LATIN = re.compile(r'[Ͱ-ϿЀ-ӿ֐-׿؀-ۿ぀-ヿ㐀-鿿가-힯]')


def _seg_stats(result):
    """(avg_no_speech_prob, avg_logprob) over segments, or (None, None)."""
    segs = result.get("segments") or []
    if not segs:
        return None, None
    ns = sum(s.get("no_speech_prob", 0.0) for s in segs) / len(segs)
    lp = sum(s.get("avg_logprob", 0.0) for s in segs) / len(segs)
    return ns, lp


def _stt_options(language=None):
    return {
        "language": language or STT_LANGUAGE,
        "task": "transcribe",
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "no_speech_threshold": NO_SPEECH_MAX,
        "logprob_threshold": -1.0,
    }


def _accept(result):
    """Return (text, discard_reason). text is '' when the decode looks like a
    silence hallucination; discard_reason is a short string for the audit log
    (None when accepted)."""
    text = (result.get("text") or "").strip()
    if not text:
        return "", "empty"
    avg_ns, avg_lp = _seg_stats(result)
    if avg_ns is not None and avg_ns > NO_SPEECH_MAX:
        return "", f"no_speech_prob {avg_ns:.2f}>{NO_SPEECH_MAX}"
    if avg_lp is not None and avg_lp < AVG_LOGPROB_MIN:
        return "", f"avg_logprob {avg_lp:.2f}<{AVG_LOGPROB_MIN}"
    if _NON_LATIN.search(text):
        return "", "non-latin (English lock)"
    norm = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if norm in _BOILERPLATE and (avg_lp is None or avg_lp < BOILERPLATE_LOGPROB_MIN):
        return "", f"boilerplate '{text}' (avg_logprob {avg_lp})"
    return text, None

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
            rms = float(np.sqrt(np.mean(audio_flat**2))) if audio_flat.size else 0.0
            if rms < 0.004:
                return {"text": None, "language": STT_LANGUAGE, "error": None}
            result = self._model.transcribe(audio_flat, **_stt_options(language))
            text, _reason = _accept(result)
            return {"text": text or None, "language": result.get("language", ""), "error": None}
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
        options = _stt_options(language)
        try:
            result = self._model.transcribe(filepath, **options)
            return self._result(result)
        except Exception as e:
            if "CUDA" in str(e) and self._model is not None:
                log.warning("CUDA error in transcription — falling back to CPU")
                try:
                    self._model = self._model.to("cpu")
                    result = self._model.transcribe(filepath, **options)
                    return self._result(result)
                except Exception as cpu_e:
                    return {"text": None, "error": f"Transcription error (CPU fallback): {cpu_e}"}
            return {"text": None, "error": str(e)}

    def _result(self, result):
        """Wrap a raw Whisper result with the hallucination gate's verdict:
        accepted text (None if discarded), the raw decode, why it was discarded,
        and the confidence signals — so the server can log/label the audit trail."""
        text, reason = _accept(result)
        avg_ns, avg_lp = _seg_stats(result)
        return {"text": text or None, "error": None,
                "discard_reason": reason,
                "raw_text": (result.get("text") or "").strip(),
                "no_speech_prob": avg_ns, "avg_logprob": avg_lp,
                "language": result.get("language", "")}

    def status(self):
        if self._loading: return f"Whisper {WHISPER_MODEL} loading..."
        if self._available:
            import torch
            return f"Whisper {WHISPER_MODEL} ready on {'cuda' if torch.cuda.is_available() else 'cpu'}"
        if SR_AVAILABLE: return "Whisper unavailable — using Google fallback"
        return "No speech recognition available"
