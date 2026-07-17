"""
vision_module.py — Stack-Chan-only vision.

Phase 2: frames come from Dio's built-in CoreS3 GC0308 camera, never a local
webcam. Flow: the server asks Dio to capture (HTTP to her LAN IP); Dio pauses
her face, grabs a JPEG, and POSTs it to /vision/frame; the server analyses it
with LLaVA. There is NO OBSBOT / /dev/video fallback — if Dio is offline, vision
reports offline. "Stack-Chan only" means only.

Every captured frame lands in ~/ph3b3_data/captures — the one and only photo
store. Prompt-only rule (Phase 1) holds: `look` is on-demand; the ghost-hunt
monitoring path (set_baseline / check_anomaly / start_monitoring) is gated to an
active investigation by the server dispatch.
"""
import base64
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("ph3b3.vision")

OLLAMA_API_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/generate"
VISION_MODEL   = os.getenv("PH3B3_VISION_MODEL", "llava")
CAPTURE_DIR    = Path.home() / "ph3b3_data" / "captures"   # the ONLY photo store, ever

# Dio's on-device HTTP camera control (served by the CoreS3 firmware, Phase-2 fw).
DIO_CAM_PORT    = int(os.getenv("PH3B3_DIO_CAM_PORT", "8080"))
CAPTURE_TIMEOUT = float(os.getenv("PH3B3_CAPTURE_TIMEOUT", "12"))  # s to await a frame

ANALYSIS_PROMPT = (
    "You are Ph3b3, seeing through Dio's camera right now. "
    "Describe what you observe — people, objects, hardware, anything unusual. "
    "Be direct and precise. Note anything that seems out of place."
)

OFFLINE_MSG = ("[Dio's camera is offline — Stack-Chan is not reachable, so I can't see right "
               "now. I don't fall back to any other camera.]")


class VisionModule:
    def __init__(self, memory_module=None):
        self.memory       = memory_module
        self.dio_host     = None          # Dio's LAN IP, learned from her inbound requests
        self._latest_jpeg = None          # bytes of the most recent frame Dio POSTed
        self._latest_ts   = 0.0
        self._frame_event = threading.Event()
        self.baseline_jpeg = None         # baseline frame for ghost-hunt anomaly checks
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Vision module ready — Stack-Chan only (Dio CoreS3 GC0308 camera)")

    # ── device address (set by the server when Dio calls in) ──────────────────
    def set_dio_host(self, host: str) -> None:
        if host and host != self.dio_host:
            self.dio_host = host
            log.info(f"Dio camera host → {host}")

    # ── inbound frame from Dio (POST /vision/frame) ───────────────────────────
    def receive_frame(self, jpeg: bytes) -> str:
        """Persist + hold a JPEG Dio POSTed. Every capture lands in CAPTURE_DIR."""
        if not jpeg:
            return "empty frame"
        self._latest_jpeg = jpeg
        self._latest_ts   = time.time()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = CAPTURE_DIR / f"capture_{ts}.jpg"
        path.write_bytes(jpeg)
        self._frame_event.set()
        return path.name

    # ── ask Dio to capture, then wait for the frame to arrive ─────────────────
    def _request_and_wait(self):
        """Trigger a capture on Dio and block until a NEW frame lands (or timeout).
        Returns the JPEG bytes, or None if Dio is unreachable / no frame arrives."""
        if not self.dio_host:
            return None
        self._frame_event.clear()
        prev_ts = self._latest_ts
        try:
            requests.post(f"http://{self.dio_host}:{DIO_CAM_PORT}/snapshot", timeout=5)
        except Exception as e:
            log.warning(f"Dio capture request failed ({self.dio_host}): {e}")
            return None
        deadline = time.time() + CAPTURE_TIMEOUT
        while time.time() < deadline:
            if self._frame_event.wait(0.25) and self._latest_ts > prev_ts:
                return self._latest_jpeg
        log.warning("Dio capture: no frame arrived before timeout")
        return None

    # ── prompt-only look ──────────────────────────────────────────────────────
    def look(self, prompt=None):
        jpeg = self._request_and_wait()
        if jpeg is None:
            return OFFLINE_MSG
        return self._analyze(jpeg, prompt or ANALYSIS_PROMPT)

    # ── timed capture (evening capture): pull + persist a frame, no analysis ──
    def capture(self) -> bool:
        """Pull one frame from Dio and persist it to CAPTURE_DIR (no LLaVA).
        Returns True if a frame landed, False if Dio is offline / timed out.
        _request_and_wait already saves the frame via receive_frame."""
        return self._request_and_wait() is not None

    # ── ghost-hunt: baseline / anomaly (gated to an investigation in dispatch) ─
    def set_baseline(self):
        jpeg = self._request_and_wait()
        if jpeg is None:
            return OFFLINE_MSG
        self.baseline_jpeg = jpeg
        return f"Baseline set at {datetime.now():%H:%M:%S}. I know what normal looks like now."

    def check_anomaly(self):
        if self.baseline_jpeg is None:
            return "No baseline set. Tell me to set a baseline first."
        jpeg = self._request_and_wait()
        if jpeg is None:
            return OFFLINE_MSG
        analysis = self._analyze(
            jpeg,
            "This is a live frame from a ghost-hunt camera whose scene was empty/normal at "
            "baseline. Report ONLY what is new, moved, or unusual — if nothing stands out, "
            "say so plainly."
        )
        if self.memory:
            self.memory.log_anomaly(description=analysis[:200], source="camera")
        return analysis

    # ── monitor mode: Dio detects on-device and posts on motion ───────────────
    def start_monitoring(self, interval_seconds=30):
        # interval kept for signature compatibility; detection is on-device (motion),
        # not a fixed timer. Server just flips Dio into monitor mode.
        if not self.dio_host:
            return OFFLINE_MSG
        try:
            requests.post(f"http://{self.dio_host}:{DIO_CAM_PORT}/monitor/start", timeout=5)
            return "Monitor mode on — Dio will capture on motion for this investigation."
        except Exception as e:
            return f"Could not start Dio monitor mode: {e}"

    def stop_monitoring(self):
        if self.dio_host:
            try:
                requests.post(f"http://{self.dio_host}:{DIO_CAM_PORT}/monitor/stop", timeout=5)
            except Exception:
                pass
        return "Monitoring stopped."

    # ── LLaVA ─────────────────────────────────────────────────────────────────
    def _analyze(self, jpeg: bytes, prompt: str) -> str:
        try:
            payload = {
                "model":  VISION_MODEL,
                "prompt": prompt,
                "images": [base64.b64encode(jpeg).decode("ascii")],
                "stream": False,
            }
            r = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
            if r.status_code == 200:
                return r.json().get("response", "No response from vision model.")
            return f"Vision model error: {r.status_code}"
        except Exception as e:
            return f"Vision error: {e}"
