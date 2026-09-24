"""The boot line cannot be read as a restart date.

2026-09-24: asked "what is the capital of France" she answered "Paris is the
capital of France. You asked this question earlier today at 9:43 AM EDT. I
remember because it was your first query to me since my last restart on June 1,
2026."

Only ONE clause in that was false. memory_module emitted "Running since
2026-06-01" — her FIRST boot ever, months back — and she restated it as her
last restart. Real data, misread, said with confidence. That is deterministic
and it is fixed at source, which is what this file holds.

THE REST WAS TRUE, and that is worth recording because it was nearly "fixed".
mnemosyne.db holds every one of those turns: a test harness had been asking the
same five questions all morning (rows 1519-1534). "You asked me this three
times in a row via nyx" was accurate recall, not confabulation. An
anti-confabulation instruction was written, shipped, measured live, found not
to work — 3/10 plain questions still volunteered context, and the "answer when
ASKED" half came out worse — and removed the same day. See the note above
system_prompt() in agent/server.py. If it is picked up again the lever is WHEN
the recall block is injected, not how the prompt is phrased.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

from agent import server  # noqa: E402


def test_the_boot_line_cannot_be_read_as_a_restart_date():
    # Assert on what is EMITTED, not the source: an earlier version of this
    # grepped the file and tripped over the comment explaining the fix.
    out = server.memory.as_context()
    assert "Running since" not in out, "the misreadable wording is back"
    assert "first boot ever, not your most recent start" in out
    assert "You have existed since" in out


def test_no_anti_narration_instruction_is_in_the_prompt():
    """It was tried, measured, and removed. A test so it is not re-added
    without someone reading why it failed first."""
    assert not hasattr(server, "_CONTEXT_IS_YOURS"), \
        "the reverted instruction is back — read the note above system_prompt()"
    p = server.system_prompt()
    assert "for you, not for the person you are talking to" not in p


def test_the_reason_it_was_reverted_is_recorded_in_the_code():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "Why there is no anti-narration instruction here" in src
    assert "The recall was REAL" in src
