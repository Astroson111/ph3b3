import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.reminders")
REMINDERS_FILE = Path.home() / "ph3b3_data" / "reminders.json"

class RemindersModule:
    def __init__(self):
        REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.reminders = self._load()
        log.info(f"Reminders loaded. {len(self.reminders)} active.")

    def _load(self):
        if REMINDERS_FILE.exists():
            try:
                return json.loads(REMINDERS_FILE.read_text())
            except Exception:
                pass
        return []

    def _save(self):
        REMINDERS_FILE.write_text(json.dumps(self.reminders, indent=2))

    def add(self, text, when=None, tag="general"):
        entry = {
            "id": len(self.reminders) + 1,
            "text": text,
            "tag": tag,
            "created": datetime.now().isoformat(),
            "when": when,
            "done": False,
        }
        self.reminders.append(entry)
        self._save()
        when_str = f" at {when}" if when else ""
        return f"Reminder saved{when_str}: {text}"

    def list_pending(self):
        pending = [r for r in self.reminders if not r["done"]]
        if not pending:
            return "No pending reminders."
        lines = []
        for r in pending:
            when = f" [{r['when']}]" if r.get("when") else ""
            lines.append(f"#{r['id']} {r['tag']}{when}: {r['text']}")
        return "\n".join(lines)

    def done(self, reminder_id):
        for r in self.reminders:
            if r["id"] == reminder_id:
                r["done"] = True
                self._save()
                return f"Reminder #{reminder_id} marked done."
        return f"Reminder #{reminder_id} not found."

    def due_today(self):
        today = datetime.now().strftime("%Y-%m-%d")
        due = [r for r in self.reminders
               if not r["done"] and r.get("when","").startswith(today)]
        if not due:
            return "Nothing due today."
        return "\n".join(f"#{r['id']}: {r['text']}" for r in due)

    def on_boot(self):
        pending = [r for r in self.reminders if not r["done"]]
        if not pending:
            return None
        count = len(pending)
        return f"You have {count} pending reminder{'s' if count > 1 else ''}. Ask me to list them."
