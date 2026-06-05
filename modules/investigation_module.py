import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.investigation")
INVEST_DIR = Path.home() / "ph3b3_data" / "investigations"

class InvestigationModule:
    def __init__(self):
        INVEST_DIR.mkdir(parents=True, exist_ok=True)
        self._active = None
        log.info("Investigation module ready.")

    def start(self, location, investigator="Astroson"):
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
        }
        self._save()
        return f"Investigation started: {location} [{session_id}]"

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
        return (
            f"Location: {self._active['location']}\n"
            f"Session: {self._active['session_id']}\n"
            f"Elapsed: {mins} minutes\n"
            f"Events: {len(self._active['events'])}\n"
            f"EVP timestamps: {len(self._active['evp_timestamps'])}\n"
            f"EMF readings: {len(self._active['emf_readings'])}\n"
            f"Anomalies: {len(self._active['anomalies'])}"
        )

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
        return "\n".join(lines)

    def _save(self):
        if not self._active:
            return
        path = INVEST_DIR / f"{self._active['session_id']}.json"
        path.write_text(json.dumps(self._active, indent=2))

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
