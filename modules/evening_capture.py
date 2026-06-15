#!/usr/bin/env python3
"""
evening_capture.py  —  a Ph3b3 way to keep the night.

Snaps a photo on an interval through the evening and logs every frame to your
Desktop. Built to run two ways:

  1) Right now, standalone, no wiring needed:
       python capture_evening.py --label for_<friend> --interval 120 --source opencv:0

  2) As a Ph3b3 tool handler Hermes3 can call by voice (see the bottom of the
     file) so Ph3b3 owns the task and announces it through Alba.

Camera source is pluggable — point it at whatever gives the nicest frame:
  opencv:0               the 4K AI Webcam on /dev/video0 (confirmed working)
  opencv:0@3840x2160     same, pinned to 4K MJPG (default for server handlers)
  http://IP/snap         a JPEG endpoint on the CoreS3 itself

Files land in:  ~/Desktop/<label>_<YYYY-MM-DD>/NNNN_HHMMSS.jpg
A single bad frame never kills the session — it's logged and skipped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")  # quiet the v4l/ffmpeg chatter


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "evening"


# ---- frame sources -------------------------------------------------------

class FrameSource:
    def grab(self) -> Optional[bytes]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class HttpSource(FrameSource):
    """GET a JPEG from a URL — e.g. an endpoint on the CoreS3."""
    def __init__(self, url: str, timeout: int = 10):
        import requests  # lazy: only needed for this source
        self._requests = requests
        self.url = url
        self.timeout = timeout

    def grab(self) -> Optional[bytes]:
        r = self._requests.get(self.url, timeout=self.timeout)
        r.raise_for_status()
        return r.content or None


class OpenCVSource(FrameSource):
    """Capture from a local camera index via OpenCV (USB cam / capture card).

    Set an explicit resolution and MJPG format or you'll get a low-res frame.
    Spec supports opencv:N@WxH — verified: 4K AI Webcam supports 3840x2160 MJPG.
    """
    def __init__(self, index: int, width: int | None = None,
                 height: int | None = None, fourcc: str = "MJPG"):
        import cv2  # lazy: only needed for this source
        self._cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera index {index} wouldn't open")
        if fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(3):          # warm up so the card settles before first save
            self.cap.read()

    def grab(self) -> Optional[bytes]:
        ok, frame = self.cap.read()
        if not ok:
            return None
        ok, buf = self._cv2.imencode(".jpg", frame)
        return buf.tobytes() if ok else None

    def close(self) -> None:
        try:
            self.cap.release()
        except Exception:
            pass


def _parse_opencv(spec: str) -> tuple[int, Optional[int], Optional[int]]:
    """opencv:0  ->  (0, None, None)   |   opencv:0@1920x1080  ->  (0, 1920, 1080)"""
    body = spec.split(":", 1)[1]
    if "@" in body:
        idx_s, res = body.split("@", 1)
        w, h = (int(x) for x in res.lower().split("x", 1))
        return int(idx_s), w, h
    return int(body), None, None


def make_source(spec: str) -> FrameSource:
    if spec.startswith("opencv:"):
        idx, w, h = _parse_opencv(spec)
        return OpenCVSource(idx, w, h)
    if spec.startswith(("http://", "https://")):
        return HttpSource(spec)
    raise ValueError(f"unknown source '{spec}' — use opencv:N[@WxH] or http(s)://...")


def probe(max_index: int = 10) -> None:
    """Audit local video devices: name, whether OpenCV opens them, resolution,
    and whether they return a live (non-black) frame. Flags the 4K device."""
    try:
        import cv2
    except ImportError:
        print("OpenCV isn't installed yet:\n  pip install opencv-python-headless --break-system-packages")
        return
    import glob

    devs = sorted(glob.glob("/dev/video*"),
                  key=lambda p: int(re.sub(r"\D", "", p) or 0))
    indices = [int(re.search(r"(\d+)$", d).group(1)) for d in devs if re.search(r"(\d+)$", d)]
    if not indices:
        indices = list(range(max_index))

    print(f"{'idx':<5}{'name':<26}{'opens':<7}{'resolution':<13}{'bright':<8}note")
    print("-" * 70)
    best = None
    for i in indices:
        try:
            name = open(f"/sys/class/video4linux/video{i}/name").read().strip()[:24]
        except OSError:
            name = "?"
        cap = cv2.VideoCapture(i)
        opened = cap.isOpened()
        res, bright, note = "-", None, ""
        if opened:
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                res = f"{w}x{h}"
                bright = round(float(frame.mean()), 1)
                if w >= 3840:
                    note = "4K"
                elif w >= 1920:
                    note = "hi-res"
                if bright <= 5:
                    note = (note + " (black)").strip()
                elif best is None:
                    best = i
        cap.release()
        print(f"{i:<5}{name:<26}{'yes' if opened else 'no':<7}"
              f"{res:<13}{(str(bright) if bright is not None else '-'):<8}{note}")

    print("-" * 70)
    if best is not None:
        print(f"Recommend:  --source opencv:{best}")
    else:
        print("No device returned a live frame. Close anything else using it and re-probe.")


# ---- the capture session -------------------------------------------------

class EveningCapture:
    def __init__(
        self,
        label: str = "evening",
        interval: float = 120.0,
        source: str = "opencv:0@3840x2160",
        root: Optional[str] = None,
        announce: Optional[Callable[[str], None]] = None,
    ):
        self.label = label
        self.interval = float(interval)
        self.source_spec = source
        self.announce = announce
        base = Path(root).expanduser() if root else Path.home() / "Desktop"
        self.dir = base / f"{_safe(label)}_{dt.date.today().isoformat()}"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._src: Optional[FrameSource] = None
        self.count = 0
        self.errors = 0

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _tick(self) -> None:
        try:
            data = self._src.grab()
            if not data:
                self.errors += 1
                return
            self.count += 1
            ts = dt.datetime.now().strftime("%H%M%S")
            (self.dir / f"{self.count:04d}_{ts}.jpg").write_bytes(data)
        except Exception as e:
            self.errors += 1
            print(f"[capture] frame skipped: {e}")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._tick()
                self._stop.wait(self.interval)
        finally:
            if self._src:
                self._src.close()

    def start(self) -> dict:
        if self.is_running():
            return {"ok": False, "msg": "already capturing"}
        self._src = make_source(self.source_spec)   # raises early if camera is bad
        self.dir.mkdir(parents=True, exist_ok=True)  # only after the camera opens
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        msg = f"Capturing the evening. Saving to {self.dir}"
        print("[capture]", msg)
        if self.announce:
            self.announce("Capturing the evening.")
        return {"ok": True, "dir": str(self.dir)}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
        msg = f"Saved {self.count} moments to {self.dir}"
        print("[capture]", msg)
        if self.announce:
            self.announce(f"Stopped. Saved {self.count} moments to your desktop.")
        return {"count": self.count, "errors": self.errors, "dir": str(self.dir)}


# ---- Ph3b3 tool handlers -------------------------------------------------
# One session shared across tool calls so "start" and "stop" talk to the same
# thing. Wire `alba_say` in server.py after import:
#   import evening_capture as _ec_mod
#   _ec_mod.alba_say = lambda t: tts.speak(t, blocking=False)

_session: Optional[EveningCapture] = None


def alba_say(text: str) -> None:
    pass  # no-op placeholder; server.py overwrites this after import


def tool_start_evening_capture(label: str = "evening", interval: float = 120,
                               source: str = "opencv:0@3840x2160") -> str:
    """Ph3b3 tool: begin logging the evening to the desktop."""
    global _session
    if _session and _session.is_running():
        return "I'm already capturing the evening."
    try:
        _session = EveningCapture(label, interval, source, announce=alba_say)
        _session.start()
    except Exception as e:
        _session = None
        return f"I couldn't start the camera: {e}"
    return f"Capturing the evening every {float(interval):g} seconds, saving to your desktop."


def tool_stop_evening_capture() -> str:
    """Ph3b3 tool: stop logging and report the count."""
    global _session
    if not _session:
        return "Nothing is capturing right now."
    res = _session.stop()
    _session = None
    return f"Saved {res['count']} moments to {res['dir']}."


# ---- standalone CLI ------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Ph3b3 evening capture")
    ap.add_argument("--probe", action="store_true", help="list cameras and exit")
    ap.add_argument("--label", default="evening", help="folder label")
    ap.add_argument("--interval", type=float, default=120, help="seconds between shots")
    ap.add_argument("--source", default="opencv:0@3840x2160",
                    help="opencv:N[@WxH] or http(s)://IP/snap")
    ap.add_argument("--root", default=None, help="base dir (default: ~/Desktop)")
    args = ap.parse_args()

    if args.probe:
        probe()
        return

    cap = EveningCapture(args.label, args.interval, args.source, root=args.root)
    try:
        cap.start()
    except Exception as e:
        print(f"Couldn't start: {e}")
        return
    print(f"Capturing every {args.interval:g}s. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
    res = cap.stop()
    print(f"Done — {res['count']} photos ({res['errors']} skipped) in {res['dir']}")


if __name__ == "__main__":
    main()
