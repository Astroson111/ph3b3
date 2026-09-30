"""Keyframe → motion: the approval that binds to one exact image.

THE SHAPE OF THE FLOW, and the reason this module exists at all:

    1. a still is rendered from text (Qwen-Image-Edit-2509 driven as T2I)
    2. a HUMAN looks at it and approves it, or re-rolls
    3. only then does Wan animate it, for ~12 minutes

Step 2 is the whole point. On this box the motion stage costs ~12 minutes and
91% of that is sampling with both 14B experts offloaded, so an unapproved
keyframe is twelve minutes of GPU spent on a picture nobody wanted. There is NO
auto-proceed here by design.

WHAT "BINDS" MEANS, precisely, because a loose version of this is worthless:

  * approval names ONE job id. Not "the latest keyframe", not "this session's
    keyframe" — the id that was on screen when the person said yes.
  * a re-roll invalidates any prior approval in that session. The second render
    is a different picture; consent to the first is not consent to it.
  * a keyframe-origin image may be animated ONLY while approved. Dropping the
    keyframe flag from the request does not turn it back into an ordinary
    gallery render — registration is what makes it keyframe-origin, and that
    fact travels with the id.

Ordinary gallery renders are untouched: they were floor-passed when created and
keep the provenance rule they already had. This module only governs images that
came out of the keyframe flow.

State is in memory on purpose. An approval that outlived a restart would be a
consent token with no one behind it.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("Ph3b3")

_lock = threading.Lock()
# session_id -> {"job_id": str, "approved": bool, "prompt": str, "aspect": str,
#                "at": float, "approved_at": float | None}
_current: dict[str, dict] = {}
# job_id -> session_id, so a job id alone can be judged without the caller
# having to tell us which session it came from (a caller that could choose its
# own session could approve its own keyframe).
_origin: dict[str, str] = {}

APPROVED_COUNT = [0]
REROLL_INVALIDATED_COUNT = [0]
REJECTED_COUNT = [0]


def register(session_id: str, job_id: str, prompt: str = "", aspect: str = "") -> None:
    """A keyframe render has started. Any prior approval in this session dies.

    Called when the render is QUEUED, not when it finishes: the invalidation has
    to happen the moment a re-roll is asked for, or a slow second render would
    leave the first one approved and animatable in the meantime.
    """
    sid = session_id or "default"
    with _lock:
        prev = _current.get(sid)
        if prev and prev.get("approved"):
            REROLL_INVALIDATED_COUNT[0] += 1
            log.info("[keyframe] re-roll invalidated the approval of %s",
                     prev.get("job_id"))
        _current[sid] = {"job_id": job_id, "approved": False, "prompt": prompt,
                         "aspect": aspect, "at": time.time(), "approved_at": None}
        _origin[job_id] = sid


def approve(session_id: str, job_id: str, image_checked: bool = False) -> bool:
    """Bind approval to this exact id. False if it is not the current keyframe.

    `image_checked` records that the IMAGE itself passed the floor, not just the
    prompt that made it. The verdict travels with the approval — the same reason
    the video route trusts a gallery render: not because of where it came from,
    but because a verdict exists for it. An approval without that flag does not
    satisfy is_approved(), so an image the floor never looked at cannot be
    animated even if somebody calls approve() directly.
    """
    sid = session_id or "default"
    with _lock:
        cur = _current.get(sid)
        if not cur or cur.get("job_id") != job_id:
            REJECTED_COUNT[0] += 1
            log.warning("[keyframe] approval refused: %s is not the current "
                        "keyframe for this session (current=%s)",
                        job_id, (cur or {}).get("job_id"))
            return False
        cur["approved"] = True
        cur["image_checked"] = bool(image_checked)
        cur["approved_at"] = time.time()
        APPROVED_COUNT[0] += 1
        log.info("[keyframe] approved %s (image floor: %s)", job_id,
                 "checked" if image_checked else "NOT CHECKED")
        return True


def is_keyframe(job_id: str) -> bool:
    """Did this id come out of the keyframe flow?"""
    with _lock:
        return job_id in _origin


def is_approved(job_id: str) -> bool:
    """Is this exact id approved RIGHT NOW? A re-roll makes this False again."""
    with _lock:
        sid = _origin.get(job_id)
        if sid is None:
            return False
        cur = _current.get(sid)
        return bool(cur and cur.get("job_id") == job_id
                    and cur.get("approved") and cur.get("image_checked"))


def current(session_id: str) -> dict | None:
    """What this session is looking at, for the UI to echo."""
    with _lock:
        cur = _current.get(session_id or "default")
        return dict(cur) if cur else None


def refuse_reason(job_id: str) -> str | None:
    """Why this id may not be animated, in words, or None if it may.

    An unknown id is NOT refused here — it is an ordinary gallery render, and
    the video route's own provenance rule governs it. This module only answers
    for the images it issued.
    """
    if not is_keyframe(job_id):
        return None
    if is_approved(job_id):
        return None
    with _lock:
        sid = _origin.get(job_id)
        cur = _current.get(sid) or {}
    if cur.get("job_id") != job_id:
        return ("that keyframe was replaced by a newer one — approve the frame "
                "you can see, or render another")
    if cur.get("approved") and not cur.get("image_checked"):
        return ("that keyframe was approved without the image being checked — "
                "approve it again through the panel")
    return "that keyframe has not been approved yet"


def forget(session_id: str) -> None:
    """Drop a session's keyframe state (tab closed, flow abandoned)."""
    sid = session_id or "default"
    with _lock:
        cur = _current.pop(sid, None)
        if cur:
            _origin.pop(cur.get("job_id", ""), None)
