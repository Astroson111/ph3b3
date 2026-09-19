"""
vad_turns.py — per-turn VAD diagnostic record.

Dio's voice endpointing works intermittently ("it fired once and never again"),
and the three channels that would say why are all unavailable on that device:
her USB serial is silent (USB-Serial-JTAG), the on-screen "voice endpoint
offline" banner was removed as noise, and the DIO_STATE UDP telemetry never
reaches Nyx. So a turn where the VAD worked and a turn where it failed look
identical from the outside. This gives those turns somewhere to land.

┌─ PRIVACY INVARIANT — inherited from the /vad/stream contract ────────────────┐
│ METADATA ONLY. This module records whether the stream connected, when the     │
│ endpoint fired, and how much heap was free — numbers ABOUT a turn, never any  │
│ part of it. No audio frames, no transcript, no text the user spoke, ever      │
│ touches this file. /vad/stream promises the mic stream is processed in memory │
│ and discarded; writing any of it here would break that promise from the other │
│ side. Do not add an audio, text, or transcript field below.                   │
└──────────────────────────────────────────────────────────────────────────────┘

One JSON object per line in PH3B3_DATA/vad_turns.jsonl, so a test session can be
read back with plain tools. Self-trimming — this is a diagnostic, not an archive.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from paths import PH3B3_DATA   # modules/ is on sys.path (server.py inserts MODULES_DIR)

LOG_PATH: Path = PH3B3_DATA / "vad_turns.jsonl"

# Self-trim: once the file passes MAX_BYTES, keep the newest KEEP_LINES. A
# diagnostic that silently eats the data partition is its own kind of bug.
MAX_BYTES = 1_000_000
KEEP_LINES = 2_000

# The complete set of fields accepted from a device. Anything else in the payload
# is DROPPED rather than stored — an allowlist, so a firmware change can never
# start writing new (or sensitive) fields here without a deliberate edit.
#
# "end" is how the CAPTURE ended (vadend | tap | cap), which is a different
# question from "why" (what the VAD stream did). Without it the two are
# conflated: a turn the user ended with a tap looks exactly like one that rode
# the backstop, so tapping made the endpoint's hit rate look worse than it is.
# "dropped" is the device's own count of diagnostic rows it failed to deliver —
# an instrument that loses data should say how much, not quietly under-report.
# Shadow fields, written by the SERVER at stream close rather than reported by
# the device — the device cannot know what an alternative rule would have done.
# They exist so a proposed endpoint change can be judged on real traffic before
# it changes any behaviour: sh_at_ms is when a windowed-majority rule WOULD have
# ended the turn, sh_run/sh_need is how close the live consecutive-run counter
# got, and sh_pct is how much of the active turn was below the speech floor.
# Nothing reads these to make a decision. They accumulate and wait.
_INT_FIELDS = ("ep_ms", "dur_ms", "heap_free", "heap_max", "samples", "dropped",
               "sh_at_ms", "sh_run", "sh_need", "sh_pct", "sh_runs")
_STR_FIELDS = ("why", "fw", "end")
_BOOL_FIELDS = ("ok",)

# Capture-end reasons the device may report. Anything else is kept as-is but
# counted under "other" rather than silently folded into a real category.
END_VADEND = "vadend"   # the endpoint fired — the VAD did its job
END_TAP = "tap"         # user ended it by hand — the VAD never got the chance
END_CAP = "cap"         # rode the 8 s backstop — a genuine miss


def _coerce_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _trim_if_needed() -> None:
    try:
        if not LOG_PATH.exists() or LOG_PATH.stat().st_size <= MAX_BYTES:
            return
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-KEEP_LINES:]
        tmp = LOG_PATH.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(tail) + "\n", encoding="utf-8")
        os.replace(tmp, LOG_PATH)          # atomic — a crash mid-trim can't truncate the log
    except Exception:
        pass                                # diagnostics must never break a voice turn


def record(device: str, data: dict) -> dict:
    """Append one turn. Returns the stored row (useful for the endpoint's reply).

    Never raises: this sits on the voice path, and a failed diagnostic write must
    not cost the user their turn."""
    row: dict = {
        "ts": round(time.time(), 3),
        "device": str(device or "unknown")[:32],
    }
    for k in _INT_FIELDS:
        if k in data:
            row[k] = _coerce_int(data.get(k))
    for k in _STR_FIELDS:
        if k in data:
            v = data.get(k)
            row[k] = (str(v)[:48] if v is not None else None)
    for k in _BOOL_FIELDS:
        if k in data:
            row[k] = bool(data.get(k))
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        _trim_if_needed()
    except Exception:
        pass
    return row


def recent(limit: int = 50) -> list[dict]:
    """Newest-first turns, for the panel or a quick curl."""
    try:
        if not LOG_PATH.exists():
            return []
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        if len(out) >= max(1, min(limit, 500)):
            break
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue                        # a torn line never poisons the read
    return out


def _shadow_report(rows: list[dict]) -> dict:
    """What the alternative rule would have done on the turns that went wrong.

    Scoped to CAP-ended turns on purpose: those are the genuine misses. A turn
    that ended by tap or by a working endpoint is not evidence either way, and
    folding them in would flatter whichever rule is being tested.
    """
    missed = [r for r in rows if r.get("end") == END_CAP and r.get("sh_need")]
    if not missed:
        return {"shadow_turns": 0, "shadow_would_fire": None,
                "shadow_saved_ms_avg": None, "shadow_verdict": "no data yet"}
    fired = [r for r in missed if isinstance(r.get("sh_at_ms"), int)]
    saved = [r["dur_ms"] - r["sh_at_ms"] for r in fired
             if isinstance(r.get("dur_ms"), int) and r["dur_ms"] > r["sh_at_ms"]]
    # Why the live rule missed, from how far its counter got.
    never_paused = sum(1 for r in missed if (r.get("sh_run") or 0) == 0)
    reset = len(missed) - never_paused
    return {
        "shadow_turns": len(missed),
        "shadow_would_fire": len(fired),
        "shadow_saved_ms_avg": (round(sum(saved) / len(saved)) if saved else None),
        # The one-line reading, so nobody has to interpret the numbers.
        "shadow_verdict": (
            f"{len(fired)}/{len(missed)} missed turns would have ended"
            + (f", avg {round(sum(saved) / len(saved))}ms sooner" if saved else "")
            + f"; {reset} looked like counter-resets, {never_paused} never paused"),
    }


def summary(limit: int = 200) -> dict:
    """Aggregate the recent window — the actual question is 'how often does it
    work', which is tedious to eyeball from raw rows.

    The rate is computed over turns where the endpoint actually had a chance to
    fire. A tap-ended turn is not a miss: the user cut the capture short, so the
    VAD was never allowed to reach a verdict. Counting those in the denominator
    is what made earlier sessions read worse than they were. They are reported
    separately rather than dropped, because a session that is mostly taps says
    something about the sample, not the VAD."""
    rows = recent(limit)
    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok"))
    fired = sum(1 for r in rows if (r.get("ep_ms") or 0) > 0)

    ends: dict[str, int] = {}
    for r in rows:
        e = r.get("end") or "unreported"
        ends[e] = ends.get(e, 0) + 1

    # Eligible = the VAD was given the chance to end the turn.
    eligible = ends.get(END_VADEND, 0) + ends.get(END_CAP, 0)
    hits = ends.get(END_VADEND, 0)
    misses = ends.get(END_CAP, 0)

    whys: dict[str, int] = {}
    for r in rows:
        w = r.get("why")
        if w:
            whys[w] = whys.get(w, 0) + 1

    # The device counts diagnostic rows it could not deliver. It is cumulative
    # since boot, so the largest value in the window is the floor on how many
    # turns are missing from this file — the instrument declaring its own loss
    # instead of letting it read as a clean session.
    drops = [r["dropped"] for r in rows if isinstance(r.get("dropped"), int)]
    heaps = [r["heap_max"] for r in rows if isinstance(r.get("heap_max"), int)]
    return {
        "turns": total,
        "stream_ok": ok,
        "endpoint_fired": fired,
        "ended_by": dict(sorted(ends.items(), key=lambda kv: -kv[1])),
        # Rate over eligible turns only; None (not 0) when nothing was eligible,
        # so "no data" can never be misread as "it never fired".
        "eligible_turns": eligible,
        "endpoint_hits": hits,
        "endpoint_misses": misses,
        "endpoint_rate": (round(hits / eligible, 3) if eligible else None),
        "tap_ended": ends.get(END_TAP, 0),
        # ── the shadow rule's report card ────────────────────────────────────
        # Of the turns the live rule MISSED, how many would a windowed-majority
        # rule have caught, and how much sooner? That is the whole question, and
        # answering it from rows beats grepping a journal that rotates away.
        **_shadow_report(rows),
        "rows_lost_reported": max(drops) if drops else 0,
        "fail_reasons": dict(sorted(whys.items(), key=lambda kv: -kv[1])),
        "heap_max_min": min(heaps) if heaps else None,
        "heap_max_max": max(heaps) if heaps else None,
    }
