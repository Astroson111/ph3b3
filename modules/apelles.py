"""
apelles.py — Ph3b3's local photo editor.

Named for Apelles of Kos, who was known above all for knowing when a picture was
finished. This module finishes pictures. It does not invent them.

┌─ RULING A — Apelles EDITS. Morpheus GENERATES. ──────────────────────────────┐
│ Every operation in this module takes an existing image as input. There is no  │
│ text-to-image entry point, and this is enforced by SHAPE, not by validation:  │
│ no public function here accepts a prompt without also requiring a source      │
│ image, so there is no argument combination that yields a picture from a blank │
│ canvas. If a proposed feature does not take an image, it belongs in Morpheus. │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ RULING B — face RESTORATION in, face REPLACEMENT welded shut ───────────────┐
│ Recovering detail in a face already present in the photo is allowed. Putting  │
│ a face into a photo it was never in is refused at the floor, with no off      │
│ switch and no profile that relaxes it. Same reasoning as the no-voice-cloning │
│ rule in Amphion: Ph3b3 does not help put a person somewhere they weren't.     │
│ Note the honest limit — see `identity_refusal`. The refusal catches asking.   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─ RULING C — non-destructive ────────────────────────────────────────────────┐
│ Originals are never overwritten. Every operation writes a NEW file and the    │
│ source is left byte-identical. Users can be careless; the module cannot be.   │
│ Enforced in `_open_source` (read-only) and `export` (refuses to write over a  │
│ path it was given as input).                                                  │
└──────────────────────────────────────────────────────────────────────────────┘

PRIVACY: never log image content, prompts, or file paths — same rule as
Morpheus. Log job ids, operation names and pixel dimensions. Nothing that
identifies the picture or where it lives.
"""
from __future__ import annotations

import io
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from paths import PH3B3_DATA

log = logging.getLogger("Ph3b3")

APELLES_DATA: Path = PH3B3_DATA / "apelles"
OUT_DIR: Path = APELLES_DATA / "edits"

# ── Untrusted input ───────────────────────────────────────────────────────────
# An image file is an attack surface: the decoder is C, and "just open it" is
# how you get a heap overflow from a JPEG. Validate the header BEFORE decoding,
# and cap the pixel count so a 100-megapixel PNG cannot be used as a memory bomb
# against a box that is also holding six GPU tenants.
ALLOWED_IN = {"PNG", "JPEG", "WEBP", "BMP", "TIFF", "GIF"}
ALLOWED_OUT = {"PNG", "JPEG", "WEBP"}
MAX_PIXELS = 80_000_000          # ~80 MP; a 24 MP phone shot is 24 MP
MAX_BYTES = 80 * 1024 * 1024
MIN_DIM, MAX_DIM = 1, 20_000

# PIL's own bomb guard. Ours is stricter and louder, but leaving theirs at the
# default None would disable the backstop entirely.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ApellesError(Exception):
    """Loud failure. Never degrade silently — a photo editor that quietly
    returns the input unchanged is worse than one that refuses."""


# ── Ruling B: the weld ────────────────────────────────────────────────────────
# Face replacement is not a feature with a guard in front of it; it is a feature
# that does not exist. This regex exists so a CHAT request for it gets an honest
# refusal instead of a confusing "no such operation", and so the refusal is
# greppable in the audit. It is not the enforcement — the enforcement is that no
# swap operation is implemented, no endpoint accepts a second face, and no
# parameter combination reaches one.
_IDENTITY_TERMS = (
    r"face[\s\-_]*swap", r"swap[\s\-_]*(?:the[\s\-_]*)?faces?", r"faceswap",
    r"deep[\s\-_]*fake", r"deepfake",
    r"identity\s+transfer", r"face\s+transplant",
    # A possessive can be a CHAIN — "my brother's face", "her friend's face" — and
    # an earlier version only allowed a single token, so "put my brother's face on
    # my body" walked straight through. Allow up to three words between the verb
    # and "face"; that covers the phrasings people actually use without swallowing
    # unrelated sentences, because the trailing preposition still has to be there.
    r"\bput\s+(?:[\w'’]+\s+){0,3}faces?\s+(?:on|onto|in|into)\b",
    r"\bswap\s+(?:[\w'’]+\s+){0,3}faces?\b",
    r"\breplace\s+(?:[\w'’]+\s+){0,3}faces?\b",
    r"\bstick\s+(?:[\w'’]+\s+){0,3}faces?\s+(?:on|onto)\b",
    r"\bpaste\s+(?:[\w'’]+\s+){0,3}faces?\s+(?:on|onto|in|into)\b",
    r"\bfaces?\s+(?:on|onto)\s+(?:[\w'’]+\s+){0,3}(?:body|head|photo|picture|someone|another)\b",
    r"\bmake\s+it\s+look\s+like\s+[\w'’ ]{1,24}\s+(?:was|were)\s+(?:there|in\s+the\s+(?:photo|picture|shot))\b",
    r"\bput\s+(?:[\w'’]+\s+){0,3}(?:in|into)\s+(?:this|the|that)\s+(?:photo|picture)\s+with\b",
)
_IDENTITY_RE = re.compile("|".join(_IDENTITY_TERMS), re.I)

# Restoration is explicitly ALLOWED and must not be caught by the weld. A
# request to "restore" or "enhance" a face already in the shot is the in-scope
# half of ruling B, and refusing it would be the guard misfiring.
_RESTORE_RE = re.compile(
    r"\b(?:restore|restoration|enhance|sharpen|deblur|repair|fix|clean\s*up|"
    r"unblur|denoise)\b[^.]{0,40}\bfaces?\b"
    r"|\bfaces?\b[^.]{0,40}\b(?:restore|restoration|enhance|sharpen|deblur|"
    r"repair|clean\s*up|unblur|denoise)\b",
    re.I,
)


def _normalize(text: str) -> str:
    """Fold unicode look-alikes before matching, so 'ｆａｃｅ ｓｗａｐ' and
    zero-width-joined spellings do not walk past the weld."""
    t = unicodedata.normalize("NFKC", str(text or ""))
    t = "".join(c for c in t if unicodedata.category(c) != "Cf")   # strip ZWJ/ZWSP
    return t


def identity_refusal(text: str) -> str | None:
    """Return a refusal string if the request asks to put a face where it wasn't.

    Restoration wins ties: 'restore her face' is in scope, and only reads as a
    swap if it ALSO carries swap language.

    HONEST LIMIT — this catches the request, phrased in words. It is not a
    detector: nothing here inspects pixels, so it cannot tell that a supplied
    source image is itself a composite. The architectural half of ruling B (no
    swap operation exists) is what actually holds; this is the part that
    explains why.
    """
    norm = _normalize(text)
    if not _IDENTITY_RE.search(norm):
        return None
    if _RESTORE_RE.search(norm) and not re.search(
            r"face[\s\-_]*swap|faceswap|deep[\s\-_]*fake|identity\s+transfer", norm, re.I):
        return None
    return (
        "I won't do face replacement — swapping a face in, or putting someone's "
        "face onto another body, is off the table permanently, not just for now. "
        "It's the same line as voice cloning: I don't help put a person somewhere "
        "they weren't. What I can do is RESTORE a face that's already in the "
        "photo — recovering detail in an old or low-light shot."
    )


# ── Untrusted input: validate before decode ───────────────────────────────────
def probe(data: bytes | Path) -> dict:
    """Read the header ONLY and decide whether this is safe to decode.

    Raises ApellesError loudly on anything malformed, oversized or unsupported.
    Deliberately does not decode pixels: the whole point is to find out what we
    are about to hand the decoder before we hand it over.
    """
    if isinstance(data, Path):
        try:
            size = data.stat().st_size
        except OSError:
            raise ApellesError("that file can't be read")
        raw = None
    else:
        size = len(data)
        raw = data

    if size == 0:
        raise ApellesError("that file is empty")
    if size > MAX_BYTES:
        raise ApellesError(f"that image is too large ({size // 1048576} MB; limit is {MAX_BYTES // 1048576} MB)")

    try:
        src = io.BytesIO(raw) if raw is not None else data
        with Image.open(src) as im:
            fmt = (im.format or "").upper()
            w, h = im.size
    except ApellesError:
        raise
    except Exception:
        # Malformed → refuse by name rather than letting the decoder try harder.
        raise ApellesError("that doesn't parse as an image I can read")

    if fmt not in ALLOWED_IN:
        raise ApellesError(f"{fmt or 'unknown'} isn't a format I handle (PNG, JPEG, WebP, BMP, TIFF, GIF)")
    if not (MIN_DIM <= w <= MAX_DIM and MIN_DIM <= h <= MAX_DIM):
        raise ApellesError(f"those dimensions are out of range ({w}x{h})")
    if w * h > MAX_PIXELS:
        raise ApellesError(f"that's {w * h // 1_000_000} megapixels; the limit is {MAX_PIXELS // 1_000_000} MP")
    return {"format": fmt, "width": w, "height": h, "bytes": size}


def _open_source(path: Path) -> Image.Image:
    """Open READ-ONLY and hand back a detached copy.

    Ruling C lives here: the file object is closed before anything touches the
    pixels, so no operation can hold a writable handle on someone's original.
    """
    probe(path)
    with Image.open(path) as im:
        im.load()
        return im.copy()


# ── EXIF — the flagship ───────────────────────────────────────────────────────
# Stripped by DEFAULT on export. Not buried in an advanced panel, not a checkbox
# someone discovers later: the default state of this module is that your GPS
# coordinates, your device serial and your timestamps do not leave with the
# picture. Preserving them is possible and requires saying so explicitly.
_EXIF_LABELS = {
    0x8825: "GPS location", 0x010F: "camera make", 0x0110: "camera model",
    0x0132: "timestamp", 0x9003: "original timestamp", 0x9004: "digitised timestamp",
    0xA431: "camera serial number", 0xA430: "camera owner", 0x013B: "artist",
    0x8298: "copyright", 0xC62F: "camera label", 0x001C: "GPS area",
}


def describe_metadata(img_or_path) -> list[str]:
    """Plain-language list of what is in the file's metadata.

    The UI states what was removed, so it has to be able to say it in words
    rather than showing tag numbers."""
    try:
        im = _open_source(img_or_path) if isinstance(img_or_path, Path) else img_or_path
        exif = im.getexif()
    except Exception:
        return []
    if not exif:
        return []
    found: list[str] = []
    for tag, label in _EXIF_LABELS.items():
        if tag in exif and str(exif.get(tag)).strip():
            found.append(label)
    # GPS is the one that matters most; it hides in a sub-IFD.
    try:
        if exif.get_ifd(0x8825) and "GPS location" not in found:
            found.append("GPS location")
    except Exception:
        pass
    other = max(0, len(exif) - len(found))
    if other:
        found.append(f"{other} other tag{'s' if other != 1 else ''}")
    return found


# ── Tier 1: deterministic operations (CPU, no model, sub-second) ──────────────
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "tiktok":            (1080, 1920),   # 9:16
    "square":            (1080, 1080),   # 1:1  — Etsy
    "portrait_4_5":      (1080, 1350),   # 4:5
    "widescreen":        (1920, 1080),   # 16:9
    "linkedin_headshot": (800, 800),
    "youtube_thumb":     (1280, 720),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def op_crop(im: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    l, t, r, b = (int(v) for v in box)
    if r <= l or b <= t:
        raise ApellesError("that crop box has no area")
    l, t = max(0, l), max(0, t)
    r, b = min(im.width, r), min(im.height, b)
    if r <= l or b <= t:
        raise ApellesError("that crop box falls outside the image")
    return im.crop((l, t, r, b))


def op_rotate(im: Image.Image, degrees: float, expand: bool = True) -> Image.Image:
    """Rotate. Doubles as straighten — a small angle IS a straighten, so there is
    no reason for two code paths that can disagree."""
    return im.rotate(-float(degrees), resample=Image.BICUBIC, expand=bool(expand))


def op_flip(im: Image.Image, axis: str = "horizontal") -> Image.Image:
    a = str(axis).lower()
    if a in ("h", "horizontal", "x"):
        return ImageOps.mirror(im)
    if a in ("v", "vertical", "y"):
        return ImageOps.flip(im)
    raise ApellesError("flip axis must be horizontal or vertical")


def op_exposure(im: Image.Image, stops: float) -> Image.Image:
    """Exposure in STOPS, which is what the word means to anyone who has held a
    camera: +1 is twice the light. Applied in linear light, not on gamma-encoded
    bytes, so a +1 does not just wash the highlights out."""
    f = 2.0 ** _clamp(stops, -5, 5)
    a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    lin = np.power(a, 2.2) * f
    out = np.power(np.clip(lin, 0, 1), 1 / 2.2)
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGB")


def op_contrast(im: Image.Image, amount: float) -> Image.Image:
    return ImageEnhance.Contrast(im.convert("RGB")).enhance(_clamp(amount, 0, 3))


def op_saturation(im: Image.Image, amount: float) -> Image.Image:
    return ImageEnhance.Color(im.convert("RGB")).enhance(_clamp(amount, 0, 3))


def op_temperature(im: Image.Image, kelvin_shift: float) -> Image.Image:
    """Warm/cool. Positive is warmer. Scaled so ±100 is a strong but not absurd
    shift, because a raw Kelvin number means nothing without a reference white."""
    k = _clamp(kelvin_shift, -100, 100) / 100.0
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    a[..., 0] *= 1.0 + 0.28 * k          # red up when warm
    a[..., 2] *= 1.0 - 0.28 * k          # blue down when warm
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def op_levels(im: Image.Image, black: int = 0, white: int = 255,
              gamma: float = 1.0) -> Image.Image:
    b, w = int(black), int(white)
    if not (0 <= b < w <= 255):
        raise ApellesError("levels need 0 <= black < white <= 255")
    g = _clamp(gamma, 0.1, 10)
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    a = np.clip((a - b) / float(w - b), 0, 1)
    a = np.power(a, 1.0 / g)
    return Image.fromarray((a * 255 + 0.5).astype(np.uint8), "RGB")


def op_sharpen(im: Image.Image, amount: float = 1.0) -> Image.Image:
    a = _clamp(amount, 0, 4)
    if a == 0:
        return im
    return im.convert("RGB").filter(
        ImageFilter.UnsharpMask(radius=2, percent=int(80 * a), threshold=3))


def op_denoise(im: Image.Image, amount: float = 1.0) -> Image.Image:
    """Edge-preserving denoise. A plain blur removes noise and the subject with
    it, which is why this uses a bilateral filter."""
    a = _clamp(amount, 0, 3)
    if a == 0:
        return im
    try:
        import cv2
        arr = np.asarray(im.convert("RGB"))
        out = cv2.bilateralFilter(arr, d=0, sigmaColor=18 * a, sigmaSpace=6 * a)
        return Image.fromarray(out, "RGB")
    except Exception:
        # Loud in the log, but a soft fallback is right here: the user asked to
        # reduce noise, and a median filter genuinely does that.
        log.warning("[apelles] bilateral denoise unavailable; using median")
        return im.convert("RGB").filter(ImageFilter.MedianFilter(size=3))


def op_resize(im: Image.Image, width: int | None = None, height: int | None = None,
              preset: str | None = None, mode: str = "cover") -> Image.Image:
    """Resize to explicit dimensions or an aspect preset.

    mode="cover" fills the target and centre-crops the overflow (what you want
    for a TikTok frame); mode="fit" letterboxes nothing and just contains the
    image inside the box, preserving every pixel.
    """
    if preset:
        key = str(preset).lower()
        if key not in ASPECT_PRESETS:
            raise ApellesError(f"unknown preset '{preset}' (have: {', '.join(sorted(ASPECT_PRESETS))})")
        tw, th = ASPECT_PRESETS[key]
    else:
        if not width or not height:
            raise ApellesError("resize needs both width and height, or a preset")
        tw, th = int(width), int(height)
    if not (MIN_DIM <= tw <= MAX_DIM and MIN_DIM <= th <= MAX_DIM):
        raise ApellesError(f"target size out of range ({tw}x{th})")
    if str(mode).lower() == "fit":
        out = im.copy()
        out.thumbnail((tw, th), Image.LANCZOS)
        return out
    return ImageOps.fit(im, (tw, th), method=Image.LANCZOS, centering=(0.5, 0.5))


# ── Export ────────────────────────────────────────────────────────────────────
def export(im: Image.Image, fmt: str = "PNG", quality: int = 92,
           strip_metadata: bool = True, source_exif: bytes | None = None,
           out_dir: Path | None = None, stem: str | None = None,
           never_overwrite: Path | None = None, dest: Path | None = None) -> dict:
    """Write a NEW file and report what happened to the metadata.

    strip_metadata defaults to True — see the flagship note above. Passing False
    is the deliberate action that preserves EXIF, and it only does anything when
    the caller also hands over the original's exif block, so metadata cannot be
    resurrected by accident from some other picture.
    """
    f = str(fmt).upper()
    if f == "JPG":
        f = "JPEG"
    if f not in ALLOWED_OUT:
        raise ApellesError(f"can't export as {fmt} (PNG, JPEG, WebP)")

    if dest is not None:
        # Batch supplies an exact destination so its dry-run can state the real
        # path instead of a pattern. Still refuses to land on anything existing.
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = Path(out_dir) if out_dir else OUT_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{(stem or 'edit')}_{uuid.uuid4().hex[:8]}.{f.lower()}"

    # Ruling C, belt and braces: even a caller that constructs its own filename
    # cannot land on the source path.
    if never_overwrite is not None and dest.resolve() == Path(never_overwrite).resolve():
        raise ApellesError("refusing to overwrite the original")
    if dest.exists():
        raise ApellesError("output name collision")

    out = im
    if f == "JPEG" and out.mode in ("RGBA", "LA", "P"):
        out = out.convert("RGB")           # JPEG has no alpha; say so by converting

    params: dict = {}
    if f == "JPEG":
        params.update(quality=int(_clamp(quality, 1, 100)), optimize=True, subsampling=1)
    elif f == "WEBP":
        params.update(quality=int(_clamp(quality, 1, 100)), method=4)
    elif f == "PNG":
        params.update(optimize=True, compress_level=6)

    removed: list[str] = []
    if strip_metadata:
        removed = describe_metadata(im)
        # Rebuilding from the raw array is the only way to be certain nothing
        # rides along in a chunk we forgot to name. Saving without an exif=
        # argument still carries ICC profiles, XMP and PNG text chunks.
        clean = Image.new(out.mode, out.size)
        clean.putdata(list(out.getdata()))
        out = clean
    elif source_exif:
        params["exif"] = source_exif

    out.save(dest, format=f, **params)
    log.info("[apelles] export fmt=%s %dx%d stripped=%s removed=%d",
             f, out.width, out.height, strip_metadata, len(removed))
    return {
        "path": str(dest),
        "format": f,
        "width": out.width,
        "height": out.height,
        "bytes": dest.stat().st_size,
        "metadata_stripped": bool(strip_metadata),
        "metadata_removed": removed,
    }


# ── Pipeline ──────────────────────────────────────────────────────────────────
_OPS = {
    "crop": op_crop, "rotate": op_rotate, "straighten": op_rotate, "flip": op_flip,
    "exposure": op_exposure, "contrast": op_contrast, "saturation": op_saturation,
    "temperature": op_temperature, "levels": op_levels, "sharpen": op_sharpen,
    "denoise": op_denoise, "resize": op_resize,
}


def apply_pipeline(im: Image.Image, steps: list[dict]) -> Image.Image:
    """Run an ordered list of {"op": name, ...args} against an image.

    Unknown ops raise rather than being skipped — a pipeline that quietly drops
    a step produces a picture the user did not ask for and cannot tell apart."""
    out = im
    for i, step in enumerate(steps or []):
        name = str(step.get("op", "")).lower()
        fn = _OPS.get(name)
        if fn is None:
            raise ApellesError(f"step {i + 1}: unknown operation '{name}'")
        args = {k: v for k, v in step.items() if k != "op"}
        try:
            out = fn(out, **args)
        except ApellesError:
            raise
        except TypeError as e:
            raise ApellesError(f"step {i + 1} ({name}): wrong arguments — {e}")
        except Exception as e:
            raise ApellesError(f"step {i + 1} ({name}) failed: {type(e).__name__}")
    return out


def edit_file(src: Path, steps: list[dict], fmt: str = "PNG", quality: int = 92,
              strip_metadata: bool = True, out_dir: Path | None = None) -> dict:
    """Whole job: open read-only → pipeline → export a new file.

    The original is untouched; `source_sha` in the result is how a caller can
    prove that rather than trust it."""
    src = Path(src)
    before = src.stat()
    im = _open_source(src)
    exif = im.info.get("exif")
    result = export(apply_pipeline(im, steps), fmt=fmt, quality=quality,
                    strip_metadata=strip_metadata, source_exif=exif,
                    out_dir=out_dir, stem=src.stem[:32], never_overwrite=src)
    after = src.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ApellesError("INVARIANT BROKEN: the original changed during the edit")
    result["original_intact"] = True
    return result


# ── Tier 4: batch ─────────────────────────────────────────────────────────────
# Ruling C matters most here. A careless pipeline pointed at a folder of
# irreplaceable photos is exactly the scenario the non-destructive rule exists
# for, so batch NEVER writes into the source folder: outputs go to a separate
# directory, and the dry-run shows every destination before a byte is written.
import json as _json
import threading as _threading

PIPELINES_PATH: Path = APELLES_DATA / "pipelines.json"

# Shipped recipes, because "the Etsy pipeline" and "the TikTok pipeline" are the
# actual reason anyone opens a batch tool.
BUILTIN_PIPELINES: dict[str, list[dict]] = {
    "etsy":     [{"op": "resize", "preset": "square"}, {"op": "sharpen", "amount": 0.8}],
    "tiktok":   [{"op": "resize", "preset": "tiktok"}],
    "linkedin": [{"op": "resize", "preset": "linkedin_headshot"}, {"op": "sharpen", "amount": 0.6}],
    "youtube":  [{"op": "resize", "preset": "youtube_thumb"}, {"op": "contrast", "amount": 1.1}],
}

_BATCHES: dict[str, dict] = {}
_BATCH_LOCK = _threading.Lock()


def _valid_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_-]+", "_", str(name or "").strip().lower())[:40].strip("_")
    if not n:
        raise ApellesError("that pipeline name isn't usable")
    return n


def list_pipelines() -> dict[str, list[dict]]:
    """Built-ins plus anything the user saved. User entries win on a name clash,
    so a saved 'etsy' overrides the shipped one rather than silently doing
    something different from what the name says."""
    out = dict(BUILTIN_PIPELINES)
    try:
        if PIPELINES_PATH.exists():
            saved = _json.loads(PIPELINES_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                out.update({k: v for k, v in saved.items() if isinstance(v, list)})
    except Exception:
        log.warning("[apelles] saved pipelines unreadable; serving built-ins only")
    return out


def save_pipeline(name: str, steps: list[dict]) -> dict:
    n = _valid_name(name)
    # Validate against a scratch image now, so a broken pipeline fails at SAVE
    # time rather than 400 files into a batch.
    apply_pipeline(Image.new("RGB", (64, 64)), steps)
    saved = {}
    try:
        if PIPELINES_PATH.exists():
            saved = _json.loads(PIPELINES_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        saved = {}
    saved[n] = steps
    PIPELINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PIPELINES_PATH.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(saved, indent=2), encoding="utf-8")
    os.replace(tmp, PIPELINES_PATH)
    return {"name": n, "steps": steps}


def delete_pipeline(name: str) -> bool:
    n = _valid_name(name)
    if n in BUILTIN_PIPELINES:
        raise ApellesError(f"'{n}' is a built-in pipeline and can't be deleted")
    try:
        saved = _json.loads(PIPELINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    if n not in saved:
        return False
    saved.pop(n)
    PIPELINES_PATH.write_text(_json.dumps(saved, indent=2), encoding="utf-8")
    return True


def _scan_folder(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise ApellesError("that isn't a folder I can read")
    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in exts)


def batch_plan(folder: Path, steps: list[dict], fmt: str = "PNG",
               out_dir: Path | None = None) -> dict:
    """DRY RUN. Lists exactly what would be produced and where — before anything
    is written. Files that cannot be read are listed as such here, so a batch
    does not surprise the user halfway through."""
    folder = Path(folder)
    f = "JPEG" if str(fmt).upper() == "JPG" else str(fmt).upper()
    if f not in ALLOWED_OUT:
        raise ApellesError(f"can't export as {fmt} (PNG, JPEG, WebP)")
    apply_pipeline(Image.new("RGB", (64, 64)), steps)      # fail early, not mid-run

    dest_dir = Path(out_dir) if out_dir else (OUT_DIR / f"batch_{uuid.uuid4().hex[:8]}")
    if dest_dir.resolve() == folder.resolve():
        raise ApellesError("batch output can't go into the source folder — originals stay untouched")

    items, ok = [], 0
    for src in _scan_folder(folder):
        dest = dest_dir / f"{src.stem}.{f.lower()}"
        row = {"source": src.name, "dest": str(dest), "status": "ready", "reason": None}
        try:
            info = probe(src)
            row["size"] = f"{info['width']}x{info['height']}"
        except ApellesError as e:
            row.update(status="unreadable", reason=str(e))
        if row["status"] == "ready" and dest.exists():
            row.update(status="collision", reason="a file of that name is already there")
        if row["status"] == "ready":
            ok += 1
        items.append(row)
    return {
        "folder": str(folder), "out_dir": str(dest_dir), "format": f,
        "total": len(items), "ready": ok, "problems": len(items) - ok,
        "items": items, "written": False,
        "note": "Dry run — nothing has been written. Originals are never modified.",
    }


def batch_start(folder: Path, steps: list[dict], fmt: str = "PNG", quality: int = 92,
                strip_metadata: bool = True, out_dir: Path | None = None) -> str:
    """Reserve a batch and FREEZE its plan.

    The plan is stored, not recomputed at execute time: with no explicit out_dir
    each call would mint a different random directory, so status would report one
    path while the files landed in another."""
    plan = batch_plan(folder, steps, fmt=fmt, out_dir=out_dir)
    bid = uuid.uuid4().hex[:12]
    with _BATCH_LOCK:
        _BATCHES[bid] = {"id": bid, "state": "running", "cancel": False,
                         "total": plan["total"], "done": 0, "ok": 0, "failed": 0,
                         "out_dir": plan["out_dir"], "results": [],
                         "_plan": plan, "_steps": steps,
                         "_quality": quality, "_strip": strip_metadata}
    return bid


def batch_status(bid: str) -> dict | None:
    with _BATCH_LOCK:
        b = _BATCHES.get(bid)
        if not b:
            return None
        pub = {k: v for k, v in b.items() if not k.startswith("_")}
        pub["results"] = list(b["results"])
        return pub


def batch_cancel(bid: str) -> bool:
    with _BATCH_LOCK:
        b = _BATCHES.get(bid)
        if not b or b["state"] != "running":
            return False
        b["cancel"] = True
        return True


def batch_execute(bid: str) -> dict:
    """Run the FROZEN plan from batch_start. One bad file is REPORTED and the run
    continues — it is not silently skipped, and it does not abort the batch."""
    with _BATCH_LOCK:
        b = _BATCHES.get(bid)
        if b is None:
            raise ApellesError("that batch is gone")
        plan, steps = b["_plan"], b["_steps"]
        quality, strip_metadata = b["_quality"], b["_strip"]
    f = plan["format"]
    for row in plan["items"]:
        with _BATCH_LOCK:
            b = _BATCHES.get(bid)
            if b is None:
                raise ApellesError("that batch is gone")
            if b["cancel"]:
                b["state"] = "cancelled"
                return batch_status(bid)
        src = Path(plan["folder"]) / row["source"]
        entry = {"source": row["source"], "dest": row["dest"]}
        if row["status"] != "ready":
            entry.update(ok=False, reason=row["reason"])
        else:
            try:
                before = src.stat()
                im = _open_source(src)
                res = export(apply_pipeline(im, steps), fmt=f, quality=quality,
                             strip_metadata=strip_metadata,
                             source_exif=im.info.get("exif"), dest=Path(row["dest"]),
                             never_overwrite=src)
                after = src.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ApellesError("INVARIANT BROKEN: original changed during batch")
                entry.update(ok=True, reason=None, width=res["width"], height=res["height"],
                             metadata_removed=res["metadata_removed"])
            except Exception as e:
                entry.update(ok=False, reason=str(e) if isinstance(e, ApellesError)
                             else f"{type(e).__name__}")
        with _BATCH_LOCK:
            b = _BATCHES[bid]
            b["results"].append(entry)
            b["done"] += 1
            b["ok" if entry["ok"] else "failed"] += 1
    with _BATCH_LOCK:
        b = _BATCHES[bid]
        b["state"] = "done"
    log.info("[apelles] batch %s finished total=%d ok=%d failed=%d",
             bid, b["total"], b["ok"], b["failed"])
    return batch_status(bid)


# ── Capability map ────────────────────────────────────────────────────────────
# THE GOVERNING RULE of the surface: every operation Apelles knows about appears
# in the interface, and the unavailable ones say WHY. A selector that lists only
# what happens to work is indistinguishable from a selector that is broken —
# that was the Amphion Mode-dropdown lesson, and it is a standing rule now.
#
# Read from actual node and model presence. Nothing here is hardcoded to
# "unavailable": drop a model into the right folder, restart, and the feature
# lights up on its own with no code change.
_COMFY_HOST = os.getenv("COMFY_HOST", "http://127.0.0.1:8188")
_COMFY_MODELS = Path(os.getenv("COMFY_MODELS_DIR",
                               str(Path.home() / "Desktop" / "comfyui" / "models")))
_PLACEHOLDER = re.compile(r"^put_.*_here$|^\.", re.I)

_caps_cache: dict | None = None


def _models_in(subdir: str) -> list[str]:
    """Real model files in a ComfyUI model folder, ignoring the placeholder
    'put_x_here' breadcrumbs ComfyUI ships."""
    d = _COMFY_MODELS / subdir
    try:
        return [p.name for p in d.iterdir()
                if p.is_file() and not _PLACEHOLDER.match(p.name)]
    except Exception:
        return []


def _comfy_nodes(timeout: float = 3.0) -> set[str] | None:
    """Node types ComfyUI currently exposes, or None if it isn't reachable.

    None and empty are different answers and must stay different: 'ComfyUI is
    down' is a fixable outage, 'the node isn't installed' is a missing file."""
    try:
        import httpx
        r = httpx.get(f"{_COMFY_HOST}/object_info", timeout=timeout)
        if r.status_code != 200:
            return None
        return set(r.json().keys())
    except Exception:
        return None


def capabilities(refresh: bool = False) -> dict:
    """What Apelles can actually do on THIS box, right now, with reasons.

    The UI renders straight from this, so anything the UI shows disabled has its
    explanation from the same source the chat tools quote."""
    global _caps_cache
    if _caps_cache is not None and not refresh:
        return _caps_cache

    nodes = _comfy_nodes()
    comfy_up = nodes is not None
    have = (lambda *n: comfy_up and any(x in nodes for x in n))

    def _any_node(pattern: str) -> bool:
        return comfy_up and any(re.search(pattern, n, re.I) for n in nodes)

    upscale_models = _models_in("upscale_models")
    checkpoints = _models_in("checkpoints")
    sdxl = [c for c in checkpoints if "xl" in c.lower()]

    try:
        import rembg  # noqa: F401
        have_rembg = True
    except Exception:
        have_rembg = False
    bg_node = _any_node(r"birefnet|rembg|removebg|imagesegment")
    # The u2net matting model was already on this box. We run it directly through
    # onnxruntime rather than installing the rembg wrapper, which would have meant
    # a download — the capability was present all along, just not detected.
    have_matte = u2net_available()
    bg_ok = have_rembg or bg_node or have_matte

    def cap(cid, label, tier, ok, reason=None, fix=None):
        return {"id": cid, "label": label, "tier": tier, "available": bool(ok),
                "reason": None if ok else reason, "fix": None if ok else fix}

    tier1 = [cap(k, l, 1, True) for k, l in [
        ("crop", "Crop"), ("rotate", "Rotate / straighten"), ("flip", "Flip"),
        ("exposure", "Exposure"), ("contrast", "Contrast"), ("saturation", "Saturation"),
        ("temperature", "Temperature"), ("levels", "Levels"), ("sharpen", "Sharpen"),
        ("denoise", "Denoise"), ("resize", "Resize / aspect presets"),
        ("descratch", "Dust & scratch removal (scans)"),
        ("clahe", "Local contrast / fade recovery (CLAHE)"),
        ("decast", "Remove age colour cast"),
        ("deblur", "Deblur (Wiener deconvolution)"),
        ("export", "Export (PNG / JPEG / WebP)"), ("strip_metadata", "Strip metadata"),
    ]]

    comfy_down = "ComfyUI isn't reachable" if not comfy_up else None
    items = tier1 + [
        cap("background_removal", "Background removal (u2net, local)", 2, bg_ok,
            "no matting model found (~/.u2net/u2net.onnx)",
            "put a u2net.onnx in ~/.u2net/, or add a BiRefNet node to ComfyUI"),
        cap("composite", "Composite onto colour / image", 2, bg_ok,
            "needs background removal, which has no model",
            "same as background removal"),
        cap("edge_refine", "Edge refine (erode / feather)", 2, bg_ok,
            "needs a cutout to refine",
            "same as background removal"),
        cap("upscale", "Upscale (Real-ESRGAN)", 3,
            bool(upscale_models) and have("ImageUpscaleWithModel"),
            comfy_down or "no model in models/upscale_models/",
            "drop a Real-ESRGAN .pth into models/upscale_models/ and restart"),
        cap("object_removal", "Object removal (inpaint)", 3,
            bool(sdxl) and have("VAEEncodeForInpaint", "SetLatentNoiseMask"),
            comfy_down or "no SDXL checkpoint found",
            "add an SDXL checkpoint to models/checkpoints/"),
        cap("outpaint", "Canvas extend / outpaint", 3,
            bool(sdxl) and have("ImagePadForOutpaint"),
            comfy_down or "no SDXL checkpoint found",
            "add an SDXL checkpoint to models/checkpoints/"),
        cap("depth_blur", "Depth-based background blur", 3,
            _any_node(r"depthanything|midas|zoedepth|depthmap"),
            comfy_down or "no depth-estimation node in ComfyUI",
            "install a depth node (Depth Anything / MiDaS) in ComfyUI"),
        # RESTORATION is the in-scope half of ruling B and genuinely wanted (old
        # photos, graphic-design work). But the popular ComfyUI "face" nodes —
        # ReActor above all — are face SWAPPERS that happen to bundle restoration.
        # Telling someone to "install a face-restore node" would hand them the exact
        # capability this module welds shut. So the advice names restoration-only
        # options and says why, rather than sending them to the top search result.
        cap("face_restore", "Face restoration (in-photo only)", 3,
            _any_node(r"gfpgan|codeformer|restoreformer|facerestore(?!.*reactor)"),
            comfy_down or "no restoration model on this box",
            "drop a GFPGAN or CodeFormer model in and restart. Use a RESTORATION-ONLY "
            "package — do NOT install ReActor or any 'face swap' node: those add "
            "identity replacement, which Apelles refuses by design"),
        cap("batch", "Batch a folder through a pipeline", 4, True),
    ]

    # Ruling B is stated in the capability map too, so the UI can show that face
    # replacement is REFUSED rather than merely missing. "Not installed" and
    # "we will not build this" are different claims and must read differently.
    welded = [{"id": "face_replacement", "label": "Face swap / replacement",
               "tier": None, "available": False, "welded": True,
               "reason": "permanently refused — Ph3b3 doesn't put a person somewhere they weren't",
               "fix": None}]

    out = {
        "comfy_reachable": comfy_up,
        "available": sum(1 for i in items if i["available"]),
        "total": len(items),
        "items": items,
        "welded": welded,
        "presets": sorted(ASPECT_PRESETS),
        "pipelines": sorted(list_pipelines()),
    }
    _caps_cache = out
    return out


def capability(cid: str) -> dict | None:
    for i in capabilities()["items"] + capabilities()["welded"]:
        if i["id"] == cid:
            return i
    return None


def require(cid: str) -> None:
    """Raise the SPECIFIC reason a blocked operation is blocked.

    Chat and HTTP both call this, so 'remove the background' gets 'the model
    isn't installed on this box' rather than a generic failure."""
    c = capability(cid)
    if c is None:
        raise ApellesError(f"'{cid}' isn't an operation I have")
    if not c["available"]:
        msg = f"{c['label']} — unavailable: {c['reason']}"
        if c.get("fix"):
            msg += f". To enable it: {c['fix']}"
        raise ApellesError(msg)


# ── Intent claims ─────────────────────────────────────────────────────────────
# "What can you do to photos?" was being answered by the model, which cheerfully
# described the CAMERA — it talked about taking pictures and LLaVA, none of which
# is photo editing, and none of which it checked. Same class as Metis: a question
# about what this machine can actually do must be answered from the machine, not
# improvised. So the capability question is claimed deterministically.
#
# The edit claim only takes turns that are clearly about EDITING an existing
# picture. "Take a photo" and "what do you see" belong to vision and must not be
# swallowed here.
import intent_registry as _ir

_PHOTO_CAP_RE = re.compile(
    r"\b(?:what|which|can|could|are)\b[^.?]{0,60}"
    r"(?:"
    r"(?:do\s+(?:to|with)|edit|editing|editor|adjust|able\s+to\s+edit)"
    r"[^.?]{0,25}\b(?:photos?|pictures?|images?)\b"
    r"|\b(?:photos?|pictures?|images?)\b[^.?]{0,25}"
    r"(?:edit|editing|editor|do\s+(?:to|with)|adjust)"
    r")"
    r"|\bwhat\b[^.?]{0,25}\bapelles\b"
    r"|\bphoto[- ]?editing\b[^.?]{0,25}\b(?:can|able|support|available)\b",
    re.I,
)

# Vision owns the camera, and a CONCRETE edit request owns itself. If the turn
# names an actual operation ("crop this", "convert it to jpeg") it must reach the
# tools, not be answered with a list of what's possible.
_NOT_APELLES_RE = re.compile(
    r"\b(?:take|snap|shoot|capture)\s+(?:a\s+|another\s+)?(?:photo|picture|selfie|shot)\b"
    r"|\bwhat\s+(?:do|can)\s+you\s+see\b|\bdescribe\s+(?:what|the\s+(?:view|scene))\b"
    r"|\blook\s+(?:at\s+)?(?:through\s+)?(?:the\s+)?camera\b"
    r"|\b(?:crop|resize|rotate|straighten|convert|export|brighten|darken|sharpen|"
    r"denoise|strip|batch)\b",
    re.I,
)

_ir.register("apelles", "photo_capabilities", _PHOTO_CAP_RE, exclude=_NOT_APELLES_RE)


# ── Tier 2: cutout suite ──────────────────────────────────────────────────────
# Runs the u2net matting model that is ALREADY on this box (~/.u2net/u2net.onnx)
# straight through onnxruntime. The `rembg` package is only a thin wrapper around
# exactly this, and installing it would mean a download; the model is local, so
# the zero-egress rule is kept rather than argued with. Nothing is fetched.
U2NET_PATH = Path(os.getenv("APELLES_U2NET", str(Path.home() / ".u2net" / "u2net.onnx")))
_u2net_session = None


def u2net_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return U2NET_PATH.is_file()


def _u2net():
    global _u2net_session
    if _u2net_session is None:
        import onnxruntime as ort
        if not U2NET_PATH.is_file():
            raise ApellesError("the background-removal model isn't on this machine")
        # CPU on purpose: the GPU has six tenants and a 168 MB matting pass does not
        # justify evicting one of them. It costs a couple of seconds.
        _u2net_session = ort.InferenceSession(str(U2NET_PATH),
                                              providers=["CPUExecutionProvider"])
    return _u2net_session


def alpha_matte(im: Image.Image) -> Image.Image:
    """Single-channel foreground matte at the image's own size."""
    sess = _u2net()
    rgb = im.convert("RGB")
    small = rgb.resize((320, 320), Image.LANCZOS)
    a = np.asarray(small, dtype=np.float32) / 255.0
    # u2net's normalisation, not ImageNet's — using the wrong one produces a matte
    # that looks plausible and is subtly wrong at the edges.
    a = (a - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    a = np.transpose(a, (2, 0, 1))[None].astype(np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: a})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    out = (out - lo) / (hi - lo) if hi > lo else out * 0
    m = Image.fromarray((out * 255).astype(np.uint8), "L")
    return m.resize(rgb.size, Image.LANCZOS)


def op_remove_background(im: Image.Image, erode: int = 1, feather: float = 1.5) -> Image.Image:
    """Cut the subject out. Returns RGBA with a real alpha channel.

    erode/feather are the HALO FIX and are on by default: a cutout that keeps a
    one-pixel fringe of the original wall is the single most common failure of
    every tool in this category, and shipping it off-by-default would just mean
    shipping that failure."""
    matte = alpha_matte(im)
    matte = op_edge_refine(matte, erode=erode, feather=feather)
    out = im.convert("RGBA")
    out.putalpha(matte)
    return out


def op_edge_refine(mask: Image.Image, erode: int = 1, feather: float = 1.5) -> Image.Image:
    """Pull the matte in slightly, then soften it. Order matters: feather-then-erode
    eats the softness you just made."""
    m = mask.convert("L")
    e = int(max(0, min(int(erode), 12)))
    if e:
        m = m.filter(ImageFilter.MinFilter(size=2 * e + 1))
    f = float(max(0.0, min(float(feather), 12.0)))
    if f:
        m = m.filter(ImageFilter.GaussianBlur(radius=f))
    return m


def _parse_colour(c) -> tuple:
    if isinstance(c, (list, tuple)) and len(c) in (3, 4):
        return tuple(int(x) for x in c)
    s = str(c or "white").strip().lower()
    named = {"white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128),
             "gray": (128, 128, 128), "transparent": None}
    if s in named:
        return named[s]
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        v = m.group(1)
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    raise ApellesError(f"I don't recognise the colour '{c}'")


def op_composite(im: Image.Image, background="white") -> Image.Image:
    """Place a cut-out subject on a solid colour (or leave it transparent).

    Accepts an already-RGBA cutout, or does the cutout itself if handed a flat
    image — so "put me on white" is one step for the user."""
    src = im if im.mode == "RGBA" else op_remove_background(im)
    colour = _parse_colour(background)
    if colour is None:
        return src
    bg = Image.new("RGBA", src.size, tuple(colour) + (255,) if len(colour) == 3 else tuple(colour))
    return Image.alpha_composite(bg, src)


_OPS["remove_background"] = op_remove_background
_OPS["composite"] = op_composite


# ── Blocked-operation requests must fail CLOSED ───────────────────────────────
# Found during the values audit: asked to "restore the blurry face in this old
# photo", the model replied "Let me use my camera... [camera sound] There we go.
# The restored version shows much greater detail" — a confident description of
# work that never happened, for a capability with no model installed. Exactly the
# Metis fabrication class: an unavailable capability answered from imagination.
#
# So a request naming a SPECIFIC operation is resolved against the capability map
# before the model ever sees it. Unavailable → the honest reason, deterministically.
# Available → return None and let normal tool routing do its job; this gate exists
# to prevent invention, not to intercept work that can actually be done.
_OP_PHRASES: tuple = (
    # FACE-specific generative restoration only. General scan restoration is now
    # available (non-generative), so "restore this old photo" must NOT be refused
    # — refusing something we can actually do is its own kind of dishonesty.
    ("face_restore", re.compile(
        r"\b(?:restore|restoration|deblur|unblur|repair|reconstruct)\b"
        r"[^.?]{0,40}\bfaces?\b"
        r"|\bfaces?\b[^.?]{0,40}\b(?:restore|restoration|deblur|unblur|reconstruct)\b",
        re.I)),
    ("upscale", re.compile(
        r"\b(?:upscale|up-?res|enlarge|super[\s-]?resolution|make\s+it\s+(?:bigger|larger|higher\s+res)"
        r"|increase\s+the\s+resolution|4k\s+it)\b", re.I)),
    ("depth_blur", re.compile(
        r"\b(?:bokeh|depth\s+blur|blur\s+the\s+background|portrait\s+mode)\b", re.I)),
    ("object_removal", re.compile(
        r"\b(?:remove|erase|get\s+rid\s+of|delete)\b[^.?]{0,30}"
        r"\b(?:object|person|thing|photobomber|sign|car|logo)\b", re.I)),
    ("background_removal", re.compile(
        r"\b(?:remove|cut\s+out|knock\s+out|delete)\b[^.?]{0,20}\bbackgrounds?\b"
        r"|\bbackgrounds?\b[^.?]{0,20}\b(?:removed?|cut\s+out)\b"
        r"|\bwhite\s+background\b", re.I)),
)


def blocked_request(text: str) -> str | None:
    """If the turn asks for an operation this box cannot do, say so honestly.

    Returns None when the operation IS available (normal routing proceeds) and
    when no specific operation is named."""
    t = _normalize(text or "")
    for cid, rx in _OP_PHRASES:
        if not rx.search(t):
            continue
        c = capability(cid)
        if c is None or c.get("available"):
            return None                     # we can do it — don't intercept
        msg = (f"I can't do that one on this machine. {c['label']} is unavailable: "
               f"{c['reason']}.")
        if c.get("fix"):
            msg += f" To enable it: {c['fix']}."
        if cid == "face_restore":
            # Don't leave them with only a no. The non-generative restoration is
            # real and often enough for a faded scan.
            msg += (" What I CAN do is scan restoration — dust and scratch removal, "
                    "fade and colour-cast recovery, and deconvolution sharpening. "
                    "That's all non-generative: it recovers what's in the picture "
                    "rather than inventing detail, so it won't reconstruct a face "
                    "that's genuinely gone, but on a faded or dusty print it does a "
                    "lot. Say restore this scan and I'll run it.")
        return msg + (" I'd rather tell you that than describe a result I didn't produce.")
    return None


# ── Scan restoration — NON-GENERATIVE ─────────────────────────────────────────
# For faded, dusty, scratched and softly-blurred scans of real photographs.
#
# THE PROPERTY THAT MATTERS: nothing here invents. Every output pixel is derived
# from input pixels — a median of its neighbours, a redistribution of its own
# histogram, a deconvolution of the frequencies actually present. There is no
# learned prior and no model, so this cannot produce a face that isn't the
# person's. That is the whole reason it ships before the generative kind: it is
# the honest baseline the generative version has to be measured against.
#
# The one operation that fills pixels it did not have is `descratch`, and it
# fills them by diffusing SURROUNDING pixels into a speck-sized hole (Telea),
# not by imagining content. It is deliberately conservative — see the size cap.


def _cv(im: Image.Image) -> "np.ndarray":
    import cv2
    return cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def _pil(arr) -> Image.Image:
    import cv2
    return Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB), "RGB")


def op_descratch(im: Image.Image, strength: float = 1.0, max_speck: int = 5) -> Image.Image:
    """Remove dust specks and hairline scratches from a scan.

    Finds pixels that disagree sharply with their neighbourhood, keeps only the
    SMALL ones (a speck, not a feature), and diffuses the surrounding pixels in.
    The size cap is what stops it eating eyes, jewellery and starfields — the
    classic failure of every dust-removal filter that was too pleased with itself.
    """
    import cv2
    s = _clamp(strength, 0.0, 3.0)
    if s == 0:
        return im
    src = _cv(im)
    grey = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    med = cv2.medianBlur(grey, 5)
    diff = cv2.absdiff(grey, med)
    # Threshold scales with the image's own noise, so a clean scan isn't attacked
    # and a filthy one isn't under-treated.
    sigma = float(np.std(diff)) or 1.0
    thresh = max(6.0, (14.0 / max(s, 0.05)) * (sigma / 8.0))
    mask = (diff > thresh).astype(np.uint8) * 255
    # Keep only small blobs: anything bigger than max_speck px across is picture.
    k = int(max(1, min(int(max_speck), 15)))
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    mask = cv2.subtract(mask, opened)          # drop the big stuff — that's content
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    if int(mask.sum()) == 0:
        return im
    out = cv2.inpaint(src, mask, 3, cv2.INPAINT_TELEA)
    return _pil(out)


def op_clahe(im: Image.Image, clip: float = 2.0, grid: int = 8) -> Image.Image:
    """Local contrast (CLAHE) on lightness only.

    Applied to L in LAB so colours are not pushed around — a global curve either
    blows the highlights or leaves the shadows dead, which is exactly the failure
    of a faded scan."""
    import cv2
    c = _clamp(clip, 0.1, 8.0)
    g = int(_clamp(grid, 2, 16))
    lab = cv2.cvtColor(_cv(im), cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=c, tileGridSize=(g, g)).apply(l)
    return _pil(cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR))


def op_decast(im: Image.Image, amount: float = 1.0) -> Image.Image:
    """Pull out an age cast (the yellow/orange of a faded print).

    Percentile-anchored per channel rather than grey-world: grey-world is fooled
    by a legitimately warm photograph, and 'correcting' a sunset is a bug."""
    a = _clamp(amount, 0.0, 1.0)
    if a == 0:
        return im
    arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    out = arr.copy()
    for ch in range(3):
        lo, hi = np.percentile(arr[..., ch], (1.0, 99.0))
        if hi - lo < 1e-3:
            continue
        stretched = (arr[..., ch] - lo) * (255.0 / (hi - lo))
        out[..., ch] = arr[..., ch] * (1 - a) + stretched * a
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGB")


def _psf(radius: float, angle: float | None) -> "np.ndarray":
    """Point-spread function: a disc/gaussian for defocus, a line for motion."""
    r = max(0.6, float(radius))
    if angle is None:
        n = int(max(3, round(r * 6)) | 1)
        ax = np.arange(n) - n // 2
        xx, yy = np.meshgrid(ax, ax)
        k = np.exp(-(xx ** 2 + yy ** 2) / (2 * (r ** 2)))
    else:
        n = int(max(3, round(r * 2)) | 1)
        k = np.zeros((n, n), np.float32)
        th = np.deg2rad(float(angle))
        for t in np.linspace(-r, r, n * 4):
            x = int(round(n // 2 + t * np.cos(th)))
            y = int(round(n // 2 + t * np.sin(th)))
            if 0 <= x < n and 0 <= y < n:
                k[y, x] = 1.0
    tot = k.sum()
    return (k / tot).astype(np.float32) if tot else k


def op_deblur(im: Image.Image, radius: float = 2.0, angle: float | None = None,
              noise: float = 0.012) -> Image.Image:
    """Wiener deconvolution — recover detail the blur SMEARED, not detail it erased.

    This is the honest ceiling of non-generative sharpening: it can undo a known
    point-spread function, and where the blur destroyed a frequency entirely there
    is nothing to bring back. It will not rescue a hopeless face, and it does not
    pretend to. Over-pushing shows as ringing, which is the image telling the truth
    about how much information was actually there."""
    k = _psf(radius, angle)
    nsr = float(_clamp(noise, 1e-4, 1.0))
    arr = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    h, w = arr.shape[:2]
    pad = max(k.shape) * 2
    out = np.empty_like(arr)
    K = None
    for ch in range(3):
        # Reflect-pad so the FFT's wraparound doesn't smear the opposite edge in.
        c = np.pad(arr[..., ch], pad, mode="reflect")
        if K is None:
            kp = np.zeros_like(c)
            kh, kw = k.shape
            kp[:kh, :kw] = k
            kp = np.roll(kp, (-(kh // 2), -(kw // 2)), axis=(0, 1))
            K = np.fft.rfft2(kp)
        G = np.fft.rfft2(c)
        F = G * np.conj(K) / (np.abs(K) ** 2 + nsr)
        r = np.fft.irfft2(F, s=c.shape)
        out[..., ch] = r[pad:pad + h, pad:pad + w]
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


_OPS["descratch"] = op_descratch
_OPS["clahe"] = op_clahe
_OPS["decast"] = op_decast
_OPS["deblur"] = op_deblur

# A default recipe for "this is an old scan". Conservative on purpose: it should
# make a faded print legible, not make it look processed.
BUILTIN_PIPELINES["restore_scan"] = [
    {"op": "descratch", "strength": 1.0},
    {"op": "decast", "amount": 0.7},
    {"op": "clahe", "clip": 2.0},
    {"op": "deblur", "radius": 1.4},
]


# Restoration is claimed deterministically too. Left to the tool picker, the model
# improvised a workflow — "Stack-chan will use her camera to take a new photo…
# this process typically takes a few minutes" — for an operation that uses the
# already-loaded photo and finishes in under a second. Not a fabricated result
# this time, but a fabricated procedure, and the user would have waited for it.
_RESTORE_RE_CLAIM = re.compile(
    r"\b(?:restore|restoration|clean\s*up|fix|repair|rescue)\b[^.?]{0,40}"
    r"\b(?:scan|scans|old|faded|fading|damaged|scratched|dusty|vintage|antique|"
    r"yellowed|photo|photos|photograph|picture|print)\b"
    r"|\b(?:old|faded|damaged|scratched|dusty|vintage)\s+"
    r"(?:photo|photograph|picture|print|scan)\b[^.?]{0,30}\b(?:restore|fix|clean)\b",
    re.I,
)
# The face half is refused earlier by blocked_request(), which runs BEFORE intent
# resolution, so a face request can never land here.
_ir.register("apelles", "restore_scan", _RESTORE_RE_CLAIM)


def descratch_stats(im: Image.Image, strength: float = 1.0, max_speck: int = 5) -> dict:
    """How much `descratch` would change, WITHOUT changing it.

    Exists because of a values-audit finding: at two pixels across, a dust speck
    and a freckle are the same object to any local-contrast test. There is no
    threshold that removes one and keeps the other — that is physics, not a bug
    to fix. So the honest move is to report the damage rather than choose
    silently: how many specks, and how much of the frame they cover. A user who
    can see "412 specks, 0.08% of the image" alongside a before/after has what
    they need to notice a mole went missing.
    """
    import cv2
    s = _clamp(strength, 0.0, 3.0)
    if s == 0:
        return {"specks": 0, "pixels": 0, "percent": 0.0}
    src = _cv(im)
    grey = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(grey, cv2.medianBlur(grey, 5))
    sigma = float(np.std(diff)) or 1.0
    thresh = max(6.0, (14.0 / max(s, 0.05)) * (sigma / 8.0))
    mask = (diff > thresh).astype(np.uint8) * 255
    k = int(max(1, min(int(max_speck), 15)))
    opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    mask = cv2.subtract(mask, opened)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    px = int((mask > 0).sum())
    total = mask.shape[0] * mask.shape[1]
    return {"specks": max(0, n - 1), "pixels": px,
            "percent": round(100.0 * px / total, 3) if total else 0.0}


def assess(im: Image.Image) -> dict:
    """Does this actually look like a damaged scan?

    Values-audit finding: the restore preset IMPROVES a faded scan (PSNR 14.9 →
    21.1 dB) and DEGRADES a photo that was already fine (19.7 dB against the
    original, with the dust pass flagging 3.8% of the frame). Worse, the speck
    count is inverted as a signal — a sharp, detailed photo produces MORE
    "specks" than a dusty one, because hair and skin texture look exactly like
    dirt to a local-contrast test. So degradation is judged on things that do not
    invert: dynamic range, colour cast and high-frequency energy.

    This is advisory. It never blocks — the user may know something the numbers
    don't — but running restoration on a healthy photo should say so first.
    """
    import cv2
    # Measure at a CANONICAL size. Laplacian variance scales with resolution, so
    # thresholds tuned on a thumbnail silently invert on a full-size scan — which
    # is exactly how the first version of this passed its unit test and then
    # failed to warn on a 2544x3392 photo through the live service.
    probe_im = im.convert("RGB")
    if max(probe_im.size) > 1000:
        probe_im = probe_im.copy()
        probe_im.thumbnail((1000, 1000), Image.LANCZOS)
    arr = np.asarray(probe_im, dtype=np.float32)
    grey = cv2.cvtColor(np.asarray(probe_im), cv2.COLOR_RGB2GRAY)
    lo, hi = np.percentile(grey, (1, 99))
    rng = float(hi - lo)                       # faded prints lose the ends
    cast = float(np.std([arr[..., i].mean() for i in range(3)]))
    focus = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    faded = rng < 170
    casted = cast > 14.0
    soft = focus < 120.0
    reasons = []
    if faded:
        reasons.append(f"washed-out range ({rng:.0f}/255)")
    if casted:
        reasons.append(f"colour cast ({cast:.1f})")
    if soft:
        reasons.append(f"soft focus (detail energy {focus:.0f})")
    return {"degraded": bool(faded or casted or soft), "range": round(rng, 1),
            "cast": round(cast, 1), "focus": round(focus, 1), "reasons": reasons}


# ── Tier 3: upscale ───────────────────────────────────────────────────────────
# Through ComfyUI, on the SAME queue and gpu_lock as Morpheus and Amphion — the
# brief is explicit that a second inference path does not get stood up, and the
# GPU already has six tenants arguing over 16 GB.
#
# Nothing here is conditional on a model existing: the graph is built the same way
# whether or not one is installed, and the capability map decides whether it can
# run. Drop a Real-ESRGAN file into models/upscale_models/, restart, and it works
# with no code change — that is the whole point of reading capability from disk.
UPSCALE_DIR_HINT = "models/upscale_models/"


def upscale_models() -> list[str]:
    """Installed upscale models, newest-looking name first for a stable default."""
    return sorted(_models_in("upscale_models"))


def build_upscale_workflow(input_filename: str, model_name: str,
                           out_prefix: str = "apelles/upscale") -> dict:
    """LoadImage → UpscaleModelLoader → ImageUpscaleWithModel → SaveImage.

    The scale factor is a property of the MODEL (a 4x ESRGAN is 4x), not a knob —
    exposing a scale slider here would be a lie about what the model does. If the
    user wants a specific size afterwards, that is `resize`, which is honest about
    being a resample."""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": input_filename}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model_name}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["3", 0], "filename_prefix": out_prefix}},
    }


def upscale_precheck(model_name: str | None = None) -> tuple[str, str | None]:
    """Resolve which model to use, or say plainly why we can't.

    Returns (model_name, error). Never guesses: a named model that isn't there is
    an error, not a silent fallback to whichever file happens to be first."""
    have = upscale_models()
    if not have:
        return "", ("There's no upscale model on this machine. Drop a Real-ESRGAN "
                    f"file into {UPSCALE_DIR_HINT} and restart, and this turns on by "
                    "itself — no code change needed.")
    if model_name:
        if model_name not in have:
            return "", (f"I don't have '{model_name}'. Installed: {', '.join(have)}.")
        return model_name, None
    return have[0], None
