import json
import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.investigation")
INVEST_DIR = Path.home() / "ph3b3_data" / "investigations"

# How far outside an investigation's own window a device recording may fall and
# still be counted as part of it. The operator says "start the investigation" at
# a slightly different moment than Dio starts recording, and neither clock is the
# authority on the other.
LINK_GRACE = timedelta(minutes=5)

# Match cemetery / burial-ground synonyms across common languages.
# Word-boundary anchors used throughout; accented and plain-ASCII forms both covered.
_CEMETERY_RE = re.compile(
    r'\b(?:'
    r'cemetery|cemeteries|graveyard|graveyards?|burial\s+grounds?|'
    r'memorial\s+park|churchyard|necropolis|mausoleum|catacombs?|columbarium|'
    r"garden\s+of\s+remembrance|potter'?s?\s+field|"
    r'cimeti[e\xe8]re|'             # French: cimetière / cimetiere
    r'cementerio|cemit[e\xe9]rio|'  # Spanish / Portuguese
    r'camposanto|campo\s+santo|'    # Spanish / Italian
    r'pante[o\xf3]n|'              # Spanish / Portuguese: panteón
    r'friedhof|kirchhof|'           # German
    r'begraafplaats|kerkhof|'       # Dutch
    r'cimitero|'                    # Italian
    r'cmentarz'                     # Polish
    r')\b',
    re.IGNORECASE,
)

class InvestigationModule:
    # ── Cemetery tribute ────────────────────────────────────────────────────────
    # PERSONAL TRIBUTE — this exact line must not be altered or removed in
    # refactors, renames, or model upgrades. It is hardcoded here (not LLM-
    # generated) so it survives any backend swap.
    _CEMETERY_TRIBUTE = "Oh hey — it's the place people are dying to get into."

    def __init__(self):
        INVEST_DIR.mkdir(parents=True, exist_ok=True)
        self._active = None
        self._cemetery_tribute_fired = False  # reset on each new session
        # The device-sync endpoint links bundles from a worker thread while the
        # conversation thread may be logging an EVP into the same record.
        # Reentrant because the link path calls _save() while already holding it.
        self._lock = threading.RLock()
        log.info("Investigation module ready.")

    def is_active(self) -> bool:
        """True while a ghost-hunting session is open. Gates the camera-monitoring
        tools (set_baseline / check_anomaly / start_monitoring) so vision only runs
        continuously during an investigation — otherwise vision is prompt-only."""
        return self._active is not None

    def _is_cemetery(self, location: str) -> bool:
        return bool(_CEMETERY_RE.search(location))
        # TODO: when GPS support is added (USB dongle, roadmap), also trigger on
        # detected cemetery coordinates here — pass lat/lon and check against a
        # local or bundled cemetery boundary dataset.

    def start(self, location, investigator="Operator"):
        ts = datetime.now()
        session_id = ts.strftime("%Y%m%d_%H%M%S")
        self._active = {
            "session_id": session_id,
            "location": location,
            "investigator": investigator,
            "started": ts.isoformat(),
            "ended": None,
            "events": [],
            "evp_timestamps": [],
            "emf_readings": [],
            "anomalies": [],
            "notes": [],
            "weather": None,
            "device_sessions": [],   # Dio/Pan bundles that recorded during this hunt
        }
        self._cemetery_tribute_fired = False
        self._save()

        result = f"Investigation started: {location} [{session_id}]"
        if self._is_cemetery(location):
            result += f"\n\n{self._CEMETERY_TRIBUTE}"
            self._cemetery_tribute_fired = True
            log.info("Cemetery tribute delivered.")
        return result

    def log_event(self, description, category="general"):
        if not self._active:
            return "No active investigation. Start one first."
        entry = {
            "time": datetime.now().isoformat(),
            "category": category,
            "description": description,
        }
        self._active["events"].append(entry)
        self._save()
        return f"Event logged [{category}]: {description}"

    def log_evp(self, note=""):
        if not self._active:
            return "No active investigation."
        ts = datetime.now().isoformat()
        self._active["evp_timestamps"].append({"time": ts, "note": note})
        self._save()
        return f"EVP timestamp: {ts} — {note}"

    def log_emf(self, reading, location_note=""):
        if not self._active:
            return "No active investigation."
        entry = {
            "time": datetime.now().isoformat(),
            "reading": reading,
            "location": location_note,
        }
        self._active["emf_readings"].append(entry)
        self._save()
        return f"EMF logged: {reading} at {location_note}"

    def log_anomaly(self, description, source="manual"):
        if not self._active:
            return "No active investigation."
        entry = {
            "time": datetime.now().isoformat(),
            "source": source,
            "description": description,
        }
        self._active["anomalies"].append(entry)
        self._save()
        return f"Anomaly logged [{source}]: {description}"

    def add_note(self, note):
        if not self._active:
            return "No active investigation."
        self._active["notes"].append({
            "time": datetime.now().isoformat(),
            "note": note,
        })
        self._save()
        return f"Note added: {note}"

    def set_weather(self, weather_data):
        if not self._active:
            return "No active investigation."
        self._active["weather"] = weather_data
        self._save()
        return "Weather data attached to investigation."

    def status(self):
        if not self._active:
            return "No active investigation."
        elapsed = datetime.now() - datetime.fromisoformat(self._active["started"])
        mins = int(elapsed.total_seconds() // 60)
        devices = self._active.get("device_sessions") or []
        lines = [
            f"Location: {self._active['location']}",
            f"Session: {self._active['session_id']}",
            f"Elapsed: {mins} minutes",
            f"Events: {len(self._active['events'])}",
            f"EVP timestamps: {len(self._active['evp_timestamps'])}",
            f"EMF readings: {len(self._active['emf_readings'])}",
            f"Anomalies: {len(self._active['anomalies'])}",
        ]
        # Bundles only appear once Dio syncs, which is usually after the hunt —
        # so "none yet" here means not uploaded, not nothing recorded.
        if devices:
            for d in devices:
                c = d.get("counts") or {}
                lines.append(
                    f"Device {d.get('device','?')} [{d.get('mode','?')}]: "
                    f"{c.get('audio',0)} audio, {c.get('photo',0)} photos, "
                    f"{c.get('env',0)} env readings"
                )
        else:
            lines.append("Device evidence: none synced yet")
        return "\n".join(lines)

    def end(self):
        if not self._active:
            return "No active investigation."
        self._active["ended"] = datetime.now().isoformat()
        report = self._generate_report()
        self._save()
        session_id = self._active["session_id"]
        self._active = None
        return f"Investigation ended. Report saved: {session_id}\n\n{report}"

    def _generate_report(self):
        s = self._active
        started = datetime.fromisoformat(s["started"])
        ended = datetime.fromisoformat(s["ended"])
        duration = int((ended - started).total_seconds() // 60)
        lines = [
            f"INVESTIGATION REPORT",
            f"====================",
            f"Location:     {s['location']}",
            f"Investigator: {s['investigator']}",
            f"Started:      {s['started'][:19]}",
            f"Ended:        {s['ended'][:19]}",
            f"Duration:     {duration} minutes",
            f"",
            f"WEATHER",
            f"-------",
            str(s.get("weather") or "Not recorded."),
            f"",
            f"ANOMALIES ({len(s['anomalies'])})",
            f"----------",
        ]
        for a in s["anomalies"]:
            lines.append(f"  [{a['time'][11:19]}] [{a['source']}] {a['description']}")
        lines += [
            f"",
            f"EVP TIMESTAMPS ({len(s['evp_timestamps'])})",
            f"---------------",
        ]
        for e in s["evp_timestamps"]:
            lines.append(f"  [{e['time'][11:19]}] {e.get('note','')}")
        lines += [
            f"",
            f"EMF READINGS ({len(s['emf_readings'])})",
            f"-------------",
        ]
        for e in s["emf_readings"]:
            lines.append(f"  [{e['time'][11:19]}] {e['reading']} — {e.get('location','')}")

        devices = s.get("device_sessions") or []
        lines += [
            f"",
            f"DEVICE EVIDENCE ({len(devices)})",
            f"---------------",
        ]
        if devices:
            for d in devices:
                c = d.get("counts") or {}
                lines.append(
                    f"  {d.get('session_id')} — {d.get('device','?')} "
                    f"[{d.get('mode','?')}], {c.get('audio',0)} audio / "
                    f"{c.get('photo',0)} photos / {c.get('env',0)} env"
                )
                lines.append(f"    {d.get('path','')}")
        else:
            # Said plainly: a report generated at end() normally predates the
            # sync, so an empty section here is about upload, not about capture.
            lines.append("  None synced at the time of this report.")
        return "\n".join(lines)

    # ── Device evidence ──────────────────────────────────────────────────────
    # An investigation is the human record — where you were, what you noticed,
    # what the EMF meter said. A device session is what Dio actually captured
    # while you were noticing it. They are recorded independently, on separate
    # clocks, and joined here after the fact by time.

    def find_session_for(self, when, grace=LINK_GRACE):
        """Which investigation was running at `when` (naive local datetime)?

        A closed record owns [started, ended] with a few minutes' grace either
        side. A record with no `ended` counts ONLY while it is the one open in
        this process: a session left unclosed before a restart is stale, not
        ongoing, and must not silently swallow every recording made since. There
        is such a record on disk from 2026-07-16, which is exactly why this rule
        exists. Returns a session_id, or None — never a guess.
        """
        if when is None:
            return None
        with self._lock:
            active_id = self._active["session_id"] if self._active else None
            for path in sorted(INVEST_DIR.glob("*.json")):
                try:
                    data = self.get_session(path.stem) or {}
                    started = data.get("started")
                    if not started:
                        continue
                    start = datetime.fromisoformat(started)
                    ended = data.get("ended")
                    if ended:
                        end = datetime.fromisoformat(ended)
                    elif data.get("session_id") == active_id:
                        end = datetime.now()       # genuinely still running
                    else:
                        continue                   # stale open record — not a candidate
                    if start - grace <= when <= end + grace:
                        return data["session_id"]
                except (ValueError, OSError, json.JSONDecodeError):
                    continue
        return None

    def get_session(self, session_id):
        """The record as it stands. Reads from memory when it is the open one,
        so a caller never sees a file the live session is about to overwrite."""
        with self._lock:
            if self._active and self._active["session_id"] == session_id:
                return self._active
            path = INVEST_DIR / f"{session_id}.json"
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return None

    def attach_device_session(self, session_id, entry):
        """Cross-link a synced device bundle onto an investigation.

        Idempotent by entry["session_id"], so re-syncing a bundle updates the
        link in place instead of piling up duplicates. If the target is the
        investigation currently open, the in-memory copy is what gets mutated —
        writing its file directly would be undone by the next _save().
        """
        with self._lock:
            live = self._active is not None and self._active["session_id"] == session_id
            record = self._active if live else self.get_session(session_id)
            if record is None:
                return False

            sessions = record.setdefault("device_sessions", [])
            for i, existing in enumerate(sessions):
                if existing.get("session_id") == entry.get("session_id"):
                    sessions[i] = entry
                    break
            else:
                sessions.append(entry)
            sessions.sort(key=lambda e: e.get("started_at") or "")

            if live:
                self._save()
            else:
                path = INVEST_DIR / f"{session_id}.json"
                tmp = path.with_suffix(".json.part")
                tmp.write_text(json.dumps(record, indent=2))
                tmp.replace(path)
            log.info("[investigation] %s ← device session %s",
                     session_id, entry.get("session_id"))
            return True

    def _save(self):
        with self._lock:
            if not self._active:
                return
            path = INVEST_DIR / f"{self._active['session_id']}.json"
            tmp = path.with_suffix(".json.part")
            tmp.write_text(json.dumps(self._active, indent=2))
            tmp.replace(path)   # never leave a half-written record behind

    def list_sessions(self):
        files = sorted(INVEST_DIR.glob("*.json"), reverse=True)
        if not files:
            return "No investigation sessions found."
        lines = []
        for f in files[:10]:
            try:
                data = json.loads(f.read_text())
                ended = "ongoing" if not data.get("ended") else data["ended"][:10]
                lines.append(f"{data['session_id']} — {data['location']} [{ended}]")
            except Exception:
                lines.append(f.stem)
        return "\n".join(lines)

    def load_session(self, session_id):
        path = INVEST_DIR / f"{session_id}.json"
        if not path.exists():
            return f"Session not found: {session_id}"
        try:
            self._active = json.loads(path.read_text())
            return f"Session loaded: {session_id}"
        except Exception as e:
            return f"Error loading session: {e}"
