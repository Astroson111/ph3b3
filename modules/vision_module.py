import cv2
import base64
import os
import subprocess
import time
import logging
import threading
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.vision")

OLLAMA_API_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/generate"
VISION_MODEL   = os.getenv("PH3B3_VISION_MODEL", "llava")
CAPTURE_DIR    = Path.home() / "ph3b3_data" / "captures"
ANOMALY_DIR    = Path.home() / "ph3b3_data" / "anomalies"

# Camera-capture retention: saved frames/anomaly snapshots older than this are
# deleted on capture and at startup. Room imagery, so the privacy default is 7
# days. Set PH3B3_CAPTURE_TTL_DAYS=0 to keep captures forever.
CAPTURE_TTL_DAYS = int(os.getenv("PH3B3_CAPTURE_TTL_DAYS", "7"))

ANALYSIS_PROMPT = (
    "You are Ph3b3. This is what your camera sees right now. "
    "Describe what you observe — people, objects, hardware, anything unusual. "
    "Be direct and precise. Note anything that seems out of place. "
    "This is your environment. You are watching it."
)

# ── UVC PTZ constants (OBSBOT Tiny 4K via v4l2) ──────────────────────────────
PAN_MIN,  PAN_MAX  = -36000, 36000
TILT_MIN, TILT_MAX = -36000, 36000
ZOOM_MIN, ZOOM_MAX = 10, 19
PAN_STEP  = 3600   # one click ≈ 18°
TILT_STEP = 3600


class VisionModule:
    def __init__(self, memory_module=None, camera_device: int = 0):
        """
        camera_device: v4l2 device index.
            0 = primary camera (/dev/video0)
            1+ = secondary cameras as they are added
        """
        self.memory        = memory_module
        self.camera_device = camera_device
        self.device_path   = f"/dev/video{camera_device}"
        self.baseline      = None
        self.monitoring    = False
        self._monitor_thread = None
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        ANOMALY_DIR.mkdir(parents=True, exist_ok=True)
        self._prune_captures()
        log.info(f"Vision module ready — device {self.device_path} — vision model: {VISION_MODEL}")

    def _prune_captures(self) -> None:
        """Delete saved frames/anomaly snapshots older than CAPTURE_TTL_DAYS."""
        if CAPTURE_TTL_DAYS <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=CAPTURE_TTL_DAYS)).timestamp()
        for d, pattern in ((CAPTURE_DIR, "capture_*.jpg"), (ANOMALY_DIR, "anomaly_*.jpg")):
            if not d.exists():
                continue
            for f in d.glob(pattern):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError as e:
                    log.warning(f"Capture prune failed for {f.name}: {e}")

    # ── Core capture / analysis ───────────────────────────────────────────────

    def look(self, prompt=None):
        frame = self._capture_frame()
        if frame is None:
            return f"[hardware error: could not read a frame from {self.device_path} — device may be busy or disconnected. Try again.]"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = CAPTURE_DIR / f"capture_{ts}.jpg"
        cv2.imwrite(str(filepath), frame)
        self._prune_captures()
        return self._analyze_frame(frame, prompt or ANALYSIS_PROMPT)

    def set_baseline(self):
        frame = self._capture_frame()
        if frame is None:
            return "Cannot set baseline — camera unavailable."
        self.baseline = frame
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"Baseline set at {ts}. I know what normal looks like now."

    def check_anomaly(self):
        if self.baseline is None:
            return "No baseline set. Tell me to set a baseline first."
        current = self._capture_frame()
        if current is None:
            return "Camera unavailable."
        score = self._motion_score(self.baseline, current)
        if score < 15.0:
            return "Room is unchanged. Nothing to report."
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        savepath = ANOMALY_DIR / f"anomaly_{ts}.jpg"
        cv2.imwrite(str(savepath), current)
        self._prune_captures()
        analysis = self._analyze_frame(current, ANALYSIS_PROMPT)
        if self.memory:
            self.memory.log_anomaly(
                description=f"Motion score {score:.0f}: {analysis[:200]}",
                source="camera"
            )
        return f"I see something. Motion score: {score:.0f}\n\n{analysis}"

    def start_monitoring(self, interval_seconds=30):
        if self.monitoring:
            return "Already monitoring."
        if self.baseline is None:
            self.set_baseline()
        self.monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self._monitor_thread.start()
        return f"Monitoring started. Checking every {interval_seconds} seconds."

    def stop_monitoring(self):
        self.monitoring = False
        return "Monitoring stopped."

    # ── UVC PTZ (OBSBOT Tiny 4K — only valid on camera_device=0) ─────────────

    def look_left(self, steps: int = 1) -> str:
        cur = self._get_ctrl("pan_absolute")
        new = max(PAN_MIN, cur - PAN_STEP * steps)
        return self._set_ctrl("pan_absolute", new, f"Pan left → {new}")

    def look_right(self, steps: int = 1) -> str:
        cur = self._get_ctrl("pan_absolute")
        new = min(PAN_MAX, cur + PAN_STEP * steps)
        return self._set_ctrl("pan_absolute", new, f"Pan right → {new}")

    def look_up(self, steps: int = 1) -> str:
        cur = self._get_ctrl("tilt_absolute")
        new = min(TILT_MAX, cur + TILT_STEP * steps)
        return self._set_ctrl("tilt_absolute", new, f"Tilt up → {new}")

    def look_down(self, steps: int = 1) -> str:
        cur = self._get_ctrl("tilt_absolute")
        new = max(TILT_MIN, cur - TILT_STEP * steps)
        return self._set_ctrl("tilt_absolute", new, f"Tilt down → {new}")

    def zoom_in(self, steps: int = 1) -> str:
        cur = self._get_ctrl("zoom_absolute")
        new = min(ZOOM_MAX, cur + steps)
        return self._set_ctrl("zoom_absolute", new, f"Zoom in → {new}/{ZOOM_MAX}")

    def zoom_out(self, steps: int = 1) -> str:
        cur = self._get_ctrl("zoom_absolute")
        new = max(ZOOM_MIN, cur - steps)
        return self._set_ctrl("zoom_absolute", new, f"Zoom out → {new}/{ZOOM_MAX}")

    def center(self) -> str:
        results = []
        for ctrl, val in [("pan_absolute", 0), ("tilt_absolute", 0), ("zoom_absolute", ZOOM_MIN)]:
            ok = self._run_v4l2("--set-ctrl", f"{ctrl}={val}")
            results.append("✓" if ok else "✗")
        return f"Camera centered — pan 0, tilt 0, zoom reset [{' '.join(results)}]"

    def ptz_status(self) -> str:
        pan  = self._get_ctrl("pan_absolute")
        tilt = self._get_ctrl("tilt_absolute")
        zoom = self._get_ctrl("zoom_absolute")
        return (f"OBSBOT PTZ — pan {pan} ({pan//3600:+d} steps), "
                f"tilt {tilt} ({tilt//3600:+d} steps), "
                f"zoom {zoom}/{ZOOM_MAX}")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _capture_frame(self):
        try:
            cam = cv2.VideoCapture(self.camera_device, cv2.CAP_V4L2)
            cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if not cam.isOpened():
                log.warning(f"Cannot open {self.device_path}")
                return None
            for _ in range(5):
                cam.read()
            ret, frame = cam.read()
            cam.release()
            return frame if ret else None
        except Exception as e:
            log.error(f"Camera error ({self.device_path}): {e}")
            return None

    def _frame_to_base64(self, frame):
        _, buffer = cv2.imencode('.jpg', frame)
        return base64.b64encode(buffer).decode('utf-8')

    def _motion_score(self, baseline, current):
        b_gray = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
        c_gray = cv2.cvtColor(current,  cv2.COLOR_BGR2GRAY)
        diff   = cv2.absdiff(b_gray, c_gray)
        return float(np.mean(diff))

    def _analyze_frame(self, frame, prompt):
        try:
            import requests
            payload = {
                "model":  VISION_MODEL,
                "prompt": prompt,
                "images": [self._frame_to_base64(frame)],
                "stream": False
            }
            r = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
            if r.status_code == 200:
                return r.json().get("response", "No response from vision model.")
            return f"Vision model error: {r.status_code}"
        except Exception as e:
            return f"Vision error: {e}"

    def _monitor_loop(self, interval):
        while self.monitoring:
            try:
                result = self.check_anomaly()
                if "Nothing to report" not in result:
                    log.info(f"Anomaly: {result[:100]}")
            except Exception as e:
                log.error(f"Monitor error: {e}")
            time.sleep(interval)

    def _run_v4l2(self, *args) -> bool:
        """Run v4l2-ctl on self.device_path. Returns True on success."""
        try:
            subprocess.run(
                ["v4l2-ctl", "-d", self.device_path, *args],
                capture_output=True, timeout=4, check=True
            )
            return True
        except Exception as e:
            log.error(f"v4l2-ctl error: {e}")
            return False

    def _get_ctrl(self, ctrl: str) -> int:
        try:
            r = subprocess.run(
                ["v4l2-ctl", "-d", self.device_path, "--get-ctrl", ctrl],
                capture_output=True, text=True, timeout=4
            )
            return int(r.stdout.strip().split(":")[-1].strip())
        except Exception:
            return 0

    def _set_ctrl(self, ctrl: str, value: int, msg: str) -> str:
        ok = self._run_v4l2("--set-ctrl", f"{ctrl}={value}")
        return msg if ok else f"PTZ error — could not set {ctrl}={value}"
