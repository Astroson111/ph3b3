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

# Languages whose scripts are non-Latin and need romanization.
# Keyed on the base language code (before any hyphen).
NON_LATIN_LANGS = {
    'ja', 'zh', 'ko', 'ar', 'ru', 'uk', 'bg', 'sr', 'mk', 'be',
    'hi', 'mr', 'ne', 'th', 'el', 'he', 'fa', 'bn', 'gu', 'ta',
    'te', 'kn', 'ml', 'si', 'my', 'km', 'lo', 'ka', 'am', 'mn',
}

# deep_translator / Google Translate requires exact casing for a handful of codes.
_TRANSLATOR_CODE = {
    'zh-cn': 'zh-CN',
    'zh-tw': 'zh-TW',
    'mni-mtei': 'mni-Mtei',
}

LANG_NAMES = {
    'ja': 'Japanese',       'zh': 'Chinese',
    'zh-cn': 'Chinese',     'zh-tw': 'Chinese (Traditional)',
    'ko': 'Korean',         'ar': 'Arabic',
    'ru': 'Russian',        'uk': 'Ukrainian',
    'bg': 'Bulgarian',      'sr': 'Serbian',
    'mk': 'Macedonian',     'be': 'Belarusian',
    'hi': 'Hindi',          'mr': 'Marathi',
    'ne': 'Nepali',         'th': 'Thai',
    'el': 'Greek',          'he': 'Hebrew',
    'fa': 'Persian',        'bn': 'Bengali',
    'gu': 'Gujarati',       'ta': 'Tamil',
    'te': 'Telugu',         'kn': 'Kannada',
    'ml': 'Malayalam',      'si': 'Sinhala',
    'my': 'Burmese',        'km': 'Khmer',
    'lo': 'Lao',            'ka': 'Georgian',
    'am': 'Amharic',        'mn': 'Mongolian',
}


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
        translator_target = _TRANSLATOR_CODE.get(target, target)
        try:
            translated = GoogleTranslator(source="auto", target=translator_target).translate(text)
            display = self._format(translated, target)
            self._save_log(text, display, target)
            return {"original": text, "translated": display, "target_lang": target, "error": None}
        except Exception as e:
            return {"error": str(e), "text": text}

    def _format(self, translated: str, target: str) -> str:
        """Attach romanization for non-Latin scripts: 'Japanese: こんにちは (Konnichiwa)'"""
        base = target.split('-')[0]
        if base not in NON_LATIN_LANGS:
            return translated

        lang_name = LANG_NAMES.get(target) or LANG_NAMES.get(base, target.title())
        romanized = self._romanize(translated, base)

        if romanized and romanized.strip().lower() != translated.strip().lower():
            return f"{lang_name}: {translated} ({romanized})"
        return f"{lang_name}: {translated}"

    def _romanize(self, text: str, base_lang: str) -> str | None:
        """Convert non-Latin text to a Latin pronunciation approximation."""

        if base_lang == 'ja':
            try:
                import pykakasi
                kks = pykakasi.kakasi()
                parts = kks.convert(text)
                romaji = ''.join(p['hepburn'] for p in parts).strip()
                return romaji.capitalize() or None
            except ImportError:
                log.warning("pykakasi not installed — run: pip install pykakasi")
            except Exception as e:
                log.warning(f"pykakasi error: {e}")

        if base_lang == 'zh':
            try:
                from pypinyin import lazy_pinyin
                pinyin = ' '.join(lazy_pinyin(text)).strip()
                return pinyin.capitalize() or None
            except ImportError:
                log.warning("pypinyin not installed — run: pip install pypinyin")
            except Exception as e:
                log.warning(f"pypinyin error: {e}")

        # General fallback: unidecode handles Cyrillic, Arabic, Korean, Greek, etc.
        try:
            from unidecode import unidecode
            result = unidecode(text).strip()
            return result.capitalize() or None
        except ImportError:
            log.warning("unidecode not installed — run: pip install unidecode")
        except Exception as e:
            log.warning(f"unidecode error: {e}")

        return None

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
