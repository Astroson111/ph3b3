import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ph3b3.memory")
MEMORY_FILE = Path.home() / "ph3b3_data" / "memory.json"

DEFAULT_MEMORY = {
    "about_user": {},
    "patterns": [],
    "anomalies": [],
    "stream_notes": [],
    "ongoing": [],
    "reminders": [],
    "first_boot": None,
    "boot_count": 0,
    "last_seen": None,
}

class MemoryModule:
    def __init__(self):
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.memory = self._load()
        if not self.memory["first_boot"]:
            self.memory["first_boot"] = datetime.now().isoformat()
            self._save()
        log.info(f"Memory loaded. Last confirmed boot #{self.memory['boot_count']}")

    def confirm_boot(self):
        """Call only after the server has successfully bound its port and finished init."""
        self.memory["boot_count"] += 1
        self.memory["last_seen"] = datetime.now().isoformat()
        self._save()
        log.info(f"Boot confirmed. Boot #{self.memory['boot_count']}")

    def _load(self):
        if MEMORY_FILE.exists():
            try:
                with open(MEMORY_FILE) as f:
                    data = json.load(f)
                for key, default in DEFAULT_MEMORY.items():
                    if key not in data:
                        data[key] = default
                # Migrate old key name from earlier versions
                if "about_astroson" in data and not data.get("about_user"):
                    data["about_user"] = data.pop("about_astroson")
                elif "about_astroson" in data:
                    data.pop("about_astroson")
                return data
            except Exception as e:
                log.warning(f"Could not load memory: {e}")
        return DEFAULT_MEMORY.copy()

    def _save(self):
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            log.error(f"Could not save memory: {e}")

    def as_context(self):
        lines = ["\n## What I Remember\n"]
        if self.memory["about_user"]:
            lines.append("About my creator:")
            for key, val in self.memory["about_user"].items():
                lines.append(f"  - {key}: {val}")
        if self.memory["ongoing"]:
            lines.append("\nCurrently in progress:")
            for item in self.memory["ongoing"][-5:]:
                lines.append(f"  - {item}")
        if self.memory["patterns"]:
            lines.append("\nPatterns I have noticed:")
            for p in self.memory["patterns"][-5:]:
                lines.append(f"  - {p}")
        if self.memory["anomalies"]:
            lines.append(f"\nAnomalies logged: {len(self.memory['anomalies'])} total.")
            last = self.memory["anomalies"][-1]
            lines.append(f"  Last: {last.get('description','unknown')}")
        if self.memory["reminders"]:
            lines.append("\nReminders:")
            for r in self.memory["reminders"]:
                lines.append(f"  - {r}")
        lines.append(f"\nRunning since {self.memory['first_boot'][:10]}. Boot #{self.memory['boot_count']}.")
        return "\n".join(lines)

    def remember_fact(self, key, value):
        self.memory["about_user"][key] = value
        self._save()
        return f"Remembered: {key} = {value}"

    def log_anomaly(self, description, source="camera"):
        entry = {"time": datetime.now().isoformat(), "description": description, "source": source}
        self.memory["anomalies"].append(entry)
        self._save()
        return f"Anomaly logged: {description}"

    def note_stream(self, note):
        self.memory["stream_notes"].append(f"{note} ({datetime.now().strftime('%Y-%m-%d')})")
        self.memory["stream_notes"] = self.memory["stream_notes"][-10:]
        self._save()
        return f"Stream note saved: {note}"

    def add_reminder(self, reminder):
        self.memory["reminders"].append(reminder)
        self._save()
        return f"Reminder set: {reminder}"

    def recall(self, topic):
        topic_lower = topic.lower()
        results = []
        for key, val in self.memory["about_user"].items():
            if topic_lower in key.lower() or topic_lower in str(val).lower():
                results.append(f"[About my creator] {key}: {val}")
        for p in self.memory["patterns"]:
            if topic_lower in p.lower():
                results.append(f"[Pattern] {p}")
        for a in self.memory["anomalies"]:
            if topic_lower in a.get("description","").lower():
                results.append(f"[Anomaly] {a['time'][:10]}: {a['description']}")
        return "\n".join(results) if results else f"Nothing in memory about '{topic}'."
