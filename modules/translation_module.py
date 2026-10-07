import os
import re
import logging
from datetime import datetime

log = logging.getLogger("ph3b3.translator")
BASE_LOG_DIR = os.path.abspath(os.path.expanduser("~/ph3b3_data/translation_logs"))

# OFFLINE ONLY (Captain's ruling, 2026-10-07). This module used deep_translator's
# GoogleTranslator, which sent the text of a chat turn to translate.google.com as
# a URL query string. The audit found 43 such calls in skill_log.jsonl, 35 of
# them answered HTTP 429 — i.e. received by Google — between 2026-10-04 and
# 2026-10-07, after tool_groups put translate_text on every turn. There is no
# Google path left in this file: no import, no fallback, no "if offline fails".
# Argos Translate runs on this machine; with no language pack installed for a
# pair, translate() says so rather than reaching anywhere.
#
# The voice path (listen_and_translate -> recognize_google) is gone too. Nothing
# called it, and it would have sent microphone audio to Google.
try:
    import argostranslate.translate as _argos
    TRANSLATOR_AVAILABLE = True
except ImportError:
    _argos = None
    TRANSLATOR_AVAILABLE = False
    log.warning("argostranslate not installed — translation unavailable.")

# ARGOS IS NOT OFFLINE BY DEFAULT. Measured under strace, 2026-10-07: the first
# es->en translation connected to raw.githubusercontent.com and to an AWS/
# CloudFront CDN. Argos sentence-splits with stanza.Pipeline() and never passes
# download_method=None, so stanza fetches resources.json and any processor it
# decides the language "expects" (Spanish pulled in mwt). No user text went out
# — but a translator that phones home on first use is not zero-egress.
#
# Two locks, both local to this module (site-packages untouched):
#  1. _LocalSplitter replaces Argos' sentencizer, so stanza is never constructed
#     on our path at all. Chat-length text needs nothing smarter than this.
#  2. stanza.Pipeline is pinned to download_method=None, so if anything else in
#     the process does build one it fails on a missing file instead of fetching.
try:
    import functools as _ft
    import stanza as _stanza
    if not getattr(_stanza.Pipeline, "_ph3b3_offline", False):
        _orig_pipeline = _stanza.Pipeline

        class _OfflinePipeline(_orig_pipeline):            # noqa: N801
            _ph3b3_offline = True

            def __init__(self, *a, **kw):
                kw["download_method"] = None
                super().__init__(*a, **kw)

        _stanza.Pipeline = _OfflinePipeline
except ImportError:
    pass


class _LocalSplitter:
    """Sentence split on terminal punctuation. No model, no download."""
    _RX = re.compile(r"(?<=[.!?。！？])\s+")

    def split_sentences(self, text: str) -> list[str]:
        return [s for s in self._RX.split(text.strip()) if s] or [text]


def _pin_local_splitter(tr) -> None:
    """Every leg of a (possibly pivoted) Argos translation splits locally."""
    if tr is None:
        return
    if hasattr(tr, "sentencizer"):
        tr.sentencizer = _LocalSplitter()
    for leg in ("underlying", "t1", "t2"):     # CachedTranslation wraps; Composite = pivot via en
        _pin_local_splitter(getattr(tr, leg, None))

# Languages whose scripts are non-Latin and need romanization.
# Keyed on the base language code (before any hyphen).
NON_LATIN_LANGS = {
    'ja', 'zh', 'ko', 'ar', 'ru', 'uk', 'bg', 'sr', 'mk', 'be',
    'hi', 'mr', 'ne', 'th', 'el', 'he', 'fa', 'bn', 'gu', 'ta',
    'te', 'kn', 'ml', 'si', 'my', 'km', 'lo', 'ka', 'am', 'mn',
    'tg',
}

# deep_translator / Google Translate requires exact casing for a handful of codes.
_TRANSLATOR_CODE = {
    'zh-cn': 'zh-CN',
    'zh-tw': 'zh-TW',
    'mni-mtei': 'mni-Mtei',
}

# Dialect / alias names → canonical Google Translate code (also used as romanization base).
# Covers Farsi variants and common alternate spellings.
_DIALECT_MAP = {
    'farsi':   'fa',
    'dari':    'fa',
    'tehrani': 'fa',
    'kabuli':  'fa',
    'tajiki':  'tg',
    'tajik':   'tg',
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
    'tg': 'Tajik',
    # Farsi dialect display names
    'farsi':   'Farsi',
    'dari':    'Dari',
    'tehrani': 'Tehrani Persian',
    'kabuli':  'Kabuli Dari',
    'tajiki':  'Tajik',
    'tajik':   'Tajik',
}


class TranslationModule:
    def __init__(self):
        self.target_lang = "es"
        os.makedirs(BASE_LOG_DIR, mode=0o755, exist_ok=True)
        log.info("Translation module ready.")

    def installed_pairs(self) -> set[tuple[str, str]]:
        """(from, to) codes with a language pack on disk. Never touches the network."""
        if not TRANSLATOR_AVAILABLE:
            return set()
        import argostranslate.package as _pkg
        return {(p.from_code, p.to_code) for p in _pkg.get_installed_packages()}

    def translate(self, text, target_lang=None, source_lang="en"):
        if not TRANSLATOR_AVAILABLE:
            return {"error": "offline translation (argostranslate) is not installed", "text": text}
        if not text or not text.strip():
            return {"error": "No text provided", "text": ""}
        target = (target_lang or self.target_lang).lower().strip()
        resolved = _DIALECT_MAP.get(target, target)
        to_code = _TRANSLATOR_CODE.get(resolved, resolved).split("-")[0]
        from_code = (source_lang or "en").lower().strip().split("-")[0]
        if from_code == to_code:
            return {"error": f"source and target are both '{to_code}'", "text": text}
        # Argos pivots through English on its own when both legs are installed,
        # so a missing DIRECT pack is not yet a refusal — get_translation is the
        # authority, and it is local.
        langs = {l.code: l for l in _argos.get_installed_languages()}
        src, dst = langs.get(from_code), langs.get(to_code)
        tr = src.get_translation(dst) if (src and dst) else None
        if tr is None:
            return {"error": f"no offline language pack for {from_code} -> {to_code}; "
                             "nothing was sent anywhere", "text": text}
        _pin_local_splitter(tr)
        try:
            translated = tr.translate(text)
            display = self._format(text, translated, target)
            tts_text = self._format_tts(text, translated, target)
            self._save_log(text, display, target)
            return {
                "original": text,
                "translated": display,   # full display string — native script + romanisation
                "tts_text": tts_text,    # romanisation-only — safe to pass directly to Piper
                "target_lang": target,
                "error": None,
            }
        except Exception as e:
            return {"error": str(e), "text": text}

    def _format(self, original: str, translated: str, target: str) -> str:
        """Produce 'Hello in Japanese: こんにちは (Konnichiwa)' for non-Latin scripts."""
        rom_base = _DIALECT_MAP.get(target, target.split('-')[0])
        if rom_base not in NON_LATIN_LANGS:
            return translated

        lang_name = LANG_NAMES.get(target) or LANG_NAMES.get(rom_base, target.title())
        romanized = self._romanize(translated, rom_base)

        if romanized and romanized.strip().lower() != translated.strip().lower():
            return f"{original} in {lang_name}: {translated} ({romanized})"
        return f"{original} in {lang_name}: {translated}"

    def _format_tts(self, original: str, translated: str, target: str) -> str:
        """Spoken-only variant: romanisation without native-script characters.

        The display string keeps the native script for the UI; this version is
        what should reach Piper/Alba — native chars would be misread or skipped.
        """
        rom_base = _DIALECT_MAP.get(target, target.split('-')[0])
        if rom_base not in NON_LATIN_LANGS:
            return translated

        lang_name = LANG_NAMES.get(target) or LANG_NAMES.get(rom_base, target.title())
        romanized = self._romanize(translated, rom_base)

        if romanized and romanized.strip().lower() != translated.strip().lower():
            return f"{original} in {lang_name}: {romanized}"
        # No romanisation available — fall back to display text; _strip_for_piper
        # in tts_module will drop any characters Piper still can't handle.
        return f"{original} in {lang_name}: {translated}"

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
