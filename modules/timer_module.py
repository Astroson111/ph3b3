import time
import threading
import logging
from datetime import datetime

log = logging.getLogger("ph3b3.timer")

class TimerModule:
    def __init__(self):
        self._timers = {}
        self._session_start = None
        log.info("Timer module ready.")

    def start_session(self, label="session"):
        self._session_start = datetime.now()
        return f"Session started: {label} at {self._session_start.strftime('%H:%M:%S')}"

    def session_elapsed(self):
        if not self._session_start:
            return "No session running."
        elapsed = datetime.now() - self._session_start
        mins = int(elapsed.total_seconds() // 60)
        secs = int(elapsed.total_seconds() % 60)
        return f"Session time: {mins}m {secs}s"

    def pomodoro(self, minutes=25, callback=None):
        def run():
            time.sleep(minutes * 60)
            msg = f"Pomodoro done. {minutes} minutes up. Time for a break."
            log.info(msg)
            if callback:
                callback(msg)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return f"Pomodoro started. {minutes} minutes on the clock."

    def set_timer(self, name, seconds, callback=None):
        def run():
            time.sleep(seconds)
            msg = f"Timer '{name}' done."
            log.info(msg)
            if callback:
                callback(msg)
        if name in self._timers:
            return f"Timer '{name}' already running."
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._timers[name] = t
        mins = seconds // 60
        secs = seconds % 60
        return f"Timer set: {name} — {mins}m {secs}s"

    def stopwatch(self):
        return f"Stopwatch started at {datetime.now().strftime('%H:%M:%S')}"

    def timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
