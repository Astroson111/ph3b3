"""retention.py — one authority for how long camera frames are kept.

WHY THIS EXISTS, and why it is not a merge. A retention TTL for captures was
written on 2026-06-13 (e9e1815 / 82d5ae1, "privacy: add retention TTL to camera
captures", 7-day default, "These are room imagery, so the privacy default is 7
days"). It was committed to a `windows` branch and NEVER MERGED — neither commit
is an ancestor of HEAD, PH3B3_CAPTURE_TTL_DAYS appears in no .env, and nothing
in the tree has ever pruned anything. Frames go back to 2026-06-03.

It would also not have worked if merged. It globbed `capture_*.jpg`; the writers
were later renamed and now emit `webcam_*.jpg` and `dio_*.jpg`, so a merge today
would delete the 25 legacy files, skip the other 50, log nothing, and look fixed.

AND THE STORE IS NOT WHAT ITS OWN COMMENT SAYS. vision_module calls
~/ph3b3_data/captures "the ONLY photo store, ever". It holds 2,601 files: 889
stackchan .wav, 676 stackchan .txt, 374 iris .wav, 302 iris .txt, 285
.discarded — and 75 images. One folder, four data types, three devices, no
charter. A naive age sweep over that directory deletes 1,263 voice recordings of
a house and every transcript in it.

SO THIS OWNS CLASSES BY PREFIX, NEVER A DIRECTORY.

AUDIO IS NOW IN SCOPE (Captain's ruling, 2026-10-07): "Audio TTL = 7 days,
matching images. One number fleet-wide." The audit found 1,576 device voice
recordings kept since 2026-07-18 and copied into six months of backups. Raw
recordings of the house (.wav under a device prefix, and the frozen mic-debug
dump in debug_audio/) share the image TTL — the SAME number, not a second knob.
TRANSCRIPTS ARE NOT: .txt and .discarded sidecars are "a separate store and a
separate future decision", and raw audio is not kept on their account — the
.wav goes at the TTL, its sidecar stays.

Out of scope on purpose: deliberate recordings and generated audio (Orpheus
takes, songs, karaoke stems, Calliope speech). Those are work, not residue.

REFUSAL IS LOUD. A file whose name matches an image class but whose extension is
not an image is never deleted and never silently skipped — it raises a red-flag
audit line, so mixed-store drift is seen rather than tolerated. That is the
failure mode that made this module necessary twice over.
"""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.retention")

CAPTURE_DIR = Path.home() / "ph3b3_data" / "captures"

# The June default, honoured. 0 disables retention entirely.
DEFAULT_TTL_DAYS = int(os.getenv("PH3B3_CAPTURE_TTL_DAYS", "7"))

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".wav"}
# Kept beside the audio they describe and never deleted here — see the ruling.
TRANSCRIPT_EXT = {".txt", ".discarded"}

# THE REGISTRY. A writer that lands frames in the capture store registers its
# prefix here, or tests/test_retention.py fails the build. Per-class TTL via
# PH3B3_CAPTURE_TTL_DAYS_<PREFIX>; unset means the default.
CLASSES: dict = {
    "webcam":    {"ext": IMAGE_EXT},                 # local /dev/video fallback
    "capture":   {"ext": IMAGE_EXT},                 # legacy name, pre-rename
    # Dio's frames, and her voice too if the identity rename ever moves
    # _persist_capture's "stackchan" prefix to "dio".
    "dio":       {"ext": IMAGE_EXT | AUDIO_EXT, "keep": TRANSCRIPT_EXT},
    # Device voice recordings (server._persist_capture). Same TTL as frames.
    "stackchan": {"ext": AUDIO_EXT, "keep": TRANSCRIPT_EXT},
    "iris":      {"ext": AUDIO_EXT, "keep": TRANSCRIPT_EXT},
    "pan":       {"ext": AUDIO_EXT, "keep": TRANSCRIPT_EXT},
}

# Raw mic recordings outside the capture store, swept by extension (their names
# lead with a date, not a device). Frozen since 2026-07-18.
RECORDING_DIRS = [Path.home() / "ph3b3_data" / "debug_audio"]

# Explicitly NOT ours. Named so the refusal can say why rather than just skip.
NOT_OURS = TRANSCRIPT_EXT | {".json"}


def ttl_days(prefix: str) -> int:
    return int(os.getenv(f"PH3B3_CAPTURE_TTL_DAYS_{prefix.upper()}", DEFAULT_TTL_DAYS))


def _audit(event: str, ok: bool, source: str = "-", reason: str = "-",
           nbytes: int = 0) -> None:
    """Same greppable shape vision_module uses, so prunes sit in one audit trail."""
    log.info("[vision-audit] event=%s ok=%s source=%s bytes=%d reason=%s",
             event, ok, source, nbytes, reason)


def sweep(directory: Path | None = None, *, dry_run: bool = False) -> dict:
    """Delete image frames older than their class TTL. Never raises.

    Returns {'removed': n, 'bytes': n, 'refused': n, 'kept': n}.
    """
    d = Path(directory) if directory else CAPTURE_DIR
    out = {"removed": 0, "bytes": 0, "refused": 0, "kept": 0}

    for prefix, spec in (CLASSES.items() if d.is_dir() else ()):
        days = ttl_days(prefix)
        if days <= 0:
            continue
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        for f in d.glob(f"{prefix}_*"):
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            if suffix in spec.get("keep", ()):
                out["kept"] += 1            # a transcript beside its audio: not ours
                continue
            if suffix not in spec["ext"]:
                # NEVER delete. This is the drift alarm: something that is not an
                # image is being written under an image class's name.
                out["refused"] += 1
                _audit("prune_refused", ok=False, source=prefix,
                       reason=f"extension {suffix or '(none)'} is not a {prefix}_ class "
                              f"type — not deleted")
                continue
            try:
                st = f.stat()
                if st.st_mtime < cutoff:
                    if not dry_run:
                        f.unlink()
                    out["removed"] += 1
                    out["bytes"] += st.st_size
                else:
                    out["kept"] += 1
            except OSError as e:
                _audit("prune_failed", ok=False, source=prefix, reason=str(e))

    if directory is None:                   # production: also the mic-debug dumps
        for rd in RECORDING_DIRS:
            _sweep_recordings(rd, out, dry_run)

    if out["removed"] or out["refused"]:
        _audit("prune", ok=True, source="captures", nbytes=out["bytes"],
               reason=(f"removed={out['removed']} kept={out['kept']} "
                       f"refused={out['refused']} ttl={DEFAULT_TTL_DAYS}d"
                       + (" DRY-RUN" if dry_run else "")))
    return out


def _sweep_recordings(d: Path, out: dict, dry_run: bool) -> None:
    """Raw .wav anywhere under d, at the one fleet-wide TTL. Nothing else."""
    days = DEFAULT_TTL_DAYS
    if days <= 0 or not Path(d).is_dir():
        return
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    for f in Path(d).rglob("*"):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXT:
            continue
        try:
            st = f.stat()
            if st.st_mtime < cutoff:
                if not dry_run:
                    f.unlink()
                out["removed"] += 1
                out["bytes"] += st.st_size
            else:
                out["kept"] += 1
        except OSError as e:
            _audit("prune_failed", ok=False, source=str(d.name), reason=str(e))


# A store that is only swept at boot or on a camera frame keeps audio forever on
# a quiet week — and voice arrives without any frame. Callers on the audio path
# use this; it sweeps at most once an hour.
_last_sweep = 0.0


def maybe_sweep(min_interval_s: float = 3600.0) -> dict | None:
    global _last_sweep
    import time as _t
    now = _t.time()
    if now - _last_sweep < min_interval_s:
        return None
    _last_sweep = now
    return sweep()
