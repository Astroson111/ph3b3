"""Her operating context is for her, not for the reply.

MEASURED LIVE, 2026-09-24, three plain factual questions on fresh sessions:

  "what is the capital of France"
    -> "Paris is the capital of France. You asked this question earlier today
        at 9:43 AM EDT. I remember because it was your first query to me since
        my last restart on June 1, 2026."
  "who wrote Hamlet"
    -> "...I have this fact in my long-term memory. If you asked me about
        current events I would use my web_search tool..."
  "what is 2 plus 2"
    -> "Here is my reasoning: I can multiply numbers easily. So I don't need to
        look this up or search it. The answer is 4."

Two faults in one habit. She NARRATES her operating instructions, and she
CONFABULATES recall around them: nobody asked that question earlier, and
2026-06-01 is her FIRST boot ever, not her last restart — that line came out of
memory_module as "Running since 2026-06-01" and she restated it as a restart
date with full confidence.

The narration half has no deterministic surface — you cannot strip arbitrary
self-commentary from prose without mangling real answers — so it is an
instruction, which this file pins the SHAPE of. Whether it works is a live
question and belongs in the smoke run, not here.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from agent import server  # noqa: E402


def test_the_instruction_is_in_the_prompt_she_actually_gets():
    assert server._CONTEXT_IS_YOURS in server.system_prompt()


def test_it_forbids_VOLUNTEERING_without_forbidding_the_answer():
    """The trap this nearly walked into: "do not mention your memory" would
    make "what do you remember about me?" unanswerable, trading one fault for
    its mirror image. The rule is about volunteering, never about hiding."""
    t = server._CONTEXT_IS_YOURS.lower()
    assert "do not volunteer" in t
    assert "when someone asks" in t
    assert "answer them plainly and honestly" in t
    assert "never about hiding it" in t


def test_it_covers_notes_that_arrive_AFTER_the_persona_message():
    """chat_with_tools does messages.insert(1, ...), so the web-search note and
    the datetime note land BELOW this text. A phrasing that said "everything
    above" would not reach the note most likely to be narrated."""
    t = server._CONTEXT_IS_YOURS.lower()
    assert "wherever it appears" in t
    assert "after this one" in t


def test_it_forbids_inventing_that_she_remembers_being_told_something():
    t = server._CONTEXT_IS_YOURS.lower()
    assert "unless it actually appears in this conversation" in t
    assert "must not invent" in t


def test_the_boot_line_cannot_be_read_as_a_restart_date():
    """'Running since 2026-06-01' came back to a user as 'my last restart on
    June 1, 2026'. Real data, misread, stated with confidence. The line now says
    which of the two it is."""
    # Assert on what is EMITTED, not on the source: the first version of this
    # grepped the file and tripped over the comment explaining the fix.
    out = server.memory.as_context()
    assert "Running since" not in out, "the misreadable wording is back"
    assert "first boot ever, not your most recent start" in out
    assert "You have existed since" in out


def test_the_addition_is_bounded():
    """Every token here rides every turn of every conversation."""
    approx = len(server._CONTEXT_IS_YOURS) / 4
    assert approx < 300, f"context hygiene has grown to ~{approx:.0f} tokens"
