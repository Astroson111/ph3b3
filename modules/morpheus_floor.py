"""morpheus_floor.py — content-safety floor for the Morpheus-lite path.

Extracted VERBATIM from origin/main:modules/morpheus.py (the hard floor + the
profile layer) so the six welded categories are byte-identical to Nyx. Contains
NO generation code and no Pillow/ComfyUI/httpx dependencies. floor_check() runs
before any gpu_lock, on every request, every profile, with no off switch.
Do not edit the floor logic here; it is a mirror of the canonical floor.
"""
import re

from content_profiles import ACTIVE_PROFILE_NAME, load_profile

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
)

# Name-shaped bigram: proxy for named individuals (First Last).
# IGNORECASE: elon musk / Elon Musk / ELON MUSK all match the structure.
# Signal fires ONLY when paired with a compromising-context term (AND-gate in
# floor_check). Applied via _person_signal() which strips floor terms first.
_PERSON_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse separator tricks (n_u_d_e, n.u.d.e → nude)."""
    s = text.lower().strip()
    # Collapse non-space separators between single letters: underscores, hyphens, dots
    s = re.sub(r"(?<=[a-z])[_.\-](?=[a-z])", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _person_signal(text: str) -> bool:
    """Return True if text contains a name-shaped bigram that is not itself a
    floor term. Floor terms are blanked out first so multi-word tokens like
    'adult content' or 'drug dealer' don't self-match as person references."""
    s = text.lower()
    for t in _ALL_FLOOR_TERMS:
        s = s.replace(t, " ")
    return bool(_PERSON_RE.search(s))


def floor_check(prompt: str) -> str | None:
    """Return a category string if the hard floor fires, else None.
    No off switch. Runs before gpu_lock, before profile checks, before queuing.
    The returned string is for internal logging only — never expose to callers."""
    norm = _normalize(prompt)

    has_sex    = any(t in norm for t in _FLOOR_SEXUAL)
    has_minor  = any(t in norm for t in _FLOOR_MINOR)

    # Category 1: minor + sexual/suggestive
    if has_minor and has_sex:
        return "minor-sexual"

    # Category 5: bestiality / non-consensual (standalone — no second signal needed)
    if any(t in norm for t in _FLOOR_NONCONSENSUAL):
        return "nonconsensual"

    # Categories 2/3/4: two-signal — real-person reference + compromising context.
    # Compromising = sexual (cats 2/3) OR criminal/defamatory (cat 4).
    has_criminal    = any(t in norm for t in _FLOOR_CRIMINAL)
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


def profile_check(prompt: str, denylist: frozenset | None = None) -> bool:
    """Return True if prompt passes the denylist, False if denied.
    Must be called only after floor_check passes.
    Pass denylist=morpheus.STRICT_DENYLIST to force strict (used by the
    localhost interlock when permissive is active but request is non-local)."""
    active = denylist if denylist is not None else _PROFILE_DENYLIST
    norm = _normalize(prompt)
    return not any(term in norm for term in active)


