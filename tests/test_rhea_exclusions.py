"""Rhea's snapshot set follows the TTL (Captain's ruling, 2026-10-07).

Captures were deleted on the SSD after 7 days and kept for up to six months on
RHEA (keep-monthly 6). The ruling: exclusion, not expiry logic. Transcripts are a
separate decision and must NOT be swept out with the audio.
"""
import fnmatch
import pathlib
import re

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "rhea" / "rhea-backup.sh"
DATA = "/home/astroson/ph3b3_data"


def _excludes():
    src = SCRIPT.read_text(encoding="utf-8")
    block = src[src.index('"$RESTIC_BIN" backup'):src.index('|| fail "restic backup failed"')]
    # The whole shell token: "$DATA_DIR"/'*.db' is ONE pattern. Cutting at the
    # first closing quote read it as "$DATA_DIR" — i.e. "exclude everything".
    pats = [t.replace('"', "").replace("'", "") for t in re.findall(r"--exclude (\S+)", block)]
    return [p.replace("$DATA_DIR", DATA) for p in pats]


def _excluded(path):
    # restic matches each pattern against the path and its parents.
    parts = pathlib.PurePosixPath(path)
    cands = [str(parts)] + [str(p) for p in parts.parents]
    return any(fnmatch.fnmatchcase(c, p) for p in _excludes() for c in cands)


def test_device_audio_and_frames_are_out_of_the_snapshot():
    for name in ("stackchan_20260101_000000_1.wav", "iris_20260901_1.wav",
                 "webcam_20261001_1.jpg", "dio_20261001_1.jpg"):
        assert _excluded(f"{DATA}/captures/{name}"), name


def test_mic_debug_dumps_are_out_of_the_snapshot():
    assert _excluded(f"{DATA}/debug_audio/after_fix_v1/20260718_iris.wav")


def test_transcripts_stay_in_the_snapshot():
    for name in ("stackchan_20260101_000000_2.txt",
                 "stackchan_20260101_000000_1.discarded"):
        assert not _excluded(f"{DATA}/captures/{name}"), name


def test_deliberate_work_stays_in_the_snapshot():
    for p in ("orpheus/projects/31b35364eae3/takes/take1.wav", "songs/abc.wav",
              "speech/x.wav", "mnemosyne.db.snapshot"):
        assert not _excluded(f"{DATA}/{p}"), p
