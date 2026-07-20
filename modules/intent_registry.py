"""Dedicated-module intent registry — precedence OVER Metis forced search.

The problem this closes: Metis's search-intent detector matches weather phrasing
("what's the weather", "search the weather for me", "look up the forecast") and
force-routes those turns to the open web — stale or empty results instead of the
weather module's live data. A dedicated module (weather, and later time, notes,
fleet status, translation, …) must win that intent BEFORE forced search ever fires.

Design: the registry is DATA, not router logic. Each module DECLARES the phrasing
it owns by calling `register(...)` at import time — the router just asks
`resolve(text)` which claim, if any, wins, and never grows a per-module branch of
its own. This keeps the "who owns what" knowledge out of the router (the brief's
rule) and lets a new module claim an intent without touching intent resolution.

Precedence = registration order (first match wins); register the most specific
claims first. A claim may carry an `exclude` pattern so a near-miss (e.g. "cpu
temperature") does NOT get swallowed by a broad domain claim ("temperature").

Metis stays available as an ANNOUNCED fallback when a claiming module errors — but
that lives in the server dispatch, not here. This module only answers "who claims
this?".
"""
import re

_REGISTRY: list = []   # ordered list of Claim; first match wins


class Claim:
    """A dedicated module's declaration that it owns a class of phrasing.

    module   — stable key the server dispatches on (e.g. "weather").
    handler  — advisory label of the entry point (e.g. "weather_current"); the
               server maps `module` → action, so this is documentation only.
    pattern  — compiled regex; a match on the user message hands the turn to `module`.
    exclude  — optional compiled regex; if it matches, this claim does NOT fire
               (lets a broad claim step aside for a sibling domain, e.g. hardware
               "temperature" vs. weather "temperature").
    """
    __slots__ = ("module", "handler", "pattern", "exclude")

    def __init__(self, module, handler, pattern, exclude=None):
        self.module = module
        self.handler = handler
        self.pattern = pattern if hasattr(pattern, "search") else re.compile(pattern, re.I)
        self.exclude = (exclude if (exclude is None or hasattr(exclude, "search"))
                        else re.compile(exclude, re.I))

    def claims(self, text: str) -> bool:
        t = text or ""
        if self.exclude is not None and self.exclude.search(t):
            return False
        return bool(self.pattern.search(t))


def register(module: str, handler: str, pattern, exclude=None) -> Claim:
    """Declare that `module` owns `pattern`. Called by modules at import time.
    Idempotent per (module, handler): re-registering replaces the prior claim so a
    reimport in tests doesn't stack duplicates."""
    global _REGISTRY
    _REGISTRY = [c for c in _REGISTRY if not (c.module == module and c.handler == handler)]
    claim = Claim(module, handler, pattern, exclude)
    _REGISTRY.append(claim)
    return claim


def resolve(text: str):
    """Return the first Claim that owns `text`, or None if no dedicated module
    claims it (→ the caller falls through to Metis search-intent, unchanged)."""
    for claim in _REGISTRY:
        if claim.claims(text):
            return claim
    return None


def claimed_modules() -> list:
    """The distinct module keys currently holding a claim (introspection/tests)."""
    seen = []
    for c in _REGISTRY:
        if c.module not in seen:
            seen.append(c.module)
    return seen
