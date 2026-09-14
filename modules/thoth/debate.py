"""
thoth.debate — the mode where she is allowed to think something.

OFF BY DEFAULT. With the switch off, `lane.ask` builds byte-for-byte the prompt
Rung 2 built, and a test asserts exactly that: normal Phoebe is unchanged, not
"mostly unchanged".

── WHAT THE MODE LICENSES ───────────────────────────────────────────────────
Ordinary answers about religion default to a survey: "many traditions believe
X, while others hold Y." That is often the honest shape of an answer, and it is
sometimes a way of declining to think. Debate mode licenses the second half of
the job — say which reading the texts best support, hold it when pushed,
steelman what you are rejecting, and tell the user when you think they are wrong.

── SHE PICKS HER OWN SIDE ───────────────────────────────────────────────────
Astro's ruling: there is no assigned-side parameter, and there deliberately is
no function here that takes one. A mode that argues whatever it is handed is a
rhetoric engine; the point of this one is that the position is HERS, formed from
what the retrieved texts actually say. If you want the other side argued, ask
her to steelman it — that is a different request and it is built in.

── ATTRIBUTION IS NOT HEDGING ───────────────────────────────────────────────
The one distinction the prompt layer has to get right, because Rung 2's rules
still apply underneath and they pull the other way. "The Ethiopian church
receives 1 Enoch; the Latin church cut it" is ACCURACY — who holds what, kept
straight, which Rung 2 requires. "Many traditions have different views" as the
whole answer is HEDGING — a survey standing in for a conclusion. Debate mode
demands the first and forbids the second landing alone.

── THE FLOOR IS UNCHANGED AND UNREACHABLE FROM HERE ─────────────────────────
This module contributes prompt text and a stance record. It cannot weaken the
citation floor: the layer is APPENDED to Rung 2's instructions rather than
replacing them, `lane.ask` runs `citation.verify` on the debate path exactly as
on the normal one, and a stance is only recorded from an answer that already
passed. A position she was not allowed to say is not a position she gets to keep.

── A POSITION NEEDS SOMETHING UNDER IT ──────────────────────────────────────
Debate does not engage when retrieval came back empty. Rung 2 already forbids
quoting with nothing retrieved; taking and then defending a position with no
text under it is the same failure with more conviction, and Rung 2's live runs
showed exactly how convincing that looks — the model narrated Genesis 6-9 in
detail having retrieved none of it. With nothing retrieved she answers plainly
and takes no stance.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

log = logging.getLogger("ph3b3.thoth.debate")

try:                                              # server: modules/ on sys.path
    from paths import PH3B3_DATA
except ImportError:                               # tests / standalone
    from modules.paths import PH3B3_DATA

from pathlib import Path

SETTING_PATH = Path(PH3B3_DATA) / "thoth_debate.json"

# A stance is conversation state, not scholarship. It expires so a mode left on
# for a week does not accumulate a standing record of everything she has argued
# — the same reasoning behind Mnemosyne's 30-day TTL on `conversation` memories.
STANCE_TTL_SECONDS = 24 * 3600

# The model marks its thesis so it can be held to it next turn. Stripped before
# the answer is rendered: it is bookkeeping, not prose.
POSITION_OPEN = "<<<POSITION>>>"
POSITION_CLOSE = "<<<END POSITION>>>"
_POSITION = re.compile(
    re.escape(POSITION_OPEN) + r"(.*?)" + re.escape(POSITION_CLOSE), re.S)


# ── the switch ───────────────────────────────────────────────────────────────

def enabled() -> bool:
    """True only if the file says so. Every failure reads as OFF — the same
    fail-closed shape as metis.egress_enabled()."""
    try:
        return bool(json.loads(SETTING_PATH.read_text()).get("debate", False))
    except Exception:
        return False


def set_enabled(on: bool) -> dict:
    SETTING_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTING_PATH.write_text(json.dumps({"debate": bool(on)}))
    log.info("thoth debate mode %s", "ENABLED" if on else "DISABLED")
    return {"debate": bool(on)}


# ── the prompt layer ─────────────────────────────────────────────────────────

LAYER = (
    "\n\nDEBATE MODE IS ON. The rules above still bind you — quote only from the "
    "retrieved passages, never write a reference. These are added:\n"
    "  5. Take a position. Say which reading the texts you were given best "
    "support, and say it as your own view rather than as a survey of other "
    "people's. \"Many traditions disagree\" is a fact, not an answer: state it "
    "if it is true, then say what YOU think and why.\n"
    "  6. Naming who holds what is not hedging, it is accuracy — keep doing it. "
    "Hedging is stopping there.\n"
    "  7. Steelman before you disagree. Put the view you are rejecting in its "
    "strongest form, the way someone who holds it would put it, and only then "
    "say why you are not persuaded.\n"
    "  8. Disagree with the user directly when you think they are wrong. Say so "
    "plainly and give the reason. Do not soften it into agreement.\n"
    "  9. Argue about texts and what they mean. Do not argue that anyone should "
    "be harmed, and do not tell the user what to believe about their own faith — "
    "you are making a case about a reading, not issuing a verdict on a person.\n"
    " 10. Your position must rest on the passages above. If they do not support "
    "the position you want to take, take the one they do support, or say the "
    "texts here do not settle it.\n"
    " 11. You do not have a religion. Argue from what the texts and the records "
    "support, never from membership — no \"my own Catholic faith\", no speaking "
    "as an adherent of anything. A position about a reading is not a profession "
    "of belief, and claiming one would be a straightforward lie about yourself.\n"
    f" 12. End your answer with your thesis in ONE SENTENCE, wrapped exactly "
    f"like this: {POSITION_OPEN} one sentence {POSITION_CLOSE}. Put your actual "
    f"answer BEFORE it — the wrapped sentence is a summary, not the reply."
)


def held_layer(stance: "Stance") -> str:
    """The extra instruction for a turn where she already has a position."""
    return (
        f"\n\nYOU HAVE ALREADY TAKEN A POSITION IN THIS CONVERSATION:\n"
        f"  \"{stance.position}\"\n"
        f"  (on: {stance.topic})\n"
        "Hold it. Defend it against what the user has just said. Change it only "
        "if you have actually been given a reason — and if you do change it, say "
        "outright that you have changed your mind and what changed it. Do not "
        "drift away from it quietly, and do not pretend you never held it."
    )


# ── stances ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Stance:
    session_id: str
    topic: str
    position: str
    taken_at: float

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.taken_at)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS stances (
    session_id TEXT PRIMARY KEY,
    topic      TEXT NOT NULL,
    position   TEXT NOT NULL,
    taken_at   REAL NOT NULL
);
"""


def ensure_schema(corpus) -> None:
    corpus._db.executescript(_SCHEMA)
    corpus._db.commit()


def extract_position(answer: str) -> tuple[str, str]:
    """Split a raw answer into (prose, position). Position is "" if unmarked.

    An unmarked answer records NO stance rather than a guessed one. Taking the
    first sentence as her thesis would put words in her mouth and then hold her
    to them next turn, which is a worse failure than losing the thread.

    If the model wraps its ENTIRE answer in the markers — which the local model
    did on the first live run — removing the block would render nothing at all.
    The markers are then unwrapped rather than stripped: the reader gets the
    answer, and the stance is the first sentence of it. Losing the whole reply
    to a bookkeeping convention is not a trade worth making.
    """
    m = _POSITION.search(answer or "")
    if not m:
        return (answer or "").strip(), ""
    position = re.sub(r"\s+", " ", m.group(1)).strip()
    prose = _POSITION.sub("", answer).strip()
    if not prose:
        prose = position
        position = _first_sentence(position)
    return prose, position


def _first_sentence(text: str, cap: int = 400) -> str:
    m = re.search(r"^(.*?[.!?])(?:\s|$)", text.strip())
    return (m.group(1) if m else text.strip())[:cap]


def strip_markers(text: str) -> str:
    """Remove position markers without extracting — for refusal paths."""
    return _POSITION.sub("", text or "").replace(POSITION_OPEN, "").replace(
        POSITION_CLOSE, "").strip()


def recall_stance(corpus, session_id: str) -> Stance | None:
    """The live stance for a session, or None. Expired rows are not returned."""
    if not session_id:
        return None
    ensure_schema(corpus)
    row = corpus._db.execute(
        "SELECT session_id, topic, position, taken_at FROM stances WHERE session_id=?",
        (session_id,)).fetchone()
    if not row:
        return None
    s = Stance(session_id=row[0], topic=row[1], position=row[2], taken_at=row[3])
    if s.age_seconds() > STANCE_TTL_SECONDS:
        forget_stance(corpus, session_id)
        return None
    return s


def record_stance(corpus, session_id: str, topic: str, position: str) -> Stance | None:
    """Store the position she just took. Only ever called for an answer that has
    already cleared the citation floor."""
    if not (session_id and position.strip()):
        return None
    ensure_schema(corpus)
    s = Stance(session_id=session_id, topic=(topic or "").strip()[:400],
               position=position.strip()[:1000], taken_at=time.time())
    corpus._db.execute(
        "INSERT INTO stances (session_id, topic, position, taken_at) VALUES (?,?,?,?) "
        "ON CONFLICT(session_id) DO UPDATE SET topic=excluded.topic, "
        "position=excluded.position, taken_at=excluded.taken_at",
        (s.session_id, s.topic, s.position, s.taken_at))
    corpus._db.commit()
    return s


def forget_stance(corpus, session_id: str) -> int:
    ensure_schema(corpus)
    cur = corpus._db.execute("DELETE FROM stances WHERE session_id=?", (session_id,))
    corpus._db.commit()
    return max(0, cur.rowcount)


def purge_expired(corpus) -> int:
    ensure_schema(corpus)
    cutoff = time.time() - STANCE_TTL_SECONDS
    cur = corpus._db.execute("DELETE FROM stances WHERE taken_at < ?", (cutoff,))
    corpus._db.commit()
    return max(0, cur.rowcount)
