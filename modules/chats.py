"""
chats.py — per-session chat transcripts for the Argus Chats view.

PRIVACY POSTURE: this is the deliberate "Phoebe now keeps transcripts" store,
enabled by Captain decision 2026-07-18. One JSONL file per session under
~/ph3b3_data/chats/ (timestamp-named), holding both user and Phoebe turns from
every source (portal chat / Iris PTT / Dio). The read side groups sessions by
date for the panel. Strictly SEPARATE from Mnemosyne — Argus never touches
memory. Read-only from the portal (no delete/edit in v1). No retention window in
v1 (it's a history); transcripts are small JSONL and kept until manually cleared.
"""
from __future__ import annotations

import datetime
import json
import re
import threading
import time
from pathlib import Path

from paths import PH3B3_DATA

CHATS_DIR = Path(PH3B3_DATA) / "chats"
# device (X-Ph3b3-Device / dispatch device) → human source label
_SOURCE = {"nyx": "portal", "portal": "portal", "iris": "iris",
           "stackchan": "dio", "dio": "dio", "pan": "pan"}


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(s))[:32] or "session"


class ChatLog:
    def __init__(self, chats_dir: Path = CHATS_DIR):
        self.dir = Path(chats_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, Path] = {}     # session_id → file (per server run)
        self._lock = threading.Lock()

    # ── write (chat time) ──
    def log_turn(self, session_id: str, device: str, role: str, text: str) -> None:
        """Append one turn to the session's JSONL. role is 'user' or 'phoebe'."""
        if not text:
            return
        source = _SOURCE.get((device or "nyx").lower(), "portal")
        sid = session_id or "default"
        with self._lock:
            f = self._files.get(sid)
            if f is None:
                stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                f = self.dir / f"{stamp}_{_safe(sid)}.jsonl"
                self._files[sid] = f
            rec = {"ts": int(time.time()), "role": role, "source": source, "text": text}
            try:
                with f.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass

    # ── read (panel) ──
    def _turns(self, f: Path):
        try:
            return [json.loads(l) for l in
                    f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except Exception:
            return []

    def _summary(self, f: Path):
        turns = self._turns(f)
        if not turns:
            return None
        first_user = next((t.get("text", "") for t in turns if t.get("role") == "user"),
                          turns[0].get("text", ""))
        return {"name": f.name,
                "ts": turns[0].get("ts", int(f.stat().st_mtime)),
                "source": turns[0].get("source", "portal"),
                "preview": (first_user or "").strip()[:120],
                "turns": len(turns)}

    def sessions(self) -> list:
        out = []
        for f in self.dir.glob("*.jsonl"):
            s = self._summary(f)
            if s:
                out.append(s)
        out.sort(key=lambda x: x["ts"], reverse=True)
        return out

    def transcript(self, name: str):
        """Full turns for one session file, or None. Traversal-safe."""
        f = (self.dir / Path(name).name)
        if f.suffix != ".jsonl":
            return None
        rf = f.resolve()
        if not rf.is_file() or self.dir.resolve() not in rf.parents:
            return None
        return self._turns(f)

    def group_by_day(self, sessions: list, now: float = None) -> list:
        """Group sessions under date headers, newest first, Today open. Same
        pattern as captures: key = first-turn ts in server local time."""
        now = now if now is not None else time.time()
        today = datetime.date.fromtimestamp(now)
        order, groups = [], {}
        for s in sessions:
            key = datetime.date.fromtimestamp(s["ts"]).isoformat()
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(s)
        out = []
        for key in order:
            d = datetime.date.fromisoformat(key)
            delta = (today - d).days
            label = ("Today" if delta == 0 else "Yesterday" if delta == 1
                     else d.strftime("%a, %b ") + str(d.day))
            out.append({"key": key, "label": label, "count": len(groups[key]),
                        "open": delta == 0, "sessions": groups[key]})
        return out
