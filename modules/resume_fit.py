"""
resume_fit.py — relevance-weighted cutting for Ariadne.

When a built resume overflows its page target, something has to go. Cutting the
tail, or the oldest entries, kills the wrong lines: a 2016 bullet that answers
the posting outranks a 2024 bullet that does not. So score every cuttable line
and remove the lowest first.

Three terms, per brief:
  relevance    keyword and semantic overlap with the target posting
  uniqueness   a claim already made elsewhere is cheap to lose; a singular one
               is not
  dependency   a line the summary/profile leans on is near-uncuttable — cutting
               it strands a claim the top of the document already made

RECENCY IS DELIBERATELY NOT A TERM. That is the entire point of the change: an
older bullet that hits the posting must outrank a recent one that misses.

┌─ TRUTHFULNESS ──────────────────────────────────────────────────────────────┐
│ This module only ever REMOVES and REORDERS. It cannot introduce a word into  │
│ the document — nothing here writes prose, and no LLM is called. Cutting       │
│ changes emphasis; it must never change the factual record, which is why the  │
│ never-cuttable set below is enforced STRUCTURALLY rather than by asking a     │
│ model nicely.                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("ph3b3.ariadne.fit")

# Block kinds that are never content-to-lose. Removing the name or contact block
# does not de-emphasise anything, it damages the document.
_PROTECTED_KINDS = frozenset({"name", "contact", "header"})

# Sections whose body IS the factual record. Cutting a credential or a date
# changes what the document asserts about the candidate rather than what it
# emphasises — a different act entirely, and not one a page-fitting routine is
# entitled to perform.
_PROTECTED_SECTIONS = frozenset({"EDUCATION", "CERTIFICATIONS"})

# A line carrying a date is load-bearing for the employment record: it is a role
# header, a tenure, or a gap-of-record boundary. Never cuttable.
_DATE_RE = re.compile(
    r"(?:\b(19|20)\d{2}\b)|(?:\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(19|20)\d{2})",
    re.I,
)

_STOP = frozenset("""
a an the and or but if then than that this these those of in on at to for with by from as is are was
were be been being it its their they them our we you your i he she his her not no do does did have has
had will would can could should may might must about into over under out up down more most other some
such only own same so too very s t just don now
""".split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#.]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


@dataclass
class Line:
    """One cuttable-or-not line, with the arithmetic that decided it."""
    index: int                      # position in the original block list
    kind: str
    text: str
    section: str = ""
    cuttable: bool = True
    protected_reason: str = ""
    relevance: float = 0.0
    uniqueness: float = 0.0
    dependency: float = 0.0
    score: float = 0.0

    def why(self) -> str:
        if not self.cuttable:
            return f"protected ({self.protected_reason})"
        return (f"score {self.score:.2f} "
                f"[relevance {self.relevance:.2f}, uniqueness {self.uniqueness:.2f}, "
                f"dependency {self.dependency:.2f}]")


def classify(blocks: list[tuple[str, str]]) -> list[Line]:
    """Walk the block list, tagging each line with its section and whether it may
    be cut. Section state is tracked as we go, since blocks are a flat sequence."""
    out: list[Line] = []
    section = ""
    for i, (kind, text) in enumerate(blocks):
        if kind == "header":
            section = (text or "").strip().upper()
        ln = Line(index=i, kind=kind, text=text or "", section=section)

        if kind in _PROTECTED_KINDS:
            ln.cuttable, ln.protected_reason = False, f"{kind} is structural"
        elif section in _PROTECTED_SECTIONS:
            ln.cuttable, ln.protected_reason = False, f"{section.lower()} is part of the factual record"
        elif _DATE_RE.search(ln.text):
            ln.cuttable, ln.protected_reason = False, "carries a date (role/tenure/gap of record)"
        out.append(ln)
    return out


def _summary_tokens(lines: list[Line]) -> set[str]:
    return set().union(*[_tokens(l.text) for l in lines if l.section == "SUMMARY"] or [set()])


def score(lines: list[Line], jd_required: list[str] | None = None,
          jd_preferred: list[str] | None = None, job_text: str = "") -> list[Line]:
    """Fill in relevance / uniqueness / dependency / score for every cuttable line.

    Weights: relevance dominates (it is the whole thesis), dependency guards the
    summary's claims, uniqueness breaks ties between two equally-relevant lines
    by preferring to drop the one that repeats something.
    """
    req = {t.lower() for t in (jd_required or [])}
    pref = {t.lower() for t in (jd_preferred or [])}
    jd_tok = _tokens(job_text)
    summary_tok = _summary_tokens(lines)

    cuttable = [l for l in lines if l.cuttable]
    tok_cache = {l.index: _tokens(l.text) for l in cuttable}

    for l in cuttable:
        t = tok_cache[l.index]
        if not t:
            l.relevance = l.uniqueness = l.dependency = l.score = 0.0
            continue

        low = l.text.lower()
        hard = sum(1 for k in req if k in low) * 1.0 + sum(1 for k in pref if k in low) * 0.5
        soft = len(t & jd_tok) / len(t) if jd_tok else 0.0
        l.relevance = min(1.0, hard / 3.0) * 0.7 + soft * 0.3

        # Uniqueness: 1.0 when nothing else says this. Compared against OTHER
        # cuttable lines only — echoing a protected role header is not repetition.
        best = 0.0
        for o in cuttable:
            if o.index == l.index:
                continue
            ot = tok_cache[o.index]
            if not ot:
                continue
            j = len(t & ot) / len(t | ot)
            best = max(best, j)
        l.uniqueness = 1.0 - best

        # Dependency: does the summary lean on this line's distinctive terms?
        # Terms shared with the summary AND rare among other lines.
        #
        # A SUMMARY line is skipped outright — it IS the summary, so measuring its
        # overlap with itself returns ~1.0 and hands the profile statement a
        # maximum dependency score it did not earn. Left in, the summary survived
        # cuts for the wrong reason, and the term stopped meaning anything.
        if summary_tok and l.section != "SUMMARY":
            shared = t & summary_tok
            rare = {w for w in shared
                    if sum(1 for o in cuttable if o.index != l.index and w in tok_cache[o.index]) == 0}
            l.dependency = min(1.0, (len(shared) * 0.15) + (len(rare) * 0.35))

        l.score = 0.55 * l.relevance + 0.30 * l.dependency + 0.15 * l.uniqueness
    return lines


@dataclass
class CutPlan:
    cut_indices: list[int] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    protected_count: int = 0
    exhausted: bool = False          # nothing cuttable left, and it still does not fit

    def report(self) -> list[str]:
        if not self.cut_indices:
            return ["  (nothing cut)"]
        return [f"  − {r}" for r in self.rationale]


def plan_cuts(blocks: list[tuple[str, str]], n: int,
              jd_required: list[str] | None = None,
              jd_preferred: list[str] | None = None,
              job_text: str = "") -> CutPlan:
    """Choose the n lowest-scoring cuttable lines. Returns the plan and the
    justification for each cut, so the report can state what went and why and the
    user can overrule it."""
    plan = CutPlan()
    if n <= 0:
        return plan
    lines = score(classify(blocks), jd_required, jd_preferred, job_text)
    plan.protected_count = sum(1 for l in lines if not l.cuttable)

    candidates = sorted((l for l in lines if l.cuttable), key=lambda l: (l.score, -l.index))
    if len(candidates) < n:
        plan.exhausted = True
        log.warning("[ariadne] cut plan wants %d lines but only %d are cuttable — "
                    "%d protected", n, len(candidates), plan.protected_count)

    for l in candidates[:n]:
        plan.cut_indices.append(l.index)
        plan.rationale.append(f'"{l.text[:64]}" — {l.why()}')
    return plan


def apply_cuts(blocks: list[tuple[str, str]], cut_indices: list[int]) -> list[tuple[str, str]]:
    """Remove the planned lines, then drop any section header left with no body.
    A header standing alone over nothing is worse than the overflow it fixed."""
    drop = set(cut_indices)
    kept = [b for i, b in enumerate(blocks) if i not in drop]
    out: list[tuple[str, str]] = []
    for i, (kind, text) in enumerate(kept):
        if kind == "header":
            nxt = kept[i + 1] if i + 1 < len(kept) else None
            if nxt is None or nxt[0] == "header":
                continue
        out.append((kind, text))
    return out
