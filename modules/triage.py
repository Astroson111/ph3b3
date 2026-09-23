"""
triage.py — clarification guard before main Hermes3 inference.

A generalized "insufficient context" exit: before the assistant confabulates an
answer to a context-starved request ("summarize the file" with no file, "what did
I tell you about that" with empty history), a fast triage call decides whether the
request is answerable and, if not, hands back a clarifying question to ask instead.

Clean-room implementation from the PH3B3 TRIAGE GATE spec (concept borrowed from
Quorum, AGPL-3.0 — no Quorum source was read or referenced).

Design guarantees:
  * FAIL OPEN on ANY error (answerable=True) — the guard can never be the thing
    that breaks Ph3b3. Every failure path logs a cause-differentiated line.
  * Hermes3 RESIDENT-ONLY: if the model is not already loaded (e.g. evicted during
    a Morpheus GPU swap) the gate fails open and does NOT trigger a reload. It
    never acquires or observes Morpheus' gpu_lock.
  * No new dependencies (stdlib + httpx, already used).
"""
import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("ph3b3.triage")

OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
HERMES_MODEL = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3"))
_HERMES_STEM = HERMES_MODEL.split(":")[0]

_TRIAGE_TIMEOUT = 2.0    # hard bound on the triage inference call
_PS_TIMEOUT     = 1.0    # residency pre-check
_MAX_TOKENS     = 120

_SYSTEM_HEAD = (
    "You are a triage gate for an assistant that has general knowledge and live "
    "tools (web search, weather, music, recipes, screenshots, vision). Decide "
    "whether the user's request can be answered responsibly from the provided "
    "context, from general knowledge, or via those tools. It is NOT answerable "
    "only when it refers to a specific file, artifact, or prior detail that is "
    "absent from the context and cannot be fetched. ")

_SYSTEM_TAIL = (
    'Return strict JSON: {"answerable": bool, "missing": [strings], '
    '"question": string or null}. When answerable is false, "question" MUST be a '
    "short, natural question asking the user for the missing information, and it "
    "MUST carry enough context to be answerable — name what you do have, or what "
    "you need, so the user is never asked to guess. Never a restatement of their "
    "request, and never a bare question like \"which one?\" that could be asked "
    "about anything. "
    "NEVER name, suggest or ask the user to pick a real musician, band, singer or "
    "recording artist. For anything musical, ask about STYLE, mood, era, "
    "instruments or tempo instead — \"what kind of sound?\", not \"which artist?\". "
    "Suggesting an artist pushes the user toward a request that will be refused. "
    "Nothing else."
)

# The unqualified prompt, unchanged — this is what a caller with no manifest
# gets, and what the clarifier tests assert against.
_SYSTEM = _SYSTEM_HEAD + _SYSTEM_TAIL


def _system_for(manifest: str | None) -> str:
    """The triage prompt, with the context manifest in the one place it makes
    sense: after the rule about absent artifacts, before the output format.

    Appending it at the END instead puts it after "Nothing else.", where it
    reads as an afterthought to the JSON contract rather than an exception to
    the answerability rule.
    """
    if not manifest or not manifest.strip():
        return _SYSTEM
    return _SYSTEM_HEAD + manifest.strip() + " " + _SYSTEM_TAIL

# A prompt is guidance; this is the guard. The clarifier runs on a local model
# that can ignore an instruction, and a question naming a real performer is
# exactly the steer the voice-clone floor exists to prevent — so a question that
# names somebody is replaced rather than shown.
_PERFORMER = r"(?:artists?|musicians?|bands?|singers?|vocalists?|performers?|groups?)"
_ARTIST_ASK_RE = re.compile(
    # "which artist", and "which outlaw country artist" — adjectives in between
    rf"\b(?:which|what|whose|name a|pick an?)\s+(?:[\w'-]+\s+){{0,4}}{_PERFORMER}\b"
    rf"|\b{_PERFORMER}\s+(?:do|would|are|did|should)\s+you\b"
    rf"|\bbased\s+on\s+(?:which|what)\b"
    rf"|\bsound(?:s|ing)?\s+like\s+(?:which|what|who)\b"
    rf"|\bin\s+the\s+style\s+of\s+(?:which|what|who)\b"
    rf"|\bwho\s+(?:should|would)\s+(?:it|the\s+\w+)\s+sound\s+like\b"
    rf"|\bwhose\s+(?:voice|vocals?|sound|style)\b", re.I)

# ...but a question about OUR OWN singer profiles is exactly the right question
# to ask. "Which of your saved singers?" points at the local list, names nobody,
# and blocking it would replace a good clarifier with a vaguer one.
_OWN_LIST_RE = re.compile(
    r"\b(?:your|my|the)\s+(?:saved\s+)?(?:singers?|voices?|profiles?|library|list)\b"
    r"|\bsaved\s+singers?\b|\bin\s+your\s+library\b", re.I)

_MUSIC_SAFE_ASK = ("What sort of sound are you after — style, mood, tempo, and what "
                   "the singer should be like? Describe it rather than naming anyone.")


def _scrub_artist_ask(q: str | None) -> str | None:
    """Replace a clarifying question that steers toward a named performer."""
    if q and _ARTIST_ASK_RE.search(q) and not _OWN_LIST_RE.search(q):
        return _MUSIC_SAFE_ASK
    return q


# A clarifying question that names nothing is a dead end: it asks the user to
# guess at a list only this process can see, costs a turn, and teaches nothing.
# The prompt's own EXAMPLE used to be "Which file do you mean?" and the model
# emitted it verbatim — which is the usual way an example fails. The example is
# gone, but the guard matches the SHAPE rather than that one string, because the
# next model will invent its own phrasing for the same dead end.
_BARE_ASK_RE = re.compile(
    r"^\s*(?:which|what)\s+"
    r"(?:file|one|story|stories|item|document|doc|thing|work|book|entry|record)s?\b"
    r"[^?]{0,40}?\?\s*$", re.I)


def _scrub_bare_ask(q: str | None) -> str | None:
    """Drop a clarifier that carries no information. Returning None sends
    _clarifying to its missing-fields fallback, which at least names what it is
    short of."""
    if q and _BARE_ASK_RE.match(q.strip()):
        return None
    return q


def _clarifying(missing: list, user_text: str, model_q: str | None) -> str:
    """Guarantee a sensible spoken question on a hold: prefer the model's, but
    reject an empty one or a verbatim echo of the request; fall back to the
    missing fields, then to a generic ask."""
    mq = _scrub_bare_ask(_scrub_artist_ask((model_q or "").strip()))
    if mq and len(mq) > 4 and mq.lower() != (user_text or "").strip().lower():
        return mq
    if missing:
        return ("I don't have enough to answer that yet — could you give me a bit "
                "more about " + ", ".join(str(m) for m in missing) + "?")
    return "I don't have enough to go on yet — could you give me a bit more detail?"


@dataclass
class TriageResult:
    answerable: bool
    missing: list = field(default_factory=list)
    question: str | None = None


def _fail_open(cause: str) -> TriageResult:
    # Cause-differentiated, never cause-agnostic. cause ∈ {TIMEOUT, PARSE, CONN, EVICTED}
    log.info("TRIAGE_FAILOPEN_%s", cause)
    return TriageResult(answerable=True, missing=[], question=None)


async def _hermes_resident(http: httpx.AsyncClient) -> bool:
    """True only if Hermes3 is already loaded. Never loads it."""
    try:
        ps = (await http.get(f"{OLLAMA_HOST}/api/ps", timeout=_PS_TIMEOUT)).json()
        return any(m.get("name", "").startswith(_HERMES_STEM)
                   for m in ps.get("models", []))
    except Exception:
        return False


def _parse(text: str) -> TriageResult | None:
    """Strict JSON → prose fallback → None (caller fails open)."""
    if not text:
        return None
    # 1. strict JSON (possibly wrapped in prose/fences — grab the first {...})
    for candidate in (text, *re.findall(r"\{.*?\}", text, re.S)):
        try:
            obj = json.loads(candidate)
            ans = bool(obj["answerable"])
            missing = [str(x) for x in (obj.get("missing") or [])]
            q = obj.get("question")
            return TriageResult(ans, missing, q if not ans else None)
        except Exception:
            continue
    # 2. prose fallback — scan for an answerable verdict
    m = re.search(r"answerable\D{0,6}(true|false|yes|no)", text, re.I)
    if m:
        ans = m.group(1).lower() in ("true", "yes")
        q = None
        if not ans:
            qm = re.search(r'question\D{0,6}["\']([^"\']{3,})["\']', text, re.I)
            q = qm.group(1) if qm else None
        return TriageResult(ans, [], q)
    # 3. total failure
    return None


async def triage_gate(user_text: str, context: str,
                      manifest: str | None = None) -> TriageResult:
    """Decide whether `user_text` is answerable given `context`.

    `manifest` names what prompt-assembly will add to the context AFTER this
    gate runs (see modules/context_manifest.py). It teaches the gate what will
    exist; it never tells it what to permit. Default None keeps every existing
    caller and test on the exact prompt they had.

    NEVER raises. Returns answerable=True (fail open) on timeout, parse failure,
    connection error, or an evicted model. Only a confident model verdict of
    answerable=False holds the turn.
    """
    try:
        async with httpx.AsyncClient() as http:
            if not await _hermes_resident(http):
                return _fail_open("EVICTED")   # resident-only — no reload trigger

            payload = {
                "model": HERMES_MODEL,
                "messages": [
                    {"role": "system", "content": _system_for(manifest)},
                    {"role": "user",
                     "content": f"CONTEXT:\n{context or '(none)'}\n\nREQUEST:\n{user_text}"},
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0, "num_predict": _MAX_TOKENS},
            }
            try:
                r = await asyncio.wait_for(
                    http.post(f"{OLLAMA_HOST}/api/chat", json=payload,
                              timeout=_TRIAGE_TIMEOUT),
                    timeout=_TRIAGE_TIMEOUT,
                )
            except (asyncio.TimeoutError, httpx.TimeoutException):
                return _fail_open("TIMEOUT")
            except httpx.HTTPError:
                return _fail_open("CONN")

            content = (r.json().get("message") or {}).get("content", "")
            result = _parse(content)
            if result is None:
                return _fail_open("PARSE")
            if not result.answerable:
                result.question = _clarifying(result.missing, user_text, result.question)
            return result

    except (asyncio.TimeoutError, httpx.TimeoutException):
        return _fail_open("TIMEOUT")
    except httpx.HTTPError:
        return _fail_open("CONN")
    except Exception:
        # Belt-and-suspenders: any unforeseen error still fails open.
        return _fail_open("CONN")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    async def _demo():
        for txt, ctx in [("what is the capital of France", ""),
                         ("summarize the file", ""),
                         ("what did I tell you about that", "")]:
            print(txt, "->", await triage_gate(txt, ctx))
    asyncio.run(_demo())
