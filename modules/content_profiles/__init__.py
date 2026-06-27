"""
content_profiles — profile loader for Morpheus content safety.

Active profile is set by PH3B3_CONTENT_PROFILE env var (default: strict).
Profile files:
  strict.py          — committed; demo-safe default
  permissive.local.py — gitignored; never committed; loaded only when present

The hard floor in morpheus.py runs BEFORE any profile check and cannot be
affected by profile selection.
"""
import importlib.util
import logging
import os
from pathlib import Path

log = logging.getLogger("ph3b3.content_profiles")

_DIR = Path(__file__).parent
ACTIVE_PROFILE_NAME: str = os.getenv("PH3B3_CONTENT_PROFILE", "strict").lower()


def load_profile(name: str) -> frozenset:
    """Load and return the denylist frozenset for the requested profile name.
    Falls back to strict with a logged warning if the requested profile is
    unavailable (e.g. permissive requested but local file not present)."""
    if name == "strict":
        from content_profiles.strict import DENYLIST
        log.info("[content_profiles] active profile: strict (%d terms)", len(DENYLIST))
        return DENYLIST

    if name == "permissive":
        local_path = _DIR / "permissive.local.py"
        if local_path.exists():
            spec = importlib.util.spec_from_file_location("permissive_local", local_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            denylist = mod.DENYLIST
            log.info("[content_profiles] active profile: permissive (%d terms)", len(denylist))
            return denylist
        log.warning(
            "[content_profiles] PH3B3_CONTENT_PROFILE=permissive but %s not found"
            " — falling back to STRICT profile", local_path.name
        )
        from content_profiles.strict import DENYLIST
        return DENYLIST

    log.warning(
        "[content_profiles] unknown profile %r — falling back to STRICT profile", name
    )
    from content_profiles.strict import DENYLIST
    return DENYLIST
