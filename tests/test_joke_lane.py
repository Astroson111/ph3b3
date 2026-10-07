"""The joke lane is deterministic, and its triggers are narrow.

WHY IT EXISTS. "tell me a joke" had no lane. The only path was the tell_joke
tool at the model's discretion, and across five battery runs on 2026-10-05 the
same prompt scored 1/3, 0/3, 2/3, 0/3 and 3/3 — pure coin-flip. Worse, the tool
returned the literal string "Joke delivered." and nothing else, so when it DID
fire the model had to narrate around a result containing no joke, producing
"Here is a random joke I found" over a joke it had invented itself.

Same doctrine as fleet, head and Thoth: anything that must happen every time
gets a deterministic path, and the prompt is for character, never guarantees.

WHY THE TRIGGERS ARE TIGHT. A joke is something people talk ABOUT constantly.
"that's a joke", "the joke was that nobody came", "is this a joke?" are all
ordinary conversation, and a keyword match would eat every one of them. So the
pattern is anchored to the whole message, exactly like dio_head's head commands.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


def _joke_re():
    i = SRC.index("_JOKE_RE = re.compile(")
    j = SRC.index("re.I)", i) + 5
    ns = {"re": re}
    exec(SRC[i:j], ns)
    return ns["_JOKE_RE"]


JOKE_RE = _joke_re()


@pytest.mark.parametrize("text", [
    "tell me a joke", "Phoebe, tell me a joke", "tell me another joke",
    "give me a joke", "got any jokes?", "got a joke", "do you know any jokes",
    "make me laugh", "another joke", "can you tell me a joke please",
    "hey phoebe tell me a joke", "tell me one joke",
])
def test_a_joke_request_is_claimed(text):
    assert JOKE_RE.match(text), f"{text!r} did not claim the joke lane"


@pytest.mark.parametrize("text", [
    "that's a joke",
    "the joke was that nobody came",
    "is this a joke?",
    "I told a joke yesterday",
    "explain the joke",
    "jokes are hard to write",
    "tell me about the joke",
    "what did you think of my joke",
    "tell me a story",
    "tell me a joke about my tax return",   # a SUBJECT request, not the canon
])
def test_talking_about_jokes_is_not_a_joke_request(text):
    assert not JOKE_RE.match(text), f"{text!r} wrongly claimed the joke lane"


def test_the_lane_returns_the_joke_not_a_receipt():
    """The reply IS the joke, so the transcript records what was said."""
    i = SRC.index("def _answer_joke")
    body = SRC[i:SRC.index("intent_registry.register(\"jokes\"", i)]
    assert "return joke" in body, "the lane must return the joke text"
    assert "Joke delivered" not in body, "no receipts"
    assert "tts.speak" in body, "the joke should still be spoken"


def test_an_empty_canon_says_so_rather_than_inventing():
    i = SRC.index("def _answer_joke")
    body = SRC[i:SRC.index("intent_registry.register(\"jokes\"", i)]
    assert "if not joke" in body, "an empty canon must be reported, not papered over"


def test_the_tool_also_returns_the_joke():
    """The tool stays as the model's fallback, but it must hand back the text —
    a result the model cannot see is a result it will talk over."""
    i = SRC.index('elif name == "tell_joke"')
    body = SRC[i:i + 900]
    assert "result = joke" in body, "tell_joke must return the joke text"
    assert 'result = "Joke delivered."' not in body


def test_the_lane_logs_a_marker_so_it_can_be_measured():
    """fleet-status-* failed nine passes in every baseline because its lane
    emitted nothing. A lane nobody can see is a lane nobody can measure."""
    assert 'log.info("[joke]' in SRC
    markers = (ROOT / "tests" / "smoke" / "run_battery.py").read_text(encoding="utf-8")
    assert '"[joke]": "lane:joke"' in markers
    assert '"[fleet]": "lane:fleet"' in markers
