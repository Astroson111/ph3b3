"""Resolve the SAME Layer B judge the service uses — import before `morpheus`.

`morpheus._LAYER_B_MODEL` is decided at import time from the environment. The
service gets that environment from systemd (`EnvironmentFile=.env`); a probe run
by hand does not, so it silently fell back to "hermes3:latest" while production
judged with ph3b3-chat. Every Layer B figure these probes printed described the
wrong model until 2026-08-28.

conftest.py does this for pytest. This module does it for script mode, and must
be imported BEFORE morpheus or it has no effect.

Only model-selection keys are read, and only when unset, so an explicit override
still wins and nothing else from .env enters the process.
"""
import os
from pathlib import Path

_ENV = Path(__file__).resolve().parent.parent / ".env"
_KEYS = ("PH3B3_FLOOR_MODEL", "PH3B3_LIGHT_MODEL", "PH3B3_HEAVY_MODEL")

if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
        if _k in _KEYS and _k not in os.environ:
            os.environ[_k] = _v
