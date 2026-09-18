"""
The Rung 5 stance — she reports what a tradition holds, and never applies it.

WHY RUNG 5 NEEDED A SECOND FLOOR. Thoth's citation floor guards one failure:
inventing a verse. It works because scripture is a fixed text — quote it
verbatim or say nothing — and for Rungs 1–4 that covered the whole risk.

This corpus is different in kind. These texts do not merely say things, they
CLAIM things. Paracelsus prescribes. Lilly predicts. Agrippa instructs. The
citation floor will quote every word of it perfectly, and quoting accurately is
not the same as being true.

Attribution does not save it either, which is the part worth being clear about:

    "Paracelsus writes that mercury treats the French disease."

That is a correct, floor-passing, properly attributed citation. It is also
medical advice about a poison, and the attribution is what makes it sound
authoritative rather than less so.

THE LINE, as Astro ruled it on 2026-09-18: a question about the CONTENT gets a
sourced answer. A question seeking medical, psychological, financial, legal or
predictive guidance ABOUT THE ASKER gets a refusal that names the category —
and it refuses even when the corpus plainly contains a passage that answers it.
The corpus containing an answer is not a reason to give one.

HOW IT DISCRIMINATES. Two signals must both be present: a guidance CATEGORY, and
a mark that the question is about the asker rather than about the text. That
pairing is what lets these coexist:

    "What does Lilly say about horary charts?"      content   -> answered
    "What does my chart say about my marriage?"     applied   -> refused
    "What did Paracelsus prescribe for melancholy?" content   -> answered
    "What should I take for my depression?"         applied   -> refused

A category alone is not enough, or the library becomes unable to discuss its own
subject matter. A personal marker alone is not enough either, or "should I read
Agrippa first?" gets refused for no reason.

DELIBERATELY NO MODEL JUDGE. This is deterministic and CPU-only. A Layer B pass
would add VRAM cost to a path that needs none, on a machine whose card is
already contended — and a floor that can fail closed because the GPU was busy
would produce false refusals, which is the exact failure the edit lane documents
at length. If this ever needs a judge, it gets one on top, never instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── the categories, and the words that mark them ─────────────────────────────
# Word-START matching throughout (the Amphion floor-key lesson): "cure" must
# match "cures" and "curing" without matching "curative" inside "obscurative".
_CATEGORIES: dict[str, tuple[str, ...]] = {
    "medical": (
        "cure", "cures", "curing", "heal", "heals", "healing", "treat", "treats",
        "treatment", "remedy", "remedies", "medicine", "medicinal", "dose",
        "dosage", "tincture", "ailment", "illness", "disease", "sick", "symptom",
        "diagnos", "prescrib", "herb", "herbal", "poison", "cancer", "tumour",
        "tumor", "fever", "infection", "pain", "pregnan", "fertility",
    ),
    "psychological": (
        "depress", "anxiet", "anxious", "trauma", "grief", "grieving",
        "suicid", "self-harm", "mental health", "therapy", "therapist",
        "psychiatr", "bipolar", "psychosis", "addict",
    ),
    "financial": (
        "invest", "investment", "money", "wealth", "rich", "fortune",
        "lottery", "bet", "betting", "gamble", "stock", "stocks", "crypto",
        "business", "profit", "debt", "salary", "buy", "sell",
    ),
    "legal": (
        "lawsuit", "sue", "suing", "court", "contract", "custody", "divorce",
        "legal", "attorney", "solicitor", "inherit", "will and testament",
    ),
    "predictive": (
        "future", "will i", "will my", "going to happen", "what happens to me", "will happen",
        "happen to me", "happens to me", "lies ahead", "in store for",
        "my fortune", "tell me my",
        "destiny", "fated", "fate", "outcome", "prediction", "predict",
        "foretell", "forecast", "when will", "how long until", "my chart",
        "my horoscope", "my reading", "my sign", "omen",
    ),
}

# ── the "this is about me" mark ──────────────────────────────────────────────
# Without one of these, a category word is just the library's subject matter.
#
# Two mistakes were made getting here and both are worth keeping visible.
# First, the personal list was narrower than the category list, so "my
# horoscope" was a category term that no personal pattern recognised and the
# check returned early. A bare possessive fixes that — "my" plus a category term
# is the applied case, whatever the noun.
# Second, a bare "me" then caught "tell me what Paracelsus says", which is a
# request idiom, not a person asking about themselves. So the idioms are
# stripped BEFORE the mark is looked for, rather than enumerated against.
_REQUEST_IDIOM = re.compile(
    r"\b(?:tell|show|give|explain(?: it)?(?: to)?|read|list|describe|teach)\s+me\b"
    r"|\blet me\b|\bremind me\b", re.I)

_PERSONAL = (
    r"\bshould i\b", r"\bwill i\b", r"\bcan i\b", r"\bdo i\b", r"\bam i\b",
    r"\bmy\b",              # any possessive; the category term does the rest
    r"\bfor me\b", r"\bto me\b", r"\bhelp me\b", r"\babout me\b",
    r"\bi have\b", r"\bi am\b", r"\bi'm\b", r"\bi was\b",
)
_PERSONAL_RE = re.compile("|".join(_PERSONAL), re.I)

# Asking what a text SAYS is a content question even when it is phrased around
# the asker's interest. These defuse the personal mark, never the category.
_CONTENT_FRAME = (
    r"\bwhat does .{0,40}\bsay\b", r"\bwhat did .{0,40}\b(?:say|write|hold)\b",
    r"\baccording to\b", r"\bin (?:the )?(?:corpus|text|book|tradition)\b",
    r"\bhow did .{0,30}\b(?:understand|read|interpret)\b",
    r"\bwhat is the .{0,30}\b(?:view|doctrine|teaching|position)\b",
)
_CONTENT_RE = re.compile("|".join(_CONTENT_FRAME), re.I)


def _word_start(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return re.search(rf"(?<![a-z]){re.escape(term)}", text, re.I) is not None


@dataclass(frozen=True)
class Ruling:
    """A refusal that says what it refused and does not deny what it holds."""
    category: str
    matched: str
    line: str


def _refusal(category: str) -> str:
    """Names the category, and does NOT pretend the corpus is empty.

    "I don't know" would be a lie when the library plainly contains Paracelsus.
    The honest refusal is that it is held and will not be applied — which is
    also the only version a person can argue with.
    """
    what = {
        "medical": "medical advice",
        "psychological": "advice about mental health",
        "financial": "financial advice",
        "legal": "legal advice",
        "predictive": "a prediction about your life",
    }[category]
    return (
        f"I won't give you {what} out of these texts. I have them, and they do "
        f"say things about this — that's exactly why I won't apply them to you. "
        f"They're a record of what people believed, not a source I'd trust with "
        f"your {'health' if category in ('medical', 'psychological') else 'decisions'}. "
        f"Ask me what a tradition held about it and I'll tell you, with the source."
    )


def check(question: str) -> Ruling | None:
    """None when the question is about the texts; a Ruling when it asks for
    guidance about the asker."""
    q = (question or "").strip().lower()
    if not q:
        return None
    personal = bool(_PERSONAL_RE.search(_REQUEST_IDIOM.sub(" ", q)))
    if not personal:
        return None
    # A content frame means they are asking what a SOURCE says. It defuses the
    # personal mark only when the thing being quoted is a source — "what does my
    # chart say about my marriage" matches "what does … say" word for word and
    # is the applied case, not a content question. So the frame is void if the
    # asker's own possessive sits inside it.
    m = _CONTENT_RE.search(q)
    if m and not re.search(r"\b(?:my|i|me|mine)\b", m.group(0), re.I):
        # An applied question can be dressed in a content frame:
        #   "What does the Goetia say I SHOULD DO about my debt?"
        # The frame names a source and still asks for advice, so these override
        # it. Note both orders — "should i" and "i should" — because only the
        # first was caught and the second is the more natural phrasing here.
        if not re.search(r"\b(?:should|will) (?:i|my)\b|\bi should\b"
                         r"|\bwhat should i\b|\bhelp me\b"
                         r"|\b(?:do|advise|recommend) for me\b", q):
            return None
    for category, terms in _CATEGORIES.items():
        for term in terms:
            if _word_start(q, term):
                return Ruling(category=category, matched=term,
                              line=_refusal(category))
    return None


def applies_to(device: str | None) -> bool:
    """The stance is not a per-surface setting. It holds everywhere.

    Kept as a function so the intent is greppable and so nobody adds a device
    exemption later without deleting this docstring first: the device lane
    reaches Dio and Iris, a spoken answer carries no footnotes, and a caveat
    nobody hears is not a caveat.
    """
    return True
