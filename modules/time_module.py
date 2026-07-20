"""Time module — deterministic clock/date answers, claimed via the intent registry.

Time-of-day used to be answered implicitly: the server injects a "Current date and
time:" system note and the (weak 8B) model reads it back — non-deterministic and
occasionally mangled. This module CLAIMS clock/date phrasing so the answer comes
straight from the host clock, never the model, and Metis's search-intent gate can
never hijack it either. Precedence lives in the intent registry, same as weather;
see [[project_intent_precedence_registry]].

Scope is intentionally small: "what time is it" / "what's the date" / "what day is
it" — the CURRENT wall clock. It deliberately does NOT claim timer phrasing ("set a
timer", "time left"), durations ("how long until…"), or event times ("what time is
my meeting" → calendar). The full time/scheduler ambition is the future Chronos
project; this is just correct time-telling.
"""
import re
import logging
from datetime import datetime

try:
    import intent_registry
except ImportError:
    from modules import intent_registry

log = logging.getLogger("ph3b3.time")

# ── Intent claim (precedence over Metis) ──────────────────────────────────────
# NARROW positive patterns (current wall clock / today's date only). `exclude`
# steps aside for timers, durations, and event/calendar times that share the word
# "time" but not the domain.
_TIME_INTENT_RE = re.compile(
    r"\bwhat time is it\b|"
    r"\bwhat(?:'?s| is) the (?:current )?time\b|"
    r"\bcurrent time\b|"
    r"\btell me the time\b|"
    r"\btime is it (?:right )?now\b|"
    # bare "what's the date" is TODAY — but NOT "what's the date OF/FOR <event>"
    # (that's a factual/lookup question, not a clock read), so guard with a lookahead.
    r"\bwhat(?:'?s| is) (?:the |today'?s )?date\b(?!\s+(?:of|for)\b)|"
    r"\btoday'?s date\b|"
    r"\bwhat day is it(?: today)?\b|"
    r"\bwhat(?:'?s| is) the date today\b",
    re.I,
)
# Timers, durations, and event/calendar times are DIFFERENT domains — don't claim.
_NOT_TIME_RE = re.compile(
    r"\btimer\b|\btime (?:left|remaining)\b|\bhow (?:much|long)\b|"
    r"\b(?:my|the|a|an|this|next|that|his|her|their|our) "
    r"(?:meeting|appointment|call|event|reminder|flight|class|shift|game|show|"
    r"match|dinner|lunch|train|bus|alarm)\b",
    re.I,
)


class TimeModule:
    def __init__(self):
        log.info("Time module ready.")

    def now(self, _ignored=None) -> str:
        """Current local date + time as a plain sentence, straight from the host
        clock. No apology language, no model involvement — always exact."""
        n = datetime.now().astimezone()
        clock = n.strftime("%-I:%M %p")
        stamp = n.strftime("%A, %B %-d, %Y")
        tz = n.strftime("%Z")
        return f"It's {clock}{(' ' + tz) if tz else ''} on {stamp}."


intent_registry.register("time", "time_now", _TIME_INTENT_RE, exclude=_NOT_TIME_RE)
