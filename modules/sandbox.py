"""Sandbox sessions: every lane runs, no actuator fires.

WHY THIS EXISTS. On 2026-10-03 a 168-turn smoke battery sent "read Genesis" as
a live /chat turn. The Thoth read lane does not merely route — it starts reading
aloud through TTS and keeps going. She recited Genesis in the Captain's room,
unasked, because of an unattended test. Three passes were queued; it was stopped
at Genesis 1:25.

That was the SECOND time one of my test runs reached into the physical world
through her — the first opened the webcam. Both times the test was correct about
what it wanted to measure and wrong about what it would cause.

THE GUARANTEE IS AT THE ACTUATOR, NOT THE LANE. A per-lane opt-out is a list
someone has to remember to extend, and the next lane will forget. So the check
sits at the last function before something happens in the room: the audio write,
the servo POST, the camera trigger, the memory write. A new lane inherits the
guarantee for free because it has to go through one of those to do anything.

WHAT IS SUPPRESSED: TTS playback, Thoth read-aloud (it goes through TTS), head
motion, camera capture, and memory writes. Everything else — triage, the floor,
retrieval, tool dispatch, the model — runs exactly as in a real turn, because
that is the thing being measured.

WHAT IS NOT SUPPRESSED, deliberately: the floor. A sandbox that skipped the
floor would measure a system that does not exist, and the floor is the last
thing anyone should be able to switch off with a session id.
"""
from __future__ import annotations

import contextvars
import logging

log = logging.getLogger("Ph3b3")

# Same reserved-prefix pattern as __argus_probe__.
SMOKE_PREFIX = "__smoke__"

# A context variable, not a module global: a real conversation must not be
# silenced because a battery turn is in flight on another request. contextvars
# propagate through asyncio.to_thread, which is how the blocking actuators are
# called.
_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "ph3b3_sandbox_active", default=False)


def is_smoke_session(session_id: str | None) -> bool:
    return bool(session_id) and str(session_id).startswith(SMOKE_PREFIX)


def enter(session_id: str | None):
    """Mark this request's context as sandboxed. Returns the reset token."""
    return _active.set(is_smoke_session(session_id))


def leave(token) -> None:
    try:
        _active.reset(token)
    except Exception:                                      # noqa: BLE001
        pass


def active() -> bool:
    return bool(_active.get())


def would(action: str, detail: str = "") -> None:
    """Record what WOULD have happened. WARNING level on purpose: a suppressed
    actuator is the whole output of a sandbox run and must not be filtered out
    with the debug noise."""
    log.warning("[sandbox] would %s: %s", action, (detail or "")[:200])


def suppress(action: str, detail: str = "") -> bool:
    """True if this call must not actually happen. Logs what it would have done.

    Call shape is deliberately `if sandbox.suppress("speak", text): return ...`
    so the guard and its log line cannot drift apart.
    """
    if not active():
        return False
    would(action, detail)
    return True
