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

SO THIS OWNS IMAGE CLASSES BY PREFIX, NEVER A DIRECTORY. Audio, transcripts and
discards are out of scope by ruling and stay untouched; what to do with them is
its own question, unanswered on purpose.

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

# THE REGISTRY. A writer that lands frames in the capture store registers its
# prefix here, or tests/test_retention.py fails the build. Per-class TTL via
# PH3B3_CAPTURE_TTL_DAYS_<PREFIX>; unset means the default.
CLASSES: dict = {
    "webcam":  {"ext": IMAGE_EXT},   # local /dev/video fallback
    "capture": {"ext": IMAGE_EXT},   # legacy name, pre-rename
    "dio":     {"ext": IMAGE_EXT},   # Stack-Chan pushed frames
}

# Explicitly NOT ours. Named so the refusal can say why rather than just skip.
NOT_OURS = {".wav", ".txt", ".discarded", ".json"}


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
    if not d.is_dir():
        return out

    for prefix, spec in CLASSES.items():
        days = ttl_days(prefix)
        if days <= 0:
            continue
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        for f in d.glob(f"{prefix}_*"):
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            if suffix not in spec["ext"]:
                # NEVER delete. This is the drift alarm: something that is not an
                # image is being written under an image class's name.
                out["refused"] += 1
                _audit("prune_refused", ok=False, source=prefix,
                       reason=f"non-image extension {suffix or '(none)'} — not deleted")
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

    if out["removed"] or out["refused"]:
        _audit("prune", ok=True, source="captures", nbytes=out["bytes"],
               reason=(f"removed={out['removed']} kept={out['kept']} "
                       f"refused={out['refused']} ttl={DEFAULT_TTL_DAYS}d"
                       + (" DRY-RUN" if dry_run else "")))
    return out
