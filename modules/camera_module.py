import cv2
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("ph3b3.camera")

PHOTOS_DIR = Path.home() / "ph3b3_data" / "photos"
VIDEOS_DIR = Path.home() / "ph3b3_data" / "videos"

# Camera-capture retention: photos/videos older than this are deleted on capture
# and at startup. These are room imagery, so the privacy default is 7 days.
# Set PH3B3_CAPTURE_TTL_DAYS=0 to keep captures forever.
CAPTURE_TTL_DAYS = int(os.getenv("PH3B3_CAPTURE_TTL_DAYS", "7"))


class CameraModule:
    def __init__(self, camera_device: int = 0):
        self.camera_device = camera_device
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        self._prune_captures()
        log.info(f"Camera module ready — device /dev/video{camera_device}")

    def _prune_captures(self) -> None:
        """Delete photos/videos older than CAPTURE_TTL_DAYS (privacy retention)."""
        if CAPTURE_TTL_DAYS <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=CAPTURE_TTL_DAYS)).timestamp()
        for d, pattern in ((PHOTOS_DIR, "photo_*.jpg"), (VIDEOS_DIR, "video_*.mp4")):
            if not d.exists():
                continue
            for f in d.glob(pattern):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError as e:
                    log.warning(f"Capture prune failed for {f.name}: {e}")

    def take_photo(self) -> str:
        """Open camera, capture one frame, save timestamped JPG, close camera."""
        cam = cv2.VideoCapture(self.camera_device, cv2.CAP_V4L2)
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not cam.isOpened():
            return "Camera unavailable."
        try:
            for _ in range(5):   # warm up sensor
                cam.read()
            ret, frame = cam.read()
            if not ret or frame is None:
                return "Failed to capture frame."
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = PHOTOS_DIR / f"photo_{ts}.jpg"
            cv2.imwrite(str(path), frame)
            self._prune_captures()
            log.info(f"Photo saved: {path}")
            return f"Photo saved: {path}"
        except Exception as e:
            log.error(f"take_photo error: {e}")
            return f"Camera error: {e}"
        finally:
            cam.release()

    def record_video(self, seconds: int = 10) -> str:
        """Open camera, record for `seconds`, save timestamped MP4, close camera."""
        seconds = max(1, min(int(seconds), 300))   # clamp 1–300 s
        cam = cv2.VideoCapture(self.camera_device, cv2.CAP_V4L2)
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        if not cam.isOpened():
            return "Camera unavailable."
        try:
            width  = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps    = cam.get(cv2.CAP_PROP_FPS) or 30.0

            ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
            path   = VIDEOS_DIR / f"video_{ts}.mp4"
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))

            deadline = time.time() + seconds
            frames   = 0
            while time.time() < deadline:
                ret, frame = cam.read()
                if not ret:
                    break
                writer.write(frame)
                frames += 1

            writer.release()
            self._prune_captures()
            log.info(f"Video saved: {path} ({frames} frames, {seconds}s)")
            return f"Video saved: {path} ({frames} frames, {seconds}s)"
        except Exception as e:
            log.error(f"record_video error: {e}")
            return f"Camera error: {e}"
        finally:
            cam.release()
