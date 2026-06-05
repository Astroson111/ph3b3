import os
import re
import logging
from datetime import datetime

log = logging.getLogger("ph3b3.translator")
BASE_LOG_DIR = os.path.abspath(os.path.expanduser("~/ph3b3_data/translation_logs"))

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False
    GoogleTranslator = None
    log.warning("deep-translator not installed.")

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

class TranslationModule:
    def __init__(self):
        self.target_lang = "es"
        os.makedirs(BASE_LOG_DIR, mode=0o755, exist_ok=True)
        log.info("Translation module ready.")

    def translate(self, text, target_lang=None):
        if not TRANSLATOR_AVAILABLE:
            return {"error": "deep-translator not installed", "text": text}
        if not text or not text.strip():
            return {"error": "No text provided", "text": ""}
        target = (target_lang or self.target_lang).lower().strip()
        try:
            translated = GoogleTranslator(source="auto", target=target).translate(text)
            self._save_log(text, translated, target)
            return {"original": text, "translated": translated, "target_lang": target, "error": None}
        except Exception as e:
            return {"error": str(e), "text": text}

    def set_default_language(self, lang):
        self.target_lang = lang.lower().strip()
        return f"Default language set to {self.target_lang}"

    def listen_and_translate(self, target_lang=None):
        if not SR_AVAILABLE:
            return {"error": "SpeechRecognition not installed", "text": ""}
        recognized = self._capture_voice()
        if not recognized:
            return {"error": "Could not capture audio", "text": ""}
        result = self.translate(recognized, target_lang)
        result["recognized"] = recognized
        return result

    def _capture_voice(self):
        try:
            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=20)
                return recognizer.recognize_google(audio)
        except Exception as e:
            log.warning(f"Voice capture failed: {e}")
            return None

    def _save_log(self, original, translated, target_lang):
        try:
            clean_lang = re.sub(r'[^a-zA-Z]', '', target_lang)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"Trans_{clean_lang}_{timestamp}.txt"
            target_path = os.path.abspath(os.path.join(BASE_LOG_DIR, filename))
            if not target_path.startswith(BASE_LOG_DIR):
                log.warning("Security block: invalid path")
                return
            with open(target_path, "w") as f:
                f.write(f"DATE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"ORIGINAL:\n{original}\n\nTRANSLATED:\n{translated}\n")
        except Exception as e:
            log.warning(f"Could not save translation log: {e}")