import base64
import cv2
import logging
import os
import requests
from pathlib import Path

log = logging.getLogger("ph3b3.vision_stream")

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://localhost:11434")
VISION_MODEL = os.getenv("PH3B3_VISION_MODEL", "llava")


class VisionStreamModule:
    """Single-shot visual analysis via LLaVA.
    Camera is opened on demand and released immediately — no passive monitoring.
    """

    def __init__(self):
        log.info(f"VisionStream ready — model: {VISION_MODEL}")

    def analyze(self, prompt: str) -> str:
        """Capture one frame, send to LLaVA with `prompt`, return analysis text."""
        if not prompt or not prompt.strip():
            prompt = "Describe what you see in this image."
        frame = self._capture_frame()
        if frame is None:
            return "Camera unavailable — cannot capture frame for analysis."
        _, buf = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buf).decode("utf-8")
        try:
            payload = {
                "model": VISION_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [b64],
                    }
                ],
                "stream": False,
            }
            r = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json=payload,
                timeout=60,
            )
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "No response from vision model.")
        except Exception as e:
            log.error(f"Vision analyze error: {e}")
            return f"Vision error: {e}"

    def _capture_frame(self):
        """Open camera, grab one frame, close camera immediately."""
        try:
            cam = cv2.VideoCapture(0, cv2.CAP_V4L2)
            cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if not cam.isOpened():
                return None
            for _ in range(5):   # warm up sensor
                cam.read()
            ret, frame = cam.read()
            cam.release()
            return frame if ret else None
        except Exception as e:
            log.error(f"Camera capture error: {e}")
            return None
