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

_SYSTEM = (
    "You are a triage gate for an assistant that has general knowledge and live "
    "tools (web search, weather, music, recipes, screenshots, vision). Decide "
    "whether the user's request can be answered responsibly from the provided "
    "context, from general knowledge, or via those tools. It is NOT answerable "
    "only when it refers to a specific file, artifact, or prior detail that is "
    "absent from the context and cannot be fetched. "
    'Return strict JSON: {"answerable": bool, "missing": [strings], '
    '"question": string or null}. When answerable is false, "question" MUST be a '
    "short, natural question asking the user for the missing information "
    '(e.g. "Which file do you mean?") — never a restatement of their request. '
    "Nothing else."
)


def _clarifying(missing: list, user_text: str, model_q: str | None) -> str:
    """Guarantee a sensible spoken question on a hold: prefer the model's, but
    reject an empty one or a verbatim echo of the request; fall back to the
    missing fields, then to a generic ask."""
    mq = (model_q or "").strip()
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


async def triage_gate(user_text: str, context: str) -> TriageResult:
    """Decide whether `user_text` is answerable given `context`.

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
                    {"role": "system", "content": _SYSTEM},
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
