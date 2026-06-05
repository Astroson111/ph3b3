import logging
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.calendar")

# Google Calendar is accessed via the gcalcli command-line tool
# Install: pip install gcalcli
# Auth: gcalcli init (opens browser for Google OAuth)
# Ph3b3 calls gcalcli as a subprocess — no API keys needed

class CalendarModule:
    def __init__(self):
        self._available = self._check()
        if self._available:
            log.info("Calendar module ready via gcalcli.")
        else:
            log.warning("gcalcli not found. Run: pip install gcalcli && gcalcli init")

    def _check(self):
        try:
            result = subprocess.run(["which", "gcalcli"], capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def _run(self, args, timeout=15):
        try:
            result = subprocess.run(
                ["gcalcli"] + args,
                capture_output=True, text=True, timeout=timeout
            )
            return result.stdout.strip() or result.stderr.strip()
        except subprocess.TimeoutExpired:
            return "Calendar request timed out."
        except Exception as e:
            return f"Calendar error: {e}"

    def today(self):
        if not self._available:
            return "gcalcli not installed. Run: pip install gcalcli && gcalcli init"
        return self._run(["agenda", "today", "tomorrow"])

    def week(self):
        if not self._available:
            return "gcalcli not available."
        return self._run(["calw", "--monday"])

    def upcoming(self, days=7):
        if not self._available:
            return "gcalcli not available."
        end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        return self._run(["agenda", datetime.now().strftime("%Y-%m-%d"), end])

    def add_event(self, title, when, duration_mins=60, calendar=None):
        if not self._available:
            return "gcalcli not available."
        args = ["quick", f"{when} {title}"]
        if calendar:
            args = ["--calendar", calendar] + args
        return self._run(args)

    def search(self, query):
        if not self._available:
            return "gcalcli not available."
        return self._run(["search", query])

    def status(self):
        if self._available:
            return "Google Calendar connected via gcalcli."
        return "gcalcli not installed. Run: pip install gcalcli && gcalcli init"
