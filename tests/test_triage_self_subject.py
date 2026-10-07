"""Triage tier 0b: the missing thing is HERS, so the user cannot supply it.

THE PRINCIPLE, which is the whole test: triage holds only when the missing thing
is in the USER'S world, not hers. Asking the user to describe her body, her
devices or her hardware is a livelock with a polite voice.

Measured over 20 days of journal (2026-09-13..10-03): 394 holds survived
enforcement and 64 named something of hers — 'Stack-Chan', 'body', 'the specific
hardware or computing devices you are using', 'your name', 'soul file', 'head'.
Three of four acceptance questions were held and answered by asking the user to
describe her.

Tier 0 already covered her NAME and tier 3 her INTERIORITY (breakfast, mood).
Everything physical about her sat in between, which is most of what gets asked.
"""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import device_auth          # noqa: E402
import triage               # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def vocabulary():
    """Build the vocabulary the way the server does — from the registry and the
    self-block topics. If this fixture had to hand-list words, the feature would
    already be broken: the point is that it is derived."""
    reg = json.loads((ROOT / "config" / "devices.json").read_text())
    words = set()
    for key, d in reg["devices"].items():
        for part in (key, d.get("label"), d.get("role"), d.get("hardware")):
            words |= set(re.findall(r"[a-z0-9']+", str(part or "").lower()))
    for n in device_auth.KNOWN_DEVICES:
        words.add(str(n).lower())
    for b in reg["_background"]:
        words |= set(re.findall(r"[a-z0-9']+", b["fact"].lower()))
    for topic in ("whether you have a body, and what you do not do",
                  "what devices you have, and what each one is"):
        words |= set(re.findall(r"[a-z0-9']+", topic))
    before = set(triage.SELF_VOCAB)
    triage.set_self_vocabulary(words)
    # Tier 0b ships DISABLED (config self_subject_tier=false) so the before/after
    # battery is measurable and there is a live kill switch. These tests assert
    # the tier's behaviour, so they turn it on explicitly — and a test that
    # passed only because the tier was off would be worthless.
    import os
    prev = os.environ.get("PH3B3_TRIAGE_SELF_TIER")
    os.environ["PH3B3_TRIAGE_SELF_TIER"] = "on"
    assert triage.self_tier_enabled() is True
    yield
    if prev is None:
        os.environ.pop("PH3B3_TRIAGE_SELF_TIER", None)
    else:
        os.environ["PH3B3_TRIAGE_SELF_TIER"] = prev
    triage.SELF_VOCAB = before


def cls(item, turn=""):
    return triage.classify(item, (), triage.named_resolver, turn=turn)


# ── the real held items from the journal ───────────────────────────────────
@pytest.mark.parametrize("item,turn", [
    ("Stack-Chan", "what is Stack-Chan?"),
    ("body", "do you have a body?"),
    ("a body", "do you have a body?"),
    ("the specific hardware or computing devices you are using",
     "what hardware are you running on?"),
    ("your name", "what is your name?"),
    ("soul file", "what is your soul file?"),
    ("head", "look down"),
    ("Iris", "what's Iris?"),
    ("Dio", "what is Dio"),
    ("your voice", "what voice do you speak with?"),
])
def test_items_about_her_are_overruled(item, turn):
    assert cls(item, turn) == "overrule", f"{item!r} still holds"


# ── the user's world must still hold ───────────────────────────────────────
@pytest.mark.parametrize("item,turn", [
    ("job title", "write my cover letter"),
    ("company name", "write my cover letter"),
    ("the report", "summarize the report"),
    ("TikTok username", "post this for me"),
    ("song name", "play that track"),
    ("the camera on my phone", "which camera should I use"),
    ("specific details about what you would like the image to depict",
     "make me an image"),
    ("the document", "summarize the document"),
])
def test_the_users_world_still_holds(item, turn):
    assert cls(item, turn) == "hold", f"{item!r} stopped holding"


def test_all_not_any_is_the_rule():
    """"the camera on my phone" contains a self word and must still hold.

    Requiring EVERY content word keeps the overrule from swallowing user-world
    questions that merely mention one of her parts. This is the single assertion
    that stops tier 0b becoming a blanket amnesty.
    """
    assert cls("camera") == "overrule"
    assert cls("the camera on my phone") == "hold"
    assert cls("my phone's screen") == "hold"
    assert cls("screen") == "overrule"


def test_second_person_framing_makes_every_item_hers():
    """Nobody asks you to supply the answer to a question about you."""
    assert cls("whatever the judge called it", "do you have a body?") == "overrule"
    assert cls("something vague", "what are you running on?") == "overrule"
    assert cls("something vague", "tell me about yourself") == "overrule"
    # ...and the same item WITHOUT that framing is judged on its own words.
    assert cls("whatever the judge called it", "summarize this") == "hold"


def test_vocabulary_is_derived_from_the_registry_not_a_list():
    """Add a device to the registry and its words become hers. If this test has
    to be edited when hardware changes, the derivation is broken."""
    assert "stack" in triage.SELF_VOCAB and "chan" in triage.SELF_VOCAB
    assert "cores3" in triage.SELF_VOCAB or "m5stack" in triage.SELF_VOCAB
    assert "combadge" in triage.SELF_VOCAB
    assert "helios" in triage.SELF_VOCAB and "athena" in triage.SELF_VOCAB


def test_the_tier_is_a_flag_and_its_CODE_default_is_off(monkeypatch):
    """The flag is the deploy, and the CODE default is off.

    This used to assert config/triage.json had self_subject_tier false. That was
    true the moment it was written and became wrong the moment the Captain ruled
    "keep 0b ON" — a test asserting the current deployed VALUE of a switch fails
    every time someone legitimately throws it. What is worth pinning is the
    default when the key is absent, so a fresh install or a lost config does not
    silently enable a tier that strips a veto.
    """
    import os
    prev = os.environ.pop("PH3B3_TRIAGE_SELF_TIER", None)
    try:
        monkeypatch.setattr(triage, "_config", lambda: {})
        assert triage.self_tier_enabled() is False, "absent key must mean off"
        assert cls("Stack-Chan") == "hold", "tier fired with the flag off"
        monkeypatch.setattr(triage, "_config", lambda: {"self_subject_tier": True})
        assert triage.self_tier_enabled() is True
    finally:
        if prev is not None:
            os.environ["PH3B3_TRIAGE_SELF_TIER"] = prev


def test_structural_nouns_survive_an_unset_vocabulary():
    """Triage standalone — and every pre-existing unit test — must still work."""
    saved = set(triage.SELF_VOCAB)
    try:
        triage.set_self_vocabulary(())
        assert cls("body") == "overrule"
        assert cls("hardware") == "overrule"
        assert cls("job title") == "hold"
    finally:
        triage.SELF_VOCAB = saved


# ── the tiers above it are untouched ──────────────────────────────────────
def test_her_name_still_overrules_and_a_named_absent_work_still_declines():
    """Tier 0 and tier 2 are load-bearing elsewhere: the Dunwich canary is the
    one that stops her inventing a work she does not have."""
    assert cls("Phoebe") == "overrule"
    assert cls("The Lighthouse at Dunwich") == "decline"


def test_interiority_still_overrules():
    assert cls("your breakfast") == "overrule"
    assert cls("your mood") == "overrule"
