"""Camera control — pan / tilt / zoom on the USB webcam, via UVC v4l2 controls.

Lets Phoebe reframe the shot she is seen through: pan, tilt, zoom, and put it
back. The pan/tilt on this camera is DIGITAL — nothing physically moves, it
crops within the 4K sensor — so a move costs nothing but a hard zoom spends
pixels. Capture runs at 720p from a 4K sensor, so there is real headroom, not
unlimited headroom.

Guarantees enforced here:
  - Master switch, default OFF. OFF means no ioctl reaches the device, and the
    server drops the camera tools from what Phoebe is offered (same rule as
    Metis: a tool she can see is a tool she will mention).
  - Every value is clamped AND snapped to the step the DEVICE reports, read
    live. No hardcoded range table — a different camera has different limits.
  - The device is found by CARD NAME, never a fixed /dev/videoN. Node numbering
    shifts when a camera is replugged or another is added, and driving the wrong
    device is worse than refusing.
  - Control ioctls do not need exclusive access, so these work while OBS is
    streaming — verified live: pan/tilt/zoom applied mid-stream, zero dropped
    frames.
  - Subprocess is list-form, shell=False. No caller data ever reaches a shell.
  - Failures are LOUD and named (off / no camera / bad axis), never a silent
    no-op that looks like the camera ignored her.
"""
import json
import logging
import re
import subprocess
from pathlib import Path

from paths import PH3B3_DATA

log = logging.getLogger(__name__)

STATE_PATH = PH3B3_DATA / "camera_control.json"

# Substring matched against the v4l2 card name. Set to "" to accept the first
# capture device found (useful if the camera is swapped for a different model).
CARD_MATCH = "Webcam"

AXES = ("pan", "tilt", "zoom")
_CTRL = {"pan": "pan_absolute", "tilt": "tilt_absolute", "zoom": "zoom_absolute"}

_TIMEOUT = 5.0


class CameraOff(RuntimeError):
    """Master switch is OFF. Stated, never silently ignored."""


class CameraMissing(RuntimeError):
    """No matching capture device — camera unplugged or renamed."""


# ── device discovery ──────────────────────────────────────────────────────────
def _device() -> str | None:
    """Path of the CAPTURE node for the matching camera, or None.

    A UVC camera exposes several /dev/video* nodes sharing one card name — the
    later ones are metadata, not video. index==0 is the capture node, which is
    the same rule /dev/v4l/by-id/...-video-index0 uses.
    """
    for sysdir in sorted(Path("/sys/class/video4linux").glob("video*")):
        try:
            name = (sysdir / "name").read_text().strip()
            index = (sysdir / "index").read_text().strip()
        except OSError:
            continue
        if index != "0":
            continue
        if CARD_MATCH and CARD_MATCH.lower() not in name.lower():
            continue
        dev = Path("/dev") / sysdir.name
        if dev.exists():
            return str(dev)
    return None


def _run(args: list[str]) -> str:
    """v4l2-ctl, list-form. Returns stdout; raises on failure with its reason."""
    r = subprocess.run(["v4l2-ctl", *args], capture_output=True, text=True,
                       timeout=_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:200] or "v4l2-ctl failed")
    return r.stdout


# ── master switch ─────────────────────────────────────────────────────────────
def enabled() -> bool:
    try:
        return bool(json.loads(STATE_PATH.read_text()).get("enabled", False))
    except Exception:
        return False


def set_enabled(on: bool) -> dict:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"enabled": bool(on)}))
    log.info("camera control %s", "ENABLED" if on else "DISABLED")
    return {"enabled": bool(on)}


# ── ranges + position, read live from the device ──────────────────────────────
_RANGE_RE = re.compile(
    r"^\s*(?P<ctrl>\w+)\s+0x[0-9a-f]+\s+\(\w+\)\s*:\s*(?P<body>.*)$", re.M)


def _ranges(dev: str) -> dict:
    """{axis: {min,max,step,value}} for whichever of pan/tilt/zoom exist."""
    out: dict[str, dict] = {}
    text = _run(["-d", dev, "--list-ctrls"])
    wanted = {v: k for k, v in _CTRL.items()}
    for m in _RANGE_RE.finditer(text):
        axis = wanted.get(m.group("ctrl"))
        if not axis:
            continue
        body = m.group("body")
        f = {k: int(v) for k, v in re.findall(r"(min|max|step|value)=(-?\d+)", body)}
        if {"min", "max", "step"} <= f.keys():
            out[axis] = {"min": f["min"], "max": f["max"],
                         "step": f["step"] or 1, "value": f.get("value", 0)}
    return out


def _clamp(v: int, r: dict) -> int:
    """Clamp into range, then snap to the device's step grid."""
    v = max(r["min"], min(r["max"], int(v)))
    step = r["step"] or 1
    snapped = r["min"] + round((v - r["min"]) / step) * step
    return max(r["min"], min(r["max"], snapped))


# ── public surface ────────────────────────────────────────────────────────────
def status() -> dict:
    """Switch state + live position. Safe to call when off or unplugged."""
    dev = _device()
    st: dict = {"enabled": enabled(), "device": dev, "present": bool(dev)}
    if not dev:
        return st
    try:
        st["axes"] = _ranges(dev)
    except Exception as e:                      # camera there but not answering
        st["present"] = False
        st["error"] = str(e)[:200]
    return st


def move(pan: int | None = None, tilt: int | None = None,
         zoom: int | None = None) -> dict:
    """Set any of pan/tilt/zoom to absolute values. Refuses loudly when off.

    Values are clamped and snapped to the device grid rather than rejected, so a
    caller asking to pan further than possible gets the edge of travel and is
    told what it actually became — never a silent no-op.
    """
    if not enabled():
        raise CameraOff("camera control is off — enable it in the Status tab")
    dev = _device()
    if not dev:
        raise CameraMissing("no camera found — unplugged, or its name changed")

    want = {"pan": pan, "tilt": tilt, "zoom": zoom}
    if all(v is None for v in want.values()):
        raise ValueError("nothing to set — give pan, tilt and/or zoom")

    axes = _ranges(dev)
    applied, settings = {}, []
    for axis, v in want.items():
        if v is None:
            continue
        if axis not in axes:
            raise ValueError(f"this camera has no {axis} control")
        c = _clamp(v, axes[axis])
        applied[axis] = c
        settings.append(f"{_CTRL[axis]}={c}")

    _run(["-d", dev, "--set-ctrl", ",".join(settings)])
    log.info("camera move %s", applied)
    return {"ok": True, "applied": applied}


def reset() -> dict:
    """Centre pan/tilt and pull zoom fully wide."""
    if not enabled():
        raise CameraOff("camera control is off — enable it in the Status tab")
    dev = _device()
    if not dev:
        raise CameraMissing("no camera found — unplugged, or its name changed")
    axes = _ranges(dev)
    want = {}
    if "pan" in axes:
        want["pan"] = _clamp(0, axes["pan"])
    if "tilt" in axes:
        want["tilt"] = _clamp(0, axes["tilt"])
    if "zoom" in axes:
        want["zoom"] = axes["zoom"]["min"]       # min zoom = widest shot
    return move(**want)
