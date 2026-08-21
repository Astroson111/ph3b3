"""Jokes — curated canon read from config/jokes.yaml.

DATA, not code, the same way moods.yaml and emotions.yaml are. The old shape put
the jokes in a Python dict, which meant every addition was a code edit and the
canon could not be reviewed as a list.

Entries carry an id and a text and nothing else. No tags, no groan rating, no
attribution: Ph3b3 just needs the jokes. The consequence is that the FILE has to
carry the only structure the module gets, which is why it has top-level groups
(jokes / reflections / roasts.dnd / roasts.security) rather than per-entry tags.
Without them roast_dnd() and roast_security() could not be told apart.

Hot-reloaded on mtime, so editing the canon applies without a restart.

FAILURE MODE IS "NO JOKE". A missing, unreadable or malformed jokes.yaml leaves
the pools empty and every entry point returns a plain line saying so. It must
never raise into the Hermes tool path — a bad YAML edit should cost a punchline,
not the chat turn.
"""
import logging
import random
import threading

import yaml

try:
    from paths import PH3B3_HOME
except ImportError:
    from modules.paths import PH3B3_HOME

log = logging.getLogger("ph3b3.jokes")

REGISTRY_PATH = PH3B3_HOME / "config" / "jokes.yaml"

# Groups the tell-a-joke path draws from. "reflections" is in here because that
# is where those entries already were when they lived in this file — dropping it
# is a one-line edit, and the only one needed to stop them surfacing unprompted.
DEFAULT_POOL = ("jokes", "reflections")

# Aliases the model is likely to pass to tell_joke(category=...). Anything not
# listed falls back to DEFAULT_POOL rather than returning nothing.
_CATEGORY_ALIASES = {
    "any": DEFAULT_POOL,
    "": DEFAULT_POOL,
    "joke": ("jokes",),
    "jokes": ("jokes",),
    "reflection": ("reflections",),
    "reflections": ("reflections",),
    "mental_health": ("reflections",),
}

_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime: float | None = None


def _load() -> dict:
    """Parse the canon, re-reading only when the file has changed on disk."""
    global _cache, _cache_mtime
    try:
        mtime = REGISTRY_PATH.stat().st_mtime
    except OSError as e:
        if _cache is None:
            log.warning("[jokes] %s unreadable (%s) — no jokes available", REGISTRY_PATH, e)
            _cache = {}
        return _cache
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    try:
        with REGISTRY_PATH.open(encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        if not isinstance(doc, dict):
            raise ValueError("top level is not a mapping")
        _cache, _cache_mtime = doc, mtime
        log.info("[jokes] loaded %d jokes, %d reflections, %d roasts",
                 len(_group(doc, "jokes")), len(_group(doc, "reflections")),
                 len(_roasts(doc, "dnd")) + len(_roasts(doc, "security")))
    except Exception as e:
        # Keep the last good copy if we have one; an editing typo should not
        # empty the canon mid-session.
        log.warning("[jokes] %s malformed (%s) — keeping previous canon", REGISTRY_PATH, e)
        if _cache is None:
            _cache = {}
    return _cache


def _entries(raw) -> list[dict]:
    """Normalize a group to the entries that actually have text."""
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and str(e.get("text", "")).strip()]


def _group(doc: dict, name: str) -> list[dict]:
    return _entries(doc.get(name))


def _roasts(doc: dict, topic: str) -> list[dict]:
    roasts = doc.get("roasts")
    return _entries(roasts.get(topic)) if isinstance(roasts, dict) else []


class JokesModule:
    def __init__(self):
        doc = _load()
        self._told: set[str] = set()          # ids used this session — no repeats
        log.info("Jokes module loaded (%s).",
                 "canon present" if doc else "canon EMPTY — check config/jokes.yaml")

    # ── internals ────────────────────────────────────────────────────────────
    def _pick(self, pool: list[dict], track: bool) -> str:
        """Choose an entry, preferring ones not yet told this session.

        When the pool is exhausted the session record for THOSE ids is cleared
        and it starts over, rather than repeating early or returning nothing.
        """
        if not pool:
            return ""
        if not track:
            return str(random.choice(pool).get("text", "")).strip()
        with _lock:
            fresh = [e for e in pool if str(e.get("id", "")) not in self._told]
            if not fresh:
                self._told -= {str(e.get("id", "")) for e in pool}
                fresh = pool
            choice = random.choice(fresh)
            self._told.add(str(choice.get("id", "")))
        return str(choice.get("text", "")).strip()

    # ── public API — signatures unchanged, server.py calls all three ─────────
    def tell_joke(self, category="any"):
        """Tell a joke, never repeating one within a session.

        `category` is kept because the Hermes tool schema still passes it, but
        entries no longer carry tags, so it can only select a top-level GROUP.
        The old per-topic routing (cybersecurity / dnd / paranormal / tech) has
        no data behind it any more; anything unrecognised draws from the default
        pool instead of failing.
        """
        doc = _load()
        groups = _CATEGORY_ALIASES.get(str(category or "any").strip().lower(), DEFAULT_POOL)
        pool = [e for g in groups for e in _group(doc, g)]
        if not pool and groups != DEFAULT_POOL:
            pool = [e for g in DEFAULT_POOL for e in _group(doc, g)]
        return self._pick(pool, track=True) or "I've got nothing — my joke file didn't load."

    def roast_dnd(self):
        return self._pick(_roasts(_load(), "dnd"), track=True) or "The party survived. Barely."

    def roast_security(self):
        return self._pick(_roasts(_load(), "security"), track=True) or "Someone clicked it. Someone always clicks it."
