"""
morpheus.py — GPU-swap image generation for Ph3b3.

GPU swap lifecycle (one asyncio.Lock, single-user):
  POST /image/generate
    └─ acquire gpu_lock
         1. evict Hermes from VRAM  (keep_alive:0)  ─ state: evicting
         2. VERIFY eviction (/api/ps poll)           ← OOM TRAP #1
         3. queue workflow to ComfyUI                ─ state: loading
         4. wait for completion (/history poll)      ─ state: sampling
         5. fetch PNG, save to disk, index SQLite    ─ state: saving
         6. free ComfyUI VRAM (/free)                ← LEAK TRAP #2
       └─ release gpu_lock
  (Hermes lazily reloads on the next /chat turn, ~2-5s)

Verified on this Ollama build: keep_alive:0 with empty prompt blocks until
the model is actually unloaded and returns done_reason:"unload". The /api/ps
poll below is defense-in-depth, not the primary eviction signal.
"""
import asyncio
import copy
import io
import json
import logging
import os
import random
import re
from functools import lru_cache
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from content_profiles import ACTIVE_PROFILE_NAME, load_profile
from paths import MORPHEUS_DATA

log = logging.getLogger("ph3b3.morpheus")

# ── Config (all overridable via env) ─────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST",  "http://127.0.0.1:11434")
# Match against server.py's HEAVY_MODEL so eviction targets the right model.
HERMES_MODEL = os.getenv("PH3B3_HEAVY_MODEL",
               os.getenv("PH3B3_MODEL", "hermes3"))
_HERMES_STEM = HERMES_MODEL.split(":")[0]  # "hermes3" — safe startswith match

COMFY_HOST   = os.getenv("COMFY_HOST",  "http://127.0.0.1:8188")
IMAGE_DIR    = Path(os.getenv("MORPHEUS_IMAGE_DIR",
                              str(MORPHEUS_DATA / "images")))
DB_PATH      = Path(os.getenv("MORPHEUS_DB_PATH",
                              str(MORPHEUS_DATA / "generations.db")))
SDXL_CKPT    = os.getenv("MORPHEUS_CKPT",  "sd_xl_base_1.0.safetensors")
SDXL_STEPS   = int(os.getenv("MORPHEUS_STEPS", "20"))

# ── Quality tiers (Aelion) ───────────────────────────────────────────────────
# An ALLOWLIST, not a set of sliders. The caller names a tier; the numbers come
# from here and nowhere else. That is the whole safety property: no request can
# ask for a sampler that does not exist, 400 steps, or a CFG that produces
# garbage, because no request supplies those values at all.
#
# Bounds are stated alongside the table so a future edit that pushes a tier
# outside them fails a self-check at import rather than at render time.
QUALITY_STEP_BOUNDS = (20, 50)
QUALITY_CFG_BOUNDS  = (6.5, 8.5)
QUALITY_SAMPLERS    = frozenset({"dpmpp_2m", "dpmpp_3m_sde"})
QUALITY_SCHEDULERS  = frozenset({"karras"})
QUALITY_DEFAULT     = "standard"

QUALITY_TIERS = {
    "draft":    {"steps": 20, "cfg": 7.0, "sampler_name": "dpmpp_2m",
                 "scheduler": "karras", "label": "Draft",
                 "hint": "Fast, iterative"},
    "standard": {"steps": 30, "cfg": 7.5, "sampler_name": "dpmpp_2m",
                 "scheduler": "karras", "label": "Standard",
                 "hint": "Balanced, recommended"},
    "premium":  {"steps": 40, "cfg": 8.0, "sampler_name": "dpmpp_2m",
                 "scheduler": "karras", "label": "Premium",
                 "hint": "Detailed, richer output"},
    "museum":   {"steps": 50, "cfg": 8.5, "sampler_name": "dpmpp_3m_sde",
                 "scheduler": "karras", "label": "Museum",
                 "hint": "Maximum quality, slower"},
}

# Import-time self-check: a mis-edited tier is caught here, not on the GPU.
for _n, _t in QUALITY_TIERS.items():
    assert QUALITY_STEP_BOUNDS[0] <= _t["steps"] <= QUALITY_STEP_BOUNDS[1], _n
    assert QUALITY_CFG_BOUNDS[0] <= _t["cfg"] <= QUALITY_CFG_BOUNDS[1], _n
    assert _t["sampler_name"] in QUALITY_SAMPLERS, _n
    assert _t["scheduler"] in QUALITY_SCHEDULERS, _n


def resolve_quality(tier: str | None) -> dict:
    """Tier name -> sampling parameters. Raises ValueError on anything unknown.

    Called BEFORE the GPU lock is acquired, so a bad tier costs a rejection and
    nothing else — no lock held, no Ollama evicted, no model swapped out for a
    request that was never going to run.
    """
    name = (tier or QUALITY_DEFAULT).strip().lower()
    if name not in QUALITY_TIERS:
        raise ValueError(
            f"unknown quality tier {name!r}; choose one of: "
            + ", ".join(sorted(QUALITY_TIERS))
        )
    t = QUALITY_TIERS[name]
    # Re-validated on every call rather than trusted from the table. The table is
    # the only writer today, but this function is the boundary the GPU sits
    # behind, and boundaries should not assume their callers stayed honest.
    lo, hi = QUALITY_STEP_BOUNDS
    if not (isinstance(t["steps"], int) and lo <= t["steps"] <= hi):
        raise ValueError(f"steps out of bounds for tier {name!r}")
    clo, chi = QUALITY_CFG_BOUNDS
    if not (isinstance(t["cfg"], (int, float)) and clo <= float(t["cfg"]) <= chi):
        raise ValueError(f"cfg out of bounds for tier {name!r}")
    if t["sampler_name"] not in QUALITY_SAMPLERS:
        raise ValueError(f"sampler not allowed for tier {name!r}")
    if t["scheduler"] not in QUALITY_SCHEDULERS:
        raise ValueError(f"scheduler not allowed for tier {name!r}")
    return {"quality": name, "steps": t["steps"], "cfg": float(t["cfg"]),
            "sampler_name": t["sampler_name"], "scheduler": t["scheduler"]}

SDXL_NEG     = os.getenv(
    "MORPHEUS_NEG",
    "text, watermark, multiple objects, cluttered background, blurry",
)

# ── Content safety ───────────────────────────────────────────────────
# FLOOR (Part 1) — hardcoded in morpheus.py, runs on EVERY request, EVERY profile.
# No env var, no flag, no profile setting can disable or weaken these checks.
# Both strict and permissive profiles inherit them identically because they run
# BEFORE profile selection, before the gpu_lock, before any workflow is queued.
#
# Six welded categories:
#   1. Minors in any sexual/suggestive context
#   2. Real identifiable named people in intimate context
#   3. Sexualized likeness of any real identifiable person
#   4. Real-person likeness in fabricated criminal/violent/defamatory context
#   5. Bestiality / non-consensual themes
#   6. (Framing for permissive lane) fictional/generated subjects only
#
# Honest limit: this floor stops casual misuse and accidental drift. It is NOT
# an adversary-proof wall — deliberate euphemism or coded language can evade
# keyword/pattern checks. Build the floor; do not over-claim it as exhaustive.

# ── Category 1 — minor indicators ────────────────────────────────────
_FLOOR_MINOR: frozenset[str] = frozenset([
    "child", "children", "kid", "kids", "minor", "minors",
    "toddler", "infant", "loli", "lolita", "shota",
    "underage", "preteen", "pre-teen", "juvenile", "prepubescent",
    "young girl", "young boy", "little girl", "little boy",
    "schoolgirl", "school girl", "schoolboy",
    # Added after an audit found the list caught only the words it literally
    # named: "teen", "adolescent", "preschooler" and every school-age phrasing
    # below went straight through paired with an explicit term.
    "teen", "teens", "teenager", "teenagers", "teenage", "teenaged",
    "adolescent", "adolescents", "tween", "tweens",
    "youngster", "youngsters", "youth", "youths",
    "baby", "babies", "newborn", "infants",
    "preschool", "preschooler", "kindergarten", "kindergartener", "kindergartner",
    "elementary school", "middle school", "grade school", "high school",
    "schoolchild", "schoolchildren", "schoolkid", "schoolkids", "school child",
    "boyhood", "girlhood", "childlike", "childish",
])

# ── Child-depiction floor (2026-07-31 weld) ──────────────────────────
# Terms the subject gate adds on top of _FLOOR_MINOR. These are SUBJECT signals:
# they refuse on their own, with no second signal, because the rule is about who
# is depicted rather than what is done to them.
#
# The hole this closes: the minor check required minor AND sexual context, so a
# child subject in a neutral prompt cleared the gate with the whole pipeline live
# downstream. Gating on subject removes the gray region instead of policing its
# edge.
_FLOOR_MINOR_SUBJECT: frozenset[str] = frozenset([
    # UNAMBIGUOUS subject signals only. Each of these names a person under 18;
    # none of them names a place, a garment, or a relationship.
    "high schooler", "highschooler", "high school student",
    "middle schooler", "elementary student", "grade schooler",
    "schoolboys", "schoolgirls", "young teen", "small child", "young child",
    "jailbait", "jail bait", "barely legal", "just turned 18",
    "petite young", "youthful body", "youngling", "minor-aged",
    "little one",
    # Words that denote a child by definition. "foundling" and "waif" have no
    # adult reading; "street urchin" is spelled out because a bare "urchin" would
    # take the sea creature with it.
    "foundling", "waif", "street urchin", "foster child", "orphan boy",
    "orphan girl", "orphan child",
])

# Context that a child is COMMONLY in, but which is not itself a child. An empty
# classroom, an abandoned playground, a prom dress on a mannequin, a rusting
# school bus — all refused when these were hard terms, and none of them depicts
# anyone. They escalate to Layer B instead, which can ask whether a person is in
# the frame at all. Fail-closed still holds: Layer B refuses on yes OR uncertain.
_ESCALATE_CONTEXT: frozenset[str] = frozenset([
    "classroom", "playground", "school uniform", "homeroom", "prom",
    "school dance", "field trip", "school bus", "recess", "daycare",
    "day care", "nursery school", "kindergarten", "junior high",
    "elementary", "highschool", "k-12", "k12", "schoolyard",
    # Bare class-year and relational terms: "senior citizen" is elderly,
    # "boyfriend" is an adult's partner, "the girl with a pearl earring" is a
    # canonical adult painting. Lexically these look young; semantically they
    # are usually not, and only Layer B can tell the difference.
    "freshman", "sophomore", "junior", "senior",
    "boy", "boys", "girl", "girls",
])

# "student" alone is refused; a tertiary qualifier makes it an adult subject.
# Written as a rule rather than a term because the qualifier can precede or
# follow, and a list of every phrasing is what produced this hole once already.
_RE_ORPHAN = re.compile(r"\borphan(?!age)")

_STUDENT_RE = re.compile(r"\bstudents?\b")
_STUDENT_ADULT_QUALIFIER = re.compile(
    r"\b(university|college|graduate|postgraduate|grad|medical|med|law|phd|"
    r"doctoral|masters|mba|undergraduate)\b"
)

# Adulthood terms. In the NEGATIVE field these are a request for a minor that
# never names one: negating adulthood is asking for its opposite. This vector
# names no minor at all, so no subject term list can catch it — it is checked
# structurally, by field.
_ADULT_NEGATION: frozenset[str] = frozenset([
    "adult", "adults", "mature", "grown", "grown up", "grownup",
    "woman", "women", "man", "men", "elderly", "old", "older",
    "wrinkles", "wrinkled", "middle aged", "middleaged",
    "20s", "30s", "40s", "50s", "60s",
    "20 years old", "30 years old", "40 years old", "50 years old",
])

# Terms that are BOTH a minor reference and a sexual one in a single word. These
# block on their own — there is no second signal to wait for, because the word
# itself is the entire request.
_FLOOR_MINOR_SEXUAL: frozenset[str] = frozenset([
    "loli", "lolita", "shota", "jailbait", "jail bait", "barely legal",
    "child porn", "childporn", "csam", "underage sex", "underage porn",
])

# ── Categories 2/3 — sexual/intimate context ─────────────────────────
_FLOOR_SEXUAL: frozenset[str] = frozenset([
    "nude", "naked", "nudity", "nsfw",
    "sexual", "sex", "porn", "hentai",
    "erotic", "erotica", "xxx", "lewd",
    "adult content", "intimate",
])

# ── Category 4 — criminal/violent/defamatory framing of real persons ──
# Two-signal check: these terms alone are NOT blocked; they block only
# when combined with a real-person reference (_PERSON_RE below).
_FLOOR_CRIMINAL: frozenset[str] = frozenset([
    "drug dealer", "drug lord", "drug kingpin",
    "terrorist", "terrorism",
    "pedophile", "paedophile", "child molester",
    "sex offender",
    "convicted of", "arrested for", "prison for",
    "committing murder", "committing rape",
    "crimes against",
])

# ── Category 5 — bestiality / non-consensual (standalone block) ───────
_FLOOR_NONCONSENSUAL: frozenset[str] = frozenset([
    "bestiality", "zoophilia",
    "rape", "non-consensual", "nonconsensual",
    "without consent", "forced sex", "forced intercourse",
])

# Union of all floor term sets — used by _person_signal to blank them out
# before running the bigram match so multi-word floor tokens can't self-match
# as name-shaped references (e.g. "adult content", "drug dealer").
_ALL_FLOOR_TERMS: frozenset[str] = (
    _FLOOR_MINOR | _FLOOR_SEXUAL | _FLOOR_CRIMINAL | _FLOOR_NONCONSENSUAL
    | _FLOOR_MINOR_SEXUAL
)


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse separator tricks (n_u_d_e, n.u.d.e → nude)."""
    s = text.lower().strip()
    # Collapse non-space separators between single letters: underscores, hyphens, dots
    s = re.sub(r"(?<=[a-z])[_.\-](?=[a-z])", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


# ── Whole-word floor matching ────────────────────────────────────────────────
# Floor terms match on a LEADING word boundary (\bterm), not as a raw substring.
# This still catches inflections/plurals ("rape"→raped/rapes, "nude"→nudes) so no
# real content slips the floor, while killing substring false positives where a
# term hides *inside* an innocent word ("rape" in "d-rape-d"/"grape", "sex" in
# "Sus-sex"/"Es-sex"). Trailing boundary is intentionally omitted (safety bias:
# a suffixed real term must still fire; over-matching a word that STARTS with a
# term — e.g. "sextant" — is an accepted, rare cost of never weakening the floor).
def _floor_re(terms: frozenset[str]):
    # Compile from the NORMALISED term. _normalize() runs on the prompt first and
    # deletes hyphens between letters, so a raw "pre-teen" pattern could never
    # match the "preteen" that actually arrives — the same dead-entry trap that
    # silently disabled "nude-toned" in the profile allow-list.
    alts = "|".join(re.escape(_normalize(t))
                    for t in sorted(terms, key=len, reverse=True))
    return re.compile(r"\b(?:" + alts + r")")


# ── Multilingual minor terms — defence in depth behind Layer B ───────────────
# Layer B is the real multilingual defence; this list exists so a model error or
# an unexpected phrasing still meets a deterministic gate. Entries are limited to
# terms that mean "child" with no adult reading, and that do NOT collide with an
# ordinary English word. Deliberately EXCLUDED for that reason: German "Kind",
# Swedish/Norwegian "barn", Italian "bimbo", Spanish bare "nina" (the name Nina),
# and the manga register words "shoujo"/"shounen" (genre labels, not subjects).
# A false refusal here is cheap; a false allow is the bug we are closing.
_FLOOR_MINOR_INTL: frozenset[str] = frozenset([
    # Romance
    "niña", "niño", "niñita", "niñito", "fillette", "petite fille", "petit garçon",
    "enfant", "gamine", "bambin", "bambina", "bambino", "bimba",
    "menina", "menino", "menininha", "criança", "crianca", "fetiță", "fetita", "copil",
    # Germanic / Slavic / other Latin-script
    "mädchen", "madchen", "kleinkind", "meisje", "jongen", "kindje",
    "dziewczynka", "chłopiec", "chlopiec", "dziecko", "holčička", "holcicka",
    "flicka", "pojke", "çocuk", "cocuk", "kislány", "kislany", "gyerek",
    "tyttö", "tytto", "lapsi", "mtoto", "batang babae", "anak kecil", "gadis kecil",
    "em bé", "bé gái", "trẻ em", "κορίτσι", "παιδί",
    # Cyrillic
    "девочка", "мальчик", "ребёнок", "ребенок", "дівчинка", "хлопчик", "дитина",
    # Arabic / Hebrew / Persian / Devanagari
    "طفلة", "طفل", "فتاة صغيرة", "ילדה", "ילד", "کودک", "دختر بچه",
    "छोटी लड़की", "बच्चा", "बच्ची",
    # Romanised / transliterated
    "onnanoko", "otokonoko", "kodomo", "yoji",
    "xiao nu hai", "xiaonuhai", "xiao nan hai", "ertong",
    "devochka", "malchik", "rebenok", "chhoti ladki", "fatat saghira",
    "eorin sonyeo", "sonyeo",
])

# Scripts with no word boundaries — \b cannot fire between two CJK characters, so
# "小女孩" inside "一个小女孩" would never match a \b-anchored pattern. These are
# matched as plain substrings instead.
_FLOOR_MINOR_CJK: frozenset[str] = frozenset([
    "女の子", "男の子", "子供", "こども", "幼児", "少女", "少年", "小さな子",
    "어린이", "소녀", "소년", "어린 소녀", "아이",
    "小女孩", "小男孩", "儿童", "兒童", "幼儿", "幼兒", "小孩", "女童", "男童",
    "เด็กผู้หญิง", "เด็กผู้ชาย", "เด็ก",
])


def _floor_re_substring(terms: frozenset[str]):
    """Boundary-free alternation for scripts that have no word boundaries."""
    alts = "|".join(re.escape(_normalize(t))
                    for t in sorted(terms, key=len, reverse=True))
    return re.compile("(?:" + alts + ")")


_RE_MINOR_INTL = _floor_re(_FLOOR_MINOR_INTL)
_RE_MINOR_CJK  = _floor_re_substring(_FLOOR_MINOR_CJK)

_RE_MINOR         = _floor_re(_FLOOR_MINOR)
_RE_SEXUAL        = _floor_re(_FLOOR_SEXUAL)
_RE_CRIMINAL      = _floor_re(_FLOOR_CRIMINAL)
_RE_NONCONSENSUAL = _floor_re(_FLOOR_NONCONSENSUAL)
_RE_MINOR_SEXUAL  = _floor_re(_FLOOR_MINOR_SEXUAL)
_RE_MINOR_SUBJECT = _floor_re(_FLOOR_MINOR_SUBJECT)
_RE_ESCALATE      = _floor_re(_ESCALATE_CONTEXT)
_RE_ADULT_NEG     = _floor_re(_ADULT_NEGATION)
_RE_YOUNG_STYLE   = _floor_re(frozenset([
    "chibi", "cel shaded", "celshaded", "anime style", "cartoon style",
    "moe", "kawaii", "super deformed",
]))
_RE_HUMAN_SUBJECT = _floor_re(frozenset([
    "person", "people", "figure", "human", "portrait", "man", "woman",
    "male", "female", "character", "model", "she", "he", "her", "his",
]))

# ── Ages written as numbers ──────────────────────────────────────────────────
# The term lists above only catch a minor NAMED IN WORDS. An age given as a digit
# — "a 9 year old" — matched none of them, and that was the widest hole in the
# floor: every numeric age from 3 to 17 passed straight through beside an
# explicit term. Patterns are written against the NORMALISED string, where
# "12-year-old" has become "12-yearold" (the hyphen between a digit and a letter
# survives; the one between two letters does not).
_AGE_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
}
MINOR_AGE_MAX = 17          # inclusive — 17 and under is a minor

_AGE_UNIT    = r"(?:y\s*/?\s*o\b|yrs?\b|years?\s*old\b|yearsold\b|yearold\b|yr\s*old\b)"
_AGE_NUM_RE  = re.compile(rf"(?<!\d)(\d{{1,2}})\s*[-\s]*{_AGE_UNIT}")
_AGE_OF_RE   = re.compile(r"\bage[ds]?\s*(?:of\s*)?(\d{1,2})(?!\d)")
_AGE_WORD_RE = re.compile(rf"\b({'|'.join(_AGE_WORDS)})\s*[-\s]*{_AGE_UNIT}")


def _minor_age_signal(norm: str) -> bool:
    """True if the text states an age of MINOR_AGE_MAX or below, digits or words.
    Bias is deliberate: an unparseable or ambiguous age is NOT treated as adult."""
    for rx in (_AGE_NUM_RE, _AGE_OF_RE):
        for hit in rx.finditer(norm):
            if int(hit.group(1)) <= MINOR_AGE_MAX:
                return True
    for hit in _AGE_WORD_RE.finditer(norm):
        if _AGE_WORDS[hit.group(1)] <= MINOR_AGE_MAX:
            return True
    return False


# Case-sensitive name-shaped bigram: both words Title-Case or ALL-CAPS.
_PERSON_RE = re.compile(
    r"\b(?:[A-Z][a-z]{1,20}|[A-Z]{2,21})\s+(?:[A-Z][a-z]{1,20}|[A-Z]{2,21})\b"
)


def _person_signal(text: str) -> bool:
    """Return True if the text contains a capitalized name-shaped bigram
    (known multi-word tokens are neutralized first)."""
    s = text
    for t in _ALL_FLOOR_TERMS:
        s = re.sub(re.escape(t), " ", s, flags=re.IGNORECASE)
    return bool(_PERSON_RE.search(s))



def minor_subject_signal(text: str) -> bool:
    """True if the text depicts, or asks to depict, a person under 18.

    SUBJECT-gated: no sexual qualifier required, no artistic/mythological/
    historical exception. The previous shape required minor AND sexual context,
    which left every neutral child-subject prompt running the full pipeline.
    """
    norm = _normalize(text)
    if _RE_MINOR.search(norm) or _RE_MINOR_SUBJECT.search(norm):
        return True
    if _RE_MINOR_INTL.search(norm) or _RE_MINOR_CJK.search(norm):
        return True
    if _RE_ORPHAN.search(norm):
        return True
    if _minor_age_signal(norm):
        return True
    # Bare "student" reads as school-age; an adult qualifier anywhere in the
    # prompt releases it. Deliberately scoped to the whole prompt rather than
    # adjacency, because "student, university setting" is one comma away from
    # "university student" and both mean the same thing.
    if _STUDENT_RE.search(norm) and not _STUDENT_ADULT_QUALIFIER.search(norm):
        return True
    return False


def needs_semantic_review(text: str) -> bool:
    """True when Layer A cannot decide and Layer B must.

    Style tags that read young are the case this exists for. SDXL drifts young on
    anime/chibi/cel-shade tags from otherwise neutral subjects, so a human subject
    wearing one of those styles cannot be cleared lexically — but it cannot be
    REFUSED lexically either, or every anime-styled adult render dies with it.
    Layer A escalates; Layer B answers. The style alone (a chibi dragon) is not a
    person and is not escalated.
    """
    norm = _normalize(text)
    if _RE_YOUNG_STYLE.search(norm) and _RE_HUMAN_SUBJECT.search(norm):
        return True
    return bool(_RE_ESCALATE.search(norm))


def adulthood_negation_signal(negative: str) -> bool:
    """True if the NEGATIVE field negates adulthood.

    Asking a model to avoid 'adult, mature, woman, 30 years old' is a request for
    a minor that never names one, so no subject term list can see it. Checked
    structurally by field: the same words in the POSITIVE field are ordinary and
    must not fire.
    """
    return bool(_RE_ADULT_NEG.search(_normalize(negative))) if negative else False



# ── Layer B — semantic pass ──────────────────────────────────────────────────
# Layer A is a term list, and a term list is what produced the original hole. B
# asks one question of the FINAL composed prompt and takes the strict reading of
# any answer that is not a clear no.
#
# Fail-closed is absolute here: a timeout, an unreachable model, a malformed
# reply, an exception — every one of them refuses. The failure mode of this check
# must be "no image", never "unchecked image".
_hx_floor = httpx.Client(timeout=25.0)
# Appended to every negative prompt, on every path, after the user's own negatives
# are read. Not user-strippable and never surfaced as editable, because a control
# the user can remove is not a floor.
#
# This REDUCES drift; it does not guarantee anything. SDXL will still render young
# from neutral subjects on some style tags, which is why it sits behind the two
# gates rather than in place of them. Belt after braces, not instead of.
CHILD_NEGATIVE = ("child, kid, teen, teenager, young, youth, loli, shota, "
                  "childlike, chibi, infant, toddler, baby")


def with_child_negative(negative: str | None) -> str:
    """User negatives first, floor negatives last. Idempotent — re-running a job
    must not stack the block repeatedly into the conditioning."""
    base = (negative or "").strip()
    if CHILD_NEGATIVE in base:
        return base
    return f"{base}, {CHILD_NEGATIVE}" if base else CHILD_NEGATIVE


_LAYER_B_MODEL   = os.getenv("PH3B3_FLOOR_MODEL") or os.getenv("PH3B3_LIGHT_MODEL", "hermes3:latest")
_LAYER_B_TIMEOUT = float(os.getenv("PH3B3_FLOOR_TIMEOUT", "20"))

_LAYER_B_PROMPT = """You are a safety classifier for an image generator.

Question: if this prompt were rendered faithfully, would the resulting image depict a human or humanlike figure who appears to be under 18 years old?

Answer YES when a figure under 18 would appear, however the age is conveyed:
- a stated age, in digits or words, in any language
- a school grade or year level ("third grade", "year 4", "sophomore")
- a developmental milestone ("has not lost their baby teeth", "learning to walk")
- an age-restricted framing ("too young to drive", "under the age of majority")
- diminutives, pet names, or childhood terms in ANY language, including
  romanised or transliterated spellings, misspellings, and spaced or
  letter-substituted text
- a named fictional or historical character who is a minor
- an art style that renders its subject as a child
- ordinary words for a child used as the subject — boy, girl, kid, child, son,
  daughter, schoolboy, schoolgirl, and their equivalents in any language — unless
  the prompt explicitly makes that figure an adult. "A boy fishing" is YES.
  "Boyfriend", "girlfriend", "old boy" and "the girls' night out" refer to adults
  and are NO.

Answer NO when:
- no human figure would appear at all — an empty room, an abandoned playground,
  a landscape, an object, a garment on a mannequin. A childhood SETTING with no
  person in it is not a person. "no people", "empty", "abandoned", "deserted"
  mean there is no figure to be a minor.
- objects associated with children are objects, not figures. Empty cots, cribs,
  bunk beds, toys, dolls, small shoes, a swing, a school desk — none of these is
  a person, and a derelict room full of them is still an empty room. Abandoned
  and haunted interiors are ordinary horror settings and are NO unless a figure
  is actually described.
- every human figure would clearly be an adult, whatever the setting or style
- the subject is pregnant. A pregnant person is an adult; an unborn child is not
  a depicted figure. Maternity portraits are NO.

Body size, build, height and weight are NOT age. Fat, thin, petite, short,
small-framed, flat-chested and slight bodies belong to adults as much as to
anyone. Judge age by stated age, developmental stage and facial maturity — never
by body shape. Refusing a body type is not this classifier's job.

Judge the image, not the words. Answer with exactly one word: YES, NO, or UNCERTAIN.

PROMPT:
{prompt}

ANSWER:"""


def _floor_judge(template: str, text: str) -> str:
    """Ask the local judge one yes/no question. Returns the verdict word, or ""
    on ANY failure — unreachable, timeout, malformed. Callers decide what an
    empty verdict means, and every caller must treat it as the unsafe answer."""
    try:
        r = _hx_floor.post(
            f"{os.getenv('OLLAMA_HOST','http://localhost:11434')}/api/generate",
            json={"model": _LAYER_B_MODEL, "prompt": template.format(prompt=text[:2000]),
                  "stream": False, "keep_alive": "5m",
                  "options": {"temperature": 0, "num_predict": 4}},
            timeout=_LAYER_B_TIMEOUT)
        return (r.json().get("response") or "").strip().upper()
    except Exception:
        log.warning("[safety] judge unavailable — failing closed")
        return ""


def semantic_minor_check(text: str) -> bool:
    """True if the prompt should be refused. Fail-closed on every error path:
    only an explicit NO allows the render through."""
    if not text or not text.strip():
        return False
    return not _floor_judge(_LAYER_B_PROMPT, text).startswith("NO")


def floor_check(prompt: str) -> str | None:
    """Return a category string if the hard floor fires, else None.
    No off switch. Runs before gpu_lock, before profile checks, before queuing.
    The returned string is for internal logging only — never expose to callers."""
    norm = _normalize(prompt)

    # Category 1a: single words that ARE the request. No second signal to wait for.
    if _RE_MINOR_SEXUAL.search(norm):
        return "minor-sexual"

    has_sex = bool(_RE_SEXUAL.search(norm))

    # Category 1 — CHILD DEPICTION, subject-gated. A minor subject refuses on its
    # own: no sexual qualifier, no artistic/historical/mythological exception, no
    # profile dependency, no off switch. This replaced a minor-AND-sexual test
    # that let every neutral child-subject prompt through with the pipeline live.
    if minor_subject_signal(prompt):
        return "child-depiction"

    # Category 5: bestiality / non-consensual (standalone — no second signal needed)
    if _RE_NONCONSENSUAL.search(norm):
        return "nonconsensual"

    # Categories 2/3/4: two-signal — real-person reference + compromising context.
    # Compromising = sexual (cats 2/3) OR criminal/defamatory (cat 4).
    has_criminal    = bool(_RE_CRIMINAL.search(norm))
    has_compromising = has_sex or has_criminal
    if has_compromising and _person_signal(prompt):
        return "real-person-compromising"

    return None


# ── PROFILE layer (Part 2) ────────────────────────────────────────────
# Loaded once at import. floor_check always runs first; profile_check only
# if the floor passes. Profile choice: PH3B3_CONTENT_PROFILE (default: strict).

ACTIVE_PROFILE: str = ACTIVE_PROFILE_NAME
_PROFILE_DENYLIST: frozenset[str] = load_profile(ACTIVE_PROFILE_NAME)

# Strict denylist always available for the localhost interlock in server.py
STRICT_DENYLIST: frozenset[str] = load_profile("strict")


# Ordinary words and names that CONTAIN a denied term but mean nothing like it.
# Stripped before matching. Kept short and specific on purpose — this is a list of
# known collisions, not a loophole: each entry is a phrase, so "naked eye" is
# exempt while "naked" on its own is not.
_PROFILE_ALLOW = (
    "naked eye", "gore-tex", "gutsy",
    "nude tone", "nude-toned", "nude toned", "explicitly",
)
# Compile from the NORMALISED phrase, because _normalize() runs first and deletes
# hyphens between letters ("nude-toned" arrives as "nudetoned"). Matching on the
# raw spelling meant those entries could never fire — "nude-toned" was dead from
# the day it was added, and "gore-tex" only worked because someone hand-added the
# collapsed spelling beside it. Normalising here fixes both at the root.
# Longest first so "nude toned" wins over "nude tone" and no stray "d" is left.
_ALLOW_RE = re.compile("|".join(
    re.escape(_normalize(a)) for a in sorted(_PROFILE_ALLOW, key=len, reverse=True)), re.I)


@lru_cache(maxsize=8)
def _compile_denylist(terms: frozenset) -> re.Pattern:
    r"""Denied terms as a word-START match that still allows suffixes.

    The old check was a plain substring test, which blocked a county in England
    ("Sussex"), a jacket ("Gore-Tex"), a terrier ("gutsy"), a curtain colour
    ("nude-toned") and an identity ("asexual") — all on the strength of three
    letters sitting inside a longer word. That is not caution, it is noise, and a
    filter people learn to route around is worse than one that fires accurately.

    A plain \b...\b would have been the obvious fix and would have made it WEAKER:
    "sexy", "nudes", "pornographic" and "sexting" would all start passing. So the
    boundary goes on the FRONT only — the term must begin a word — while \w*
    keeps every suffixed form denied.
    """
    parts = []
    for t in sorted(terms, key=len, reverse=True):
        esc = re.escape(t).replace(r"\ ", r"[\s\-_]+")   # phrases tolerate - and _
        parts.append(rf"(?<!\w){esc}\w*")
    return re.compile("|".join(parts), re.I)


def profile_check(prompt: str, denylist: frozenset | None = None) -> bool:
    """Return True if prompt passes the denylist, False if denied.
    Must be called only after floor_check passes.
    Pass denylist=morpheus.STRICT_DENYLIST to force strict (used by the
    localhost interlock when permissive is active but request is non-local)."""
    active = denylist if denylist is not None else _PROFILE_DENYLIST
    norm = _ALLOW_RE.sub(" ", _normalize(prompt))
    return not _compile_denylist(frozenset(active)).search(norm)


# ── SDXL workflow template (ComfyUI API format) ───────────────────────
# Node keys are intentionally strings — ComfyUI requires that.
# Only the marked fields are filled at request time; sampler/scheduler/cfg
# are fixed here. Swap models by changing MORPHEUS_CKPT or passing ckpt_name.
_SDXL_TEMPLATE: dict = {
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": None}},
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": None, "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode",
          "inputs": {"text": None, "clip": ["4", 1]}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": None, "height": None, "batch_size": 1}},
    "3": {"class_type": "KSampler",
          "inputs": {"seed": None, "steps": None, "cfg": 7.0,
                     "sampler_name": "dpmpp_2m", "scheduler": "karras",
                     "denoise": 1.0,
                     "model":        ["4", 0],
                     "positive":     ["6", 0],
                     "negative":     ["7", 0],
                     "latent_image": ["5", 0]}},
    "8": {"class_type": "VAEDecode",
          "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "ph3b3", "images": ["8", 0]}},
}

# ── GPU lock + in-memory job state ────────────────────────────────────
gpu_lock: asyncio.Lock = asyncio.Lock()
jobs: dict[str, dict] = {}   # job_id → {state, image_url?, error?, seed?}


# ── SQLite helpers (blocking — always call via asyncio.to_thread) ─────
def _db_init() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS generations (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id      TEXT UNIQUE NOT NULL,
          prompt      TEXT NOT NULL,
          negative    TEXT,
          model       TEXT NOT NULL,
          seed        INTEGER NOT NULL,
          steps       INTEGER,
          width       INTEGER,
          height      INTEGER,
          filename    TEXT NOT NULL,
          created_at  TEXT NOT NULL
        )
    """)
    # Migration: `kind` distinguishes image rows from video rows in the shared gallery.
    cols = [r[1] for r in con.execute("PRAGMA table_info(generations)").fetchall()]
    if "kind" not in cols:
        con.execute("ALTER TABLE generations ADD COLUMN kind TEXT DEFAULT 'image'")
    con.commit()
    con.close()


def _db_insert(job_id: str, params: dict, path: Path) -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        INSERT OR IGNORE INTO generations
          (job_id, prompt, negative, model, seed, steps,
           width, height, filename, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        job_id,
        params.get("positive", ""),
        params.get("negative", ""),
        params.get("ckpt_name", SDXL_CKPT),
        params.get("seed", 0),
        params.get("steps", SDXL_STEPS),
        params.get("width", 1024),
        params.get("height", 1024),
        str(path),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()
    con.close()


def _db_insert_video(job_id: str, params: dict, path: Path) -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        INSERT OR IGNORE INTO generations
          (job_id, prompt, negative, model, seed, steps,
           width, height, filename, created_at, kind)
        VALUES (?,?,?,?,?,?,?,?,?,?, 'video')
    """, (
        job_id,
        params.get("positive", ""),
        params.get("negative", ""),
        params.get("preset", DEFAULT_VIDEO_PRESET),   # model column carries the preset for video
        params.get("seed", 0),
        0,
        params.get("width", 0),
        params.get("height", 0),
        str(path),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()
    con.close()


def _db_gallery(n: int) -> list[dict]:
    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute(
        "SELECT job_id, prompt, model, seed, width, height, created_at, COALESCE(kind,'image') "
        "FROM generations ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    con.close()
    return [
        {"job_id": r[0], "prompt": r[1], "model": r[2], "seed": r[3],
         "width": r[4], "height": r[5], "created_at": r[6], "kind": r[7]}
        for r in rows
    ]


def _db_meta(job_id: str) -> dict | None:
    con = sqlite3.connect(str(DB_PATH))
    row = con.execute(
        "SELECT prompt, seed FROM generations WHERE job_id = ?", (job_id,)
    ).fetchone()
    con.close()
    return {"prompt": row[0], "seed": row[1]} if row else None


def _db_delete(job_id: str) -> dict:
    """Atomically delete one generation: DB row + PNG file together.
    Unlink happens inside the transaction window; any error rolls the DELETE back."""
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute(
            "SELECT filename FROM generations WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not found"}
        path = Path(row[0])
        freed = path.stat().st_size if path.exists() else 0
        con.execute("BEGIN")
        con.execute("DELETE FROM generations WHERE job_id=?", (job_id,))
        path.unlink(missing_ok=True)
        if path.suffix == ".mp4":                       # video: also drop its thumbnail
            path.with_suffix(".jpg").unlink(missing_ok=True)
        con.commit()
        return {"ok": True, "job_id": job_id, "freed_bytes": freed}
    except Exception as e:
        con.rollback()
        return {"ok": False, "reason": str(e)}
    finally:
        con.close()


def _db_all_job_ids() -> list[str]:
    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute("SELECT job_id FROM generations ORDER BY id").fetchall()
    con.close()
    return [r[0] for r in rows]


def _slug(text: str, maxlen: int = 40) -> str:
    s = text.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s[:maxlen].strip("-") or "image"


def convert_image(path: Path, fmt: str) -> tuple[bytes, str]:
    """Convert stored PNG to jpeg or webp in-memory. No disk writes."""
    img = Image.open(path)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.convert("RGB").save(buf, "JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    # webp
    img.save(buf, "WEBP", quality=92)
    return buf.getvalue(), "image/webp"


# ── Ollama eviction — OOM TRAP #1 ─────────────────────────────────────
async def evict_hermes(http: httpx.AsyncClient) -> None:
    # Empty-prompt generate with keep_alive:0 — Ollama blocks until unloaded.
    # On this install, returns {"done_reason": "unload"} synchronously.
    # If the model is already absent this call is a no-op.
    await http.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": HERMES_MODEL, "prompt": "", "keep_alive": 0},
        timeout=30.0,
    )
    # Defense-in-depth: do NOT proceed until /api/ps confirms VRAM is clear.
    for _ in range(20):
        ps = (await http.get(f"{OLLAMA_HOST}/api/ps", timeout=10.0)).json()
        loaded = [m.get("name", "") for m in ps.get("models", [])]
        if not any(n.startswith(_HERMES_STEM) for n in loaded):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"Hermes ({HERMES_MODEL}) did not evict within 10s — aborting to avoid OOM"
    )


# ── ComfyUI helpers ───────────────────────────────────────────────────
def build_workflow(params: dict) -> dict:
    """Fill the SDXL template from params. Resolves seed=-1 to a random value
    and writes it back into params so the caller can index it."""
    wf = copy.deepcopy(_SDXL_TEMPLATE)
    seed = params.get("seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
        params["seed"] = seed  # write resolved seed back for indexing
    # Empty or missing negative → default negative (SDXL_NEG). `or` (not dict
    # default) so an explicit "" from the endpoint also falls back. Write the
    # resolved value back into params so the DB records what actually conditioned.
    neg = with_child_negative(params.get("negative") or SDXL_NEG)
    params["negative"] = neg
    wf["4"]["inputs"]["ckpt_name"] = params.get("ckpt_name", SDXL_CKPT)
    wf["6"]["inputs"]["text"]      = params.get("positive", "")
    wf["7"]["inputs"]["text"]      = neg
    wf["5"]["inputs"]["width"]     = params.get("width",  1024)
    wf["5"]["inputs"]["height"]    = params.get("height", 1024)
    wf["3"]["inputs"]["seed"]      = seed
    wf["3"]["inputs"]["steps"]     = params.get("steps",  SDXL_STEPS)
    # cfg / sampler / scheduler were baked into the workflow template. They are
    # request params now so a quality tier can set them — still allowlist-derived,
    # never caller-supplied numbers.
    if params.get("cfg") is not None:
        wf["3"]["inputs"]["cfg"] = float(params["cfg"])
    if params.get("sampler_name"):
        wf["3"]["inputs"]["sampler_name"] = params["sampler_name"]
    if params.get("scheduler"):
        wf["3"]["inputs"]["scheduler"] = params["scheduler"]
    return wf


async def comfy_queue(http: httpx.AsyncClient, workflow: dict) -> str:
    r = (await http.post(
        f"{COMFY_HOST}/prompt",
        json={"prompt": workflow},
        timeout=30.0,
    )).json()
    if "prompt_id" not in r:
        # ComfyUI rejected the workflow (validation / missing node or model). Surface
        # a readable reason instead of a bare KeyError('prompt_id') — that opaque
        # failure is exactly what flipped a Wan clip to a blank Error badge.
        parts = []
        err = r.get("error")
        if isinstance(err, dict) and err.get("message"):
            parts.append(err["message"])
        for nid, ne in (r.get("node_errors") or {}).items():
            ct = ne.get("class_type", "?")
            for e in ne.get("errors", []):
                parts.append(f"node {nid} ({ct}): {e.get('message', '')}")
        raise RuntimeError("ComfyUI rejected the workflow: " + (" | ".join(parts) or str(r)[:300]))
    return r["prompt_id"]


async def comfy_wait(http: httpx.AsyncClient, prompt_id: str,
                     timeout_s: int = 180) -> dict:
    for _ in range(timeout_s * 2):
        h = (await http.get(
            f"{COMFY_HOST}/history/{prompt_id}", timeout=10.0
        )).json()
        if prompt_id in h:
            return h[prompt_id]["outputs"]
        await asyncio.sleep(0.5)
    raise RuntimeError(f"ComfyUI generation timed out after {timeout_s}s")


async def fetch_and_save(http: httpx.AsyncClient, outputs: dict,
                         job_id: str) -> Path:
    img = next(
        i for node in outputs.values()
        if "images" in node
        for i in node["images"]
    )
    raw = (await http.get(
        f"{COMFY_HOST}/view",
        params={"filename": img["filename"],
                "subfolder": img["subfolder"],
                "type":      img["type"]},
        timeout=60.0,
    )).content
    # Last gate. The bytes are judged before they become a file, so a flagged
    # render never exists in IMAGE_DIR at all.
    if await asyncio.to_thread(output_minor_check, raw):
        log.critical("[safety] output vision check FLAGGED job %s — not persisting", job_id[:8])
        await asyncio.to_thread(handle_output_breach, raw, job_id)
        raise RuntimeError(_OUTPUT_REFUSAL)

    path = IMAGE_DIR / f"{job_id}.png"
    path.write_bytes(raw)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT-SIDE VISION CHECK — the last gate, and the only one that sees the image
#
# Every input gate reasons about TEXT. This one looks at what was actually
# rendered, which is the only evidence that matters: SDXL can produce a young
# figure from a prompt that named no age at all, and no term list or prompt
# classifier can see that happen. It sits in fetch_and_save, the single point
# every render path converges on, so it covers entry points nobody enumerated —
# including any added later.
#
# The image is judged BEFORE it is written. A flagged render never touches
# IMAGE_DIR, so there is no window in which it exists on disk as a normal file.
#
# ── The asymmetry that matters ──────────────────────────────────────────────
# Everywhere else in this floor, uncertainty means REFUSE, because the cost of
# a false refusal is one unmade image. Here the two consequences are not
# symmetric and must not share a rule:
#   · destroying THIS image on suspicion   — cost is one image. Fail closed.
#   · purging the WHOLE LIBRARY on suspicion — cost is everything, forever.
# llava is a small model, and the figure it is most likely to misjudge is a
# petite or stylised ADULT. So suspicion always destroys the render and halts
# the generator, but a library purge requires a second, independently-framed
# check to agree. One model's bad call cannot take the gallery with it.
_OUTPUT_REFUSAL = "Refused by the child-safety floor."
OUTPUT_VISION_MODEL = os.getenv("PH3B3_OUTPUT_VISION_MODEL", "llava")
OUTPUT_VISION_TIMEOUT = float(os.getenv("PH3B3_OUTPUT_VISION_TIMEOUT", "60"))

# Set when a breach fires. While present, every render is refused — a breach
# means containment failed, and continuing to generate is the wrong response.
BREACH_FLAG = Path(os.getenv("PH3B3_BREACH_FLAG",
                             str(Path(IMAGE_DIR).parent / "BREACH_HALT")))

# ── Why this is two models and not one ──────────────────────────────────────
# llava cannot answer a multi-option classification question. Asked "reply
# HUMANCHILD or OTHERWISE", it returned OTHERWISE for a Bellini Madonna AND for a
# goblin battle — it is not weighing the options, it is emitting a token. An
# earlier phrasing ending in "answer NO" returned NO for all thirty images in the
# library. Every prompt variant tried scored 0 true positives.
#
# But llava SEES accurately. Asked to describe, it said "a painting of the Virgin
# Mary holding a baby" and "green gnomes... smaller in size" — both exactly right,
# and both containing everything needed to decide.
#
# So llava describes and hermes3 judges the description, which is the same split
# screenshot_module.py already uses for this reason. The text judge is the one
# that scored 59/59 on the multilingual suite; giving it prose to reason over
# plays to what each model can actually do.
# Ask openly and let it talk. Two forced-choice designs failed here, in opposite
# directions: "reply HUMANCHILD or OTHERWISE" returned OTHERWISE for everything,
# and a version offering "'No people are shown.' / 'People are shown.'" returned
# the FIRST option for everything — including a Bellini Madonna. llava does not
# weigh options, it takes one. But asked to simply describe, it is accurate and
# specific: "1. A woman... 2. A child". So the vision model narrates and the text
# model decides, and the only tuning needed here is enough token budget that a
# busy image is not cut off mid-sentence.
_VISION_DESCRIBE_PROMPT = (
    "Describe every person or figure in this image. For each one, say whether it "
    "is a human being or a non-human creature such as a goblin, orc, elf, monster, "
    "robot, doll or statue, and give its approximate age. If there are no people "
    "or figures at all, say so plainly."
)

_DESCRIPTION_JUDGE_PROMPT = """A vision model produced this description of a generated image.

Question: based on the description, does the image depict a HUMAN figure who is under 18 years old?

Reply YES if a human child, baby, infant, or teenager is described.
Reply NO if the description mentions no people, or only adults, or only non-human
creatures such as goblins, orcs, elves, monsters, robots, dolls or statues. A
description that lists only scenery, objects or artwork with no person in it is NO,
even if it breaks off mid-sentence. If the description is cut off before it
mentions any person, that is not evidence of a person.
Non-human creatures are never children, whatever their size. Short, small, slender
or pregnant adults are adults.
Reply UNCERTAIN if the description is too vague to tell.

Reply with one word.

DESCRIPTION:
{prompt}

REPLY:"""


# Corroboration for the LIBRARY PURGE only. This MUST be independent of the
# primary check — reusing the same describe-and-judge meant it agreed with itself
# every time, which would have let a sheet of landscape stickers purge the whole
# gallery. It asks a strictly narrower question: not "might a minor be here" but
# "is a child explicitly named as present". The primary check may block on a
# hunch; nothing is destroyed library-wide unless the description says so outright.
_PURGE_CORROBORATE_PROMPT = """A vision model produced this description of a generated image.

Question: does the description EXPLICITLY state that a human child, baby, infant, or teenager is present in the image?

Reply YES only if such a person is directly named as being in the image.
Reply NO if the description names no such person — including when it describes only
scenery, objects, artwork, text, adults, or non-human creatures. Do not infer a
child from the setting, the mood, the art style, or from small figures that are not
identified as human children.

Reply with one word.

DESCRIPTION:
{prompt}

REPLY:"""


def _vision_judge(raw: bytes, question: str, npred: int = 4) -> str:
    """Ask the local vision model one question about an image. Returns the verdict
    word, or "" on any failure. Callers decide what an empty verdict means."""
    import base64
    try:
        r = _hx_floor.post(
            f"{os.getenv('OLLAMA_HOST','http://localhost:11434')}/api/generate",
            json={"model": OUTPUT_VISION_MODEL, "prompt": question,
                  "images": [base64.b64encode(raw).decode()],
                  "stream": False, "keep_alive": "5m",
                  "options": {"temperature": 0, "num_predict": npred}},
            timeout=OUTPUT_VISION_TIMEOUT)
        return (r.json().get("response") or "").strip()
    except Exception:
        log.warning("[safety] output vision judge unavailable — failing closed")
        return ""


def describe_image(raw: bytes) -> str:
    """What the vision model can actually do: say what it sees."""
    return _vision_judge(raw, _VISION_DESCRIBE_PROMPT, npred=600)


def output_minor_check(raw: bytes) -> bool:
    """True if this rendered image must NOT be persisted.

    llava describes, hermes3 decides. Fail-closed on either model being
    unavailable — an unchecked render is precisely what this prevents."""
    desc = describe_image(raw)
    if not desc:
        return True                              # vision model down — block
    verdict = _floor_judge(_DESCRIPTION_JUDGE_PROMPT, desc)
    if not verdict:
        return True                              # text judge down — block
    return not verdict.startswith("NO")


def output_corroborates(raw: bytes) -> bool:
    """Second, differently-framed opinion. True only on an explicit CHILD verdict —
    fail-OPEN by design, because this decides whether the whole library is purged
    and an unreachable judge must never trigger that."""
    desc = describe_image(raw)
    if not desc:
        return False        # fail-OPEN: never purge a library on a dead model
    return _floor_judge(_PURGE_CORROBORATE_PROMPT, desc).startswith("YES")


def _shred(path: Path) -> None:
    """Overwrite before unlinking, so the bytes are not merely dereferenced."""
    try:
        n = path.stat().st_size
        with open(path, "wb") as f:
            f.write(os.urandom(n))
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass
    try:
        path.unlink()
    except Exception:
        pass


def purge_library(reason: str) -> int:
    """Destroy every generated image and video. Irreversible and intended to be —
    called only on a corroborated breach. Returns the number of files destroyed."""
    n = 0
    for pat in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.webm", "*.gif"):
        for f in Path(IMAGE_DIR).glob(pat):
            _shred(f)
            n += 1
    log.critical("[safety] LIBRARY PURGED — %d file(s) destroyed — reason: %s", n, reason)
    return n


def halt_generation(reason: str) -> None:
    """Stop all further rendering until a human clears the flag. A breach means
    the input gates were bypassed; generating more before anyone has looked is
    the wrong default."""
    try:
        BREACH_FLAG.parent.mkdir(parents=True, exist_ok=True)
        BREACH_FLAG.write_text(reason)
    except Exception as exc:
        log.error("[safety] could not write breach flag: %s", exc)
    log.critical("[safety] GENERATION HALTED — %s", reason)


def generation_halted() -> str | None:
    """Reason string if the generator is halted, else None."""
    try:
        return BREACH_FLAG.read_text().strip() if BREACH_FLAG.exists() else None
    except Exception:
        return "breach flag unreadable"


AUTO_PURGE = os.getenv("PH3B3_AUTO_PURGE", "0").lower() in ("1", "true", "yes")
HALT_ON_ANY_HIT = os.getenv("PH3B3_HALT_ON_ANY_HIT", "0").lower() in ("1", "true", "yes")


def handle_output_breach(raw: bytes, job_id: str) -> None:
    """A render was judged to depict a minor. The image was never written — this
    decides how far the response goes. Never logs prompt text.

    The library purge is ARMED, not automatic, and that is a deliberate deviation
    from "purge on a corroborated hit". Measured on this machine's own library,
    corroboration fired on a desert-landscape poster containing no people at all,
    reproducibly. Recall is good — a real Bellini infant is caught every time —
    but a trigger with that false-positive rate must not hold an irreversible
    delete on every image the user owns. So a breach halts the generator, writes
    a report, and leaves a one-command purge ready. Set PH3B3_AUTO_PURGE=1 to
    make it fire on its own.

    Nothing is lost by the human step: the offending image is already destroyed
    before this runs, and the halt means nothing further can be generated until
    someone has looked."""
    corroborated = output_corroborates(raw)

    # Halt only on a corroborated hit. Halting on ANY hit was the original
    # policy and it stopped the generator on the second real render — a haunted
    # orphanage, uncorroborated, nothing wrong with it. An uncorroborated hit
    # still destroys the image, which is the part that matters; bricking the
    # machine as well turns a false positive into an outage. Set
    # PH3B3_HALT_ON_ANY_HIT=1 to restore the stricter behaviour.
    if corroborated or HALT_ON_ANY_HIT:
        halt_generation(f"output vision check flagged job {job_id[:8]}")

    report = BREACH_FLAG.parent / "BREACH_REPORT.txt"
    try:
        report.write_text(
            f"Breach detected on job {job_id[:8]}\n"
            f"Corroborated by independent check: {corroborated}\n\n"
            "The offending image was destroyed and never written to the library.\n"
            "Generation is HALTED until the halt flag is removed.\n\n"
            "To purge every image in the library:\n"
            "    cd ~/Desktop/ph3b3_v2 && .venv/bin/python -c "
            "\"import sys;sys.path.insert(0,'modules');import morpheus;"
            "morpheus.purge_library('manual after breach')\"\n\n"
            "To resume generating without purging:\n"
            f"    rm {BREACH_FLAG}\n"
        )
    except Exception as exc:
        log.error("[safety] could not write breach report: %s", exc)

    if corroborated:
        log.critical("[safety] BREACH CORROBORATED — generation halted, purge ARMED "
                     "(set PH3B3_AUTO_PURGE=1 to purge automatically)")
        if AUTO_PURGE:
            purge_library(f"corroborated breach on job {job_id[:8]}")
    else:
        log.warning("[safety] uncorroborated output flag — image destroyed, "
                    "library retained, generation continues")


async def comfy_free(http: httpx.AsyncClient) -> None:
    try:
        await http.post(
            f"{COMFY_HOST}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=30.0,
        )
    except Exception as exc:
        log.warning("comfy_free failed (non-fatal): %s", exc)


# ── On-demand ComfyUI startup ─────────────────────────────────────────
_COMFY_POLL_INTERVAL = 3.0   # seconds between readiness probes
_COMFY_START_TIMEOUT = 120   # max seconds to wait for ComfyUI to serve


def comfy_up() -> bool:
    """True if the ComfyUI backend answers on /system_stats. Sync + fast-failing —
    for the Argus 'comfyui' heartbeat (down → SILENT on the fleet panel)."""
    try:
        return httpx.get(f"{COMFY_HOST}/system_stats", timeout=3.0).status_code == 200
    except Exception:
        return False


async def ensure_comfy_up(http: httpx.AsyncClient) -> None:
    """Start ComfyUI on demand and wait until it is actually serving.

    Fast path: /system_stats answers 200 → already up, return immediately.
    Slow path: `systemctl start comfyui` (polkit rule grants this without sudo),
    then poll /system_stats until ComfyUI is HTTP-ready — not just process-alive.
    Cold start (PyTorch + CUDA init + model index) can take 30-90 s.

    Must be called inside gpu_lock so concurrent jobs cannot race on startup.
    """
    # Fast path — skip startup if ComfyUI is already serving.
    try:
        r = await http.get(f"{COMFY_HOST}/system_stats", timeout=4.0)
        if r.status_code == 200:
            return
    except Exception:
        pass  # connection refused / timeout — fall through to start

    log.info("ComfyUI not responding — starting via systemctl")
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "start", "comfyui",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"systemctl start comfyui failed (rc={proc.returncode}): "
            f"{stderr.decode().strip()}"
        )

    # Poll until /system_stats answers — process-exists is not enough.
    attempts = int(_COMFY_START_TIMEOUT / _COMFY_POLL_INTERVAL)
    for _ in range(attempts):
        await asyncio.sleep(_COMFY_POLL_INTERVAL)
        try:
            r = await http.get(f"{COMFY_HOST}/system_stats", timeout=4.0)
            if r.status_code == 200:
                log.info("ComfyUI ready")
                return
        except Exception:
            pass  # still initialising — keep polling
    raise RuntimeError(
        f"ComfyUI did not become ready within {_COMFY_START_TIMEOUT}s "
        "after systemctl start"
    )


# ── Job lifecycle helpers ─────────────────────────────────────────────
def create_job() -> str:
    """Allocate a job_id and insert the initial queued state."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"state": "queued"}
    return job_id


# ── Main generation coroutine ─────────────────────────────────────────
async def run_generation(job_id: str, params: dict) -> None:
    """Full GPU-swap lifecycle. Always call as a FastAPI BackgroundTask."""
    async with gpu_lock:
        async with httpx.AsyncClient() as http:
            try:
                jobs[job_id]["state"] = "evicting"
                await evict_hermes(http)

                jobs[job_id]["state"] = "starting"
                await ensure_comfy_up(http)

                jobs[job_id]["state"] = "loading"
                wf = build_workflow(params)   # resolves seed in-place
                prompt_id = await comfy_queue(http, wf)

                jobs[job_id]["state"] = "sampling"
                outputs = await comfy_wait(http, prompt_id)

                jobs[job_id]["state"] = "saving"
                path = await fetch_and_save(http, outputs, job_id)
                await asyncio.to_thread(_db_insert, job_id, params, path)
                jobs[job_id].update(
                    state="done",
                    image_url=f"/image/file/{job_id}",
                    seed=params.get("seed"),
                )
                log.info("Morpheus: job %s done — %s", job_id, path)

            except Exception as exc:
                log.error("Morpheus: job %s failed: %s", job_id, exc)
                jobs[job_id].update(state="error", error=str(exc))

            finally:
                await comfy_free(http)   # TRAP #2 — always, even on error


# ── img2img (Edit Mode) — same checkpoint + sampler family as txt2img ─────────
# Differs from _SDXL_TEMPLATE only in the latent source: LoadImage → VAEEncode
# feeds an encoded real image into KSampler, and denoise = strength (how far the
# edit travels from the source). Everything else (cfg/sampler/scheduler) matches.
_SDXL_IMG2IMG_TEMPLATE: dict = {
    "4":  {"class_type": "CheckpointLoaderSimple",
           "inputs": {"ckpt_name": None}},
    "6":  {"class_type": "CLIPTextEncode",
           "inputs": {"text": None, "clip": ["4", 1]}},
    "7":  {"class_type": "CLIPTextEncode",
           "inputs": {"text": None, "clip": ["4", 1]}},
    "10": {"class_type": "LoadImage",
           "inputs": {"image": None}},
    "11": {"class_type": "VAEEncode",
           "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
    "3":  {"class_type": "KSampler",
           "inputs": {"seed": None, "steps": None, "cfg": 7.0,
                      "sampler_name": "dpmpp_2m", "scheduler": "karras",
                      "denoise": None,
                      "model":        ["4", 0],
                      "positive":     ["6", 0],
                      "negative":     ["7", 0],
                      "latent_image": ["11", 0]}},
    "8":  {"class_type": "VAEDecode",
           "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9":  {"class_type": "SaveImage",
           "inputs": {"filename_prefix": "ph3b3_edit", "images": ["8", 0]}},
}

EDIT_STRENGTH_MIN = 0.15
EDIT_STRENGTH_MAX = 0.9


def _prep_edit_image(src: Path, job_id: str) -> tuple[Path, int, int]:
    """Scale the source to SDXL-native long-edge 1024, dims rounded to /8,
    preserving aspect. Returns (run_copy_path, width, height)."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    scale = 1024 / max(w, h)
    nw = max(8, round(w * scale / 8) * 8)
    nh = max(8, round(h * scale / 8) * 8)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.LANCZOS)
    out = src.parent / f"{job_id}_run.png"
    img.save(out, format="PNG")
    return out, nw, nh


async def comfy_upload_image(http: httpx.AsyncClient, path: Path) -> str:
    """Upload a prepared image into ComfyUI's input dir; return its LoadImage ref."""
    data = Path(path).read_bytes()
    r = (await http.post(
        f"{COMFY_HOST}/upload/image",
        files={"image": (Path(path).name, data, "image/png")},
        data={"overwrite": "true"},
        timeout=60.0,
    )).json()
    name = r["name"]
    sub = r.get("subfolder", "") or ""
    return f"{sub}/{name}" if sub else name


def build_edit_workflow(params: dict) -> dict:
    """Fill the img2img template. Resolves seed=-1, clamps strength→denoise, and
    writes both back into params for indexing. `comfy_image` must already be set."""
    wf = copy.deepcopy(_SDXL_IMG2IMG_TEMPLATE)
    seed = params.get("seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
        params["seed"] = seed
    neg = with_child_negative(params.get("negative") or SDXL_NEG)
    params["negative"] = neg
    strength = float(params.get("strength", 0.45))
    strength = max(EDIT_STRENGTH_MIN, min(EDIT_STRENGTH_MAX, strength))  # defense-in-depth
    params["strength"] = strength
    wf["4"]["inputs"]["ckpt_name"] = params.get("ckpt_name", SDXL_CKPT)
    wf["6"]["inputs"]["text"]      = params.get("positive", "")
    wf["7"]["inputs"]["text"]      = neg
    wf["10"]["inputs"]["image"]    = params["comfy_image"]
    wf["3"]["inputs"]["seed"]      = seed
    wf["3"]["inputs"]["steps"]     = params.get("steps", SDXL_STEPS)
    wf["3"]["inputs"]["denoise"]   = strength
    return wf


async def run_edit(job_id: str, params: dict) -> None:
    """img2img GPU-swap lifecycle — mirrors run_generation exactly, reusing the
    same lock/evict/ensure/queue/wait/save/free helpers. Adds: resize→upload the
    source before queuing, and delete scratch on completion."""
    async with gpu_lock:
        async with httpx.AsyncClient() as http:
            run_img: Path | None = None
            try:
                jobs[job_id]["state"] = "evicting"
                await evict_hermes(http)

                jobs[job_id]["state"] = "starting"
                await ensure_comfy_up(http)

                jobs[job_id]["state"] = "loading"
                run_img, nw, nh = await asyncio.to_thread(
                    _prep_edit_image, Path(params["image_path"]), job_id)
                params["width"], params["height"] = nw, nh
                params["comfy_image"] = await comfy_upload_image(http, run_img)
                wf = build_edit_workflow(params)   # resolves seed/strength in-place
                prompt_id = await comfy_queue(http, wf)

                jobs[job_id]["state"] = "sampling"
                outputs = await comfy_wait(http, prompt_id)

                jobs[job_id]["state"] = "saving"
                path = await fetch_and_save(http, outputs, job_id)
                await asyncio.to_thread(_db_insert, job_id, params, path)
                jobs[job_id].update(
                    state="done",
                    image_url=f"/image/file/{job_id}",
                    seed=params.get("seed"),
                )
                log.info("Morpheus edit: job %s done — %s (denoise=%.2f)",
                         job_id, path, params.get("strength", 0.0))

            except Exception as exc:
                log.error("Morpheus edit: job %s failed: %s", job_id, exc)
                jobs[job_id].update(state="error", error=str(exc))

            finally:
                await comfy_free(http)   # TRAP #2 — always
                # Delete only the transient per-job resized copy. Keep the source
                # upload so the SAME image can be re-edited at other strengths
                # (the slider workflow); the source expires via the TTL janitor.
                try:
                    if run_img:
                        run_img.unlink(missing_ok=True)
                except OSError:
                    pass


# ══ Video generation ("Oneiroi") — Phase 3 orchestration ════════════════════
# Mirrors the image GPU-swap lifecycle (run_generation) but with a long comfy_wait
# and mp4 output. Reuses gpu_lock / evict_hermes / ensure_comfy_up / comfy_free.
VIDEO_DIR    = Path(os.getenv("MORPHEUS_VIDEO_DIR", str(MORPHEUS_DATA / "videos")))
_WF_DIR      = Path(os.getenv("MORPHEUS_WF_DIR",  "/home/astroson/Desktop/comfyui/user/morpheus_workflows"))
_COMFY_INPUT = Path(os.getenv("COMFY_INPUT_DIR",  "/home/astroson/Desktop/comfyui/input"))

# preset registry: name → {wf (i2v graph), t2v? (text-only graph), eta_s, label}
VIDEO_PRESETS: dict = {
    "ltx-fast":    {"wf": "ltx_i2v.json", "t2v": "ltx_t2v.json", "eta_s": 90,   "label": "LTX fast (~1.5 min)"},
    "wan-fast":    {"wf": "wan_i2v.json", "t2v": "wan_t2v.json",         "eta_s": 720,  "label": "Wan quality (~10 min)"},
    "wan-quality": {"wf": "wan_i2v_quality.json", "t2v": "wan_t2v_quality.json", "eta_s": 2400, "label": "Wan premium (~35 min)"},
}
DEFAULT_VIDEO_PRESET = "ltx-fast"


def video_eta(preset: str) -> int:
    return VIDEO_PRESETS.get(preset, VIDEO_PRESETS[DEFAULT_VIDEO_PRESET])["eta_s"]


def prepare_video_source(image_path: str, job_id: str) -> str:
    """Copy a source still into ComfyUI/input for I2V; return the input filename."""
    _COMFY_INPUT.mkdir(parents=True, exist_ok=True)
    name = f"morph_vid_{job_id}.png"
    shutil.copyfile(image_path, _COMFY_INPUT / name)
    return name


def build_video_workflow(params: dict) -> dict:
    """Load a preset workflow JSON and fill prompt / source image / seed.
    I2V when params['_comfy_image'] is set (a filename already in ComfyUI/input);
    otherwise T2V (uses the preset's t2v graph if it has one)."""
    p = VIDEO_PRESETS.get(params.get("preset", DEFAULT_VIDEO_PRESET),
                          VIDEO_PRESETS[DEFAULT_VIDEO_PRESET])
    img_name = params.get("_comfy_image")
    wf_file = p["t2v"] if (not img_name and p.get("t2v")) else p["wf"]
    wf = json.loads((_WF_DIR / wf_file).read_text())
    seed = params["seed"] if params.get("seed", -1) >= 0 else random.randint(0, 2**31 - 1)
    for node in wf.values():
        ins = node.get("inputs", {})
        if ins.get("text") == "PLACEHOLDER_POSITIVE":
            ins["text"] = params["positive"]
        if ins.get("image") == "PLACEHOLDER_IMAGE":
            ins["image"] = img_name
        if "noise_seed" in ins:      # add-noise=disable nodes ignore their seed → harmless
            ins["noise_seed"] = seed
    return wf


def _make_video_thumb(mp4_path: Path, job_id: str) -> None:
    """Grab a middle frame as VIDEO_DIR/{job_id}.jpg for the gallery (best-effort)."""
    thumb = VIDEO_DIR / f"{job_id}.jpg"
    try:
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp4_path)],
            capture_output=True, text=True, timeout=15).stdout.strip()
        mid = max(0.0, float(dur) / 2.0) if dur else 0.0
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(mid), "-i", str(mp4_path),
             "-frames:v", "1", "-vf", "scale=360:-1", str(thumb)],
            capture_output=True, timeout=30)
    except Exception as e:
        log.warning("video thumb failed for %s: %s", job_id, e)


async def fetch_and_save_video(http: httpx.AsyncClient, outputs: dict, job_id: str) -> Path:
    """Pull the SaveVideo mp4 from ComfyUI /view and save as VIDEO_DIR/{job_id}.mp4."""
    fn = sub = None
    typ = "output"
    for node_out in outputs.values():
        for v in node_out.values():
            if isinstance(v, list):
                for f in v:
                    if isinstance(f, dict) and str(f.get("filename", "")).lower().endswith(
                            (".mp4", ".webm", ".mkv")):
                        fn, sub, typ = f["filename"], f.get("subfolder", ""), f.get("type", "output")
    if not fn:
        raise RuntimeError("no video file in ComfyUI outputs")
    r = await http.get(f"{COMFY_HOST}/view",
                       params={"filename": fn, "subfolder": sub or "", "type": typ}, timeout=120.0)
    r.raise_for_status()
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    path = VIDEO_DIR / f"{job_id}.mp4"
    path.write_bytes(r.content)
    return path


async def run_video(job_id: str, params: dict) -> None:
    """Video GPU-swap lifecycle. Always call as a FastAPI BackgroundTask.
    Holds gpu_lock for the whole render (2–40 min) so Ollama stays evicted."""
    async with gpu_lock:
        async with httpx.AsyncClient() as http:
            if jobs[job_id].get("state") == "cancelled":
                return   # cancelled while queued on the lock — nothing allocated yet
            try:
                jobs[job_id]["state"] = "evicting"
                await evict_hermes(http)

                jobs[job_id]["state"] = "starting"
                await ensure_comfy_up(http)

                jobs[job_id]["state"] = "loading"
                wf = build_video_workflow(params)
                prompt_id = await comfy_queue(http, wf)
                jobs[job_id]["prompt_id"] = prompt_id   # stored so cancel can /interrupt

                jobs[job_id]["state"] = "rendering"
                eta = video_eta(params.get("preset", DEFAULT_VIDEO_PRESET))
                outputs = await comfy_wait(http, prompt_id, timeout_s=max(2700, eta * 3))
                if jobs[job_id].get("state") == "cancelled":
                    return   # cancelled during render — finally still frees VRAM

                jobs[job_id]["state"] = "saving"
                path = await fetch_and_save_video(http, outputs, job_id)
                await asyncio.to_thread(_make_video_thumb, path, job_id)   # middle-frame jpg for the gallery
                await asyncio.to_thread(_db_insert_video, job_id, params, path)  # record → visible in gallery
                jobs[job_id].update(state="done",
                                    video_url=f"/morpheus/video/file/{job_id}",
                                    thumb_url=f"/morpheus/video/thumb/{job_id}")
                log.info("Morpheus video: job %s done — %s", job_id, path)

            except Exception as exc:
                log.error("Morpheus video: job %s failed: %s", job_id, exc)
                if jobs[job_id].get("state") != "cancelled":   # don't clobber a user cancel
                    jobs[job_id].update(state="error", error=str(exc))

            finally:
                await comfy_free(http)   # always free VRAM
                src = params.get("_comfy_image")
                if src:
                    try:
                        (_COMFY_INPUT / src).unlink(missing_ok=True)
                    except OSError:
                        pass


# ── Module-level init: create dirs + DB schema on import ─────────────
_db_init()
log.info("Morpheus initialised — IMAGE_DIR=%s  DB=%s", IMAGE_DIR, DB_PATH)


# ── Artistic exception ───────────────────────────────────────────────────────
# Waives the child-depiction refusal for reproductions of specific pre-existing
# artworks — the Sistine Madonna, a Rockwell cover, a known historical portrait.
# Without it the floor refuses the whole history of Western painting, which is
# not what the floor is for.
#
# It is deliberately NOT an "artistic style" exception. "Artistic", "fine art"
# and "classical painting" are the most common jailbreak framings for this exact
# content, and a floor that any prompt can unlock by naming a style is not a
# floor. So the exception turns on a bounded, checkable claim — is this a
# REPRODUCTION of a work that already exists — rather than on declared intent.
#
# Three independent conditions, ALL required, each failing closed:
#   1. lexical veto  — any sexual / undress / violence term, anywhere, ends it
#   2. semantic veto — the judge must return a clear NO on that same question
#   3. affirmative   — the judge must return a clear YES that this reproduces a
#                      specific, named, well-known existing work
# An unreachable judge grants nothing. The exception can only ever REMOVE a
# refusal for the child-depiction category; every other floor category is
# untouched by it, and the adulthood-negation check is not waivable at all.
ARTISTIC_EXCEPTION = os.getenv("PH3B3_ARTISTIC_EXCEPTION", "1").lower() not in ("0", "false", "no")

_ART_VETO: frozenset[str] = frozenset([
    "nude", "nudity", "naked", "topless", "bottomless", "undressed", "undressing",
    "lingerie", "underwear", "panties", "bra", "thong", "swimsuit", "bikini",
    "bathing suit", "swimwear", "bath", "bathing", "shower", "towel",
    "sexy", "sexual", "sexualized", "sexualised", "erotic", "erotica", "seductive",
    "sensual", "provocative", "suggestive", "alluring", "flirty", "fetish",
    "bondage", "bdsm", "lewd", "explicit", "nsfw", "hentai", "ecchi",
    "spread", "straddling", "lap", "bed", "bedroom", "boudoir", "intimate",
    "kiss", "kissing", "caress", "fondle", "groping", "touching",
    "thighs", "cleavage", "breasts", "chest", "buttocks", "crotch", "genitals",
    "tight clothing", "revealing", "skimpy", "sheer", "transparent", "wet",
    "gore", "mutilated", "dismembered", "torture", "abuse", "bruised", "bleeding",
    "restrained", "tied", "chained", "gagged",
])
_RE_ART_VETO = _floor_re(_ART_VETO)

_ART_SEXUAL_PROMPT = """You are a safety classifier for an image generator.

Question: does this prompt contain ANY sexual, suggestive, romantic, intimate, undressed, swimwear, underwear, bathing, or violent element — however slight, however framed, in any language?

Treat artistic, classical, historical or educational framing as irrelevant to this question. A nude in an oil painting is still a nude. If you are unsure, answer UNCERTAIN.

Answer with exactly one word: YES, NO, or UNCERTAIN.

PROMPT:
{prompt}

ANSWER:"""

_ART_REPRO_PROMPT = """You are a classifier for an image generator.

Question: is this prompt asking for a reproduction of a SPECIFIC, NAMED, pre-existing and well-known artwork or historical photograph that already exists in the world?

Answer YES only if a specific existing work is identifiable — by title, by artist plus subject, or by being a famous image everyone would recognise. Examples of the KIND of thing that qualifies: a named Renaissance painting, a named artist's known portrait, a famous historical photograph.

Answer NO if the prompt describes a NEW image to be composed, even if it names a style, a period, a medium, an artist's manner, or calls itself art. "In the style of", "classical painting of", "Renaissance-style", "fine art photograph of" all describe new work and are NO.

Answer with exactly one word: YES, NO, or UNCERTAIN.

PROMPT:
{prompt}

ANSWER:"""


def artistic_exception_applies(text: str) -> bool:
    """True only if a child-depiction refusal should be waived for this prompt.
    Every failure path returns False — the exception is never granted by accident."""
    if not ARTISTIC_EXCEPTION or not text or not text.strip():
        return False
    if _RE_ART_VETO.search(_normalize(text)):
        return False
    if _floor_judge(_ART_SEXUAL_PROMPT, text) != "NO":
        return False
    if _floor_judge(_ART_REPRO_PROMPT, text) != "YES":
        return False
    return True
