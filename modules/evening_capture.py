#!/usr/bin/env python3
"""
evening_capture.py — a Ph3b3 way to keep the night, through Stack-Chan.

Snaps a photo on an interval through the evening. Phase 2: every frame comes
from Dio's (Stack-Chan's) own CoreS3 camera and lands in ~/ph3b3_data/captures
— the one and only photo store. No local webcam, no Desktop folder, ever.

The session owns only the timer. The actual capture is a callback the server
wires to the vision module (vision.capture), which asks Dio for a frame and
persists it. A single missed frame (Dio busy/offline) is counted and skipped,
never fatal.

Wired in server.py:
    import evening_capture as _ec_mod
    _ec_mod.alba_say = lambda t: _tts_announce(t)
    ... tool_start_evening_capture(label, interval, vision.capture)
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

# A capture returns True if a frame was pulled from Dio and saved, else False.
CaptureFn = Callable[[], bool]


class EveningCapture:
    def __init__(
        self,
        label: str = "evening",
        interval: float = 120.0,
        capture: Optional[CaptureFn] = None,
        announce: Optional[Callable[[str], None]] = None,
    ):
        self.label = label
        self.interval = float(interval)
        self._capture = capture
        self.announce = announce
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.count = 0
        self.errors = 0

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _tick(self) -> None:
        try:
            if self._capture and self._capture():
                self.count += 1
            else:
                self.errors += 1          # Dio offline or no frame — skip, never fatal
        except Exception as e:
            self.errors += 1
            print(f"[capture] frame skipped: {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.interval)

    def start(self) -> dict:
        if self.is_running():
            return {"ok": False, "msg": "already capturing"}
        if not self._capture:
            return {"ok": False, "msg": "no capture source wired"}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[capture] Capturing the evening through Stack-Chan every {self.interval:g}s")
        if self.announce:
            self.announce("Capturing the evening through Stack-Chan.")
        return {"ok": True}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
        print(f"[capture] Saved {self.count} moments ({self.errors} skipped)")
        if self.announce:
            self.announce(f"Stopped. Saved {self.count} moments to my captures.")
        return {"count": self.count, "errors": self.errors}


# ---- Ph3b3 tool handlers -------------------------------------------------
# One session shared across tool calls so "start" and "stop" talk to the same
# thing. The server wires alba_say and passes vision.capture as the source:
#   import evening_capture as _ec_mod
#   _ec_mod.alba_say = lambda t: _tts_announce(t)

_session: Optional[EveningCapture] = None


def alba_say(text: str) -> None:
    pass  # no-op placeholder; server.py overwrites this after import


def tool_start_evening_capture(label: str = "evening", interval: float = 120,
                               capture: Optional[CaptureFn] = None) -> str:
    """Ph3b3 tool: begin capturing the evening through Stack-Chan's camera."""
    global _session
    if _session and _session.is_running():
        return "I'm already capturing the evening."
    _session = EveningCapture(label, interval, capture=capture, announce=alba_say)
    res = _session.start()
    if not res.get("ok"):
        _session = None
        return f"I couldn't start capturing: {res.get('msg', 'unknown error')}."
    return (f"Capturing the evening through Stack-Chan every {float(interval):g} seconds, "
            "saving to my captures folder.")


def tool_stop_evening_capture() -> str:
    """Ph3b3 tool: stop capturing and report the count."""
    global _session
    if not _session:
        return "Nothing is capturing right now."
    res = _session.stop()
    _session = None
    return f"Saved {res['count']} moments to my captures folder."
