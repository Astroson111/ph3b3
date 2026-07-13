"""Wake-word gate for Dio (Stack-Chan) hands-free conversation mode.

Dio re-arms the mic the instant she finishes speaking, so her own TTS tail can
be recorded, transcribed, and fed back into /chat — a self-echo loop that never
exits (each self-trigger resets the idle clock). Onset suppression on-device
(POST_TTS_DRAIN_MS + ONSET_THRESH) reduces how much echo is captured but did not
close the loop on its own (Test 1, 2026-07-07: 5 self-replies @ ~17 s).

This gate is the real fix: an utterance only counts as a turn if it *addresses
her by name* ("hey Ph3b3" / "Phoebe"). Her own echo transcribes to her reply
words — never her name — so it is dropped and the device just re-arms in silence.

Whisper mangles "Phoebe" hard (commonly -> "baby"), so we fuzzy-match a
deliberately generous set of mishearings. Bias is intentional: a false accept
merely makes her answer something she shouldn't have; a false reject makes her
ignore a real request — worse in a live demo.
"""
import difflib
import re

# Single-word wake tokens. Mirrors the firmware _isPhoebeName() variant list
# plus the "baby"/"babe" family Whisper emits for "Phoebe".
_WAKE_TOKENS = {
    "phoebe", "pheobe", "phoeby", "phoebee", "phoebi", "phoebs", "phebe",
    "feeby", "feebe", "feebs", "foebe", "pheeby", "fibi", "phoby", "pheebe",
    "baby", "babe", "baby",
}

# Multi-word mishearings that only read as a wake when the words are adjacent.
_WAKE_PHRASES = ("hey baby", "fee bee", "fee be", "fi bi", "hey phoebe")

# Salutation/filler words stripped off the front so the model sees the request,
# not "hey ... <request>".
_LEAD_FILLERS = {"hey", "hi", "hello", "ok", "okay", "yo", "um", "uh", "so"}

# difflib ratio floor for a fuzzy single-token hit. 0.82 accepts "phoepe"/"phebe"
# but rejects near-misses like "maybe" (~0.66 vs the set).
_CUTOFF = 0.82


def _norm(text):
    t = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _strip_fillers(s):
    toks = _norm(s).split()
    while toks and toks[0] in _LEAD_FILLERS:
        toks.pop(0)
    return " ".join(toks).strip()


def wake_match(text):
    """Return (matched, cleaned).

    matched — True if the utterance addresses Ph3b3 by name (or a Whisper
              mishearing of it).
    cleaned — the utterance with the wake token + leading filler removed, so the
              model receives the actual request. Falls back to the original text
              when stripping would leave nothing.
    """
    t = _norm(text)
    if not t:
        return False, ""
    for p in _WAKE_PHRASES:
        if p in t:
            return True, _strip_fillers(t.replace(p, " "))
    toks = t.split()
    for i, tok in enumerate(toks):
        if tok in _WAKE_TOKENS or difflib.get_close_matches(tok, _WAKE_TOKENS, n=1, cutoff=_CUTOFF):
            return True, _strip_fillers(" ".join(toks[:i] + toks[i + 1:]))
    return False, t


if __name__ == "__main__":
    # Self-test: (transcript, expect_match). Real-ish Whisper output both ways.
    CASES = [
        # --- should WAKE (real user addressing her) ---
        ("Hey Phoebe, what's two plus two?", True),
        ("Phoebe what time is it", True),
        ("hey baby can you sing", True),
        ("Baby, tell me a joke.", True),
        ("Feeby, are you there?", True),
        ("Hey Phoeby whats the weather", True),
        ("goodbye phoebe", True),          # farewell path still carries the name
        ("HEY PHOEBE", True),
        # --- should DROP (her own echo / ambient — no name) ---
        ("That's four.", False),
        ("The answer is four.", False),
        ("I'm doing great, thanks for asking!", False),
        ("what time is it", False),        # no wake -> ignored (must address her)
        ("maybe later", False),            # near-miss must NOT trip "baby"
        ("", False),
        ("um so anyway", False),
    ]
    ok = 0
    for text, expect in CASES:
        m, cleaned = wake_match(text)
        status = "PASS" if m == expect else "FAIL"
        if m == expect:
            ok += 1
        print(f"[{status}] match={m!s:5} cleaned={cleaned!r:32} <- {text!r}")
    print(f"\n{ok}/{len(CASES)} passed")
