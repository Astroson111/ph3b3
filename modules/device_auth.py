"""Per-device auth keys — decouple device (Iris, Dio) auth from the human login.

Each device authenticates with its OWN secret, matched against the X-Ph3b3-Device
header, separate from the portal username/password. Rotating the human password no
longer breaks devices, and each key is independently rotatable/revocable.

Grandfathering (no reflash): on first run each known device's key is seeded to the
CURRENT portal password — the value already flashed on the devices — so nothing
needs reflashing. From then on the human password and the device keys move
independently. A device's own key can later be changed from its on-device setup
screen (firmware follow-up), and re-entered there whenever its creds are wiped.

Storage is a plaintext JSON file (same trust model as the .env password): the
portal is single-user on the LAN and already holds the password in the clear.
Kept in an in-memory cache so device auth doesn't hit disk on every request.
"""
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

try:
    from paths import PH3B3_DATA
except ImportError:
    from modules.paths import PH3B3_DATA

log = logging.getLogger("ph3b3.device_auth")

KEYS_PATH = Path(PH3B3_DATA) / "device_keys.json"

# Devices that authenticate over the network and get a grandfathered key.
# name (X-Ph3b3-Device header) -> human label.
KNOWN_DEVICES = {"iris": "Iris", "stackchan": "Dio", "pan": "Pan"}

# Stack-Chan-class units: the ones with an on-device camera that can run the
# native photo loop. Iris is a combadge with no camera, so she is NOT in here.
# Kept beside KNOWN_DEVICES so adding a third Stack-Chan is one edit, not a
# hunt for hardcoded names scattered through the routes.
STACKCHAN_DEVICES = frozenset({"stackchan", "pan"})

MIN_KEY_LEN = 8

_cache: dict | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(KEYS_PATH.read_text())
        except Exception:
            _cache = {}
    return _cache


def _save(d: dict) -> None:
    global _cache
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = KEYS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(KEYS_PATH)                    # atomic swap
    try:
        KEYS_PATH.chmod(0o600)                # secrets — owner-only
    except Exception:
        pass
    _cache = d


def gen_secret() -> str:
    """A fresh random device key (URL-safe, ~32 chars)."""
    return secrets.token_urlsafe(24)


def grandfather(current_password: str) -> None:
    """Seed a key for each known device that doesn't have one yet, using the
    current portal password (what the devices already send). Idempotent — never
    overwrites an existing key, so a rotated key survives restarts."""
    if not current_password:
        return
    d = _load()
    changed = False
    for name in KNOWN_DEVICES:
        if not (d.get(name) or {}).get("secret"):
            d[name] = {"secret": current_password, "created": _now(), "seeded": True}
            changed = True
            log.info("[device_auth] seeded key for %s (grandfathered from portal password)", name)
    if changed:
        _save(d)


def verify(device: str, secret: str) -> bool:
    """Constant-time check that `secret` matches `device`'s stored key."""
    if not device or not secret:
        return False
    entry = _load().get(device)
    if not entry or not entry.get("secret"):
        return False
    return secrets.compare_digest(str(secret).encode(), str(entry["secret"]).encode())


def set_key(device: str, secret: str) -> dict:
    """Set an explicit key for a device (raises ValueError if too short)."""
    secret = (secret or "").strip()
    if len(secret) < MIN_KEY_LEN:
        raise ValueError(f"Device key must be at least {MIN_KEY_LEN} characters.")
    d = _load()
    d[device] = {"secret": secret, "created": _now(), "seeded": False}
    _save(d)
    return d[device]


def rotate(device: str) -> str:
    """Generate + store a fresh random key; return it (must be re-entered on the device)."""
    s = gen_secret()
    set_key(device, s)
    return s


def revoke(device: str) -> bool:
    """Remove a device's key. It can't authenticate until a key is set again."""
    d = _load()
    if device in d:
        del d[device]
        _save(d)
        return True
    return False


def listing(reveal: bool = True) -> list:
    """Devices (known first, then any extras stored) with metadata for the panel."""
    d = _load()
    names = list(KNOWN_DEVICES) + [k for k in d if k not in KNOWN_DEVICES]
    out = []
    for name in names:
        entry = d.get(name) or {}
        out.append({
            "device": name,
            "label": KNOWN_DEVICES.get(name, name),
            "configured": bool(entry.get("secret")),
            "secret": entry.get("secret") if reveal else None,
            "seeded": bool(entry.get("seeded")),
            "created": entry.get("created"),
        })
    return out
