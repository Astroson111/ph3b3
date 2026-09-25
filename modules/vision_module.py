"""
vision_module.py — Stack-Chan-primary vision, with an explicit local-camera fallback.

Frames come from Dio's built-in CoreS3 GC0308 camera FIRST: the server asks Dio
to capture (HTTP to her LAN IP); Dio pauses her face, grabs a JPEG, and POSTs it
to /vision/frame; the server analyses it with LLaVA.

Fallback (Phase 6.75 — supersedes the earlier "Stack-Chan only" rule): if Dio is
unreachable / doesn't return a frame within DIO_WAIT seconds, vision falls back
to ANY local PC camera (generic V4L2 via OpenCV — enumerate /dev/video*, use the
first that delivers a frame; force one with PH3B3_FALLBACK_CAM=<index>). Only if
BOTH sources fail does it report offline, naming both failures. The fallback is
never silent: every result string states which eyes were used, and frames are
named by source (dio_*.jpg vs webcam_*.jpg). Kill-switch: PH3B3_VISION_FALLBACK=0
restores strict Stack-Chan-only (Dio offline → offline, no webcam attempt).

The fallback changes WHICH camera, never WHEN vision may run: prompt-only `look`
(Phase 1) still holds. The PC webcam is PROMPT-ONLY (2026-08-31): the timed paths
(capture / capture_and_describe, used by evening capture) pass allow_local=False
and will use Dio or nothing — a timer is not a prompt, and that camera faces the
room the user is sitting in. and the ghost-hunt monitoring path (set_baseline /
check_anomaly / start_monitoring) is still gated to an active investigation by the
server dispatch. Every captured frame — Dio or webcam — lands in
~/ph3b3_data/captures, the one and only photo store (the Desktop "Ph3b3_Captures"
shortcut just points here).
"""
import base64
import glob
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("ph3b3.vision")

OLLAMA_API_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434") + "/api/generate"
VISION_MODEL   = os.getenv("PH3B3_VISION_MODEL", "llava")
CAPTURE_DIR    = Path.home() / "ph3b3_data" / "captures"   # the ONLY photo store, ever
# ^ that comment is aspirational: the directory also holds 889 stackchan .wav,
#   676 .txt, 374 iris .wav and 285 .discarded. Retention owns IMAGE PREFIXES
#   only and refuses anything else out loud — see modules/retention.py.
import retention                                  # one authority for how long frames are kept

# Dio's on-device HTTP camera control (served by the CoreS3 firmware, Phase-2 fw).
DIO_CAM_PORT = int(os.getenv("PH3B3_DIO_CAM_PORT", "8080"))
DIO_WAIT     = float(os.getenv("PH3B3_DIO_WAIT", "3"))   # s to wait for Dio before falling back
# Native photo loop (PUSH-primary): Dio captures on-device and POSTs the frame to
# /vision/frame right before the describe call. If a Dio push landed within this
# window, _grab_frame uses it directly and never pulls :8080 — the pull path is
# retired as the primary route (kept only as a fallback for the legacy flow).
PUSH_FRESH_S = float(os.getenv("PH3B3_PUSH_FRESH_S", "8"))
# dio_host verification backoff: every Dio POST (heartbeat/transcribe/frame) whose
# source IP isn't yet the adopted dio_host triggers a :8080/cam/status probe. When
# that probe keeps failing (e.g. her :8080 server is down but she's pushing frames
# fine), it re-probes AND re-logs on every request — a flood. After a failed verify
# for a host, skip re-probing/re-logging it for this window.
DIO_VERIFY_COOLDOWN = float(os.getenv("PH3B3_DIO_VERIFY_COOLDOWN", "300"))


def _audit(event: str, ok: bool, source: str = "-", reason: str = "-",
           nbytes: int = 0) -> None:
    """One greppable line per vision EVENT — never the frame, never the description.

    The no-tracking rule stands: this records THAT a capture was attempted and how
    it ended, not what was seen. It exists so "sight-claims vs captures returned"
    is a countable number instead of a reconstruction from the captures folder —
    which is how the 2026-08-31 hallucination had to be diagnosed after the fact.

        grep '[vision-audit]' <log> | grep 'ok=True' | wc -l
    """
    log.info("[vision-audit] event=%s ok=%s source=%s bytes=%d reason=%s",
             event, ok, source, nbytes, reason)


def _truthy(v) -> bool:
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")


ANALYSIS_PROMPT = (
    # NO persona framing here on purpose. "You are Ph3b3, looking at..." made the
    # VLM answer *as a character* — 1 in 5 runs it asked a question back instead of
    # describing ("Can you describe your current visibility?"), which reaches the
    # user as a non-answer to "can you see me". Plain instruction: 0/5 failures on
    # the same frame. Phoebe supplies the voice when she relays it; the describer
    # only has to be accurate.
    "Describe what is visible in this photograph: people, objects, the room. "
    "Be direct and precise, and note anything that seems out of place. "
    "If something is unclear, partly hidden, or you are unsure what an object is, say so "
    "('looks like', 'possibly', 'I can't tell') rather than guessing a specific object — "
    "a confident wrong answer is worse than an uncertain right one. "
    "If the image is dark, blurred or empty, say that plainly."
)

# Shorter prompt for the evening-capture narration: each frame is spoken aloud
# on a timer, so keep it to a sentence or two rather than a full report.
NARRATION_PROMPT = (
    # Same reason as ANALYSIS_PROMPT: instruction, not persona.
    "In ONE or two short sentences, say what is visible in this photograph — people, "
    "objects, what is happening. Plain and brief. If the image is dark or empty, say "
    "that plainly — do not invent detail."
)

# Every result names the source so the LLM tells the user which eyes it used.
# NOTE: phrased as SUCCESS and appended AFTER the description — an earlier version
# that led with "(... Stack-Chan offline)" made the weak local model latch onto
# "offline" and wrongly report it couldn't see. These read as "vision worked".
_SRC_TAG = {
    "stackchan": "\n\n[Vision source: Stack-Chan's own camera. You DID see this — relay it.]",
    "webcam":    ("\n\n[Vision source: the PC webcam fallback (Stack-Chan wasn't reachable, so "
                  "the computer's camera was used). Vision SUCCEEDED — relay the description "
                  "above and mention you used the backup PC camera.]"),
}


class VisionModelDown(RuntimeError):
    """The frame WAS captured but the describer failed. Never a description.

    Split out from a plain error string so a model failure can never be relayed as
    an observation — and so the audit counts it as a turn with NO description,
    which is what "sight-claims == captures returned" actually means.
    """


class VisionModule:
    def __init__(self, memory_module=None):
        self.memory       = memory_module
        self.dio_host     = None          # Dio's LAN IP, learned (and verified) from her calls
        self._latest_jpeg = None          # bytes of the most recent frame Dio POSTed
        self._latest_ts   = 0.0
        self._latest_src  = None          # 'stackchan' | 'webcam' — origin of _latest_jpeg
        self._dio_verify_fail = {}        # host -> last failed-verify ts (dio_host probe backoff)
        self._frame_event = threading.Event()
        self._cam_lock    = threading.Lock()   # serialize webcam grabs (V4L2 is single-open)
        self.baseline_jpeg = None         # baseline frame for ghost-hunt anomaly checks
        # Read tunables at construction so a .env change + restart takes effect.
        self.fallback_enabled = _truthy(os.getenv("PH3B3_VISION_FALLBACK", "1"))
        self.fallback_cam     = os.getenv("PH3B3_FALLBACK_CAM", "").strip()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        mode = ("Stack-Chan primary + local-camera fallback" if self.fallback_enabled
                else "Stack-Chan only (fallback disabled)")
        log.info(f"Vision module ready — {mode}")

    # ── device address (verified before we trust it — Part C) ─────────────────
    def try_set_dio_host(self, host: str) -> bool:
        """Adopt `host` as Dio's camera IP ONLY if it actually serves her camera
        control endpoint (:{DIO_CAM_PORT}/cam/status). All devices share one
        Basic-auth cred, so a spoofed X-Ph3b3-Device header from any authed LAN
        client must not be able to hijack dio_host. A verification ping needs no
        firmware change (a per-device token would be the stronger future fix)."""
        if not host or host == self.dio_host:
            return False
        # Backoff: a host that recently failed verification isn't re-probed or
        # re-logged until the cooldown passes — this is what silences the flood.
        now = time.time()
        if now - self._dio_verify_fail.get(host, 0.0) < DIO_VERIFY_COOLDOWN:
            return False
        try:
            r = requests.get(f"http://{host}:{DIO_CAM_PORT}/cam/status", timeout=2)
            ok = (r.status_code == 200 and "camera" in r.text)
        except Exception:
            ok = False
        if ok:
            self.dio_host = host
            self._dio_verify_fail.pop(host, None)
            log.info(f"Dio camera host → {host} (verified via /cam/status)")
            return True
        self._dio_verify_fail[host] = now
        # Logged at most once per cooldown window (not on every request). Not
        # necessarily a spoof: her push path is authenticated and works without
        # dio_host; this only gates the legacy :8080 pull/monitor fallback.
        log.warning(f"dio_host {host} unverified: no camera server at :{DIO_CAM_PORT} "
                    f"(legacy pull disabled for it; push path unaffected)")
        return False

    # ── inbound frame from Dio (POST /vision/frame) ───────────────────────────
    def receive_frame(self, jpeg: bytes, source: str = "dio") -> str:
        """Persist + hold a JPEG. Every capture lands in CAPTURE_DIR, named by
        source: dio_*.jpg (Stack-Chan) or webcam_*.jpg (local fallback)."""
        if not jpeg:
            return "empty frame"
        self._latest_jpeg = jpeg
        self._latest_ts   = time.time()
        self._latest_src  = "webcam" if source == "webcam" else "stackchan"
        prefix = "webcam" if source == "webcam" else "dio"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = CAPTURE_DIR / f"{prefix}_{ts}.jpg"
        # Registered with the retention authority: every path that lands a frame
        # sweeps, so a new writer cannot quietly opt out of the TTL. The June
        # guard was never merged and its glob would not have matched these names
        # anyway; this is the door being nailed to the same frame as the wall.
        try:
            retention.sweep()
        except Exception:                          # noqa: BLE001
            pass                                   # retention must never break a capture
        path.write_bytes(jpeg)
        self._frame_event.set()
        return path.name

    # ── source order: Stack-Chan first, then local webcam fallback ────────────
    def _grab_frame(self, allow_local: bool = True):
        """Return (jpeg_bytes, source) trying Dio first then a local camera.
        source is 'stackchan' | 'webcam' | None (both failed). BLOCKING — the
        caller must run this off the event loop (server dispatch uses to_thread).

        allow_local=False forbids the PC webcam for this grab. TIMED paths pass
        False: the PC camera points at the room the user is sitting in, and it may
        only be opened on a direct ask (Astro, 2026-08-31 — "only use camera when
        prompted"). A timer is not a prompt. Dio is a different matter — she is a
        robot the user placed deliberately, and timed capture through her stays."""
        # PUSH-primary: the native photo loop has Dio capture on-device and POST
        # the frame just before this call. If a fresh Dio push is already in hand,
        # use it directly and skip the :8080 pull entirely (pull is now fallback).
        if (self._latest_jpeg is not None and self._latest_src == "stackchan"
                and (time.time() - self._latest_ts) <= PUSH_FRESH_S):
            return self._latest_jpeg, "stackchan"
        jpeg = self._request_and_wait(DIO_WAIT)
        if jpeg is not None:
            return jpeg, "stackchan"
        if allow_local and self.fallback_enabled:
            jpeg = self._local_capture()
            if jpeg is not None:
                return jpeg, "webcam"
        return None, None

    # ── ask Dio to capture, then wait for the frame to arrive ─────────────────
    def _request_and_wait(self, timeout: float = DIO_WAIT):
        """Trigger a capture on Dio and block until a NEW frame lands (or timeout).
        Returns the JPEG bytes, or None if Dio is unreachable / no frame arrives."""
        if not self.dio_host:
            return None
        self._frame_event.clear()
        prev_ts = self._latest_ts
        try:
            requests.post(f"http://{self.dio_host}:{DIO_CAM_PORT}/snapshot",
                          timeout=min(timeout, 4))
        except Exception as e:
            log.warning(f"Dio capture request failed ({self.dio_host}): {e}")
            return None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._frame_event.wait(0.2) and self._latest_ts > prev_ts:
                return self._latest_jpeg
        log.warning("Dio capture: no frame arrived before timeout")
        return None

    # ── generic local-camera fallback (ANY PC webcam via V4L2) ────────────────
    def _local_capture(self):
        """Grab one JPEG from any local V4L2 camera. Generic: enumerate
        /dev/video*, use the first that opens and delivers a frame. No OBSBOT-
        specific code, no hardcoded index. Persists as webcam_*.jpg."""
        try:
            import cv2
        except ImportError:
            log.warning("Vision fallback: OpenCV (cv2) not installed — no local camera path")
            return None
        # Serialize: V4L2 devices are single-open, so two overlapping captures (e.g.
        # two chats, or a chat racing an Argus check) would make the second fail to
        # open and report the camera "unavailable" when it is merely busy.
        with self._cam_lock:
            return self._local_capture_locked(cv2)

    def _local_capture_locked(self, cv2):
        for idx in self._candidate_indices():
            cap = None
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
                if not cap.isOpened():
                    continue
                # Most UVC webcams only stream once given a concrete format; without
                # one the driver select()-times-out (~10s/read). MJPG at 1280x720 is
                # near-universal and generic (not device-specific), and small enough
                # for LLaVA.
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                # Warm the camera up: a cold-(re)opened UVC webcam drops its first
                # several frames (MJPG format negotiation + auto-exposure settling),
                # so 3 reads was too few — the 2nd rapid capture came back empty and
                # reported "unavailable". Read a run of frames and keep the last
                # valid one (settled exposure). Only give up if NONE arrive.
                frame = None
                for _ in range(15):
                    ok, f = cap.read()
                    if ok and f is not None:
                        frame = f
                if frame is None:
                    continue
                ok, buf = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                jpeg = buf.tobytes()
                self.receive_frame(jpeg, source="webcam")
                log.info(f"Vision fallback: captured from local /dev/video{idx} (Stack-Chan offline)")
                return jpeg
            except Exception as e:
                log.warning(f"Vision fallback: /dev/video{idx} failed: {e}")
            finally:
                if cap is not None:
                    cap.release()
        log.warning("Vision fallback: no local camera delivered a frame")
        return None

    def _candidate_indices(self):
        """Video device indices to try: a forced one (PH3B3_FALLBACK_CAM), else
        every /dev/video* in numeric order."""
        if self.fallback_cam:
            try:
                return [int(self.fallback_cam)]
            except ValueError:
                log.warning(f"PH3B3_FALLBACK_CAM={self.fallback_cam!r} is not an int — auto-detecting")
        idxs = []
        for dev in sorted(glob.glob("/dev/video*"),
                          key=lambda p: int(re.sub(r"\D", "", p) or 0)):
            m = re.search(r"(\d+)$", dev)
            if m:
                idxs.append(int(m.group(1)))
        return idxs or [0]

    # ── both sources dead → one clear message naming both failures ────────────
    # ── why did a capture fail? name it, never a vague "unavailable" ──────────
    def _device_holder(self) -> str | None:
        """Process name currently holding a /dev/video* node, or None.

        V4L2 is single-open: while OBS streams, every capture here fails. Saying
        "the webcam isn't available" for that is the same silent-ish failure the
        brief forbids — the user can act on "OBS has it", not on "unavailable".
        Best-effort /proc scan; never raises.
        """
        try:
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                fddir = f"/proc/{pid}/fd"
                try:
                    fds = os.listdir(fddir)
                except OSError:
                    continue                      # not ours / gone mid-scan
                for fd in fds:
                    try:
                        if not os.readlink(f"{fddir}/{fd}").startswith("/dev/video"):
                            continue
                    except OSError:
                        continue
                    try:
                        return open(f"/proc/{pid}/comm").read().strip() or f"pid {pid}"
                    except OSError:
                        return f"pid {pid}"
        except Exception:
            pass
        return None

    def _capture_failure_reason(self) -> str:
        """A stated reason for a failed local capture — always specific."""
        holder = self._device_holder()
        if holder:
            return f"the camera is in use by {holder}"
        if not glob.glob("/dev/video*"):
            return "no camera is connected"
        return "the camera didn't return a frame"

    def _offline_msg(self) -> str:
        if self.fallback_enabled:
            return ("[I can't see right now — Stack-Chan's camera is offline AND no local PC "
                    "camera returned a frame. Both sources failed; I'm not guessing.]")
        return ("[Dio's camera is offline — Stack-Chan is not reachable, and the local-camera "
                "fallback is disabled, so I have no other eyes right now.]")

    # ── prompt-only look ──────────────────────────────────────────────────────
    def look(self, prompt=None):
        jpeg, src = self._grab_frame()
        if jpeg is None:
            return self._offline_msg()
        try:
            desc = self._analyze(jpeg, prompt or ANALYSIS_PROMPT)
        except VisionModelDown as e:
            _audit("look", ok=False, source=src, reason=str(e))
            return f"[I got a frame but couldn't describe it — {e}. I'm not guessing.]"
        _audit("look", ok=True, source=src, nbytes=len(jpeg))
        return f"{desc}{_SRC_TAG[src]}"

    # ── explicit user-invoked webcam photo (take_photo / describe_view) ───────
    # These use the LOCAL webcam directly (not Dio), fire ONLY on a direct user
    # request, and always land the frame in CAPTURE_DIR so the Argus feed is the
    # audit trail. Never call these proactively. One frame per call — no burst.
    def take_photo(self):
        """Grab ONE webcam frame and save it (webcam_*.jpg → captures/Argus feed).
        Returns a spoken confirmation, or a NAMED failure. No retry, no guessing."""
        jpeg = self._local_capture()          # grabs + persists a webcam_*.jpg
        if jpeg is None:
            reason = self._capture_failure_reason()
            _audit("take_photo", ok=False, reason=reason)
            return f"I couldn't take the photo — {reason}."
        _audit("take_photo", ok=True, source="webcam", nbytes=len(jpeg))
        return "Photo taken — saved to your captures."

    def describe_view(self):
        """Grab ONE webcam frame, save it, then describe it with the VLM.

        NO CLAIM OF SIGHT WITHOUT A CAPTURE THAT RETURNED. A failed grab returns a
        named refusal, never a description — the 2026-08-31 transcript ("I can see
        you are holding a book" with zero captures on disk) is what this prevents.
        """
        jpeg = self._local_capture()
        if jpeg is None:
            reason = self._capture_failure_reason()
            _audit("describe_view", ok=False, reason=reason)
            return f"[I can't see anything right now — {reason}. I'm not guessing.]"
        try:
            desc = self._analyze(jpeg, ANALYSIS_PROMPT)
        except VisionModelDown as e:
            # Capture succeeded, description did not. That is NOT a sight-claim,
            # so it is not logged as one — the frame stays on disk as the record.
            _audit("describe_view", ok=False, source="webcam",
                   nbytes=len(jpeg), reason=str(e))
            return (f"[I took a frame but couldn't describe it — {e}. "
                    f"I'm not guessing at what's in it.]")
        _audit("describe_view", ok=True, source="webcam", nbytes=len(jpeg))
        # Relay hint: the weak model otherwise summarises the result away. It used
        # to say "You DID see this", which also licensed upgrading a hedge into a
        # certainty — so it now asserts the CAPTURE, not the confidence.
        return (f"{desc}\n\n[This came from ONE still frame captured just now. Relay it "
                f"as an observation and keep its uncertainty exactly as written — do not "
                f"turn 'looks like' into 'I can see that'. You take single stills when "
                f"asked; you do not watch continuously.]")

    # ── timed capture (evening capture): pull + persist a frame, no analysis ──
    def capture(self) -> bool:
        """Pull one frame (Dio, else webcam fallback) and persist it to
        CAPTURE_DIR. Returns True if a frame landed, False if both sources fail.
        The frame is named by source (dio_/webcam_); _grab_frame does the save."""
        jpeg, _src = self._grab_frame(allow_local=False)   # timer: Dio only
        return jpeg is not None

    # ── timed capture WITH per-frame narration (evening capture) ──────────────
    def capture_and_describe(self):
        """Pull one frame AND analyze it with LLaVA. Returns a SPOKEN-READY
        description (plain prose — no bracketed _SRC_TAG, since evening capture
        speaks this straight through TTS), or None if no frame arrived. When the
        webcam fallback is used, the source is said plainly so it never passes as
        Dio's eyes."""
        jpeg, src = self._grab_frame(allow_local=False)   # timer: Dio only
        if jpeg is None:
            return None
        try:
            desc = self._analyze(jpeg, NARRATION_PROMPT)
        except VisionModelDown as e:
            _audit("capture_and_describe", ok=False, source=src, reason=str(e))
            return None
        return f"Through the backup PC camera, {desc}" if src == "webcam" else desc

    # ── ghost-hunt: baseline / anomaly (gated to an investigation in dispatch) ─
    def set_baseline(self):
        jpeg, src = self._grab_frame()
        if jpeg is None:
            return self._offline_msg()
        self.baseline_jpeg = jpeg
        return (f"Baseline set at {datetime.now():%H:%M:%S}. "
                f"I know what normal looks like now.{_SRC_TAG[src]}")

    def check_anomaly(self):
        if self.baseline_jpeg is None:
            return "No baseline set. Tell me to set a baseline first."
        jpeg, src = self._grab_frame()
        if jpeg is None:
            return self._offline_msg()
        try:
            analysis = self._analyze(
            jpeg,
            "This is a live frame from a ghost-hunt camera whose scene was empty/normal at "
            "baseline. Report ONLY what is new, moved, or unusual — if nothing stands out, "
            "say so plainly."
            )
        except VisionModelDown as e:
            _audit("check_anomaly", ok=False, source=src, reason=str(e))
            return f"[I got a frame but couldn't analyse it — {e}. I'm not guessing.]"
        if self.memory:
            self.memory.log_anomaly(description=analysis[:200], source="camera")
        return f"{analysis}{_SRC_TAG[src]}"

    # ── monitor mode: Dio detects on-device and posts on motion ───────────────
    def start_monitoring(self, interval_seconds=30):
        # Detection is on-device (Dio's motion diff), not a server timer — so
        # continuous monitoring needs Stack-Chan. The webcam fallback covers the
        # single-shot paths (look/capture), not continuous monitoring (by design;
        # out of scope for Phase 6.75).
        if not self.dio_host:
            return ("Monitor mode needs Stack-Chan — she runs the on-device motion detection "
                    "and she's offline right now. (The webcam fallback covers look and capture, "
                    "not continuous monitoring.)")
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
        """Describe a frame, or raise VisionModelDown. Never returns prose on failure.

        Returning "Vision model error: 500" as if it were a description put an
        error string where an observation belongs — one relay away from being read
        aloud as what she sees. Failures raise; the caller states them.

        Retries ONCE. The observed failure is a VRAM race: ollama tries to load the
        vision model while the chat model is still resident, the runner dies
        ("llama runner terminated, exit status 2" → HTTP 500), and that crash frees
        the memory — so the second attempt usually succeeds. One retry, not a loop.
        """
        last = ""
        for attempt in (1, 2):
            try:
                r = requests.post(OLLAMA_API_URL, json={
                    "model": VISION_MODEL,
                    "prompt": prompt,
                    "images": [base64.b64encode(jpeg).decode("ascii")],
                    "stream": False,
                }, timeout=90)
                if r.status_code == 200:
                    text = (r.json().get("response") or "").strip()
                    if text:
                        return text
                    last = "the vision model returned nothing"
                else:
                    last = f"the vision model failed (HTTP {r.status_code})"
            except Exception as e:
                last = f"the vision model is unreachable ({type(e).__name__})"
            if attempt == 1:
                log.warning("vision model attempt 1 failed (%s) — retrying once", last)
                time.sleep(2.0)
        raise VisionModelDown(last)

