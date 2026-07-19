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
SETTING_PATH  = Path(PH3B3_DATA) / "language.json"      # runtime state (user's choice), not repo config
REVIEW_PATH   = Path(PH3B3_DATA) / "voice_review.json"  # runtime review verdicts, not repo config

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


# ── Voice ↔ language binding ───────────────────────────────────────────────────
# LANGUAGE is the master setting; the VOICE follows it. Piper models are
# single-language, so 'Spanish language + Alba (English) voice' produces garbage
# or silence. We make that state UNREPRESENTABLE: the active voice is always
# DERIVED from the language — there is no independent 'voice' field to drift.
# Per-language choices (es_ES vs es_MX) are remembered in voice_prefs so a
# round-trip switch restores them.
def _voice_lang(code: str) -> str:
    """The response-language a voice code pairs with (entry.lang, default code)."""
    e = (load_registry().get("voices") or {}).get(code) or {}
    return e.get("lang", code)


def approved_voices_for(lang: str) -> list:
    """Approved, installed voice codes serving `lang`, PRIMARY first (the voice
    whose code == lang), then others (es → ['es', 'es_MX'] once es_MX is
    approved). Empty when the language has no approved voice."""
    reg, review = load_registry(), _load_review()
    out = []
    for code, e in (reg.get("voices") or {}).items():
        if e.get("lang", code) != lang:
            continue
        if effective_status(code, e, review) != "approved":
            continue
        if not (VOICE_DIR / e.get("model", "")).exists():
            continue
        out.append(code)
    out.sort(key=lambda c: (c != lang, c))       # primary (code == lang) first
    return out


def default_voice_for(lang: str):
    """The voice a language uses with no saved preference — its primary approved
    voice, or None if the language has no approved voice."""
    v = approved_voices_for(lang)
    return v[0] if v else None


def language_has_voice(lang: str) -> bool:
    """True iff `lang` has ≥1 approved installed voice — i.e. it can be selected
    for SPEECH without landing in a silent state."""
    return bool(approved_voices_for(lang))


def voice_for_language(lang: str, prefs: dict | None = None):
    """The ACTIVE voice code for a response language: the user's saved preference
    if it is still an approved match, else the language's primary voice, else
    None (no approved voice → caller falls back to Alba + a spoken notice)."""
    if prefs is None:
        prefs = get_setting()["voice_prefs"]
    approved = approved_voices_for(lang)
    pref = prefs.get(lang)
    if pref and pref in approved:
        return pref
    return approved[0] if approved else None


def get_setting() -> dict:
    """Persisted {language, voice_prefs}, normalized, plus the DERIVED active
    'voice'. Never raises. Legacy {language, voice} files are migrated on read —
    the old independent voice is remembered as its own language's preference and
    the stored mismatch is discarded (the active voice re-derives from language)."""
    try:
        d = json.loads(SETTING_PATH.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    lang = d.get("language") or DEFAULT_LANG
    prefs = d.get("voice_prefs")
    if not isinstance(prefs, dict):
        prefs = {}
        old = d.get("voice")                     # migrate legacy independent voice
        if old:
            prefs[_voice_lang(old)] = old
    return {"language": lang, "voice_prefs": prefs,
            "voice": voice_for_language(lang, prefs)}


def _save(language: str, prefs: dict) -> None:
    with _lock:
        SETTING_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTING_PATH.write_text(
            json.dumps({"language": language, "voice_prefs": prefs}), encoding="utf-8")


def set_language(code: str) -> dict:
    """Master setting: switch language. The voice auto-follows (derived from the
    new language + its saved preference). Preferences are left intact so a
    round-trip switch restores each language's chosen voice."""
    s = get_setting()
    _save(code, s["voice_prefs"])
    return get_setting()


def set_voice_for_current(code: str) -> dict:
    """Manual voice pick for the CURRENT language. The voice MUST be an approved
    match for that language (the picker only offers such voices); a non-matching
    code is refused rather than saved into a mismatch."""
    s = get_setting()
    lang = s["language"]
    if code not in approved_voices_for(lang):
        raise ValueError(
            f"voice {code!r} is not an approved voice for {LANG_NAMES.get(lang, lang)}")
    prefs = dict(s["voice_prefs"]); prefs[lang] = code
    _save(lang, prefs)
    return get_setting()


def current_voice() -> dict:
    """The active voice, resolved — Alba if the language has no approved voice or
    resolution fails. Derived from the language, so never a cross-language
    mismatch."""
    code = get_setting()["voice"]
    v = resolve_voice(code) if code else None
    if v:
        return v
    log.warning("no resolvable voice for language '%s' → Alba", get_setting()["language"])
    return alba()


def voice_fell_back() -> bool:
    """True when the current language has no usable approved voice (→ Alba)."""
    code = get_setting()["voice"]
    return not code or resolve_voice(code) is None


def output_for_response(response_lang: str | None = None) -> dict:
    """Runtime binding for speaking a reply (belt + suspenders). Returns
    {'voice': code, 'notice': str|None}: the approved voice matching the response
    language, or — if that language has no approved voice — Alba ('en') plus a
    one-line notice to speak instead, so Phoebe is NEVER silent without saying
    why. `response_lang` defaults to the current language setting."""
    lang = response_lang or get_setting()["language"]
    code = voice_for_language(lang)
    if code:
        return {"voice": code, "notice": None}
    name = LANG_NAMES.get(lang, lang)
    return {"voice": "en", "notice": f"I can't voice {name} yet, so here's the text."}


def list_languages_for_ui() -> list:
    """Every response-language, each flagged `selectable` (has an approved voice).
    A non-selectable language renders disabled — it cannot be chosen into a
    silent state."""
    return [{"code": c, "name": n, "selectable": language_has_voice(c)}
            for c, n in LANG_NAMES.items()]


def voices_for_language_ui(lang: str) -> list:
    """Approved voices for `lang` (the manual picker, filtered to the current
    language): [{code, display_name, tier}], primary first."""
    reg = load_registry().get("voices") or {}
    out = []
    for code in approved_voices_for(lang):
        e = reg.get(code, {})
        out.append({"code": code, "display_name": e.get("display_name", code),
                    "tier": e.get("tier", "functional")})
    return out


def active_voice_display() -> str:
    """Display name of the current active voice — the 'Speaking with: …' line."""
    v = resolve_voice(get_setting()["voice"] or "en") or alba()
    return v.get("display_name", "Alba")


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


# ── Review gate ───────────────────────────────────────────────────────────────
# A voice is offered in the main dropdown ONLY when its effective status is
# 'approved'. The seed status lives in voices.yaml; the Captain's runtime verdict
# (approve/reject) overlays it from voice_review.json so the repo config stays
# immutable. Alba is always approved, whatever any file says. A voice with no
# explicit status defaults to 'unreviewed' — approval is never granted by omission.
def _load_review() -> dict:
    """Runtime verdicts {voice_code: 'approved'|'rejected'}. Never raises."""
    try:
        return json.loads(REVIEW_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_review(d: dict) -> None:
    with _lock:
        REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
        REVIEW_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")


def effective_status(code: str, entry: dict | None = None, review: dict | None = None) -> str:
    """'approved' | 'unreviewed' | 'rejected' for a voice code, overlay applied."""
    if code == "en":
        return "approved"                     # Alba is never gated
    if review is None:
        review = _load_review()
    verdict = review.get(code)
    if verdict in ("approved", "rejected"):
        return verdict
    if entry is None:
        entry = (load_registry().get("voices") or {}).get(code) or {}
    return entry.get("status") or "unreviewed"


def list_for_ui() -> list:
    """APPROVED, installed voices for the main picker:
    [{code, display_name, tier, language, has_model}]. The review gate — an
    unreviewed or rejected voice never reaches this list."""
    reg, review = load_registry(), _load_review()
    out = []
    for code, e in (reg.get("voices") or {}).items():
        if effective_status(code, e, review) != "approved":
            continue
        if not (VOICE_DIR / e.get("model", "")).exists():
            continue
        out.append({"code": code, "display_name": e.get("display_name", code),
                    "tier": e.get("tier", "functional"),
                    "language": LANG_NAMES.get(e.get("lang", code), code),
                    "has_model": True})
    return out


def list_for_review() -> list:
    """Installed voices awaiting the Captain's verdict (effective status
    'unreviewed'). These are reachable ONLY through the review flow, never the
    main dropdown. Rejected voices (model deleted) are excluded."""
    reg, review = load_registry(), _load_review()
    out = []
    for code, e in (reg.get("voices") or {}).items():
        if effective_status(code, e, review) != "unreviewed":
            continue
        if not (VOICE_DIR / e.get("model", "")).exists():
            continue
        out.append({"code": code, "display_name": e.get("display_name", code),
                    "lang": e.get("lang", code),
                    "language": LANG_NAMES.get(e.get("lang", code), code),
                    "tier": e.get("tier", "functional"),
                    "sample_text": e.get("sample_text", "")})
    return out


def approve(code: str) -> dict:
    """Captain's verdict: promote an unreviewed voice into the dropdown. Refuses
    a code that is unknown or not currently unreviewed (idempotent-safe)."""
    entry = (load_registry().get("voices") or {}).get(code)
    if not entry:
        raise ValueError(f"unknown voice {code!r}")
    if effective_status(code, entry) != "unreviewed":
        raise ValueError(f"voice {code!r} is not awaiting review")
    review = _load_review(); review[code] = "approved"; _save_review(review)
    return {"code": code, "status": "approved"}


def reject(code: str) -> dict:
    """Captain's verdict: drop an unreviewed voice — delete its model files from
    disk and record the rejection so setup.sh will not re-fetch it. Alba and any
    already-approved voice are protected."""
    reg = load_registry()
    entry = (reg.get("voices") or {}).get(code)
    if not entry:
        raise ValueError(f"unknown voice {code!r}")
    if code == "en" or effective_status(code, entry) == "approved":
        raise ValueError(f"voice {code!r} is protected and cannot be rejected")
    model = entry.get("model", "")
    for p in (VOICE_DIR / model, VOICE_DIR / (model + ".json")):
        try:
            p.unlink(missing_ok=True)
        except Exception as e:
            log.warning("reject: could not delete %s (%s)", p, e)
    review = _load_review(); review[code] = "rejected"; _save_review(review)
    log.info("voice %r rejected → model deleted", code)
    return {"code": code, "status": "rejected"}
