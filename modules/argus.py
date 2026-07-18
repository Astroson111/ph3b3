"""
argus.py — read-only fleet observability store + state logic.

Argus OBSERVES the fleet; it never acts (no restart/reflash/delete anywhere).
This module owns a dedicated SQLite DB (~/ph3b3_data/argus.db) that is strictly
SEPARATE from Mnemosyne — Argus never writes to memory. It stores per-device
heartbeats (ring-buffered ~14 days) and Argus's own self-heartbeat, and derives
the three display states from per-device cadence contracts:

    HEALTHY — within its contract, values OK
    SICK    — reporting bad values (below a contract threshold)
    SILENT  — past its contract with no report (shown as "last seen <time> +
              last known state", never a bare "offline")

Contracts live in config/argus_contracts.json, editable without touching code.
Heartbeat INGEST rides the server's existing verified check-in path (this module
only records what the server hands it); a separate argus-daemon writes the
self-heartbeat and prunes. stdlib + sqlite3 only — no new dependencies.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from paths import PH3B3_DATA

ARGUS_DB     = Path(PH3B3_DATA) / "argus.db"          # dedicated — NOT mnemosyne.db
CONTRACTS    = Path(__file__).resolve().parents[1] / "config" / "argus_contracts.json"
RETENTION_D  = 14                                     # ring-buffer retention (days)

HEALTHY, SICK, SILENT = "HEALTHY", "SICK", "SILENT"


# ── contracts (config-driven, editable without code) ──────────────────────────
def load_contracts(path: Path = CONTRACTS) -> dict:
    """Return {'defaults': {...}, 'devices': {id: {...}}}. Missing file → sane
    defaults so a fresh install still runs (empty fleet, service cadence)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data.setdefault("defaults", {})
        data.setdefault("devices", {})
        return data
    except Exception:
        return {"defaults": {"type": "service", "heartbeat_s": 30, "silent_after_s": 120}, "devices": {}}


def contract_for(contracts: dict, device_id: str) -> dict:
    c = dict(contracts.get("defaults", {}))
    c.update(contracts.get("devices", {}).get(device_id, {}))
    return c


def _in_sleep_window(contract: dict, now_epoch: float) -> bool:
    """A declared sleep window counts as HEALTHY silence (battery badges sleep).
    Windows are local-time ["HH:MM","HH:MM"] ranges; a range that wraps midnight
    (start > end) is handled."""
    windows = contract.get("sleep_windows") or []
    if not windows:
        return False
    lt = time.localtime(now_epoch)
    mins = lt.tm_hour * 60 + lt.tm_min
    for w in windows:
        try:
            (sh, sm), (eh, em) = (int(x) for x in w[0].split(":")), (int(x) for x in w[1].split(":"))
            start, end = sh * 60 + sm, eh * 60 + em
        except Exception:
            continue
        if start <= end:
            if start <= mins < end:
                return True
        else:  # wraps midnight, e.g. 23:00–07:00
            if mins >= start or mins < end:
                return True
    return False


def _is_sick(row: dict, contract: dict) -> Optional[str]:
    """Return a reason string if the latest values breach a contract floor, else
    None. Thresholds are per-device in the contract ('sick_if')."""
    limits = contract.get("sick_if") or {}
    batt = row.get("battery")
    heap = row.get("free_heap")
    if "battery_below" in limits and batt is not None and batt < limits["battery_below"]:
        return f"battery {batt}% < {limits['battery_below']}%"
    if "free_heap_below" in limits and heap is not None and heap < limits["free_heap_below"]:
        return f"free heap {heap} < {limits['free_heap_below']}"
    return None


# ── store ─────────────────────────────────────────────────────────────────────
class ArgusStore:
    def __init__(self, db_path: Path = ARGUS_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS heartbeats (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id     TEXT    NOT NULL,
                    ts            INTEGER NOT NULL,       -- unix epoch seconds (UTC)
                    battery       INTEGER,                -- percent, nullable
                    rssi          INTEGER,                -- dBm, nullable
                    uptime        INTEGER,                -- seconds, nullable
                    firmware_hash TEXT,
                    free_heap     INTEGER                 -- bytes, nullable
                )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hb_device_ts ON heartbeats(device_id, ts)")
            # Argus's own liveness — its gap is visible here if the daemon dies.
            c.execute("CREATE TABLE IF NOT EXISTS argus_self (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL)")

    # ── writes ──
    def record_heartbeat(self, device_id: str, *, battery=None, rssi=None,
                         uptime=None, firmware_hash=None, free_heap=None, ts=None) -> None:
        ts = int(ts if ts is not None else time.time())
        with self._conn() as c:
            c.execute(
                "INSERT INTO heartbeats(device_id,ts,battery,rssi,uptime,firmware_hash,free_heap) "
                "VALUES(?,?,?,?,?,?,?)",
                (device_id, ts, battery, rssi, uptime, firmware_hash, free_heap),
            )

    def record_self(self, ts=None) -> None:
        ts = int(ts if ts is not None else time.time())
        with self._conn() as c:
            c.execute("INSERT INTO argus_self(ts) VALUES(?)", (ts,))

    def prune(self, days: int = RETENTION_D, now: Optional[float] = None) -> int:
        cutoff = int((now if now is not None else time.time()) - days * 86400)
        with self._conn() as c:
            n = c.execute("DELETE FROM heartbeats WHERE ts < ?", (cutoff,)).rowcount
            c.execute("DELETE FROM argus_self WHERE ts < ?", (cutoff,))
            return n

    # ── reads ──
    def latest(self, device_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM heartbeats WHERE device_id=? ORDER BY ts DESC LIMIT 1",
                          (device_id,)).fetchone()
            return dict(r) if r else None

    def known_devices(self) -> list:
        with self._conn() as c:
            return [r["device_id"] for r in
                    c.execute("SELECT DISTINCT device_id FROM heartbeats").fetchall()]

    def history(self, device_id: str, limit: int = 30) -> list:
        """Most-recent-first rows for a device (sparkline / heap trend)."""
        with self._conn() as c:
            rows = c.execute("SELECT * FROM heartbeats WHERE device_id=? ORDER BY ts DESC LIMIT ?",
                             (device_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def self_last(self) -> Optional[int]:
        with self._conn() as c:
            r = c.execute("SELECT ts FROM argus_self ORDER BY ts DESC LIMIT 1").fetchone()
            return r["ts"] if r else None

    # ── state derivation (read-only) ──
    def evaluate(self, device_id: str, contracts: dict, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        contract = contract_for(contracts, device_id)
        # Argus derives its own state from its dedicated self-heartbeat table (the
        # "own table" the daemon writes to) — so the daemon's gap shows as SILENT.
        if device_id == "argus":
            ts = self.self_last()
            row = {"ts": ts, "battery": None, "rssi": None, "free_heap": None,
                   "uptime": None, "firmware_hash": None} if ts else None
        else:
            row = self.latest(device_id)

        drift = False
        expected = contract.get("expected_firmware_hash")
        if expected and row and row.get("firmware_hash") and row["firmware_hash"] != expected:
            drift = True

        if row is None:
            return {"device_id": device_id, "state": SILENT, "reason": "never reported",
                    "last_seen": None, "age_s": None, "firmware_drift": drift, "contract": contract,
                    "battery": None, "rssi": None, "free_heap": None, "firmware_hash": None}

        age = now - row["ts"]
        sick_reason = _is_sick(row, contract)
        if _in_sleep_window(contract, now):
            state, reason = HEALTHY, "declared sleep window"
        elif age > contract.get("silent_after_s", 120):
            state, reason = SILENT, "past cadence contract"
        elif sick_reason:
            state, reason = SICK, sick_reason
        else:
            state, reason = HEALTHY, "within contract"

        return {
            "device_id": device_id, "state": state, "reason": reason,
            "last_seen": row["ts"], "age_s": int(age), "firmware_drift": drift,
            "battery": row.get("battery"), "rssi": row.get("rssi"),
            "free_heap": row.get("free_heap"), "uptime": row.get("uptime"),
            "firmware_hash": row.get("firmware_hash"), "contract": contract,
        }

    def fleet(self, contracts: dict, now: Optional[float] = None) -> list:
        """Every device named in the contracts OR seen in the DB, evaluated.
        Contract devices always appear (so a never-seen device reads SILENT,
        not missing)."""
        now = now if now is not None else time.time()
        ids = list(dict.fromkeys(list(contracts.get("devices", {}).keys()) + self.known_devices()))
        return [self.evaluate(d, contracts, now) for d in ids]


def iso(ts: Optional[int]) -> Optional[str]:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None
