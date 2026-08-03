"""Mood vocabulary registry — the single source of mood terms for every consumer.

Deliberately thin, and deliberately NOT a mood engine. There is no state machine
here, nothing is persisted, and nothing is written to Mnemosyne. This module only
answers two questions: what moods exist, and what words does one contribute to a
prompt. The selection itself lives in the caller's per-session dict, exactly like
the Morpheus quality tier.

Modelled on modules/voices.py, including the per-call reload: config/moods.yaml
is re-read on every lookup so edits apply without a restart. On this box a
restart of ph3b3 redeploys whatever branch is checked out, so hot-reload is the
cheaper and safer of the two options, not merely the more convenient one.

FAILURE MODE IS "NO MOOD". A missing, unreadable or malformed moods.yaml yields
an empty registry, which makes every lookup behave exactly like None — the
zero-behaviour-change anchor. A broken data file must never break generation.

SAFETY: this module composes text only. It runs BEFORE the content floor and has
no knowledge of it. Terms from this file are appended to the prompt and the floor
then inspects the composed result exactly as it inspects any other prompt, so a
hostile edit to moods.yaml is floored like any other input rather than smuggled
through. Nothing here may ever be given a floor bypass.

Alba is untouched. No value in this registry reaches TTS by any path.
"""
import logging
from pathlib import Path

try:
    from paths import PH3B3_HOME
except ImportError:
    from modules.paths import PH3B3_HOME

log = logging.getLogger("ph3b3.moods")

MOODS_PATH = Path(PH3B3_HOME) / "config" / "moods.yaml"

NONE = "none"    # explicit no-mood; the regression anchor
AUTO = "auto"    # caller infers a mood per piece and announces it first
DEFAULT = NONE


def load_registry() -> dict:
    """Parse config/moods.yaml → {id: {...}}. Reloaded per call so edits apply
    without a restart. Returns {} on any failure, which degrades to 'no mood'."""
    try:
        import yaml
        with open(MOODS_PATH, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        moods = doc.get("moods") or {}
        if not isinstance(moods, dict):
            raise ValueError("'moods' is not a mapping")
        return moods
    except FileNotFoundError:
        log.warning("moods.yaml not found at %s — mood selector inert", MOODS_PATH)
        return {}
    except Exception as e:
        log.warning("moods.yaml load failed (%s) — mood selector inert", e)
        return {}


def registry_stamp() -> float | None:
    """mtime of moods.yaml, or None if absent. Surfaced by the API so a stale
    read is always visible rather than silent — the brief's one hard requirement
    on the reload rule, whichever rule is chosen."""
    try:
        return MOODS_PATH.stat().st_mtime
    except OSError:
        return None


def list_moods() -> list[dict]:
    """[{id, label}] for the selector, sorted by label. The panel renders whatever
    this returns and hardcodes nothing, so a new mood needs no UI change."""
    reg = load_registry()
    out = [{"id": k, "label": (v or {}).get("label") or k} for k, v in reg.items()]
    return sorted(out, key=lambda m: m["label"].lower())


def is_named(mood_id: str | None) -> bool:
    """True only for a mood that actually exists in the table. 'none', 'auto',
    None, and any unknown id are all False — unknown ids degrade to no-mood
    rather than erroring, so a stale selector value cannot break generation."""
    if not mood_id or mood_id in (NONE, AUTO):
        return False
    return mood_id in load_registry()


def _terms(mood_id: str, section: str, keys: tuple[str, ...]) -> str:
    entry = load_registry().get(mood_id) or {}
    block = entry.get(section) or {}
    vals = [str(block.get(k)).strip() for k in keys if block.get(k)]
    return ", ".join(v for v in vals if v)


def amphion_terms(mood_id: str) -> str:
    """Key/mode, tempo range and arrangement for a song prompt."""
    return _terms(mood_id, "amphion", ("key", "tempo", "arrangement"))


def morpheus_terms(mood_id: str) -> str:
    """Palette, lighting and atmosphere for an image prompt."""
    return _terms(mood_id, "morpheus", ("palette", "lighting", "atmosphere"))


def story_terms(mood_id: str) -> str:
    """One prose direction for narrative generation."""
    entry = load_registry().get(mood_id) or {}
    return str(entry.get("story") or "").strip()


def compose(prompt: str, terms: str) -> str:
    """Append mood terms to a prompt. Comma-joined because both the Amphion tag
    string and the Morpheus positive prompt are comma-separated term lists.

    Returns the prompt UNCHANGED when there are no terms — that identity is what
    makes 'None' a true zero-behaviour-change path rather than a path that merely
    adds nothing visible.
    """
    prompt = (prompt or "").strip()
    terms = (terms or "").strip()
    if not terms:
        return prompt
    if not prompt:
        return terms
    return f"{prompt}, {terms}"


def label_of(mood_id: str) -> str:
    entry = load_registry().get(mood_id) or {}
    return entry.get("label") or mood_id


def announce(mood_id: str) -> str:
    """The Auto read, stated BEFORE anything renders. Short on purpose: it has to
    be objectable at a glance, and a wall of vocabulary is not."""
    if not is_named(mood_id):
        return ""
    amp = amphion_terms(mood_id).split(",")[0].strip()
    mor = morpheus_terms(mood_id).split(",")[0].strip()
    bits = [b for b in (amp, mor) if b]
    tail = f" — {', '.join(bits)}" if bits else ""
    return f"reading this as {label_of(mood_id).lower()}{tail} — say otherwise"
