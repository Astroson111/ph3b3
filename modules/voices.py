"""Ph3b3 voice + language registry and the persisted language/voice setting.

One LANGUAGE setting localizes Phoebe across three consumers — UI strings
(Phase 2), her response language, and her voice — but the language and voice
settings stay INDEPENDENT underneath (voice pairing is offered, never forced).

Alba (en) is the invariant fallback: any missing/corrupt voice or unknown
language resolves back to Alba. The registry lists only installed, tested models.
"""
import json
import logging
import threading
from pathlib import Path

try:
    from paths import PH3B3_HOME, PH3B3_DATA
except ImportError:
    from modules.paths import PH3B3_HOME, PH3B3_DATA

log = logging.getLogger("ph3b3.voices")

REGISTRY_PATH = Path(PH3B3_HOME) / "config" / "voices.yaml"
VOICE_DIR     = Path(PH3B3_DATA) / "voices"
SETTING_PATH  = Path(PH3B3_DATA) / "language.json"   # runtime state (user's choice), not repo config

DEFAULT_LANG  = "en"          # Alba — the constant that cannot break

# Human-readable names for the response-language directive (kept here, not in the
# soul file — soul is invariant). Only languages we actually offer.
LANG_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French",
    "de": "German",  "zh": "Mandarin Chinese",
}

_lock = threading.Lock()


def load_registry() -> dict:
    """Parse config/voices.yaml → {default, voices:{code:{...}}}. Reloaded per call
    so edits apply without a restart. Returns a safe minimal registry on failure."""
    try:
        import yaml
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            reg = yaml.safe_load(f) or {}
        reg.setdefault("default", DEFAULT_LANG)
        reg.setdefault("voices", {})
        return reg
    except Exception as e:
        log.warning("voices.yaml load failed (%s) — Alba-only registry", e)
        return {"default": DEFAULT_LANG, "voices": {
            "en": {"model": "en_GB-alba-medium.onnx", "display_name": "Alba — English",
                   "script": "latin", "tier": "strong", "sample_text": "Hello, I'm Phoebe."}}}


def resolve_voice(code: str) -> dict | None:
    """Return the registry entry for `code` with an absolute, EXISTS-checked model
    path (key 'model_path'), or None if the code is unknown or the model file is
    missing/unreadable. Callers fall back to Alba on None."""
    reg = load_registry()
    entry = (reg.get("voices") or {}).get(code)
    if not entry:
        return None
    mp = VOICE_DIR / entry.get("model", "")
    if not mp.exists():
        log.warning("voice '%s' model missing: %s", code, mp)
        return None
    out = dict(entry)
    out["code"] = code
    out["model_path"] = str(mp)
    return out


def alba() -> dict:
    """The invariant fallback voice (en/Alba), model-path resolved."""
    v = resolve_voice("en")
    if v:
        return v
    # Last-ditch: Alba isn't even in the registry — point at the known filename.
    return {"code": "en", "model_path": str(VOICE_DIR / "en_GB-alba-medium.onnx"),
            "script": "latin", "display_name": "Alba", "tier": "strong"}


def get_setting() -> dict:
    """Persisted {language, voice}. Defaults to en/en (Alba). Never raises."""
    try:
        d = json.loads(SETTING_PATH.read_text(encoding="utf-8"))
        return {"language": d.get("language") or DEFAULT_LANG,
                "voice":    d.get("voice")    or DEFAULT_LANG}
    except Exception:
        return {"language": DEFAULT_LANG, "voice": DEFAULT_LANG}


def _save(setting: dict) -> None:
    with _lock:
        SETTING_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTING_PATH.write_text(json.dumps(setting), encoding="utf-8")


def set_language(code: str) -> dict:
    s = get_setting(); s["language"] = code; _save(s); return s


def set_voice(code: str) -> dict:
    s = get_setting(); s["voice"] = code; _save(s); return s


def current_voice() -> dict:
    """The selected primary voice, resolved — Alba if the selection is missing/corrupt.
    Returns (entry, fell_back:bool) so the caller can add the honest spoken note."""
    code = get_setting()["voice"]
    v = resolve_voice(code)
    if v:
        return v
    log.warning("selected voice '%s' unavailable → Alba fallback", code)
    return alba()


def voice_fell_back() -> bool:
    return resolve_voice(get_setting()["voice"]) is None


def language_directive() -> str:
    """System-prompt-layer directive for the current response language. Empty for
    English (default — no directive, zero behavior change out of the box). NOT in
    the soul file. Safety gating is unaffected — it gates the same in every language."""
    lang = get_setting()["language"]
    if lang == "en" or lang not in LANG_NAMES:
        return ""
    name = LANG_NAMES[lang]
    return (f"\n\nRESPONSE LANGUAGE: Respond to the user in {name}. Write every reply "
            f"in {name} regardless of the language the user writes in, unless they "
            f"explicitly ask for another language. Your safety rules and refusals are "
            f"unchanged and apply in {name} exactly as in English.")


def list_for_ui() -> list:
    """Installed voices for the picker: [{code, display_name, tier, has_model}]."""
    reg = load_registry()
    out = []
    for code, e in (reg.get("voices") or {}).items():
        out.append({"code": code, "display_name": e.get("display_name", code),
                    "tier": e.get("tier", "functional"),
                    "language": LANG_NAMES.get(code, code),
                    "has_model": (VOICE_DIR / e.get("model", "")).exists()})
    return out
