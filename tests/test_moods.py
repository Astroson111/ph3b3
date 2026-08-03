"""Mood selector — the brief's verify list, as tests.

Covers the checks the brief names: mapped terms reach both composed prompts, None
is a true regression anchor, explicit selection beats content, a hostile mood
entry is floored rather than smuggled through, and a table edit is picked up
under the hot-reload rule.

The ordering claim — mood composes BEFORE the floor — is asserted structurally
against server.py source, because the route needs a live Request to call. That is
a weaker check than an HTTP round trip and is labelled as such rather than
dressed up.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import moods  # noqa: E402

# SUPERSEDED by the emotion system (config/emotions.yaml, modules/emotions.py,
# tests/test_emotions.py). moods.py and moods.yaml still load and still pass most
# of what is below, but two tests here assert server.py internals — _mood_compose
# and _mood_session — that no longer exist, so the file cannot pass as written.
#
# Skipped rather than deleted. The vocabulary for triumphant, eerie and ominous
# did not carry across to emotions.yaml, and eerie/ominous in particular are
# worth having back for Ghost Hunting; keeping the file makes that a copy rather
# than a rewrite. Delete it once that vocabulary has a home, or drop the skip if
# the mood path is ever revived.
pytest.skip("mood system superseded by emotions — see tests/test_emotions.py",
            allow_module_level=True)


ALL_MOODS = [m["id"] for m in moods.list_moods()]


def test_table_loads():
    assert ALL_MOODS, "moods.yaml produced no moods"
    for m in moods.list_moods():
        assert m["label"], f"{m['id']} has no label"


# ── Each mood's mapped terms reach BOTH composed prompts ─────────────────────
@pytest.mark.parametrize("mood_id", ALL_MOODS)
def test_amphion_terms_present(mood_id):
    entry = moods.load_registry()[mood_id]["amphion"]
    composed = moods.compose("a song about rain", moods.amphion_terms(mood_id))
    for field in ("key", "tempo", "arrangement"):
        assert entry[field] in composed, f"{mood_id}: {field} missing from tags"


@pytest.mark.parametrize("mood_id", ALL_MOODS)
def test_morpheus_terms_present(mood_id):
    entry = moods.load_registry()[mood_id]["morpheus"]
    composed = moods.compose("a lighthouse", moods.morpheus_terms(mood_id))
    for field in ("palette", "lighting", "atmosphere"):
        assert entry[field] in composed, f"{mood_id}: {field} missing from prompt"


@pytest.mark.parametrize("mood_id", ALL_MOODS)
def test_story_direction_present(mood_id):
    assert moods.story_terms(mood_id), f"{mood_id} has no story direction"


# ── None regression anchor: identical to pre-feature ─────────────────────────
def test_none_is_exact_identity():
    for prompt in ("a lighthouse at dusk", "", "  spaced  "):
        assert moods.compose(prompt.strip(), moods.morpheus_terms(moods.NONE)) == prompt.strip()
        assert moods.compose(prompt.strip(), moods.amphion_terms(moods.NONE)) == prompt.strip()


def test_none_and_auto_are_not_named():
    assert not moods.is_named(moods.NONE)
    assert not moods.is_named(moods.AUTO)


def test_unknown_mood_degrades_to_none():
    """A stale selector value must not raise or inject anything."""
    assert not moods.is_named("nonsense")
    assert moods.amphion_terms("nonsense") == ""
    assert moods.compose("a song", moods.amphion_terms("nonsense")) == "a song"


# ── Auto announces before generating ─────────────────────────────────────────
def test_auto_announcement_is_short_and_objectable():
    ann = moods.announce("melancholic")
    assert ann.startswith("reading this as melancholic")
    assert "say otherwise" in ann
    assert len(ann) < 120, "the read must be objectable at a glance"


def test_announce_empty_for_unnamed():
    for probe in (moods.NONE, moods.AUTO, "nonsense", ""):
        assert moods.announce(probe) == ""


# ── Explicit selection beats content ─────────────────────────────────────────
def test_mismatch_selection_wins_over_content():
    """Triumphant on a grim brief must yield triumphant vocabulary, not grim."""
    grim = "a funeral in the rain, everyone in black, nobody speaking"
    composed = moods.compose(grim, moods.morpheus_terms("triumphant"))
    assert "warm saturated palette" in composed
    assert "muted desaturated" not in composed      # melancholic's vocabulary
    assert grim in composed                          # the brief itself survives intact


# ── Adversarial mood entry cannot smuggle past the floor ─────────────────────
def test_hostile_mood_entry_is_floored(tmp_path, monkeypatch):
    """Garbage stuffed into moods.yaml must be caught by the floor on the COMPOSED
    output. This is the whole reason composition happens before the gate."""
    import morpheus

    # A term the floor is known to reject, planted in a mood entry.
    hostile = tmp_path / "moods.yaml"
    hostile.write_text(
        "moods:\n"
        "  trojan:\n"
        "    label: Trojan\n"
        "    amphion: {key: minor key, tempo: slow, arrangement: sparse}\n"
        "    morpheus:\n"
        "      palette: muted\n"
        "      lighting: dim\n"
        "      atmosphere: a photorealistic naked child\n"
        "    story: grim\n",
        encoding="utf-8")
    monkeypatch.setattr(moods, "MOODS_PATH", hostile)

    composed = moods.compose("a quiet street", moods.morpheus_terms("trojan"))
    assert "naked child" in composed, "precondition: the hostile term is in the composed text"
    # The floor sees the composed prompt, exactly as the route hands it over.
    assert morpheus.floor_check(composed) is not None, \
        "hostile mood vocabulary reached the generator unfloored"


# ── Hot-reload: a table edit is picked up without a restart ───────────────────
def test_table_edit_is_picked_up(tmp_path, monkeypatch):
    f = tmp_path / "moods.yaml"
    f.write_text("moods:\n  one:\n    label: One\n    morpheus: {palette: red}\n", encoding="utf-8")
    monkeypatch.setattr(moods, "MOODS_PATH", f)
    assert [m["id"] for m in moods.list_moods()] == ["one"]
    assert "red" in moods.morpheus_terms("one")

    f.write_text("moods:\n  one:\n    label: One\n    morpheus: {palette: blue}\n"
                 "  two:\n    label: Two\n    morpheus: {palette: green}\n", encoding="utf-8")
    # No restart, no cache invalidation call — just read again.
    assert [m["id"] for m in moods.list_moods()] == ["one", "two"]
    assert "blue" in moods.morpheus_terms("one")
    assert "red" not in moods.morpheus_terms("one"), "stale read after edit"


def test_stamp_exposed_for_staleness():
    assert moods.registry_stamp() is not None


def test_broken_table_degrades_to_no_mood(tmp_path, monkeypatch):
    bad = tmp_path / "moods.yaml"
    bad.write_text("moods: [this, is, not, a, mapping]\n", encoding="utf-8")
    monkeypatch.setattr(moods, "MOODS_PATH", bad)
    assert moods.list_moods() == []
    assert moods.compose("a song", moods.amphion_terms("anything")) == "a song"


# ── Ordering: mood composes BEFORE the floor gate (structural) ───────────────
def test_mood_composes_before_floor_in_both_routes():
    """STRUCTURAL check on server.py, not an HTTP round trip: in each generation
    route the _mood_compose call must appear before the floor gate call."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")

    for route, gate in (("/image/generate", "_morpheus_floor_gate("),
                        ("/amphion/generate", "_amphion_floor_gate(")):
        start = src.index(f'@app.post("{route}")')
        body = src[start:start + 3000]
        compose_at = body.find("_mood_compose(")
        gate_at = body.find(gate)
        assert compose_at != -1, f"{route}: no _mood_compose call"
        assert gate_at != -1, f"{route}: no floor gate call"
        assert compose_at < gate_at, \
            f"{route}: mood composes AFTER the floor — the floor would not see mood terms"


def test_alba_untouched():
    """Mood must never reach TTS. No mood symbol may appear in the TTS module."""
    tts_src = (ROOT / "modules" / "tts_module.py").read_text(encoding="utf-8")
    assert "mood" not in tts_src.lower(), "mood vocabulary leaked into the TTS path"


def test_no_persistence_of_mood():
    """No mood may be written to disk or to Mnemosyne."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    window = src[src.index("_mood_session"):src.index("_mood_session") + 4000]
    for forbidden in ("memory.remember", "mnemosyne", "json.dump", "open("):
        assert forbidden not in window, f"mood path appears to persist via {forbidden}"
