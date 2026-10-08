"""Stage directions are not speech (Captain's ruling, 2026-10-07).

22:01 that day Dio read aloud "*Phoebe tilts her head slightly, as if listening
intently...*". Directions are dropped before TTS; emphasis is unwrapped, never
deleted, so a sentence keeps its meaning. Speech only — chat text is untouched.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules"))
import tts_module as t  # noqa: E402

CASES = [
    ("*Phoebe tilts her head slightly, as if listening intently. After a moment, she "
     "speaks in a warm, focused voice:*  Yes, I can hear you.", "Yes, I can hear you."),
    ("*smiles* Hello there.", "Hello there."),
    ("*waves warmly at you* Hi!", "Hi!"),
    ("Sure. *nods* Let us go.", "Sure. Let us go."),
    ("I *really* like that.", "I really like that."),           # emphasis: words kept
    ("It was *so* good, *honestly*.", "It was so good, honestly."),
    ("That is **very** important.", "That is very important."),
    ("5 * 3 = 15 and 2 * 4 = 8", "5 * 3 = 15 and 2 * 4 = 8"),     # arithmetic untouched
    ("No stars here at all.", "No stars here at all."),
]


@pytest.mark.parametrize("raw,spoken", CASES)
def test_directions_go_and_emphasis_stays(raw, spoken):
    assert t._strip_stage_directions(raw) == spoken


def test_every_voice_path_goes_through_it():
    """_prep is the single gate both latin and native voices pass through."""
    raw = "*nods slowly and smiles* Yes."
    assert t._prep(raw, "latin") == "Yes."
    assert t._prep(raw, "native") == "Yes."


def test_a_direction_spanning_sentences_is_stripped_before_chunking():
    """The 22:01 direction ran over two sentences. Every path that chunks raw
    text must strip first, or each half keeps one asterisk and is read aloud."""
    root = Path(__file__).resolve().parents[1]
    srv = (root / "agent" / "server.py").read_text()
    assert "split_for_tts(_strip_stage_directions(reply))" in srv
    tm = (root / "modules" / "tts_module.py").read_text()
    assert "split_for_tts(_strip_stage_directions(text)" in tm
    from tts_chunker import split_for_tts
    raw = ("*Phoebe tilts her head. After a moment, she speaks softly:* "
           "Yes, I can hear you.")
    spoken = " ".join(split_for_tts(t._strip_stage_directions(raw)))
    assert "tilts" not in spoken and "Yes, I can hear you." in spoken
