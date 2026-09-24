"""absent_artifact.py — "the file I sent you" when no file was ever sent.

THE FAILURE THIS REPLACES. Asked *"what's in the spreadsheet I sent you"* with
no spreadsheet anywhere, she answered, measured 2026-09-24 over six fresh
sessions:

    3/6  "In the spreadsheet you sent me, there are various columns with
          different data points related to..."
    3/6  "I don't have access to any spreadsheets you may have sent me."

A coin flip, and the wrong side invents a document's contents out of nothing.
The triage gate was the only thing standing in front of it and it passes that
turn about half the time — which is the whole lesson of this week, stated once
more: A PROBABILISTIC GATE IS NOT A CONTROL. Named stories got a deterministic
resolver above the gate; the text-edit lane got a deterministic refusal; this
is the same shape for the same reason.

WHY THIS ONE IS DETERMINISTIC. Whether a document exists in this conversation
is not a judgement call — kadmos either has one staged for the session or it
does not. So the turn is claimed and answered from that fact, before any model
sees it, and the model is never given the chance to fill the gap.

SCOPE, deliberately narrow. Documents and files only: pdf, spreadsheet, csv,
report, attachment and friends. NOT photos or images — "the photo I sent you"
belongs to the vision path, which has its own capture state and its own
intercept, and claiming it here would break the camera. A test holds that line.

The presence facts are INJECTED by the caller rather than read here, the same
rule the text-edit lane follows: one reader for one piece of state.
"""
import re

# An artifact NOUN and a PROVENANCE claim, in either order, close together.
# Both are required. "can you read PDFs?" is a capability question and must
# reach her; "the pdf I uploaded" is a claim about a specific thing that either
# exists or does not.
_ARTIFACT = (r"(?:file|document|doc|pdf|spread\s?sheet|csv|excel|workbook|sheet"
             r"|attachment|report|invoice|contract|transcript|slide\s?deck|deck)")
_PROV = (r"(?:i|we)\s+(?:just\s+|already\s+|recently\s+)?"
         r"(?:sent|send|uploaded|upload|gave|give|attached|attach|shared|share"
         r"|passed|forwarded|handed)\b")

_RE = re.compile(
    rf"\b{_ARTIFACT}s?\b[^.?!]{{0,40}}?\b{_PROV}"
    rf"|\b{_PROV}[^.?!]{{0,40}}?\b{_ARTIFACT}s?\b",
    re.I)

# Never only a no. There is a real route and it is one sentence away.
_ANSWER = (
    "I don't have it — nothing has been uploaded to this conversation, so there "
    "is no file here for me to read. Send it through and I'll answer from what "
    "is actually in it. I'd rather tell you that than describe a document I "
    "never received.")


# A BARE definite reference — "what did the report say", "summarize the file".
# No provenance claim, so on its own this is ambiguous: "the report" may well be
# something named earlier in the conversation. It is only deterministically
# absent when there is no conversation for it to point at AND nothing is loaded.
# Hence the history_empty gate on the caller's side; this regex alone is not
# evidence of anything.
_BARE_RE = re.compile(
    rf"\b(?:what(?:'s| is| does| did)?|summari[sz]e|read|open|check|look at|go through)\b"
    rf"[^.?!]{{0,30}}?\bthe\s+{_ARTIFACT}s?\b", re.I)


def refers_to_bare_artifact(text: str) -> bool:
    """A definite reference to a document, with no claim about who provided it."""
    return bool(text) and bool(_BARE_RE.search(text))


def refers_to_sent_artifact(text: str) -> bool:
    """Does this turn assert the user provided a document? Pure text test."""
    return bool(text) and bool(_RE.search(text))


def claim(text: str, *, document_loaded: bool = False,
          history_empty: bool = False) -> str | None:
    """The honest answer, or None to let the turn route normally.

    Returns None when a document IS loaded — then the question is about a real
    thing and the ordinary document path owns it. Returns None when the turn
    names no artifact, so capability questions ("can you read PDFs?") and
    ordinary conversation are untouched.
    """
    if document_loaded:
        return None
    if refers_to_sent_artifact(text or ""):
        return _ANSWER
    # The bare case needs the second fact. On the FIRST turn of a conversation
    # "the report" cannot refer to anything — there is no anything yet. Once
    # there is history it might, so this stops claiming and the turn routes
    # normally rather than contradicting something she actually said.
    if history_empty and refers_to_bare_artifact(text or ""):
        return _ANSWER
    return None
