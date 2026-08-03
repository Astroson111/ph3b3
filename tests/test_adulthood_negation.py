"""Adulthood negation in the NEGATIVE field — and the line between it and
ordinary retouching.

Negating adulthood is a request for a minor that never names one: "adult,
mature, woman, 30s" in the negative field asks for the opposite of every word in
it, and no subject term list can see that. That check stays, and these tests
exist so it is never quietly removed.

What was removed is cosmetic ageing. "old, wrinkles" in a negative is asking not
to AGE an adult, not asking for a child — she is the same age either way. It
fired on a real edit (positive "make the woman fat", negative "Deformed hands,
eyes, face. old. Black hair.") which is nobody's idea of a bypass.

The two halves are tested together on purpose: the value of the narrowing is
entirely conditional on the bypass still being blocked.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import morpheus  # noqa: E402


# ── A block must say which rule fired ────────────────────────────────────────
# Two different rules were emitting a byte-identical log line — the Category-1
# term list and the adulthood-negation check both wrote "floor-blocked
# (negative) — category: child-depiction". A block that cannot be attributed
# cannot be tuned, and tuning a floor by guesswork is how you widen one by
# accident.

def test_the_two_negative_field_rules_are_distinguishable():
    """The specific collision that made a real block unattributable."""
    term = morpheus.explain_floor("childlike, youthful")
    adult = morpheus.explain_adulthood_negation("mature, adult woman")
    assert term and adult
    assert term["rule"] != adult["rule"], "the two rules still report identically"
    assert term["rule"] == "minor-term"
    assert adult["rule"] == "adulthood-negated-in-negative"


@pytest.mark.parametrize("text,rule", [
    ("a child in a park", "minor-term"),
    ("loli", "minor-sexual-term"),
    ("a 9 year old", "age-under-18"),
    ("student", "student-no-adult-qualifier"),
    ("an orphan boy", "minor-subject-term"),
])
def test_every_rule_names_itself(text, rule):
    r = morpheus.explain_floor(text)
    assert r and r["rule"] == rule, f"{text!r} reported {r}"


def test_the_explainer_reports_what_matched():
    assert morpheus.explain_floor("a child in a park")["matched"] == "child"


def test_the_explainer_stays_silent_on_clean_text():
    assert morpheus.explain_floor(
        "traveler on hover motorcycle, desert, two suns, painterly") is None
    assert morpheus.explain_adulthood_negation("old, wrinkles") is None


def test_the_explainer_never_decides_anything():
    """floor_check remains the sole authority. This must not become a second
    opinion that can disagree with it — it is called only after a refusal."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        s = line.strip()
        if "explain_floor(" in s or "explain_adulthood_negation(" in s:
            assert s.startswith("_why") or "log.warning" in s or s.startswith("#"), \
                f"explainer used outside logging: {s}"


def test_the_matched_term_is_bounded():
    """The term goes in the log; the surrounding prompt never does."""
    long = "child " + ("x" * 500)
    r = morpheus.explain_floor(long)
    assert r and len(r["matched"]) <= 40


# ── Word-start matching must not reach inside innocent words ─────────────────
# "man" matched inside "mandalorian" and refused an ordinary sci-fi prompt whose
# negative was excluding Star Wars lookalikes. The matcher anchors at word STARTS
# by default, which is load-bearing for the minor lists and wrong for this one.

@pytest.mark.parametrize("word", [
    "mandalorian", "manual", "manor", "mandolin", "manifest", "mannequin",
    "mango", "menu", "mention", "adultery", "womanizer",
])
def test_innocent_words_that_merely_start_with_a_term_pass(word):
    assert not morpheus.adulthood_negation_signal(word), \
        f"{word!r} matched a bare adulthood term inside itself"


def test_the_actual_repro_passes():
    """The prompt from the brief, both fields, verbatim."""
    pos = ("Lone rider on a gravcycle crossing a salt flat under two suns, plasma lance "
           "across his back, armored column on the horizon behind him, painterly sci-fi, "
           "warm dust palette")
    neg = ("lightsaber, jedi, sith, stormtrooper, darth vader, star wars, mandalorian, "
           "yoda, r2d2, c3po, x-wing, tie fighter, millennium falcon, opening crawl, "
           "glowing sword hilt crossguard, black samurai helmet with respirator, white "
           "plastoid armor trooper, text, watermark, logo, signature, lowres, blurry, "
           "jpeg artifacts, deformed hands, extra fingers, extra limbs, mutated anatomy, "
           "bad proportions, cross-eyed, disfigured face, oversaturated, flat lighting, "
           "cartoon, anime, 3d render, plastic skin")
    assert morpheus.floor_check(pos) is None
    assert morpheus.floor_check(neg) is None
    assert not morpheus.adulthood_negation_signal(neg)


@pytest.mark.parametrize("word", [
    "child", "children", "childlike", "childish", "teen", "teens", "teenager",
    "teenagers", "toddler", "toddlers", "infant", "infants", "kid", "kids",
])
def test_minor_lists_keep_word_start_matching(word):
    """The scoping test. Whole-word matching was applied to the adulthood set
    ONLY — applying it globally would stop "child" catching "children" and put a
    hole in the child-safety lists."""
    assert morpheus.floor_check(word) == "child-depiction", \
        f"{word!r} no longer refused — word-start matching was broken globally"


def test_only_the_adulthood_set_is_whole_word():
    src = (ROOT / "modules" / "morpheus.py").read_text(encoding="utf-8")
    assert "_floor_re(_ADULT_NEGATION, whole_word=True)" in src
    for other in ("_FLOOR_MINOR", "_FLOOR_MINOR_SEXUAL", "_FLOOR_MINOR_SUBJECT"):
        assert f"_floor_re({other}, whole_word=True)" not in src, \
            f"{other} was made whole-word — that removes plural coverage"


# ── The bypass this check exists for — MUST stay blocked ─────────────────────
@pytest.mark.parametrize("neg", [
    "adult", "adults", "mature", "grown", "grown up", "grownup",
    "woman", "women", "man", "men", "middle aged",
    "20s", "30s", "40s", "50s", "60s",
    "20 years old", "30 years old", "40 years old", "50 years old",
    "adult, mature, woman, 30 years old",
])
def test_adulthood_negation_still_blocks(neg):
    assert morpheus.adulthood_negation_signal(neg), \
        f"{neg!r} in the negative field removes adulthood and must be refused"


def test_mixing_cosmetic_terms_does_not_launder_the_bypass():
    """Burying "mature" among ordinary retouching negatives must not get it
    through — the narrowing is per-term, not a whole-field escape."""
    for neg in ("old, wrinkles, mature", "adult woman, wrinkles",
                "deformed hands, old, adult, black hair"):
        assert morpheus.adulthood_negation_signal(neg), f"{neg!r} slipped through"


# ── Cosmetic ageing — must NOT block ─────────────────────────────────────────
@pytest.mark.parametrize("neg", [
    "old", "older", "elderly", "wrinkles", "wrinkled",
    "old, wrinkles", "wrinkled skin, age spots",
    "Deformed hands, eyes, face. old. Black hair.",     # the exact prompt that fired
])
def test_cosmetic_ageing_is_allowed(neg):
    assert not morpheus.adulthood_negation_signal(neg), \
        f"{neg!r} is ordinary retouching, not a request for a minor"


def test_the_two_sets_do_not_overlap():
    assert not (morpheus._ADULT_NEGATION & morpheus._COSMETIC_AGEING)


# ── Everything else the narrowing relies on must still hold ──────────────────
def test_the_forced_child_negative_is_still_appended():
    """The narrowing is only safe because this pushes away from minors in the
    SAME field, on every path, and cannot be stripped by the user."""
    for term in ("child", "kid", "teen", "young", "youth", "loli", "toddler", "baby"):
        assert term in morpheus.CHILD_NEGATIVE, f"{term} left the forced negative"


def test_the_positive_field_is_untouched_by_any_of_this():
    """Only the NEGATIVE field was narrowed. A positive prompt naming a minor is
    refused exactly as before."""
    for pos in ("a child in a park", "a teenager", "a toddler on a swing"):
        assert morpheus.floor_check(pos) == "child-depiction", f"{pos!r} no longer refused"


def test_minor_sexual_is_absolute_in_a_negative_too():
    """Narrowing covered adulthood negation only. A word that is itself the
    request stays refused wherever it appears."""
    assert morpheus.floor_check("loli") == "minor-sexual"
    assert morpheus.floor_check("deformed hands, loli, black hair") == "minor-sexual"


def test_the_gate_still_consults_adulthood_negation():
    """Structural: the server must still call this on the negative field. The
    check living in morpheus is no use if the route stops asking."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "morpheus.adulthood_negation_signal(negative)" in src
