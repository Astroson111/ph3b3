"""
watermark — the two-layer stamp on a Morpheus render.

Layer 1 is a corner signature you can see. Layer 2 is a payload in the frequency
domain you cannot, carrying when the image was made and a fingerprint of the
prompt that made it.

── WHAT THIS IS FOR, AND WHAT IT IS NOT ─────────────────────────────────────
It deters and it evidences. It does not guarantee. Anyone determined to remove
either layer can: crop the corner, re-encode hard, scale oddly, or simply paint
over it. The honest claim is narrower — an image that still carries the embed
came from this machine, and an image that does not is silent rather than proof
of anything. The measured survival numbers live in the values-audit trail and in
tests/test_watermark.py, including the cases that kill it.

── WHY DCT AND NOT LSB ──────────────────────────────────────────────────────
A least-significant-bit embed dies to the first JPEG re-encode, and these images
leave the machine. So the payload goes into the DCT coefficients of 8x8 luminance
blocks — the same transform and the same block grid JPEG itself uses, which is
what lets it survive being re-encoded. Chroma is left alone entirely: JPEG
subsamples it, so anything hidden there is gone before it starts.

Within a block the bit is carried by the RELATIVE ORDER of two mid-band
coefficients, not by their absolute values. Quantisation scales coefficients but
preserves their ordering far better than their magnitudes, so a comparison
survives what a threshold does not.

── REDUNDANCY IS THE WHOLE ROBUSTNESS STORY ─────────────────────────────────
Every bit is written into many blocks spread across the image and recovered by
majority vote. That is what buys tolerance: a crop removes some blocks, a resize
corrupts some, heavy compression flips some, and the vote still lands as long as
most survive. It is also why the payload is deliberately tiny — 24 bytes — since
capacity traded for redundancy is the only currency here.

── THE PAYLOAD CARRIES NO PROMPT ────────────────────────────────────────────
A SHA-256 of the composed prompt, truncated. The prompt itself is never embedded
and never logged by this module. The hash proves "this image came from that
exact prompt" to someone who already has the prompt; it reveals nothing to
someone who does not. Astro's standing no-tracking rule: the hash lives in the
image and nowhere else — this module writes no ledger, no log line containing it,
and no database row.
"""
from __future__ import annotations

import hashlib
import io
import logging
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.fftpack import dct, idct

log = logging.getLogger("ph3b3.watermark")

MARK_TEXT = "Astroson111"

# One clean sans, held. DejaVu ships with the distro and is not going anywhere;
# Noto Sans is the fallback if a slimmer image ever drops DejaVu. No font is
# invented and no family is chosen per image.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
)

# ── visible layer ────────────────────────────────────────────────────────────
# Everything is a FRACTION of the image, never a pixel count: a 16 px mark is a
# scrawl on a 1536 render and a banner across a 768 one.
_MARK_HEIGHT_FRAC = 0.022      # cap height as a fraction of the short edge
_MARK_MARGIN_FRAC = 0.018      # inset from the corner, same basis
_MARK_OPACITY = 0.38           # visible when looked for, not shouted
_MARK_MIN_PX = 11              # below this it stops being letters at all

# ── invisible layer ──────────────────────────────────────────────────────────
_MAGIC = 0xA511                # 2 bytes: "is anything here at all"
_BLOCK = 8
# Mid-band pair. Low coefficients carry the image and cannot be touched without
# it showing; high ones are the first thing quantisation throws away. These two
# sit where JPEG still keeps precision and the eye does not look.
_C1 = (2, 3)
_C2 = (3, 2)
_STRENGTH = 12.0               # minimum enforced gap between the pair
_PAYLOAD_BYTES = 24            # magic 2 + ts 4 + hash 16 + crc 2
_NBITS = _PAYLOAD_BYTES * 8    # 192

# The payload is TILED, not laid out sequentially from the top-left. A sequential
# layout indexes bits by (row * blocks_per_row + col), which means the moment an
# image is cropped both the origin and the row stride change and every bit lands
# in the wrong bucket — a centre crop killed it outright, measured. Tiling by
# (row mod 16, col mod 12) makes the position of a bit depend only on where a
# block sits within a repeating 16x12 stamp, so a crop shifts the PHASE of the
# tile rather than destroying the mapping, and the phase is 192 possibilities
# the reader can simply try.
_TILE_R, _TILE_C = 16, 12      # 16 * 12 == 192 == _NBITS


@dataclass(frozen=True)
class Verdict:
    """What verify_watermark found."""
    present: bool
    timestamp: str = ""        # ISO-8601 UTC
    prompt_sha256: str = ""    # first 16 bytes, hex — a prefix of the full digest
    confidence: float = 0.0    # fraction of bit-votes that agreed
    detail: str = ""

    def spoken(self) -> str:
        if not self.present:
            return ("I can't find an embed in that image. That means it either "
                    "never had one, or enough of it was destroyed that I can't "
                    "read it — a missing mark isn't proof of anything either way.")
        return (f"That one's mine. Made {self.timestamp}, prompt fingerprint "
                f"{self.prompt_sha256[:16]}… — recovered with "
                f"{self.confidence * 100:.0f}% of the bit votes agreeing.")


# ── the switch ───────────────────────────────────────────────────────────────
# Default ON, unlike egress and the camera, because the thing it guards against
# is work leaving unmarked rather than something reaching out. Off means OFF:
# neither layer, output byte-identical to a build without this feature.
try:
    from paths import PH3B3_DATA
except ImportError:                               # tests / standalone
    from modules.paths import PH3B3_DATA

SETTING_PATH = Path(PH3B3_DATA) / "watermark.json"


def enabled() -> bool:
    """True unless the file says otherwise. Fails OPEN — a corrupt settings file
    means a marked image, which is the safe direction here: the cost of a stamp
    nobody wanted is cosmetic, the cost of a missing one is unmarked work."""
    try:
        import json
        return bool(json.loads(SETTING_PATH.read_text()).get("watermark_enabled", True))
    except Exception:
        return True


def set_enabled(on: bool) -> dict:
    import json
    SETTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTING_PATH.write_text(json.dumps({"watermark_enabled": bool(on)}))
    log.info("watermark %s", "ENABLED" if on else "DISABLED")
    return {"watermark_enabled": bool(on)}


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                continue
    return ImageFont.load_default()


def apply_visible(img: Image.Image, text: str = MARK_TEXT) -> Image.Image:
    """Corner signature, scaled to the image, composited at low opacity.

    Bottom-right: the corner a crop is least likely to take first, and the one
    that collides least with a subject. Drawn on its own RGBA layer and alpha
    composited so the mark rides on top of the pixels rather than replacing them.
    """
    base = img.convert("RGBA")
    w, h = base.size
    short = min(w, h)
    px = max(_MARK_MIN_PX, int(round(short * _MARK_HEIGHT_FRAC)))
    margin = max(4, int(round(short * _MARK_MARGIN_FRAC)))
    font = _font(px)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    x, y = w - tw - margin - l, h - th - margin - t

    alpha = int(round(255 * _MARK_OPACITY))
    # A dark pass under a light one: the mark has to stay readable over a bright
    # sky and a black background alike, and one colour cannot do both.
    d.text((x + max(1, px // 12), y + max(1, px // 12)), text,
           font=font, fill=(0, 0, 0, int(alpha * 0.55)))
    d.text((x, y), text, font=font, fill=(255, 255, 255, alpha))
    return Image.alpha_composite(base, layer).convert("RGB")


# ── payload ──────────────────────────────────────────────────────────────────

def build_payload(prompt: str, when: float | None = None) -> bytes:
    """magic | uint32 UTC seconds | sha256(prompt)[:16] | crc16 — 24 bytes."""
    ts = int(when if when is not None else time.time())
    digest = hashlib.sha256((prompt or "").encode("utf-8")).digest()[:16]
    body = struct.pack(">HI", _MAGIC, ts) + digest
    crc = zlib.crc32(body) & 0xFFFF
    return body + struct.pack(">H", crc)


def parse_payload(raw: bytes) -> Verdict | None:
    """Decode 24 bytes, or None if the magic or the checksum says it is noise."""
    if len(raw) != _PAYLOAD_BYTES:
        return None
    magic, ts = struct.unpack(">HI", raw[:6])
    if magic != _MAGIC:
        return None
    if (zlib.crc32(raw[:-2]) & 0xFFFF) != struct.unpack(">H", raw[-2:])[0]:
        return None
    return Verdict(
        present=True,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        prompt_sha256=raw[6:22].hex(),
    )


def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bytes_from(bits: np.ndarray) -> bytes:
    return np.packbits(bits.astype(np.uint8)).tobytes()


# ── the DCT layer ────────────────────────────────────────────────────────────

def _blocks_of(y: np.ndarray) -> tuple[int, int]:
    return y.shape[0] // _BLOCK, y.shape[1] // _BLOCK


def _dct2(b):  return dct(dct(b.T, norm="ortho").T, norm="ortho")
def _idct2(b): return idct(idct(b.T, norm="ortho").T, norm="ortho")


def capacity_bits(width: int, height: int, repeats: int) -> int:
    return (height // _BLOCK) * (width // _BLOCK) // max(1, repeats)


def embed(img: Image.Image, payload: bytes, repeats: int = 24) -> Image.Image:
    """Write `payload` into the luminance DCT of `img`, tiled for redundancy.

    Returns a new image. Raises ValueError if the image cannot hold one whole
    tile — the caller decides what that means; this module never silently writes
    a partial mark.
    """
    ycbcr = img.convert("YCbCr")
    arr = np.array(ycbcr, dtype=np.float64)
    y = arr[:, :, 0]
    bh, bw = _blocks_of(y)
    if bh < _TILE_R or bw < _TILE_C:
        raise ValueError(f"image is {bh}x{bw} blocks, needs at least "
                         f"{_TILE_R}x{_TILE_C} to carry one tile")
    bits = _bits(payload)
    if len(bits) != _NBITS:
        raise ValueError(f"payload must be {_PAYLOAD_BYTES} bytes")

    for r in range(bh):
        for c in range(bw):
            bit = bits[(r % _TILE_R) * _TILE_C + (c % _TILE_C)]
            blk = y[r * _BLOCK:(r + 1) * _BLOCK, c * _BLOCK:(c + 1) * _BLOCK]
            d = _dct2(blk)
            a, b = d[_C1], d[_C2]
            if bit:
                if a - b < _STRENGTH:
                    mid = (a + b) / 2.0
                    a, b = mid + _STRENGTH / 2.0, mid - _STRENGTH / 2.0
            else:
                if b - a < _STRENGTH:
                    mid = (a + b) / 2.0
                    a, b = mid - _STRENGTH / 2.0, mid + _STRENGTH / 2.0
            d[_C1], d[_C2] = a, b
            y[r * _BLOCK:(r + 1) * _BLOCK, c * _BLOCK:(c + 1) * _BLOCK] = _idct2(d)

    arr[:, :, 0] = np.clip(y, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="YCbCr").convert("RGB")


def _decisions(y: np.ndarray) -> np.ndarray:
    """One DCT pass: the bit each block is carrying, as a (bh, bw) array.

    Separated from the voting so the reader can try every tile phase without
    paying for the transform again — 192 phases at one pass, not 192 passes.
    """
    bh, bw = _blocks_of(y)
    out = np.zeros((bh, bw), dtype=np.int8)
    for r in range(bh):
        for c in range(bw):
            d = _dct2(y[r * _BLOCK:(r + 1) * _BLOCK, c * _BLOCK:(c + 1) * _BLOCK])
            out[r, c] = 1 if d[_C1] > d[_C2] else 0
    return out


def _extract_at(img: Image.Image, repeats: int = 24) -> tuple[bytes, float] | None:
    """Best payload recoverable from this image at this scale, over all phases."""
    y = np.array(img.convert("YCbCr"), dtype=np.float64)[:, :, 0]
    bh, bw = _blocks_of(y)
    if bh < _TILE_R or bw < _TILE_C:
        return None
    dec = _decisions(y)
    rows, cols = np.indices((bh, bw))
    best = None
    for pr in range(_TILE_R):
        for pc in range(_TILE_C):
            idx = (((rows + pr) % _TILE_R) * _TILE_C
                   + ((cols + pc) % _TILE_C)).ravel()
            flat = dec.ravel()
            ones = np.bincount(idx, weights=flat, minlength=_NBITS)
            tot = np.bincount(idx, minlength=_NBITS)
            zeros = tot - ones
            bits = (ones > zeros).astype(np.uint8)
            agree = float(np.maximum(ones, zeros).sum()) / max(1.0, tot.sum())
            raw = _bytes_from(bits)
            if parse_payload(raw):
                if best is None or agree > best[1]:
                    best = (raw, agree)
    return best


def extract(img: Image.Image, repeats: int = 24, deep: bool = True) -> Verdict:
    """Recover a payload, putting the block grid back where it was if need be.

    Two things move the grid out from under the payload, and each needs its own
    search:

    SCALE. A resized image no longer has 8x8 blocks where the embed put them, so
    the candidate rescalings below restore the original geometry. A 50% downscale
    read back at 2x decodes cleanly.

    PHASE. An arbitrary crop shifts the grid by a number of pixels that is almost
    never a multiple of 8. Measured: a 50% centre crop of a 1024 image survives
    because 512 and the 256px offset are both exact multiples of 8, while a 70%
    crop dies on the same image purely because its offset is not. So when the
    plain read fails, `deep` walks the 64 sub-block offsets and tries each. That
    is up to 64 transforms and takes seconds — which is nothing in a verification
    tool run by hand, and is why the render path never calls this.
    """
    w, h = img.size
    scales = [img]
    for factor in (2.0, 4.0, 1.5, 3.0):
        nw, nh = int(round(w * factor)), int(round(h * factor))
        if nw * nh <= 40_000_000:
            scales.append(img.resize((nw, nh), Image.LANCZOS))

    for cand in scales:
        got = _extract_at(cand, repeats)
        if got:
            raw, agree = got
            v = parse_payload(raw)
            if v:
                return Verdict(present=True, timestamp=v.timestamp,
                               prompt_sha256=v.prompt_sha256, confidence=agree,
                               detail=f"decoded at {cand.size[0]}x{cand.size[1]}")

    # Deep search runs on the image AS GIVEN, never on the rescaled candidates.
    # Searching offsets on a 4x upscale of a 1024 render is 16x the blocks for a
    # case that has never paid: measured, saying "no embed" about a q50 JPEG took
    # 217 seconds that way and 6 this way. A verifier that takes four minutes to
    # answer "not mine" is a verifier nobody runs twice.
    if deep:
        for cand in (img,):
            cw, ch = cand.size
            for dy in range(_BLOCK):
                for dx in range(_BLOCK):
                    if dy == 0 and dx == 0:
                        continue          # already tried above
                    if cw - dx < _TILE_C * _BLOCK or ch - dy < _TILE_R * _BLOCK:
                        continue
                    got = _extract_at(cand.crop((dx, dy, cw, ch)), repeats)
                    if not got:
                        continue
                    raw, agree = got
                    v = parse_payload(raw)
                    if v:
                        return Verdict(
                            present=True, timestamp=v.timestamp,
                            prompt_sha256=v.prompt_sha256, confidence=agree,
                            detail=f"decoded at offset ({dx},{dy}) "
                                   f"on {cw}x{ch}")
    return Verdict(present=False, detail="no embed found")


# ── the whole stamp ──────────────────────────────────────────────────────────

def stamp_png(png_bytes: bytes, prompt: str, when: float | None = None,
              repeats: int = 24) -> bytes:
    """Both layers onto PNG bytes, returning new PNG bytes.

    Raises on any failure. The caller is expected to catch and save the ORIGINAL
    bytes instead — a half-marked file is worse than an unmarked one, so this
    never returns a partially stamped image.
    """
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    marked = apply_visible(img)
    marked = embed(marked, build_payload(prompt, when), repeats=repeats)
    out = io.BytesIO()
    marked.save(out, format="PNG")
    return out.getvalue()


def verify_bytes(data: bytes, repeats: int = 24) -> Verdict:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        return Verdict(present=False, detail=f"not a readable image: {e}")
    return extract(img, repeats=repeats)
