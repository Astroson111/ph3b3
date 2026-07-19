"""
captures.py — read-only device-artifact feed (audio, transcripts, images).

Reverse-chronological view over the ONE capture store (~/ph3b3_data/captures).
No database: device and type come from the filename, and an audio clip is paired
with its transcript by filename stem — `foo.wav` ↔ `foo.txt` sitting beside it.
Files are served from where they already live; this module never copies, edits,
or deletes. Sidecars are written at transcription time by the server; here we
only read what exists.

Filename conventions (prefix → device):
    dio_*.jpg        Dio / Stack-Chan camera
    webcam_*.jpg     PC webcam fallback
    iris_*.wav       Iris badge recording
    stackchan_*.wav  Dio recording
"""
from __future__ import annotations

import datetime
import time
from pathlib import Path

from paths import PH3B3_DATA

CAPTURES_DIR = Path(PH3B3_DATA) / "captures"          # the single photo/audio store

_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
_AUDIO_EXT = {".wav"}


def _device_of(name: str) -> str:
    n = name.lower()
    if n.startswith("dio_"):       return "stackchan"
    if n.startswith("webcam_"):    return "webcam"
    if n.startswith("iris_"):      return "iris"
    if n.startswith("stackchan_"): return "stackchan"
    return name.split("_", 1)[0] if "_" in name else "unknown"


def _type_of(suffix: str):
    s = suffix.lower()
    if s in _IMAGE_EXT: return "image"
    if s in _AUDIO_EXT: return "audio"
    return None


class CapturesFeed:
    def __init__(self, captures_dir: Path = CAPTURES_DIR):
        self.dir = Path(captures_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _sidecar(self, f: Path, ext: str):
        side = f.with_suffix(ext)
        if side.exists():
            try:
                return side.read_text(encoding="utf-8", errors="replace").strip()[:2000]
            except Exception:
                return None
        return None

    def _sidecar_text(self, f: Path):
        return self._sidecar(f, ".txt")

    def feed(self, device: str = None, type: str = None, limit: int = 120) -> list:
        """Reverse-chron artifacts. `.txt` sidecars are never standalone items —
        they ride on their audio card. Filter by device and/or type."""
        items = []
        for f in self.dir.iterdir():
            if not f.is_file():
                continue
            typ = _type_of(f.suffix)
            if typ is None:
                continue
            dev = _device_of(f.name)
            if device and dev != device:
                continue
            if type and typ != type:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            item = {"name": f.name, "device": dev, "type": typ,
                    "ts": int(st.st_mtime), "size": st.st_size}
            if typ == "audio":
                item["transcript"] = self._sidecar_text(f)
                # Gated captures (silence / Whisper hallucination) carry a
                # .discarded sidecar instead of a transcript — kept for the audit
                # trail, shown greyed, and never entered the chat pipeline.
                disc = self._sidecar(f, ".discarded")
                if disc is not None:
                    item["discarded"] = disc
            items.append(item)
        items.sort(key=lambda x: x["ts"], reverse=True)
        return items[:limit]

    def devices(self) -> list:
        return sorted({_device_of(f.name) for f in self.dir.iterdir()
                       if f.is_file() and _type_of(f.suffix)})

    def last_transcript(self, device: str = None):
        """Most recent audio clip (optionally for one device) that has a
        transcript. Returns {name, device, ts, transcript} or None."""
        for it in self.feed(device=device, type="audio", limit=200):
            if it.get("transcript"):
                return {"name": it["name"], "device": it["device"],
                        "ts": it["ts"], "transcript": it["transcript"]}
        return None

    def group_by_day(self, items: list, now: float = None) -> list:
        """Group already-filtered feed items under date headers, newest group
        first. Key = capture mtime in SERVER LOCAL TIME (no schema, no DB — the
        items already come from a directory walk). Labels: Today / Yesterday /
        'Wed, Jul 15'. Each group carries a count; empty days don't appear because
        only days with items form groups (so device/type filters recount headers).
        Today is marked open=True; all others open=False (collapsed by default)."""
        now = now if now is not None else time.time()
        today = datetime.date.fromtimestamp(now)
        order, groups = [], {}
        for it in items:                       # items are already newest-first
            d = datetime.date.fromtimestamp(it["ts"])
            key = d.isoformat()
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(it)
        out = []
        for key in order:
            d = datetime.date.fromisoformat(key)
            delta = (today - d).days
            if delta == 0:
                label = "Today"
            elif delta == 1:
                label = "Yesterday"
            else:
                label = d.strftime("%a, %b ") + str(d.day)   # "Wed, Jul 15"
            out.append({"key": key, "label": label, "count": len(groups[key]),
                        "open": delta == 0, "items": groups[key]})
        return out

    def resolve(self, name: str):
        """Map a requested filename to a real file INSIDE the store, or None.
        Path-traversal safe: only the basename is honored and the result must
        stay within the captures dir."""
        safe = Path(name).name
        p = (self.dir / safe).resolve()
        if p.is_file() and self.dir.resolve() in p.parents:
            return p
        return None
