"""Sentence-boundary splitter for chunked TTS synthesis.

Long replies (e.g. a 5.4 KB story = ~5 min of Alba audio) must not be
synthesised as one monolithic WAV: synth time and payload size scale linearly
with length and eventually blow the 30 s subprocess timeout / hold tens of MB
in one response. This splitter breaks reply text into bounded, sentence-sized
pieces so each chunk synthesises in well under a second and the device can
fetch-while-playing.

Design:
  - Split on sentence terminators (. ! ?), respecting a closing quote/bracket
    so dialogue like  ... told him "run."  ends cleanly.
  - Abbreviation-sane: a terminator right after a known abbreviation (Mr., Dr.,
    e.g., a.m. ...) does NOT end a sentence.
  - Greedily pack whole sentences into a chunk up to `max_chars` so we don't
    emit a flood of tiny fragments.
  - Hard backstop: no chunk exceeds `max_chars`. A single sentence longer than
    that is split at word boundaries.
  - No terminal punctuation at all -> the whole (packed) text still comes out
    as chunk(s); nothing is dropped.

Pure text-in / list-of-str-out. No I/O, no Piper, no server coupling — trivially
unit-testable (see tests/test_tts_chunker.py).
"""
import re

DEFAULT_MAX_CHARS = 300

# Tokens that end in '.' but do not end a sentence. Compared lowercased with the
# trailing '.' stripped, so "Mr" matches "Mr." and "e.g" matches "e.g.".
_ABBREV = {
    "mr", "mrs", "ms", "dr", "st", "sr", "jr", "prof", "gen", "rev", "hon",
    "capt", "sgt", "lt", "col", "gov", "pres", "supt", "rep", "sen",
    "vs", "etc", "al", "inc", "ltd", "co", "corp", "no", "vol", "fig",
    "approx", "dept", "est", "min", "max", "misc",
    "e.g", "i.e", "a.m", "p.m", "u.s", "u.k",
    # single-letter initials ("A." in "A. Turing") — treat as non-terminal
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
}

# A terminator (.!?) optionally followed by a closing quote/bracket, then either
# whitespace or end-of-string. Captures the terminator+closer as group 1.
_TERM = re.compile(r'([.!?]+["\'”’)\]]?)(\s+|$)')

# The final "word" (letters, possibly dotted like e.g / a.m) before a terminator.
_LAST_WORD = re.compile(r'([A-Za-z][A-Za-z.]*)$')


def _is_abbrev_before(text_upto):
    """True if the token immediately preceding the terminator is a known abbrev."""
    # strip a trailing terminator+closer we may have included, then look at the
    # word touching the '.'
    stripped = text_upto.rstrip('."\'”’)]')
    m = _LAST_WORD.search(stripped)
    if not m:
        return False
    tok = m.group(1).lower().rstrip('.')
    return tok in _ABBREV


def split_sentences(text):
    """Split `text` into sentences, abbreviation-sane. Whitespace-normalised.

    A monster sentence (no interior terminator) comes back as a single element;
    length capping is `split_for_tts`'s job, not this function's.
    """
    text = re.sub(r'\s+', ' ', (text or '')).strip()
    if not text:
        return []
    out = []
    start = 0
    for m in _TERM.finditer(text):
        term_end = m.end(1)                 # end of the terminator (+closer)
        if _is_abbrev_before(text[start:term_end]):
            continue                        # e.g. "Mr." — keep scanning
        # Continuation heuristic: a lowercase word right after the terminator
        # usually means the '.' was mid-sentence — an inline quote ("run." and…)
        # or an abbreviation we don't have listed. Real sentences start with a
        # capital / digit / opening quote. (Decimals never reach here: _TERM
        # requires the terminator to be followed by whitespace.)
        nxt = text[m.end():m.end() + 1]
        if nxt and nxt.islower():
            continue
        sent = text[start:term_end].strip()
        if sent:
            out.append(sent)
        start = m.end()                     # skip the whitespace after
    tail = text[start:].strip()             # trailing text with no terminator
    if tail:
        out.append(tail)
    return out


def _word_split(sentence, max_chars):
    """Split an over-long sentence into <=max_chars pieces at word boundaries.

    A single word longer than max_chars is emitted whole (never hard-cut inside a
    word) — Piper would rather over-run slightly than mangle a token.
    """
    pieces, cur = [], ""
    for word in sentence.split(' '):
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            pieces.append(cur)
            cur = word
    if cur:
        pieces.append(cur)
    return pieces


def split_for_tts(text, max_chars=DEFAULT_MAX_CHARS):
    """Return a list of TTS-ready chunks, each <= max_chars, on sentence
    boundaries where possible.

    Guarantees:
      - every chunk is non-empty and <= max_chars,
      - concatenating the chunks with single spaces reproduces the
        whitespace-normalised input (nothing dropped or duplicated),
      - short input returns a single chunk; empty/blank returns [].
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    chunks, cur = [], ""
    for sent in split_sentences(text):
        if len(sent) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_word_split(sent, max_chars))
            continue
        if not cur:
            cur = sent
        elif len(cur) + 1 + len(sent) <= max_chars:
            cur += " " + sent
        else:
            chunks.append(cur)
            cur = sent
    if cur:
        chunks.append(cur)
    return chunks
