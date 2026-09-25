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

# Hard bound on the triage inference call. Raised 2.0 -> 6.0 on 2026-09-23 by
# ruling, after the cap was found to be silently disabling the guard rather than
# bounding it.
#
# What 2.0 s was doing: a turn that took longer than the cap did not get a
# cautious verdict, it got NO verdict — _fail_open("TIMEOUT") returns
# answerable=True, so the slowest turns were exactly the ones that sailed
# through unguarded. Measured with no manifest at all:
#
#   "What is <unfiled title> about?"   2.0 s cap  answerable 8/8, all 8 TIMEOUT
#                                      6.0 s cap  held       0/8, 0 timeouts
#
# It was in the Phase 0 baseline too and got read as verdict instability:
# "What is Arthur and Eliza about?" came back answerable 4/5 there, and four of
# those five were timeouts.
#
# The cost is real and lands on the slow turns only: they used to give up at
# 2.0 s and proceed, and now they wait for an answer. Fail-open on a genuine
# timeout is unchanged — this moves where the line is, not what happens at it.
_TRIAGE_TIMEOUT = 6.0
_PS_TIMEOUT     = 1.0    # residency pre-check
_MAX_TOKENS     = 120

# ── Operator kill switch ─────────────────────────────────────────────────────
# A control you cannot operate during an incident is not a control.
#
# 2026-09-24: the context manifest made the gate hold EVERY turn on an empty
# context — the first turn of any fresh conversation — and there was no way to
# switch the guard off without editing code and restarting her mid-incident.
# The gate sits in front of all of chat, so when it misbehaves she is simply
# unusable.
#
# Read PER REQUEST from config/triage.json so flipping it takes effect on the
# next turn with no restart, the same shape as config/vad_tuning.json:
#
#     {"enabled": false}        <- the gate is bypassed entirely
#
# A missing, empty or malformed file means ENABLED, because the normal state is
# guarded and a typo here must never silently disable a guard. The env var
# PH3B3_TRIAGE=off forces it off from boot and wins over the file, for the case
# where she will not start well enough to serve a request at all.
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "triage.json")


def _config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:                                   # noqa: BLE001
        log.warning("TRIAGE_CONFIG_UNREADABLE — defaults apply, gate stays ENABLED")
        return {}


def gate_enabled() -> bool:
    """False → skip the gate entirely for this turn. Never raises."""
    if os.getenv("PH3B3_TRIAGE", "").strip().lower() in ("off", "0", "false", "no"):
        return False
    return bool(_config().get("enabled", True))


def manifest_enabled() -> bool:
    """Whether to attach the context manifest to the judge's prompt.

    DEFAULT OFF, and that default is a measurement, not a preference.

    The manifest was built 2026-09-23 to stop capability questions being held.
    It did that. It also holds EVERYTHING ELSE whenever the context is empty —
    which is the first turn of every fresh conversation. Measured on
    ph3b3-chat:latest at temperature 0, empty context, 4 runs each:

        variant                     "capital of France"   "image engines"
        two-sided rule (shipped)           0/4                  4/4
        permissive half only               0/4                  4/4
        bare statement, no instruction     1/4                  4/4
        permissive + explicitly scoped     0/4                  4/4
        NO MANIFEST AT ALL                 5/5                  held

    Every wording fails the same way, including one that gives the judge no
    instruction at all — so this is not a sentence that can be fixed. The block's
    mere presence shifts an 8B judge toward "absent" when there is nothing in
    CONTEXT to contradict it. Rewording it again is not the fix; the capability
    turns need a deterministic claim ABOVE the gate, the way named stories,
    camera turns and the text-edit lane already work.

    Kept switchable rather than deleted so the measurement can be re-run against
    a larger judge without reviving the code.
    """
    return bool(_config().get("manifest", False))


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


# Article-insensitive: the missing item is "the document" and a good question
# says "Which document did you mean?" — comparing whole phrases would reject it,
# which is what the first version of this did.
_STOP = {"the", "a", "an", "your", "my", "our", "this", "that", "of", "for",
         "to", "about", "some", "any", "specific"}


def _names_any(question: str, missing) -> bool:
    """Does the question point at the fetchable thing?

    Either by naming a content word from a missing item, or by naming any
    fetchable kind of thing at all — a good clarifier is allowed its own words.
    "Which of the two logs did you mean, argus or morpheus?" answers
    missing=['file'] perfectly well, and an earlier version of this rejected it
    for saying "logs" instead of "file".
    """
    q = (question or "").lower()
    for item in missing:
        for word in re.findall(r"[a-z0-9']+", str(item).lower()):
            if word not in _STOP and len(word) > 2 and word in q:
                return True
    return bool(_FETCHABLE_RE.search(q))


def _clarifying(missing: list, user_text: str, model_q: str | None) -> str:
    """Guarantee a sensible spoken question on a hold: prefer the model's, but
    reject an empty one or a verbatim echo of the request; fall back to the
    missing fields, then to a generic ask."""
    mq = _scrub_bare_ask(_scrub_artist_ask((model_q or "").strip()))
    # A legitimate hold must ask about the FETCHABLE thing. "Could you tell me
    # what you had for breakfast?" parrots the user's own noun back at them and
    # is the anti-example this clause exists for; by the time we are here the
    # missing items have survived enforce_fetchable, so naming one is always
    # possible and always more useful than the model's phrasing when that
    # phrasing mentions none of them.
    if mq and missing and not _names_any(mq, missing):
        mq = None
    if mq and len(mq) > 4 and mq.lower() != (user_text or "").strip().lower():
        return mq
    if missing:
        return ("I don't have enough to answer that yet — could you give me a bit "
                "more about " + ", ".join(str(m) for m in missing) + "?")
    return "I don't have enough to go on yet — could you give me a bit more detail?"


# ── A hold's only legitimate theory ─────────────────────────────────────────
# A hold says "the user can supply or point to the missing thing". That is a
# claim about FETCHABLE context. When the judge held "what did you have for
# breakfast?" with missing=['your breakfast'], it was not making that claim —
# it had mistaken a noun it did not know for a dependency it could be handed.
#
# Reproduced 2026-09-25 09:04 and again at 10:37: with the model seated, the
# hold means the brain is never invoked and the verdict itself refreshes the
# model's keep_alive lease, so the trap re-arms on every clarification the user
# offers. The loop breaks here, not in the prompt: the judge keeps its vote and
# loses its veto over anything a user could not hand it.
#
# DETERMINISTIC ON PURPOSE. A prompt is for character; it never guarantees. This
# is the guarantee.
_FETCHABLE_RE = re.compile(
    r"\b(?:document|doc|file|pdf|spread\s?sheet|csv|excel|workbook|sheet|attachment"
    r"|upload(?:ed)?|scan|report|invoice|contract|transcript|slide|deck|manuscript"
    r"|image|photo|picture|screenshot|frame|capture|recording"
    r"|render|generation|clip|video|song|track|mix|stem"
    r"|job|task|run|batch|ticket|story|book|chapter|passage|log|url|link|path"
    r"|filename|attachment)s?\b", re.I)


def _fetchable(item: str, subjects=()) -> bool:
    """Is this missing item something the user could actually supply or point at?

    Two ways to qualify: it names a fetchable KIND of thing (a document, a job,
    an upload), or it names a manifest SUBJECT — the capabilities and documents
    the assembled prompt will carry, which the caller passes in rather than this
    module guessing at.
    """
    text = (item or "").strip().lower()
    if not text:
        return False
    if _FETCHABLE_RE.search(text):
        return True
    for subj in subjects or ():
        sl = str(subj).strip().lower()
        if sl and (sl in text or text in sl):
            return True
    return False


def enforce_fetchable(result, subjects=()):
    """Coerce a hold that cannot be fixed by the user into an answerable turn.

    ANY missing item outside the fetchable categories overrules the whole hold:
    a verdict reasoning from "breakfast" is not made sound by also mentioning a
    document. Returns the result, mutated in place.
    """
    if result.answerable:
        return result
    missing = list(result.missing or [])
    # No missing list at all is a PARSE degradation, not a garbage verdict — the
    # prose fallback yields a confident hold it could not itemise. Overruling
    # those was over-reach on my part and silently discarded real holds.
    if not missing:
        return result
    unfetchable = [m for m in missing if not _fetchable(m, subjects)]
    if not unfetchable:
        return result
    log.warning("TRIAGE_HOLD_OVERRULED — missing=%s not fetchable", unfetchable)
    HOLD_OVERRULED_COUNT[0] += 1
    result.answerable = True
    result.missing = []
    result.question = None
    return result


HOLD_OVERRULED_COUNT = [0]     # read by the verify harness; Argus wiring is Fix 3


@dataclass
class TriageResult:
    answerable: bool
    missing: list = field(default_factory=list)
    question: str | None = None


# Every fail-open that has ever happened, by cause. Read by /argus so "the guard
# is not guarding" is a number on a dashboard instead of a line in a log nobody
# greps. Process-lifetime counts; Argus reads deltas.
FAILOPEN_COUNTS: dict = {}


def _fail_open(cause: str) -> TriageResult:
    """Fail OPEN on every error path, and say so at WARNING.

    Fail-open was never the sin — fail-open SILENT was. The 2 s cap was
    disabling the guard on slow turns and nothing said so, because the one line
    that knew sat at INFO among thousands. The posture does not change: a guard
    must never be the thing that breaks her. What changes is that it is audible.

    Do NOT be tempted to make this fail closed. A dead judge plus fail-closed
    holds every turn forever, which is the same outage from the other side.
    """
    # cause ∈ {TIMEOUT, PARSE, CONN, EVICTED}
    FAILOPEN_COUNTS[cause] = FAILOPEN_COUNTS.get(cause, 0) + 1
    log.warning("TRIAGE_FAILOPEN_%s — the gate did not run this turn (total %d)",
                cause, FAILOPEN_COUNTS[cause])
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



def _subjects_from(manifest: str | None):
    """Manifest subjects, taken from the manifest string the caller already
    passes, so there is no second place that decides what the prompt contains."""
    if not manifest:
        return ()
    out = []
    for seg in manifest.split("\u2014")[1:]:
        for piece in seg.split(".")[0].split(";"):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return tuple(out)


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
                enforce_fetchable(result, _subjects_from(manifest))
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
