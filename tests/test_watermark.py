"""
Morpheus watermark — two-layer stamp, verify suite.

The survival table below is MEASURED on this machine, not asserted from theory,
and it includes what kills the embed. That is the point of the feature: it
deters and it evidences, it does not guarantee, and a test suite that only
recorded the wins would be making the stronger claim on its behalf.

Run:  .venv/bin/python -m pytest tests/test_watermark.py -v
"""
import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import watermark as wm                                   # noqa: E402

PROMPT = "a brass helmet on a workbench, studio light"


def scene(w=512, h=512, seed=7):
    """A plausible render: gradients and structure, not flat colour or noise."""
    rng = np.random.default_rng(seed)
    X, Y = np.meshgrid(np.linspace(0, 1, w), np.linspace(0, 1, h))
    a = np.stack([(np.sin(X * 9) * .5 + .5) * 180 + Y * 60,
                  (np.cos(Y * 7) * .5 + .5) * 160 + X * 70,
                  ((X + Y) / 2) * 200], -1)
    return Image.fromarray(np.clip(a + rng.normal(0, 6, (h, w, 3)), 0, 255).astype(np.uint8))


def png_of(img):
    o = io.BytesIO(); img.save(o, "PNG"); return o.getvalue()


def jpeg(img, q):
    o = io.BytesIO(); img.convert("RGB").save(o, "JPEG", quality=q); o.seek(0)
    return Image.open(o)


def crop_frac(img, f):
    w, h = img.size; cw, ch = int(w * f), int(h * f)
    return img.crop(((w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch))


@pytest.fixture(scope="module")
def marked():
    return Image.open(io.BytesIO(wm.stamp_png(png_of(scene()), PROMPT)))


# ── payload ──────────────────────────────────────────────────────────────────

def test_the_payload_carries_a_hash_and_never_the_prompt():
    raw = wm.build_payload(PROMPT, when=1_700_000_000)
    assert len(raw) == 24
    assert PROMPT.encode() not in raw
    v = wm.parse_payload(raw)
    assert v and v.present and v.timestamp.endswith("Z")
    import hashlib
    assert v.prompt_sha256 == hashlib.sha256(PROMPT.encode()).hexdigest()[:32]


def test_noise_is_not_mistaken_for_a_payload():
    assert wm.parse_payload(b"\x00" * 24) is None
    assert wm.parse_payload(bytes(range(24))) is None


def test_a_corrupted_payload_fails_its_checksum():
    raw = bytearray(wm.build_payload(PROMPT))
    raw[8] ^= 0xFF
    assert wm.parse_payload(bytes(raw)) is None


# ── round trip ───────────────────────────────────────────────────────────────

def test_the_embed_round_trips_cleanly(marked):
    v = wm.extract(marked, deep=False)
    assert v.present and v.confidence > 0.95


def test_an_unmarked_image_reports_absent_not_present():
    v = wm.extract(scene(seed=3), deep=False)
    assert not v.present, "a false positive here would make the mark worthless"


def test_the_mark_does_not_wreck_the_picture(marked):
    before = np.asarray(scene(), dtype=float)
    after = np.asarray(marked.convert("RGB"), dtype=float)
    psnr = 10 * np.log10(255 ** 2 / max(1e-9, ((before - after) ** 2).mean()))
    assert psnr > 32, f"visible damage: PSNR {psnr:.1f} dB"


# ── survival, measured — including the losses ────────────────────────────────

@pytest.mark.parametrize("name,transform", [
    ("jpeg q85",       lambda i: jpeg(i, 85)),
    ("jpeg q70",       lambda i: jpeg(i, 70)),
    ("resize 50%",     lambda i: i.resize((i.width // 2, i.height // 2), Image.LANCZOS)),
    ("centre crop 70%", lambda i: crop_frac(i, 0.7)),
    ("centre crop 50%", lambda i: crop_frac(i, 0.5)),
])
def test_the_embed_survives_what_the_brief_requires(marked, name, transform):
    v = wm.extract(transform(marked))
    assert v.present, f"{name} destroyed the embed"


@pytest.mark.parametrize("name,transform", [
    ("jpeg q50", lambda i: jpeg(i, 50)),
    ("resize 50% then jpeg q85",
     lambda i: jpeg(i.resize((i.width // 2, i.height // 2), Image.LANCZOS), 85)),
])
def test_what_kills_it_is_recorded_not_hidden(marked, name, transform):
    """These fail today, deliberately and on the record.

    Documenting the losses is the difference between a deterrent described
    honestly and a guarantee implied quietly. If a future change makes one of
    these survive, this test fails and the claim gets updated — which is the
    only way the survival table stays true.
    """
    v = wm.extract(transform(marked))
    assert not v.present, (
        f"{name} now SURVIVES — good news, but the documented survival table in "
        f"watermark.py and the values-audit row are now understated. Update both.")


# ── the visible layer ────────────────────────────────────────────────────────

@pytest.mark.parametrize("w,h", [
    (768, 768), (1024, 1024), (1536, 1536), (832, 1216),
    (1216, 832), (1152, 896), (896, 1152), (640, 1536),
])
def test_the_visible_mark_scales_with_every_bucket(w, h):
    """Not fixed pixels: a mark sized for 1536 vanishes at 768 and a mark sized
    for 768 swallows a 1536."""
    out = wm.apply_visible(scene(w, h))
    assert out.size == (w, h)
    diff = np.abs(np.asarray(out, float) - np.asarray(scene(w, h), float)).sum(axis=2)
    ys, xs = np.nonzero(diff > 8)
    assert len(xs), "no visible mark was drawn at all"
    # bottom-right corner, and a sane fraction of the frame
    assert xs.max() > w * 0.55 and ys.max() > h * 0.55
    frac = len(xs) / float(w * h)
    assert 0.00002 < frac < 0.02, f"mark covers {frac:.4%} of the frame"


def test_the_font_is_chosen_once_and_held():
    src = (REPO / "modules" / "watermark.py").read_text(encoding="utf-8")
    assert "_FONT_CANDIDATES" in src
    assert wm.MARK_TEXT == "Astroson111"


# ── the switch ───────────────────────────────────────────────────────────────

def test_the_watermark_defaults_on(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "SETTING_PATH", tmp_path / "watermark.json")
    assert wm.enabled() is True


def test_a_corrupt_setting_file_fails_toward_marking(monkeypatch, tmp_path):
    p = tmp_path / "watermark.json"
    p.write_text("{ not json")
    monkeypatch.setattr(wm, "SETTING_PATH", p)
    assert wm.enabled() is True, "failing open here means marked, which is the safe way"


def test_the_switch_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(wm, "SETTING_PATH", tmp_path / "watermark.json")
    wm.set_enabled(False)
    assert wm.enabled() is False
    wm.set_enabled(True)
    assert wm.enabled() is True


# ── failure behaviour ────────────────────────────────────────────────────────

def test_a_too_small_image_raises_rather_than_marking_it_partially():
    """The caller catches this and saves the original. What must not happen is a
    half-written mark."""
    with pytest.raises(ValueError):
        wm.embed(scene(64, 64), wm.build_payload(PROMPT))


def test_verify_handles_something_that_is_not_an_image():
    v = wm.verify_bytes(b"this is not a png")
    assert not v.present and "readable" in v.detail


def test_the_spoken_verdict_does_not_overclaim():
    absent = wm.Verdict(present=False).spoken()
    assert "isn't proof" in absent, "a missing mark must not be reported as proof"


# ── the Morpheus seam ────────────────────────────────────────────────────────

def _morpheus():
    import morpheus
    return morpheus


def test_toggle_off_writes_bytes_identical_to_a_build_without_this_feature(monkeypatch):
    m = _morpheus()
    monkeypatch.setattr(wm, "enabled", lambda: False)
    raw = png_of(scene())
    out = m.maybe_stamp(raw, "job1", PROMPT)
    assert out is raw, "OFF must not touch the bytes at all"


def test_toggle_on_puts_both_layers_in(monkeypatch):
    m = _morpheus()
    monkeypatch.setattr(wm, "enabled", lambda: True)
    raw = png_of(scene())
    out = m.maybe_stamp(raw, "job2", PROMPT)
    assert out != raw
    img = Image.open(io.BytesIO(out))
    assert wm.extract(img, deep=False).present                      # layer 2
    diff = np.abs(np.asarray(img, float) - np.asarray(scene(), float)).sum(axis=2)
    assert np.count_nonzero(diff > 8), "no visible layer"           # layer 1


def test_a_stamp_failure_saves_the_image_clean_and_says_so(monkeypatch):
    """Injected failure. The render must survive the watermark, not the reverse.

    The log assertion captures morpheus's own logger rather than using caplog:
    caplog depends on propagation reaching root, and something else in the full
    suite turns that off — so this passed alone and failed in the suite, which
    is the least useful way for a test to behave.
    """
    m = _morpheus()
    monkeypatch.setattr(wm, "enabled", lambda: True)
    monkeypatch.setattr(wm, "stamp_png",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    said = []
    monkeypatch.setattr(m.log, "error", lambda msg, *a, **k: said.append(msg % a if a else msg))
    raw = png_of(scene())
    m.jobs["job3"] = {}
    out = m.maybe_stamp(raw, "job3", PROMPT)
    assert out is raw, "a failed stamp must leave the original bytes untouched"
    assert m.jobs["job3"]["watermark"] == "failed"
    assert any("STAMP FAILED" in t for t in said), "the failure was not stated loudly"


def test_the_stamp_records_no_prompt_hash_anywhere_but_the_pixels():
    """The no-tracking rule. generations.db already stores the prompt itself and
    that predates this feature — what must not happen is this feature ADDING a
    hash column, a ledger, or a log line carrying the payload."""
    msrc = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    wsrc = (REPO / "modules" / "watermark.py").read_text(encoding="utf-8")
    assert "prompt_sha" not in msrc.lower().replace("prompt_sha256", "")
    for src, name in ((msrc, "morpheus.py"), (wsrc, "watermark.py")):
        for line in src.splitlines():
            low = line.lower()
            if ("log." in low or "insert into" in low) and "sha" in low:
                raise AssertionError(f"{name} may be recording a hash: {line.strip()}")
