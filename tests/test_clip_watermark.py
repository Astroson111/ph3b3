"""
Clip watermark — verify suite.

Astro's call, 2026-09-18: add it, but on a switch. That is a deliberate
departure from the 2026-09-15 stills ruling (auto-stamp, no switch), and the
reasons are worth keeping visible:

  the mark is WEAKER    A still carries two layers — a visible corner mark and a
                        DCT embed measured against JPEG re-encoding. A clip can
                        only carry the first: H.264 predicts most frames from
                        their neighbours, so a per-frame embed has nothing stable
                        to live in and there is no survival measurement for it.

  the cost is HIGHER    Stamping a clip is a second full encode — real time and a
                        generation of quality the still path never pays.

So: opt-out rather than assumed, default on, and on its OWN key so turning clips
off never quietly unstamps the stills.

Run:  .venv/bin/python -m pytest tests/test_clip_watermark.py -v
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import morpheus       # noqa: E402
import watermark      # noqa: E402

HAVE_FFMPEG = subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(watermark, "SETTING_PATH", tmp_path / "wm.json")
    return tmp_path


@pytest.fixture
def clip(tmp_path):
    """Three seconds of test pattern — a deliberately hostile background."""
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg not installed")
    p = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc=size=480x832:rate=24:duration=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)],
                   check=True, capture_output=True)
    return p


# ── the switch ───────────────────────────────────────────────────────────────

def test_clips_default_to_marked(settings):
    """Still Ph3b3 work leaving the building. Opt-out, not opt-in."""
    assert watermark.clip_enabled() is True


def test_the_clip_switch_is_its_own_key(settings):
    """Turning clips off must not unstamp the stills, and vice versa — the
    2026-09-15 stills ruling stands whatever happens here."""
    watermark.set_clip_enabled(False)
    assert watermark.clip_enabled() is False
    assert watermark.enabled() is True, "turning clips off disabled stills too"

    watermark.set_enabled(False)
    watermark.set_clip_enabled(True)
    assert watermark.clip_enabled() is True
    assert watermark.enabled() is False, "turning clips on re-enabled stills"


def test_the_clip_note_does_not_overclaim(settings):
    note = watermark.clip_note().lower()
    assert "visible" in note
    assert "invisible" in note or "hidden" in note
    # It must say the embed is NOT there, not merely omit it.
    assert "stills" in note or "destroys" in note


# ── stamping ─────────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_a_clip_is_stamped_and_the_job_says_which_layers(settings, clip, monkeypatch):
    monkeypatch.setitem(morpheus.jobs, "j1", {})
    before = clip.stat().st_size
    out = morpheus.maybe_stamp_clip(clip, "j1")
    assert out == clip and clip.stat().st_size != before
    assert morpheus.jobs["j1"]["watermark"] == "stamped"
    assert morpheus.jobs["j1"]["watermark_layers"] == "visible", \
        "a clip must never claim the embed it cannot carry"


@needs_ffmpeg
def test_the_mark_is_actually_in_the_pixels(settings, clip, monkeypatch, tmp_path):
    """Not a byte-count check — the frame has to contain the drawn box."""
    import numpy as np
    from PIL import Image
    monkeypatch.setitem(morpheus.jobs, "j2", {})
    frame_a = tmp_path / "a.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(clip),
                    "-frames:v", "1", str(frame_a)], check=True, capture_output=True)
    morpheus.maybe_stamp_clip(clip, "j2")
    frame_b = tmp_path / "b.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(clip),
                    "-frames:v", "1", str(frame_b)], check=True, capture_output=True)
    a = np.array(Image.open(frame_a).convert("RGB")).astype(int)
    b = np.array(Image.open(frame_b).convert("RGB")).astype(int)
    h, w, _ = a.shape
    # bottom-right quadrant should change; top-left should be essentially untouched
    br = np.abs(a[h // 2:, w // 2:] - b[h // 2:, w // 2:]).mean()
    tl = np.abs(a[:h // 2, :w // 2] - b[:h // 2, :w // 2]).mean()
    assert br > tl * 2, f"no mark found bottom-right (br {br:.1f} vs tl {tl:.1f})"


@needs_ffmpeg
def test_the_switch_off_leaves_the_clip_untouched(settings, clip, monkeypatch):
    watermark.set_clip_enabled(False)
    monkeypatch.setitem(morpheus.jobs, "j3", {})
    before = clip.read_bytes()
    morpheus.maybe_stamp_clip(clip, "j3")
    assert clip.read_bytes() == before, "an off switch still re-encoded the clip"
    assert morpheus.jobs["j3"]["watermark"] == "off"


@needs_ffmpeg
def test_a_failed_stamp_keeps_the_render(settings, clip, monkeypatch):
    """A clip that took forty minutes on the card must not be lost to a missing
    font. An unstamped clip is a smaller problem than no clip."""
    monkeypatch.setattr(morpheus, "_MARK_FONT", "/nonexistent/font.ttf")
    monkeypatch.setitem(morpheus.jobs, "j4", {})
    before = clip.read_bytes()
    out = morpheus.maybe_stamp_clip(clip, "j4")
    assert out.exists() and out.read_bytes() == before
    assert morpheus.jobs["j4"]["watermark"] == "failed"
    assert morpheus.jobs["j4"]["watermark_error"]


@needs_ffmpeg
def test_a_mark_with_ffmpeg_syntax_in_it_does_not_break_the_filter(settings, clip, monkeypatch):
    """drawtext reads ':' and backslash as syntax. A mark is user text."""
    watermark.set_mark_text("a:b'c")
    monkeypatch.setitem(morpheus.jobs, "j5", {})
    before = clip.stat().st_size
    morpheus.maybe_stamp_clip(clip, "j5")
    assert morpheus.jobs["j5"]["watermark"] == "stamped"
    assert clip.stat().st_size != before


# ── where it sits in the render ──────────────────────────────────────────────

def test_the_stamp_runs_before_the_thumbnail():
    """Otherwise the gallery tile shows an unmarked frame of a marked clip."""
    src = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    body = src[src.index("async def run_video"):]
    assert body.index("maybe_stamp_clip") < body.index("_make_video_thumb")


def test_the_stamp_is_cpu_only():
    src = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    fn = src[src.index("def maybe_stamp_clip"):src.index("async def run_video")]
    assert "ffmpeg" in fn
    for smell in ("cuda", "torch", "comfy_", "COMFY_HOST"):
        assert smell not in fn, f"the clip stamp reaches the GPU stack: {smell}"


def test_the_lock_cost_is_written_down_not_hidden():
    """It runs inside gpu_lock. That is a real cost and the docstring says so
    rather than implying otherwise."""
    src = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    fn = src[src.index("def maybe_stamp_clip"):src.index("async def run_video")]
    assert "INSIDE gpu_lock" in fn


# ── the panel has to actually run ────────────────────────────────────────────

def test_every_panel_script_block_parses():
    """A JS syntax error in panel.html is a SILENT, TOTAL failure: the file
    still serves, the markup still renders, and every control on the page stops
    working with nothing in any server log to say why.

    This exists because adding the clip switch broke it. The handler landed
    inside wmSet()'s try block, orphaning its catch, and the page would not have
    executed at all — caught by parsing rather than by reading the diff, which
    looked fine.
    """
    import re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed — cannot parse the panel's JS")
    html = (REPO / "static" / "panel.html").read_text(encoding="utf-8")
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert blocks, "no script blocks found — has panel.html moved?"
    with tempfile.TemporaryDirectory() as td:
        for i, b in enumerate(blocks):
            f = Path(td) / f"b{i}.js"
            f.write_text(b, encoding="utf-8")
            r = subprocess.run([node, "--check", str(f)], capture_output=True)
            assert r.returncode == 0, (
                f"panel.html script block {i} does not parse:\n"
                + (r.stderr or b"").decode("utf-8", "replace")[:500])


def test_the_two_switches_post_different_keys():
    """One key for both would mean turning clips off silently unstamps stills,
    overriding the 2026-09-15 ruling from a control that does not say so."""
    html = (REPO / "static" / "panel.html").read_text(encoding="utf-8")
    assert "clip_watermark_enabled: cs.value === 'on'" in html
    assert "watermark_enabled: sel.value === 'on'" in html
