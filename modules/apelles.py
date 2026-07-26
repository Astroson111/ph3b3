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
    r"replace\s+(?:the\s+|his\s+|her\s+|their\s+|my\s+)?face",
    r"put\s+(?:my|his|her|their|\w+'s)\s+face\s+(?:on|onto|in|into)",
    r"swap\s+(?:my|his|her|their)\s+face",
    r"(?:his|her|their|my|\w+'s)\s+face\s+on\s+(?:another|someone|a\s+different)",
    r"identity\s+transfer", r"face\s+transplant",
    r"make\s+it\s+look\s+like\s+\w+\s+(?:was|were)\s+(?:there|in\s+the\s+photo)",
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
           never_overwrite: Path | None = None) -> dict:
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

    dest_dir = Path(out_dir) if out_dir else OUT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{(stem or 'edit')}_{uuid.uuid4().hex[:8]}.{f.lower()}"
    dest = dest_dir / name

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
