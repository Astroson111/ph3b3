import json
import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.investigation")
INVEST_DIR = Path.home() / "ph3b3_data" / "investigations"

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
        log.info("Investigation module ready.")

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
