"""Apelles preview serving — downscale for display, never for the file itself.

The preview panel needs a screen-sized image; the edit pipeline and the download
links need the real one. Both come from the same route, separated by ?preview=1.

The invariant that matters: serving a preview must not touch the source. A photo
editor that quietly re-encoded the thing you are editing would be lying about
what you are looking at, and Apelles' whole promise is that the original on disk
is not modified.
"""
import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

EDGE = 1600


def _preview_bytes(p: Path):
    """Mirror of server._apelles_preview_bytes (importing server.py costs ~11s)."""
    with Image.open(p) as im:
        if max(im.width, im.height) <= EDGE:
            return None
        im = im.copy()
        im.thumbnail((EDGE, EDGE), Image.LANCZOS)
        bio = io.BytesIO()
        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(bio, format="PNG")
        return bio.getvalue()


@pytest.fixture
def img(tmp_path):
    def make(size, mode="RGB", name="i.png"):
        p = tmp_path / name
        Image.new(mode, size).save(p)
        return p
    return make


# ── the cap ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("size,expect", [
    ((4000, 3000), (1600, 1200)),
    ((3000, 4000), (1200, 1600)),      # portrait caps the long edge too
    ((5000, 100),  (1600, 32)),        # extreme aspect ratio survives
    ((1600, 1200), None),              # exactly at the cap — no work
    ((800, 600),   None),              # under it — served as-is
])
def test_longest_edge_is_capped(img, size, expect):
    out = _preview_bytes(img(size))
    if expect is None:
        assert out is None, "an already-small image must not be re-encoded"
        return
    assert Image.open(io.BytesIO(out)).size == expect


def test_aspect_ratio_is_preserved(img):
    out = _preview_bytes(img((4000, 2500)))
    w, h = Image.open(io.BytesIO(out)).size
    assert abs((w / h) - (4000 / 2500)) < 0.01


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "LA", "P", "L"])
def test_every_mode_survives_the_downscale(img, mode):
    """A palette or alpha image must not blow up on save — the panel would show
    a broken glyph, which is the one thing the brief rules out."""
    out = _preview_bytes(img((2400, 2400), mode=mode))
    assert out is not None
    assert Image.open(io.BytesIO(out)).size == (1600, 1600)


# ── the invariant ────────────────────────────────────────────────────────────

def test_serving_a_preview_never_touches_the_source(img):
    p = img((4000, 3000))
    before_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    before_stat = (p.stat().st_size, p.stat().st_mtime_ns)

    for _ in range(3):
        _preview_bytes(p)

    assert hashlib.sha256(p.read_bytes()).hexdigest() == before_sha
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before_stat


def test_no_second_copy_is_written(img, tmp_path):
    """'Serve the files Apelles already maintains; create no new copies.'"""
    p = img((4000, 3000))
    before = {f.name for f in tmp_path.iterdir()}
    _preview_bytes(p)
    assert {f.name for f in tmp_path.iterdir()} == before


def test_preview_is_smaller_than_the_original(img):
    p = img((4000, 3000))
    out = _preview_bytes(p)
    assert len(out) < p.stat().st_size


# ── the real implementation must match this model ────────────────────────────

SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


def test_route_takes_a_preview_flag_defaulting_to_full_size():
    assert "async def apelles_file(file_id: str, preview: int = 0)" in SRC, \
        "download links depend on full resolution being the default"


def test_downscale_runs_off_the_event_loop():
    assert "await asyncio.to_thread(_apelles_preview_bytes, p)" in SRC, \
        "resampling a large image is CPU work and must not block the loop"


def test_downscale_failure_falls_back_to_the_full_file():
    """A preview that cannot be downscaled is still a preview. Failing here must
    not produce a broken image in the panel."""
    fn = SRC[SRC.index("async def apelles_file("):SRC.index("def _apelles_preview_bytes")]
    assert "except Exception" in fn
    assert fn.rstrip().endswith("return FileResponse(str(p), media_type=mime, filename=p.name)")


def test_cap_is_a_named_constant():
    assert "_APELLES_PREVIEW_EDGE = 1600" in SRC
