"""Camera frames are kept for a bounded time, and only camera frames are touched.

THE ARCHAEOLOGY, so nobody re-derives it. A retention TTL was written on
2026-06-13 (e9e1815 / 82d5ae1, 7-day default, "These are room imagery, so the
privacy default is 7 days") and NEVER MERGED — neither commit is an ancestor of
HEAD, PH3B3_CAPTURE_TTL_DAYS is in no .env, and nothing had ever pruned
anything. Frames went back to 2026-06-03.

Merging it today would not have fixed it either: it globbed `capture_*.jpg`, and
the writers were since renamed to `webcam_*` / `dio_*`. It would have deleted 25
legacy files, skipped 50, logged nothing, and looked repaired.

AND THE DIRECTORY IS MIXED. ~/ph3b3_data/captures calls itself "the ONLY photo
store, ever" and holds 2,601 files: 889 stackchan .wav, 676 stackchan .txt, 374
iris .wav, 302 iris .txt, 285 .discarded — and 75 images. An age sweep over the
directory would delete 1,263 voice recordings of a house. So retention owns
image PREFIXES, never a directory, and audio/transcripts are out of scope by
ruling.
"""
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import retention  # noqa: E402


def _plant(d: Path, name: str, age_days: float) -> Path:
    f = d / name
    f.write_bytes(b"x" * 64)
    old = time.time() - age_days * 86400
    os.utime(f, (old, old))
    return f


@pytest.fixture
def store(tmp_path):
    return tmp_path


# ── every image class is swept ───────────────────────────────────────────────
@pytest.mark.parametrize("prefix", ["webcam", "capture", "dio"])
def test_a_stale_frame_in_each_class_is_pruned(store, prefix):
    f = _plant(store, f"{prefix}_20260101_000000_1.jpg", 30)
    retention.sweep(store)
    assert not f.exists(), f"{prefix}_ frames are not being pruned"


@pytest.mark.parametrize("prefix", ["webcam", "capture", "dio"])
def test_a_fresh_frame_survives(store, prefix):
    f = _plant(store, f"{prefix}_20260925_000000_1.jpg", 0.1)
    retention.sweep(store)
    assert f.exists(), f"a fresh {prefix}_ frame was deleted"


def test_the_boundary_is_the_configured_ttl(store):
    old = _plant(store, "webcam_a.jpg", retention.DEFAULT_TTL_DAYS + 1)
    new = _plant(store, "webcam_b.jpg", retention.DEFAULT_TTL_DAYS - 1)
    retention.sweep(store)
    assert not old.exists() and new.exists()


# ── and NOTHING else is ───────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "stackchan_20260101_000000.wav", "stackchan_20260101_000000.txt",
    "iris_20260101_000000.wav", "iris_20260101_000000.txt",
    "stackchan_20260101_000000.discarded",
])
def test_audio_and_transcripts_are_never_touched(store, name):
    """1,263 voice recordings of a house live in this directory. They are out of
    scope by ruling, and nothing here may take them."""
    f = _plant(store, name, 400)
    retention.sweep(store)
    assert f.exists(), f"{name} was deleted by a CAMERA retention sweep"


def test_a_non_image_wearing_an_image_prefix_is_REFUSED_not_skipped(store):
    """The drift alarm. A .wav named webcam_* must not be deleted, and must not
    pass silently either — mixed-store drift is exactly how this directory came
    to hold four data types with no charter."""
    f = _plant(store, "webcam_20260101_000000.wav", 400)
    res = retention.sweep(store)
    assert f.exists(), "a .wav was deleted by the image retention sweep"
    assert res["refused"] == 1, "the non-image was skipped silently instead of flagged"


def test_a_dry_run_deletes_nothing(store):
    f = _plant(store, "webcam_old.jpg", 30)
    res = retention.sweep(store, dry_run=True)
    assert f.exists() and res["removed"] == 1


def test_ttl_zero_disables_retention(store, monkeypatch):
    monkeypatch.setenv("PH3B3_CAPTURE_TTL_DAYS_WEBCAM", "0")
    f = _plant(store, "webcam_old.jpg", 400)
    retention.sweep(store)
    assert f.exists(), "TTL=0 must keep captures forever"


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert retention.sweep(tmp_path / "nope")["removed"] == 0


# ── the guard that catches the NEXT door ─────────────────────────────────────
def test_every_capture_writer_registers_with_retention():
    """THE point of the whole exercise. The June guard was real and correct and
    the writers were renamed out from under it. Any module that lands a file in
    the capture store must reference the retention authority, so a new writer
    cannot quietly opt out of the TTL the way webcam_ did."""
    mods = ROOT / "modules"
    offenders = []
    for f in mods.glob("*.py"):
        if f.name == "retention.py":
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        writes = ('CAPTURE_DIR /' in src or 'CAPTURE_DIR/' in src
                  or '"ph3b3_data" / "captures"' in src)
        if writes and "retention" not in src:
            offenders.append(f.name)
    assert not offenders, (
        f"{offenders} write into the capture store without registering with "
        "modules/retention.py — that is how the 2026-06-13 TTL was orphaned")


def test_morpheus_stores_are_out_of_scope():
    """Her artwork is not surveillance residue. A privacy TTL eating watermarked
    shipped work would be its own incident."""
    src = (ROOT / "modules" / "retention.py").read_text(encoding="utf-8")
    for banned in ("IMAGE_DIR", "VIDEO_DIR", "MORPHEUS"):
        assert banned not in src, f"retention reaches into morpheus ({banned})"


def test_prune_events_reach_the_vision_audit_trail(store, caplog):
    import logging
    _plant(store, "webcam_old.jpg", 30)
    with caplog.at_level(logging.INFO, logger="ph3b3.retention"):
        retention.sweep(store)
    assert any("[vision-audit]" in r.getMessage() and "event=prune" in r.getMessage()
               for r in caplog.records), "prunes are not auditable"
