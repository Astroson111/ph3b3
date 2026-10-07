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
try:
    import model_ctx
except ImportError:
    from modules import model_ctx

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


def self_tier_enabled() -> bool:
    """Whether tier 0b (the missing thing is HERS) is live.

    Read fresh per turn like the rest of this config, so the before/after can be
    measured without a restart — which also means the baseline cannot be
    contaminated by deploying it early, and there is a kill switch if it
    over-overrules in the wild.

    Default FALSE: a tier that strips a veto is the direction that costs an
    invented answer when it is wrong, so it goes on deliberately.
    PH3B3_TRIAGE_SELF_TIER=on|off wins over the file.
    """
    env = os.getenv("PH3B3_TRIAGE_SELF_TIER", "").strip().lower()
    if env in ("on", "1", "true", "yes"):
        return True
    if env in ("off", "0", "false", "no"):
        return False
    return bool(_config().get("self_subject_tier", False))


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


# Injected by the server: does this text name something the stores can actually
# resolve? Deterministic — the same resolve() path the named-story bypass uses.
# Kept as a hook rather than an import so triage owns no library state.
named_resolver = None          # callable(str) -> bool


# A named work or proper reference: a quoted phrase, or a run of capitalised
# words (lowercase joiners allowed, as in "The Lighthouse at Dunwich").
_NAMED_RE = re.compile(
    r"[\"\u201c\u2018']([^\"\u201d\u2019']{3,})[\"\u201d\u2019']"
    r"|\b(?:[A-Z][\w'-]+)(?:\s+(?:of|at|the|and|in|on|a|an|for|to)\s+[A-Z][\w'-]+"
    r"|\s+[A-Z][\w'-]+)+")

# Her own interiority. These are the items a user CANNOT supply, because they
# are about her experience or her opinions — the breakfast/morning class that
# started the livelock. This is the ONLY tier that strips a veto.
_INTERIORITY_RE = re.compile(
    r"\b(?:your|my|her|their)?\s*"
    r"(?:breakfast|lunch|dinner|supper|meal|meals|morning|afternoon|evening|night|"
    r"day|days|weekend|mood|feeling|feelings|thought|thoughts|opinion|opinions|"
    r"view|views|experience|experiences|memory|memories|preference|preferences|"
    r"personality|life|wellbeing|sleep)\b", re.I)


# HER OWN NAME. Injected/extendable, defaulting to what she is called. She is
# the one entity that can never be "missing context the user supplies": a hold
# naming her is definitionally garbage. Measured 2026-09-25 18:36 —
# TRIAGE_HOLD missing=['Phoebe', 'today'] on "Hey, Phoebe, how you doing today,
# darling?". She could not be greeted.
SELF_NAMES = {n.strip().lower() for n in
              os.getenv("PH3B3_SELF_NAMES", "phoebe,ph3b3,pheobe,phoeby,fee bee").split(",")
              if n.strip()}

# Invention intent lives in its own module because the SERVER needs the same
# answer (it must not inject canon text into an invention turn) and two readers
# of one rule is how they drift. Guarded: if it cannot be imported, invention is
# simply never detected and every turn behaves exactly as it did before — the
# conservative direction, since the failure mode of NOT detecting invention is a
# wrong refusal, and of wrongly detecting it is a fabricated work.
try:
    import story_intent as _story_intent
except Exception:                                      # noqa: BLE001
    _story_intent = None


_WORD_RE = re.compile(r"[a-z0-9']+")


# ── Tier 0b: the missing thing is HERS ───────────────────────────────────────
#
# THE PRINCIPLE: triage holds only when the missing thing is in the USER'S
# world, not hers. A question about her body, her devices or her own hardware
# cannot be answered by the user, so asking them is a livelock with a polite
# voice.
#
# Measured over 20 days of journal (2026-09-13..10-03): 394 holds survived
# enforcement, and 64 of them named something of hers — 'Stack-Chan', 'body',
# 'the specific hardware or computing devices you are using', 'your name',
# 'soul file', 'head'. The acceptance questions "what is Stack-Chan?", "what
# hardware are you running on?" and "do you have a body?" were all held and
# answered with a request that the user describe her.
#
# Tier 0 already covers her NAME and tier 3 her INTERIORITY (breakfast, mood,
# opinions). Between them sat everything physical about her, which is most of
# what anyone actually asks.
#
# THE VOCABULARY IS DERIVED, NEVER HAND-KEPT. It comes from config/devices.json
# (labels, keys, and the words of each role and hardware string) plus the
# self-knowledge block's own topic lines, which server.py pushes in at startup
# via set_self_vocabulary(). A second hand-maintained list would drift from the
# registry within a week, and the whole point of generating the fleet block was
# to stop that happening.
_SELF_STRUCTURAL = {
    # Structural nouns with no registry home. Deliberately small.
    "body", "bodies", "hardware", "server", "memory", "memories", "voice",
    "camera", "screen", "soul", "face", "head", "neck", "name",
}
_SELF_STOPWORDS = {
    "a", "an", "the", "your", "yours", "my", "mine", "her", "his", "their",
    "its", "of", "on", "in", "for", "to", "and", "or", "you", "are", "is",
    "am", "be", "being", "own", "specific", "exact", "current", "about",
    "what", "which", "kind", "type", "types", "using", "use", "used",
    "computing", "devices", "device", "detail", "details", "more",
}
SELF_VOCAB: set[str] = set(_SELF_STRUCTURAL)


def set_self_vocabulary(words) -> None:
    """Replace the derived half of the self vocabulary.

    Called once by the server at startup with words from the device registry and
    the self-knowledge block. Structural nouns are always kept, so triage used
    standalone (and every existing unit test) still behaves sensibly.
    """
    global SELF_VOCAB
    got = {w.strip().lower() for w in (words or ()) if w and w.strip()}
    SELF_VOCAB = set(_SELF_STRUCTURAL) | got
    log.info("[triage] self vocabulary: %d terms", len(SELF_VOCAB))


# Asking the LISTENER about herself. Nobody asks you to supply the answer to a
# question about you, so every item of such a turn is hers by construction.
_SECOND_PERSON_SELF_RE = re.compile(
    r"\b(?:do|does|did|are|is|can|could|will|would|have|has|had)\s+you\b"
    r"|\bwhat\s+(?:are|is|do|does)\s+you(?:r|'re)?\b"
    r"|\byou(?:r|'re)\s+(?:own\s+)?(?:body|hardware|name|voice|memory|soul|devices?)\b"
    r"|\bwhat\s+are\s+you\s+running\s+on\b"
    r"|\btell\s+me\s+about\s+your(?:self)?\b", re.I)


def _is_self_subject(item: str, turn: str = "") -> bool:
    """True when the missing item is about HER rather than the user's world.

    Two ways in, and the second is deliberately strict:

      1. the TURN is a second-person question about her — then every item is
         hers, whatever the judge called it;
      2. every content word of the ITEM is self vocabulary. All, not any: "the
         camera on my phone" contains 'camera' and must still hold, because
         'phone' is not hers. Requiring the whole item keeps the overrule from
         swallowing user-world questions that merely mention her parts.
    """
    if turn and _SECOND_PERSON_SELF_RE.search(turn):
        return True
    words = [w for w in _WORD_RE.findall((item or "").lower())
             if w not in _SELF_STOPWORDS]
    if not words:
        return False
    return all(w in SELF_VOCAB for w in words)


def _is_self(text: str) -> bool:
    return bool(SELF_NAMES & set(_WORD_RE.findall((text or "").lower())))


def classify(item: str, subjects=(), resolver=None, turn: str = ""):
    """One of: 'hold', 'decline', 'overrule'. Deterministic, in this order.

    `turn` is the user's whole message. It is optional and defaults to "", so
    every existing caller keeps the exact behaviour it had — without it the
    invention tier cannot fire.

    RESOLUTION BEFORE VOCABULARY. The first version of this recognised category
    NOUNS only and never proper names, so "The Lighthouse at Dunwich" — a title
    the shelf does not have — read as unfetchable, lost its veto, and she
    invented a 2015 horror film, then a public-domain summary, then a 1930s
    radio serial. Three fabrications, three different lies, from a check meant
    to make her more honest.
    """
    text = (item or "").strip()
    if not text:
        return "overrule"

    # 0. HER OWN NAME, before everything. No manifest state, no resolver, no
    #    vocabulary tier gets a vote on this one.
    if _is_self(text):
        return "overrule"

    # 0b. HER BODY, HER DEVICES, HER HARDWARE. Same reasoning as tier 0 and the
    #     same answer: the user cannot supply it. See the note above the
    #     vocabulary for the measured counts. Behind a per-turn flag so the
    #     before/after is measurable and so it can be switched off live.
    if self_tier_enabled() and _is_self_subject(text, turn):
        return "overrule"

    # 1. Manifest subjects first — the caller's own statement of what the
    #    assembled prompt will carry.
    # WORD-BOUNDARY, not bare substring. The old bidirectional `in` meant any
    # single common word appearing anywhere inside a subject phrase filed a
    # social turn as fetchable context.
    tl = text.lower()
    t_words = set(_WORD_RE.findall(tl))
    for subj in subjects or ():
        sl = str(subj).strip().lower()
        if not sl:
            continue
        s_words = set(_WORD_RE.findall(sl))
        if sl in tl or (t_words and t_words <= s_words):
            return "hold"

    # 1b. AN EXPLICIT ASK TO INVENT, before the named-but-absent tier.
    #
    # 2026-09-29: "Can you make up a story about King Tom…" was declined with
    # "I'd rather tell you that than make one up" — she was asked to make one up.
    # The tier below decides on SHAPE and RESOLUTION and has no notion of what
    # the turn wanted, so this is the only place the distinction can be made
    # without letting the decline fire first.
    #
    # This tier can only ever turn a DECLINE into an overrule. A turn that
    # resolves still holds (tier 2 below returns "hold" for a real work, and a
    # named work that exists is reached the same way it always was), and a retell
    # of an absent work still declines, which is the Dunwich canary.
    if turn and _story_intent is not None and _story_intent.is_invention(turn):
        return "overrule"

    # 2. Does it LOOK like a named work? Only then is the store consulted.
    #    shelf.resolve() is FUZZY — measured 2026-09-25, it returns True for
    #    "the user's mood" — so asking it about arbitrary prose turns a social
    #    hold into a legitimate one and the livelock comes straight back. It is
    #    a good title matcher and a bad general oracle; it is now only ever
    #    asked about things shaped like titles.
    if _NAMED_RE.search(text):
        if resolver is not None:
            try:
                if resolver(text):
                    return "hold"          # a real work: she recalls it properly
            except Exception:              # noqa: BLE001
                pass                       # a lookup fault never gates a turn
        return "decline"                   # named but absent: say so, never invent

    # 3. Her own interiority — the only thing a user genuinely cannot supply.
    if _INTERIORITY_RE.search(text):
        return "overrule"

    # 4. Everything else HOLDS. A user-suppliable specific ("company name",
    #    "today's date", "the document") is precisely what a clarifying question
    #    is for. Defaulting to hold is the conservative direction: the cost is a
    #    question, where the cost of over-overruling is an invented answer.
    return "hold"


def _fetchable(item: str, subjects=()) -> bool:
    """Back-compat shim: 'is a hold legitimate for this item?'"""
    return classify(item, subjects, named_resolver) == "hold"


def _decline_line(items) -> str:
    named = next((str(i).strip() for i in items
                  if _NAMED_RE.search(str(i or ""))), None)
    if named:
        return (f"I don't have anything called {named} — it isn't on my shelf or "
                "in what I've filed. I'd rather tell you that than make one up.")
    return ("I don't have that one — it isn't on my shelf or in what I've filed. "
            "I'd rather tell you that than make one up.")


# ── The payload veto: a turn that carries its content cannot be missing it ───
# Measured live on 2026-09-25, four wrong holds out of six edit requests:
#
#   "fix the wording in this paragraph: the quick brown fox jumped over a lazy
#    dogs."                       -> TRIAGE_HOLD missing=['paragraph to fix']
#   "proofread this for me: their going to the store tommorow"
#                                 -> TRIAGE_HOLD missing=['going','store','tomorrow']
#   'Rewrite this sentence so it reads better: "The report was wrote by..."'
#                                 -> TRIAGE_HOLD missing=['sentence to rewrite']
#   "Here is a paragraph. Please tighten it.\n\nWe have decided that..."
#                                 -> TRIAGE_HOLD missing=['paragraph']
#
# The second is the one that shows what is really happening: the judge listed the
# WORDS OF THE SUPPLIED SENTENCE as missing subjects. It read the payload as
# unresolved references to things it could not find.
#
# The judge already receives the whole message — modules/triage.py has always
# sent `REQUEST:\n{user_text}` in full, so this was never a missing-input bug and
# no amount of giving it the text again would fix it. It is the familiar shape
# instead: a probabilistic gate reaching a wrong verdict on input it had. So the
# guarantee is deterministic and sits here, where the verdict is enforced.
#
# TWO PARTS, both required:
#   1. does the turn carry a PAYLOAD at all — content the user pasted, rather
#      than a reference to content elsewhere. No payload, no veto: "summarize the
#      document" and "make me a poster with readable text" hold exactly as today.
#   2. does a missing item name something whose words are IN the turn. The user
#      cannot be asked to supply what they just supplied.
#
# KNOWN SOFT EDGE, pre-accepted by ruling: "summarize the document: it's the one
# I mentioned" carries a payload segment ("it's the one I mentioned") and the word
# "document" is in the turn, so the veto fires on a legitimate no-document hold.
# The degradation is graceful — the turn flows to the brain — and absent_artifact
# runs ABOVE this gate, so it answers that shape first. Measured 2026-09-26:
# absent_artifact.claim() takes it on the FIRST turn of a conversation and
# returns None mid-conversation, which is where the edge actually lives. Not
# engineered around on purpose.
_PAYLOAD_MIN_WORDS = 4
_PAYLOAD_MIN_CHARS = 20

# A colon that introduces content: preceded by a non-digit (so "at 3:30" is not a
# payload) and followed by whitespace (so "https://host" is not either).
_COLON_BODY_RE = re.compile(r"(?<!\d):\s+(.+)", re.S)
# A quoted span long enough to be content rather than a scare-quoted word.
_QUOTED_BODY_RE = re.compile(r"[\"“‘']([^\"”’']{%d,})[\"”’']"
                             % _PAYLOAD_MIN_CHARS, re.S)
# A body after a line break: "Here is a paragraph.\n\nWe have decided that..."
_NEWLINE_BODY_RE = re.compile(r"\n+(.+)", re.S)


def _is_body(seg: str) -> bool:
    seg = (seg or "").strip()
    return (len(seg) >= _PAYLOAD_MIN_CHARS
            and len(_WORD_RE.findall(seg.lower())) >= _PAYLOAD_MIN_WORDS)


def payload_segment(text: str) -> str | None:
    """The part of the turn that IS the content, or None if it carries none.

    Deterministic and deliberately dumb: the longest of three shapes — after a
    colon, inside a long quoted span, after a line break. A turn with none of
    them is a REFERENCE to content ("summarize the document"), and a hold on it
    is the clarifying question doing its job.
    """
    found = []
    for rx in (_COLON_BODY_RE, _QUOTED_BODY_RE, _NEWLINE_BODY_RE):
        m = rx.search(text or "")
        if m and _is_body(m.group(1)):
            found.append(m.group(1).strip())
    return max(found, key=len) if found else None


def supplied_in_turn(missing, text: str) -> list:
    """Which missing items name something already present in the turn.

    Same machinery as _names_any: word-boundary tokens, stop-filtered, longer
    than two characters — so "the paragraph to fix" is ['paragraph', 'fix'] and
    an article never carries a veto on its own.
    """
    if not payload_segment(text):
        return []
    have = set(_WORD_RE.findall((text or "").lower()))
    present = []
    for item in missing or ():
        words = [w for w in _WORD_RE.findall(str(item).lower())
                 if w not in _STOP and len(w) > 2]
        if words and any(w in have for w in words):
            present.append(item)
    return present


PAYLOAD_OVERRULED_COUNT = [0]   # Argus-visible with the rest


def enforce_fetchable(result, subjects=(), resolver=None, text=""):
    """Three outcomes, not two. Returns the result, mutated in place.

      hold      every item resolves, or is a user-suppliable specific
      decline   something is NAMED but absent — say so, never improvise it
      overrule  the hold rests on her own interiority, OR on content the turn
                already carries, which no user can be asked to supply twice

    `text` is the user's turn, FULL and untruncated — the payload veto reads it.
    It defaults to "" so every existing caller and test keeps the exact
    behaviour it had; without the text the veto simply cannot fire.
    """
    if result.answerable:
        return result
    missing = list(result.missing or [])
    if not missing:
        return result                                  # prose fallback; leave it alone

    res = resolver if resolver is not None else named_resolver
    verdicts = [classify(m, subjects, res, turn=text) for m in missing]

    # Precedence: decline beats overrule. A turn naming an absent work must
    # never be handed to the brain to imagine, even if it also mentions
    # something social.
    if "decline" in verdicts:
        DECLINE_COUNT[0] += 1
        log.warning("TRIAGE_HOLD_DECLINED — missing=%s named but absent", missing)
        result.question = _decline_line(missing)
        return result
    if "overrule" in verdicts:
        bad = [m for m, v in zip(missing, verdicts) if v == "overrule"]
        log.warning("TRIAGE_HOLD_OVERRULED — missing=%s not fetchable", bad)
        HOLD_OVERRULED_COUNT[0] += 1
        result.answerable = True
        result.missing = []
        result.question = None
        return result

    # The payload veto, last: decline still wins (a named work absent from the
    # shelf is never handed to the brain to imagine, whatever else the turn
    # carries), and interiority is already handled above.
    supplied = supplied_in_turn(missing, text)
    if supplied:
        PAYLOAD_OVERRULED_COUNT[0] += 1
        log.warning("TRIAGE_HOLD_OVERRULED — content present in turn: %s", supplied)
        result.answerable = True
        result.missing = []
        result.question = None
    return result


DECLINE_COUNT = [0]
SKIP_PHATIC_COUNT = [0]     # Argus-visible with the rest
HOLD_OVERRULED_COUNT = [0]     # read by the verify harness; Argus wiring is Fix 3


# ── Pure pleasantries never reach the judge ─────────────────────────────────
# House law: a turn that can never legitimately be held should not be judged at
# all. Every judge invocation is a place a wrong verdict can happen, and this
# week's evidence is unanimous that small talk is where wrong verdicts live —
# breakfast, mornings, opinions, and on 2026-09-25 at 18:36 her own name:
# TRIAGE_HOLD missing=['Phoebe', 'today'] on "Hey, Phoebe, how you doing today,
# darling?". She could not be greeted.
#
# RECOGNITION IS WHOLE-MESSAGE AND STRICT, not "contains a greeting". Every
# token must be in the pleasantry vocabulary; one word outside it and the turn
# goes through the gate as normal. "Hey Phoebe, can you edit text?" is a real
# question wearing a hello, and it gets judged. Better ten judged greetings than
# one skipped real question.
_PHATIC_WORDS = {
    # greetings and farewells
    "hi", "hey", "heya", "hello", "hullo", "yo", "howdy", "sup", "morning",
    "afternoon", "evening", "night", "goodnight", "goodbye", "bye", "byebye",
    "cya", "later", "welcome", "back",
    # how-are-you
    "how", "are", "you", "u", "ya", "doing", "going", "is", "it", "been",
    "feeling", "today", "tonight", "everything", "things",
    # thanks
    "thanks", "thank", "ty", "thx", "cheers", "appreciate", "appreciated",
    # warmth and endearments
    "nice", "good", "great", "lovely", "wonderful", "see", "talk", "talking",
    "hear", "from", "again", "love", "missed", "miss", "glad", "happy",
    "darling", "dear", "hun", "honey", "friend", "mate", "buddy", "pal",
    "girl", "sweetheart", "babe",
    # harmless filler
    "please", "well", "so", "and", "the", "a", "an", "my", "im", "i", "m",
    "just", "to", "say", "hope", "all", "ok", "okay", "alright", "there",
    "yes", "no", "yeah", "yep", "of", "course", "much", "very", "too",
}
_PHATIC_EXTRA = {w.strip().lower() for w in
                 os.getenv("PH3B3_PHATIC_EXTRA", "").split(",") if w.strip()}


def is_phatic(text: str) -> bool:
    """True only when the WHOLE message is pleasantry. Never raises."""
    words = _WORD_RE.findall((text or "").lower())
    if not words or len(words) > 12:          # a long message is not a greeting
        return False
    allowed = _PHATIC_WORDS | _PHATIC_EXTRA | SELF_NAMES
    return all(w in allowed for w in words)


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


# ── The request half of the judge prompt is bounded ──────────────────────────
# The judge ALREADY receives the whole turn (it always has). What it does not
# have is a budget that survives a pasted essay: the gate runs on a 6s cap, and
# a 20,000-character paste in the prompt spends that cap on reading rather than
# judging, which ends in TRIAGE_FAILOPEN_TIMEOUT — the guard not running.
#
# So the text the JUDGE reads is capped, with a marker saying content continues.
# The text the VETO reads is not: enforce_fetchable gets the full turn, because
# "did the user already supply this?" must be asked of everything they supplied,
# not of the first 1,200 characters of it.
_MAX_REQUEST_CHARS = 1200        # ~300 tokens; the whole judge prompt stays small


def _bounded_request(text: str) -> str:
    t = text or ""
    if len(t) <= _MAX_REQUEST_CHARS:
        return t
    return (t[:_MAX_REQUEST_CHARS]
            + "\n… [content continues — the rest of the pasted text is present "
              "in this turn]")


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
                     "content": f"CONTEXT:\n{context or '(none)'}\n\n"
                                f"REQUEST:\n{_bounded_request(user_text)}"},
                ],
                "stream": False,
                "format": "json",
                # num_ctx IS REQUIRED, even though triage needs a fraction of
                # it. Omitting it let ollama default to 4096 while chat asked
                # for 16384 on the SAME model (triage.py:32 and server.py:99
                # read the same env var), so every turn rebuilt the runner
                # twice: ~2.6 s a turn. The 114 TRIAGE_FAILOPEN_EVICTED events
                # were this seen from the judge's side, not a VRAM shortage.
                "options": {"temperature": 0, "num_predict": _MAX_TOKENS,
                            "num_ctx": model_ctx.NUM_CTX},
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
                enforce_fetchable(result, _subjects_from(manifest), named_resolver,
                                  text=user_text)
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
