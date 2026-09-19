"""
rhea_status — what the backup actually did, read from what already exists.

WHY THIS MODULE IS SO SMALL. Rhea is a shell script and a systemd timer, and it
was already telling the truth: the journal records every run, Argus receives a
heartbeat carrying the drive's free bytes, and restic keeps the snapshot list.
None of that reached Phoebe, so asked "when did Rhea last back up?" she said she
had no access to data she demonstrably holds — and asked how Rhea was doing, she
invented a patient with vitals and doctors.

So this reads three sources that were always there and returns facts. It writes
nothing, runs no restic command that could mutate a repo, and cannot restore.

RESTORE IS DELIBERATELY ABSENT. A restore overwrites live data, and the one
thing worse than never testing a backup is a restore that can be triggered by a
sentence. It stays a human at a keyboard with sudo, on purpose.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

DATA_DIR = Path(os.path.expanduser("~/ph3b3_data"))
ARGUS_DB = DATA_DIR / "argus.db"
DRILL_MARKER = DATA_DIR / ".rhea-last-drill"      # written by the drill, if ever
UNIT = "rhea-backup.service"


def _journal_last_run() -> dict:
    """The last run's outcome, from the journal. Never raises."""
    out = {"when": None, "result": None, "detail": ""}
    try:
        r = subprocess.run(
            ["journalctl", "-u", UNIT, "-n", "80", "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return out
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "DONE" in ln or "FAIL" in ln:
            out["result"] = "ok" if "DONE" in ln else "failed"
            out["when"] = ln.split()[0] if ln.split() else None
            m = re.search(r"\[rhea-backup\]\s*(.*)$", ln)
            out["detail"] = (m.group(1) if m else ln)[:160]
            break
    return out


def _argus_last_beat() -> dict:
    """Rhea's heartbeat, which carries the drive's free bytes as free_heap."""
    out = {"ts": None, "age_s": None, "free_bytes": None}
    try:
        db = sqlite3.connect(f"file:{ARGUS_DB}?mode=ro", uri=True, timeout=5)
        cols = {r[1] for r in db.execute("PRAGMA table_info(heartbeats)")}
        field = "free_heap" if "free_heap" in cols else None
        q = f"SELECT ts{', ' + field if field else ''} FROM heartbeats " \
            "WHERE device_id='rhea' ORDER BY ts DESC LIMIT 1"
        row = db.execute(q).fetchone()
        db.close()
        if row:
            out["ts"] = row[0]
            out["age_s"] = int(time.time()) - int(row[0])
            if field and len(row) > 1:
                out["free_bytes"] = row[1]
    except Exception:
        pass
    return out


def _drill() -> dict:
    """When the restore drill was last run, if a marker was ever written.

    Absence is reported as absence. A backup nobody has restored from is a
    hypothesis, and that is worth saying out loud rather than omitting.
    """
    try:
        if DRILL_MARKER.exists():
            txt = DRILL_MARKER.read_text(encoding="utf-8").strip()[:80]
            return {"ever": True, "when": txt or None}
    except Exception:
        pass
    return {"ever": False, "when": None}


def _ago(sec: int | None) -> str:
    if sec is None:
        return "unknown"
    if sec < 3600:
        return f"{sec // 60} minutes ago"
    if sec < 172800:
        return f"{sec / 3600:.1f} hours ago"
    return f"{sec / 86400:.1f} days ago"


def status() -> dict:
    """Everything known about the backup, as data."""
    run, beat, drill = _journal_last_run(), _argus_last_beat(), _drill()
    return {"last_run": run, "heartbeat": beat, "drill": drill,
            "drive_mounted": Path("/mnt/rhea").is_mount()}


def spoken() -> str:
    """One honest paragraph. Every clause is backed by a datum or omitted."""
    s = status()
    run, beat, drill = s["last_run"], s["heartbeat"], s["drill"]
    bits = []
    if run["result"] == "ok":
        bits.append(f"The last backup finished cleanly at {run['when']}.")
    elif run["result"] == "failed":
        bits.append(f"The last backup FAILED at {run['when']} — {run['detail']}")
    else:
        bits.append("I can't find a recent backup run in the journal.")
    if beat["age_s"] is not None:
        bits.append(f"Rhea last checked in {_ago(beat['age_s'])}.")
    if beat["free_bytes"]:
        bits.append(f"The drive reports {int(beat['free_bytes']) / 1e9:.0f} GB free.")
    if not s["drive_mounted"]:
        bits.append("The RHEA drive is NOT mounted right now.")
    bits.append(
        f"The restore drill was last run {drill['when']}." if drill["ever"]
        else "No restore drill has ever been completed — the backups have never "
             "been read back, so they're unproven.")
    return " ".join(bits)
