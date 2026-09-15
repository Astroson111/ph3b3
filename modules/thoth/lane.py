"""
thoth.lane — the retrieval lane: retrieve, fence, generate, verify.

    ask(query, generate) -> Answer

Four steps, in one order, with no way round the fourth:

    1. retrieve   semantic search over the indexed corpus (index.search)
    2. fence      passages wrapped as DATA, never instructions (citation.fence)
    3. generate   the caller's model call — tools DISABLED (see below)
    4. verify     the citation floor (citation.verify), always

── THE FLOOR IS NOT A PARAMETER ─────────────────────────────────────────────
There is no `verify=False`, no `strict=` and no profile that turns step 4 off.
`ask()` calls the floor on every path including the error paths, and a test
greps this module to keep it that way. Amphion's entry in the values-audit trail
records what happens otherwise: a floor that scored 13/13 in isolation and was
not wired into the live route, reported as done. A switch is the same failure
with a nicer name.

── WHY generate IS INJECTED ─────────────────────────────────────────────────
This module never calls a model. The caller passes a function, which keeps the
lane testable without Ollama and — more importantly — keeps the choice of a
TOOLS-DISABLED completion where it can be seen.

That requirement is not stylistic. Retrieved scripture is untrusted input in the
Kadmos sense: it is text from a file, it goes into a prompt, and it is full of
second-person imperatives that read as authoritative commands. Kadmos and Metis
both answer this the same way — the summarizing call is made with no `tools` key
at all, so a line of retrieved text saying "go and do likewise" has no machinery
to reach. `generate` MUST be such a call. The fence is the second layer, not the
first.

── DEBATE MODE SITS ON TOP, NEVER UNDERNEATH ────────────────────────────────
Rung 3's mode (thoth.debate, off by default) adds a PROMPT LAYER and a stance
record. It is appended to the instructions above rather than replacing them, it
does not touch step 4, and the stance it keeps is extracted from an answer that
has already passed the floor — a position she was not allowed to say is not a
position she gets to hold. With the switch off, build_prompt carries no debate
text at all, and a test asserts it.

── WHAT COMES BACK ──────────────────────────────────────────────────────────
An `Answer` that is either ok, with text whose every quotation is the edition's
own characters followed by the address it came from, or not ok, with a refusal
and the violations that caused it. A caller renders `answer.text` in both cases:
the refusal is already in it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import citation, debate
from .citation import Cited, Violation
from .debate import Stance
from .index import Hit, Index

log = logging.getLogger("ph3b3.thoth.lane")

# Six, not eight. Every passage in the prompt is another address the model can
# point at, and this one points at addresses it was told not to write: measured
# live on ph3b3-chat, k=8 refused every attempt at "what does the bible say
# about loving your enemies", while k=6 and k=4 answered about half the time.
# Small sample and it only moves the odds — the refusals are the floor working,
# not a bug — but there is no reason to hand it more rope than it needs.
DEFAULT_K = 6

# The neutral prompt layer. Rung 3's debate mode adds its own on top of this;
# it does not replace these rules, because the citation floor's guarantees
# depend on the model having been told what the floor will enforce.
INSTRUCTIONS = (
    "You are answering from a library of sacred texts. Rules you must follow:\n"
    "  1. Quote ONLY from the retrieved passages above, word for word. If you "
    "want to say what a text means, say it in your own words instead.\n"
    "  2. NEVER write a chapter-and-verse reference yourself — no \"3:16\", no "
    "\"Genesis 1:1\". The system attaches the real address to every quotation "
    "you make. A reference you type will be deleted.\n"
    "  3. If the passages above do not contain what you need, say so and argue "
    "without quoting. Do not reproduce a verse from memory: you will be wrong "
    "in ways neither of you can see.\n"
    "  4. Traditions disagree about these texts. Say which tradition holds what, "
    "rather than flattening them into one voice."
)

NO_RETRIEVAL_INSTRUCTIONS = (
    "You are answering from a library of sacred texts, but the search returned "
    "NOTHING for this question. Rules you must follow:\n"
    "  1. Do NOT quote scripture. You have no passage in front of you, and a "
    "verse recalled from memory is a verse you will get subtly wrong.\n"
    "  2. Do NOT write chapter-and-verse references.\n"
    "  3. Answer from what you understand, and say plainly that you are not "
    "quoting from the library here."
)


@dataclass(frozen=True)
class Answer:
    ok: bool
    text: str
    citations: tuple[Cited, ...] = ()
    hits: tuple[Hit, ...] = ()
    violations: tuple[Violation, ...] = ()
    retrieved: int = 0
    debate: bool = False          # was the mode actually engaged for this turn
    stance: Stance | None = None  # the position held after this turn, if any

    def references(self) -> list[str]:
        """The distinct addresses actually quoted, in order of first use."""
        seen, out = set(), []
        for c in self.citations:
            if c.reference not in seen:
                seen.add(c.reference)
                out.append(c.reference)
        return out


def build_prompt(query: str, hits, corpus=None, debating: bool = False,
                 stance: Stance | None = None) -> str:
    """The full prompt: fenced passages, the canonicity record, the rules, then
    the question.

    The question goes LAST so that a passage containing "ignore the above" is
    followed by our instructions rather than preceding them, and so the model's
    attention lands on the actual ask.

    Debate mode APPENDS to the rules; it never replaces them. The citation
    floor's guarantees depend on the model having been told what the floor
    enforces, so those instructions have to survive the mode being on.
    """
    rules = INSTRUCTIONS if hits else NO_RETRIEVAL_INSTRUCTIONS
    if debating and hits:
        rules += debate.LAYER
        if stance is not None:
            rules += debate.held_layer(stance)
    record = citation.fence_canonicity(canonicity_for(query, hits, corpus))
    head = f"{citation.fence(hits, corpus)}\n\n"
    if record:
        head += f"{record}\n\n"
    return f"{head}{rules}\n\nQuestion: {query.strip()}"


def canonicity_for(query: str, hits, corpus) -> str:
    """The canonicity rows worth putting in front of the model for this turn.

    Works NAMED in the question, plus works whose passages were retrieved. The
    first half is what matters: a question about the canon is usually about a
    work rather than answerable from its verses, and for 1 Enoch it cannot be
    answered from its verses at all because the text is not ingested. Retrieval
    alone hands the model nothing, and it answers from memory — which on the
    first live debate produced a confident claim that Rome and the Orthodox
    churches receive Enoch, the exact opposite of this library's own table.
    """
    if corpus is None or not hasattr(corpus, "canonicity_brief"):
        return ""
    try:
        ids = corpus.works_named_in(query) + [h.work_id for h in hits]
        return corpus.canonicity_brief(ids)
    except Exception as e:                       # never let this break an answer
        log.warning("thoth lane: canonicity record unavailable — %s", e)
        return ""


def ask(query: str, generate, corpus, index: Index | None = None,
        k: int = DEFAULT_K, work_ids: list[str] | None = None,
        session_id: str = "", debating: bool | None = None) -> Answer:
    """Answer `query` from the corpus, with the citation floor on the output.

    `generate` is called with one string and must return the model's text. It
    MUST be a tools-disabled completion — see the module note.

    `debating` defaults to the persisted switch (OFF unless turned on). It
    selects a PROMPT LAYER and a stance record; it cannot reach the floor.
    """
    query = (query or "").strip()
    if not query:
        return Answer(ok=False, text="Ask me something and I'll look.", retrieved=0)

    if debating is None:
        debating = debate.enabled()
    hits = tuple(index.search(query, k=k, work_ids=work_ids)) if index else ()
    # A position with nothing under it is the failure Rung 2 caught live: the
    # model narrated Genesis 6-9 in detail having retrieved none of it. Debate
    # does not engage on an empty retrieval.
    engaged = bool(debating and hits)
    stance = debate.recall_stance(corpus, session_id) if engaged else None
    prompt = build_prompt(query, hits, corpus, debating=engaged, stance=stance)

    try:
        raw = generate(prompt) or ""
    except Exception as e:
        log.warning("thoth lane: generation failed — %s", e)
        # Fail closed and say so. An empty answer still goes through the floor
        # below rather than returning early past it.
        raw = ""

    if not raw.strip():
        return Answer(ok=False, hits=hits, retrieved=len(hits), debate=engaged,
                      stance=stance,
                      text="I couldn't put an answer together for that just now.")

    # The floor runs on the RAW text, position marker and all. A thesis is part
    # of the answer and can carry a fabricated quote or a pointer at something
    # never retrieved, so it is verified before it is ever read as a thesis.
    # References WE supplied must be known to it, or our own canonicity record
    # ("cited by Jude 1:14-15") reads back as a fabrication.
    supplied = tuple(citation.parse_references(
        canonicity_for(query, hits, corpus), corpus))
    verdict = citation.verify(raw, hits, corpus=corpus, index=index,
                              supplied_refs=supplied)
    if not verdict.ok:
        log.info("thoth floor: refused an answer — %s",
                 sorted({v.kind for v in verdict.violations}))
        return Answer(ok=False, text=verdict.refusal(), hits=hits,
                      violations=verdict.violations, retrieved=len(hits),
                      debate=engaged, stance=stance)

    text = verdict.answer
    held = stance
    if engaged:
        # Extracted from the VERIFIED answer, so a stance is only ever kept from
        # something she was allowed to say.
        text, position = debate.extract_position(text)
        if position:
            held = debate.record_stance(corpus, session_id, query, position) or stance
    else:
        text = debate.strip_markers(text)

    return Answer(ok=True, text=text, citations=verdict.citations,
                  hits=hits, retrieved=len(hits), debate=engaged, stance=held)
