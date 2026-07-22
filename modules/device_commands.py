"""Device-command intent gate — Iris track playback (Phase 1).

A pre-LLM intercept: applied to the Whisper transcript in /transcribe BEFORE it
reaches Hermes3. On a match we return a structured command for the device to run
(drive its M5 Unit AudioPlayer over UART) instead of a conversational reply.

Design (matches iris-track-playback-spec):
  - ANCHORED: the command must be essentially the WHOLE utterance. We strip an
    optional wake word + surrounding punctuation, then require the command pattern
    to consume the entire remainder. "tell me a story about a play track" does NOT
    match (extra words before/after).
  - Whisper writes number WORDS as often as digits ("play track three"), so both
    are accepted and mapped to an int.
  - Pure parsing — no range check here (the server doesn't know the SD track count;
    the caller range-checks against the device-reported total and the firmware
    validates too). Returns the parsed command or None.
"""
import re

# Whisper renders small numbers as words at least as often as digits.
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
    # common Whisper homophones / spellings
    "to": 2, "too": 2, "for": 4, "ate": 8,
}
_NUM_ALT = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))

# Optional leading wake word (Iris is push-to-talk, but Whisper may still catch a
# spoken "hey Ph3b3"); stripped before matching so it doesn't break anchoring.
_WAKE_RE = re.compile(
    r"^(?:hey\s+|ok\s+|okay\s+)?(?:ph[3e]{1,2}b[3e]|phoebe|phoebie|fee?bee?|feebie)[\s,.:-]*",
    re.I,
)

_PLAY_RE   = re.compile(rf"^(?:play|start)\s+track\s+(?:number\s+)?(\d+|{_NUM_ALT})$", re.I)
_STOP_RE   = re.compile(r"^(?:stop|pause)(?:\s+(?:the\s+)?(?:music|track|playback|audio|song|it))?$"
                        r"|^stop\s+playing$", re.I)
_VOLUP_RE  = re.compile(r"^(?:volume\s+up|turn\s+it\s+up|louder|turn\s+up\s+the\s+volume)$", re.I)
_VOLDN_RE  = re.compile(r"^(?:volume\s+down|turn\s+it\s+down|quieter|softer|turn\s+down\s+the\s+volume)$", re.I)


def _to_int(token: str):
    token = token.lower()
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


# Polite request framing around a command. Stripped (repeatedly) so natural speech
# — "can you play track one please" — reduces to the bare command, WITHOUT loosening
# the whole-utterance anchor (so "tell me a story about a play track" and
# "play track three after dinner" still don't match — their extra words aren't
# framing and survive the strip, breaking the anchor).
_LEADIN_RE = re.compile(
    r"^(?:can you|could you|would you|will you|can u|"
    r"go ahead and|i want(?: you)? to|i'?d like(?: you)? to|i would like(?: you)? to|"
    # correction / negation / affirmation framing — a user re-issuing a misheard
    # command naturally opens with "no, I said …" / "actually …" / "yeah …". These
    # are framing, not content, so stripping them keeps the whole-utterance anchor.
    r"no|nope|nah|actually|wait|sorry|oops|whoops|"
    r"i said|i meant|i mean|i just said|yeah|yep|yes|"
    r"please|hey|ok|okay|um+|uh+|just|kindly|let'?s|now)\b[\s,]*", re.I)
_TRAIL_RE = re.compile(
    r"[\s,]*\b(?:please|thanks|thank you|now|for me|for us|real quick|ok|okay)\b[.?!]*$", re.I)


def _normalize(text: str) -> str:
    """Lowercase-ish, strip a leading wake word + polite request framing (lead-in and
    trailing), drop surrounding punctuation, collapse whitespace. What remains must be
    the command and nothing else."""
    t = (text or "").strip()
    t = _WAKE_RE.sub("", t)
    t = t.strip().strip(".,!?;:\"' ")
    t = re.sub(r"\s+", " ", t).strip()
    for _ in range(4):                                   # peel repeated framing
        n = _LEADIN_RE.sub("", t).strip().strip(".,!?;:\"' ")
        n = _TRAIL_RE.sub("", n).strip().strip(".,!?;:\"' ")
        if n == t:
            break
        t = n
    return t


def parse(text: str):
    """Return a device_command dict for a matched utterance, else None.

    {"action": "play_track", "index": N} | {"action": "stop"} |
    {"action": "volume_up"} | {"action": "volume_down"}
    """
    t = _normalize(text)
    if not t:
        return None

    m = _PLAY_RE.match(t)
    if m:
        n = _to_int(m.group(1))
        # A parsed-but-unmappable token (shouldn't happen given the alternation)
        # yields no command rather than a bogus index.
        return {"action": "play_track", "index": n} if n is not None else None
    if _STOP_RE.match(t):
        return {"action": "stop"}
    if _VOLUP_RE.match(t):
        return {"action": "volume_up"}
    if _VOLDN_RE.match(t):
        return {"action": "volume_down"}
    return None


# ── Fail-open guard (chat-pipeline side) ──────────────────────────────────────
# parse() is deliberately STRICT so it never mis-fires and plays the wrong thing.
# The cost: a device-command-shaped utterance it can't cleanly resolve ("go and
# play track four for me", a mangled transcript) falls through to the LLM — which
# has NO audio-unit control and will happily fabricate "Track 4 it is." while
# nothing plays. is_device_intent() is a loose SUPERSET of parse() used ONLY to
# detect that near-miss so the pipeline can return a deterministic clarification
# instead of a fabricated confirmation. It is DETECTION ONLY — it never dispatches
# (dispatch stays strict + firmware-validated). Fail-closed, mirroring Metis.

# Negation directly on the control verb — "don't play track 4", "not going to
# stop it", "no need to play that" — means the user is NOT issuing the command.
# (Bare leading "no," is a CORRECTION, handled in _LEADIN_RE, and excluded here.)
_NEG_VERB_RE = re.compile(
    r"\b(?:not|never|no\s+need|rather\s+not|"
    r"don'?t|doesn'?t|didn'?t|won'?t|can'?t|cannot|"
    r"wouldn'?t|shouldn'?t|couldn'?t|isn'?t|aren'?t)\b"
    r"(?:\s+\w+){0,3}?\s+(?:play|start|stop|pause|resume|put\s+on|turn\s+it)\b",
    re.I)

# Strong "control the audio unit" signals. The play branch requires the audio
# noun to follow the verb closely (only articles/pronouns between) so a STORY
# request — "play me a story about tracks" — does NOT trip it.
_INTENT_SIGNAL_RE = re.compile(
    r"\b(?:play|start|put\s+on|resume)\s+"
    r"(?:(?:the|a|an|some|me|us|my|that|this|track|next|previous)\s+){0,3}"
    r"(?:track|song|music|tune|tunes|playlist|album|number|audio)\b"
    r"|\bstop\s+(?:the\s+|this\s+|that\s+)?(?:music|track|song|audio|playback|playlist)\b"
    r"|\b(?:stop|pause)\s+playing\b"
    r"|\bvolume\s+(?:up|down)\b"
    r"|\bturn\s+(?:it|the\s+(?:volume|music|song|audio))\s+(?:up|down)\b"
    r"|\b(?:louder|quieter|softer)\b",
    re.I)


def is_device_intent(text: str) -> bool:
    """True if the utterance is trying to control the audio unit (play a track /
    stop / volume) even though parse() couldn't resolve a clean command. Negated
    forms ("don't play …") and non-commands return False. Superset of parse()."""
    t = (text or "").strip()
    if not t or _NEG_VERB_RE.search(t):
        return False
    return bool(_INTENT_SIGNAL_RE.search(t))


def clarify(text: str) -> str:
    """Spoken, deterministic reply for a device-command near-miss. NEVER claims an
    action happened — it tells the user the phrasing that works. This is what stands
    in for the LLM's fabricated confirmation."""
    t = (text or "").lower()
    if re.search(r"\b(?:volume|louder|quieter|softer)\b|\bturn\s+it\b", t):
        return "To change the volume, say: volume up, or volume down."
    if re.search(r"\b(?:stop|pause)\b", t):
        return "To stop the music, just say: stop the music."
    return ("I can play a track by its number — try saying: play track four. "
            "Which track would you like?")


_ORDINAL = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
            7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def confirmation(cmd: dict) -> str:
    """A short human confirmation line for a parsed command. Phase 1: shown on the
    Iris status display; a spoken version is a later add (needs an audio path)."""
    a = cmd.get("action")
    if a == "play_track":
        n = cmd.get("index")
        return f"Playing track {_ORDINAL.get(n, n)}."
    return {"stop": "Stopped.", "volume_up": "Volume up.",
            "volume_down": "Volume down."}.get(a, "")
