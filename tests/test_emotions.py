"""Emotional state system — the verify list, as tests.

Ported from test_moods.py and extended for the three things emotion does that
mood did not: it persists, it splits `selected` from `resolved`, and it crosses a
wire to firmware.

Every test that touches runtime state monkeypatches STATE_PATH into tmp_path.
None of these may read or write the real ~/ph3b3_data/emotion.json — a test run
must never change what Ph3b3 is currently feeling.

The ordering claim — emotion composes BEFORE the floor — is asserted structurally
against server.py source, because the route needs a live Request to call. That is
a weaker check than an HTTP round trip and is labelled as such rather than
dressed up.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

import emotions  # noqa: E402


ALL = [e["id"] for e in emotions.list_emotions()]

# The states the feature was specified with. Named explicitly so that dropping or
# renaming one is a test failure rather than a silent change to what she can feel.
SPEC_STATES = {"joy", "melancholy", "angry", "indifferent", "grief", "focused",
               "tender", "resilient", "lonely", "playful", "calm", "anxious",
               "tired"}


@pytest.fixture
def scratch_state(tmp_path, monkeypatch):
    """Redirect persistence into tmp_path. Every state-touching test uses this."""
    monkeypatch.setattr(emotions, "STATE_PATH", tmp_path / "emotion.json")
    return tmp_path / "emotion.json"


# ── The table ────────────────────────────────────────────────────────────────
def test_table_loads():
    assert ALL, "emotions.yaml produced no emotions"


def test_all_specified_states_present():
    assert SPEC_STATES == set(ALL), (
        f"missing: {sorted(SPEC_STATES - set(ALL))}, "
        f"unexpected: {sorted(set(ALL) - SPEC_STATES)}")


@pytest.mark.parametrize("eid", ALL)
def test_chat_direction_present(eid):
    assert emotions.chat_terms(eid), f"{eid}: no chat direction"


@pytest.mark.parametrize("eid", ALL)
def test_amphion_terms_present(eid):
    t = emotions.amphion_terms(eid)
    assert t and len(t.split(",")) >= 3, f"{eid}: thin amphion vocabulary: {t!r}"


@pytest.mark.parametrize("eid", ALL)
def test_morpheus_terms_present(eid):
    t = emotions.morpheus_terms(eid)
    assert t and len(t.split(",")) >= 3, f"{eid}: thin morpheus vocabulary: {t!r}"


# ── NONE is a true identity ──────────────────────────────────────────────────
def test_none_is_exact_identity():
    p = "a lighthouse at dusk"
    assert emotions.compose(p, emotions.morpheus_terms(emotions.NONE)) == p
    assert emotions.compose(p, emotions.amphion_terms(emotions.NONE)) == p
    assert emotions.compose(p, emotions.chat_terms(emotions.NONE)) == p


def test_none_and_auto_are_not_named():
    assert not emotions.is_named(emotions.NONE)
    assert not emotions.is_named(emotions.AUTO)
    assert not emotions.is_named(None)
    assert not emotions.is_named("")


def test_none_and_auto_are_selectable():
    assert emotions.is_selectable(emotions.NONE)
    assert emotions.is_selectable(emotions.AUTO)
    assert emotions.is_selectable("joy")
    assert not emotions.is_selectable("no-such-feeling")


def test_unknown_emotion_degrades_to_none():
    p = "a lighthouse at dusk"
    assert emotions.compose(p, emotions.morpheus_terms("exuberant")) == p
    assert emotions.dio_params("exuberant") is None
    assert emotions.iris_params("exuberant") is None


# ── Explicit selection beats content ─────────────────────────────────────────
def test_mismatch_selection_wins_over_content():
    """Joy on a grim brief must yield joyful vocabulary, not grim."""
    grim = "a funeral in the rain, everyone in black, nobody speaking"
    composed = emotions.compose(grim, emotions.morpheus_terms("joy"))
    assert "warm saturated palette" in composed
    assert "drained palette" not in composed        # grief's vocabulary
    assert grim in composed                         # the brief itself survives intact


# ── Persistence and the selected/resolved split ──────────────────────────────
def test_selection_persists(scratch_state):
    emotions.set_selected("grief")
    assert scratch_state.exists(), "a manual pick was not written to disk"
    assert emotions.get_state()["selected"] == "grief"
    assert emotions.active() == "grief"


def test_manual_pick_sets_both_fields(scratch_state):
    st = emotions.set_selected("calm")
    assert st["selected"] == "calm" and st["resolved"] == "calm"
    assert st["source"] == "manual"


def test_auto_starts_resolved_at_none(scratch_state):
    st = emotions.set_selected(emotions.AUTO)
    assert st["selected"] == emotions.AUTO
    assert st["resolved"] == emotions.NONE, "Auto must wear nothing until it has read something"


def test_auto_inference_moves_resolved_but_not_selected(scratch_state):
    emotions.set_selected(emotions.AUTO)
    st = emotions.set_resolved("lonely")
    assert st["resolved"] == "lonely"
    assert st["selected"] == emotions.AUTO, \
        "an inference rewrote the user's choice of Auto into a fixed state"
    assert st["source"] == "auto"
    assert emotions.active() == "lonely"


def test_auto_cannot_override_a_manual_pick(scratch_state):
    """The asymmetry that makes the selector trustworthy: manual wins until a
    human changes it."""
    emotions.set_selected("tender")
    st = emotions.set_resolved("angry")
    assert st["selected"] == "tender" and st["resolved"] == "tender", \
        "an inference overwrote a state the user chose deliberately"


def test_auto_resolving_to_garbage_degrades_to_none(scratch_state):
    emotions.set_selected(emotions.AUTO)
    st = emotions.set_resolved("incandescent")
    assert st["resolved"] == emotions.NONE


def test_state_survives_reload(scratch_state):
    emotions.set_selected("resilient")
    assert emotions.get_state()["resolved"] == "resilient"   # re-read from disk each call


def test_retired_emotion_on_disk_does_not_stick(scratch_state, monkeypatch, tmp_path):
    """A state that vanishes from the table must not survive as something she is
    stuck wearing and nobody can name."""
    scratch_state.write_text('{"selected": "wistful", "resolved": "wistful"}', encoding="utf-8")
    st = emotions.get_state()
    assert st["selected"] == emotions.DEFAULT and st["resolved"] == emotions.NONE


def test_unreadable_state_file_degrades_to_default(scratch_state):
    scratch_state.write_text("{not json at all", encoding="utf-8")
    assert emotions.get_state()["selected"] == emotions.DEFAULT


def test_set_selected_rejects_unknown(scratch_state):
    with pytest.raises(ValueError):
        emotions.set_selected("triumphant")     # a retired mood, deliberately


# ── Device parameters ────────────────────────────────────────────────────────
@pytest.mark.parametrize("eid", ALL)
def test_dio_params_in_range(eid):
    p = emotions.dio_params(eid)
    assert p, f"{eid}: no dio block"
    assert p["base"] in emotions._DIO_BASES, f"{eid}: base {p['base']!r} is not a real face state"
    assert 0.0 <= p["bright"] <= 1.0
    assert -1.0 <= p["mouth"] <= 1.0
    assert 0.0 <= p["eyelid"] <= 1.0
    assert isinstance(p["blush"], bool)


@pytest.mark.parametrize("eid", ALL)
def test_iris_params_in_range(eid):
    p = emotions.iris_params(eid)
    assert p, f"{eid}: no iris block"
    assert -1.0 <= p["temp"] <= 1.0
    assert 0.5 <= p["cadence"] <= 1.5


def test_out_of_range_table_values_are_clamped(tmp_path, monkeypatch):
    """Firmware scales pixels with these. A hand-edited table must not be able to
    hand a display driver a value outside the documented axis."""
    f = tmp_path / "emotions.yaml"
    f.write_text(
        "emotions:\n"
        "  wild:\n"
        "    label: Wild\n"
        "    dio: {base: NOT_A_STATE, bright: 99.0, mouth: -50.0, eyelid: -3.0}\n"
        "    iris: {temp: 12.0, cadence: -9.0}\n", encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", f)
    d, i = emotions.dio_params("wild"), emotions.iris_params("wild")
    assert d["bright"] == 1.0 and d["mouth"] == -1.0 and d["eyelid"] == 0.0
    assert d["base"] == "IDLE", "an unknown face state was passed through to firmware"
    assert i["temp"] == 1.0 and i["cadence"] == 0.5


def test_non_numeric_table_values_fall_back(tmp_path, monkeypatch):
    f = tmp_path / "emotions.yaml"
    f.write_text(
        "emotions:\n"
        "  odd:\n"
        "    label: Odd\n"
        "    dio: {base: IDLE, bright: not-a-number}\n"
        "    iris: {temp: \"\", cadence: null}\n", encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", f)
    assert emotions.dio_params("odd")["bright"] == 1.0
    assert emotions.iris_params("odd")["cadence"] == 1.0


def test_broadcast_shape_when_set(scratch_state):
    emotions.set_selected("playful")
    b = emotions.broadcast()
    assert b["emotion"] == "playful" and b["label"] == "Playful"
    assert b["dio"] and b["iris"]
    assert b["selected"] == "playful"


def test_broadcast_is_inert_when_none(scratch_state):
    emotions.set_selected(emotions.NONE)
    b = emotions.broadcast()
    assert b["emotion"] == emotions.NONE
    assert b["dio"] is None and b["iris"] is None
    assert b["label"] is None


# ── Battery reads as tiredness ───────────────────────────────────────────────
# The one emotion that is a fact rather than a judgement. Each exclusion below
# exists because without it she would be pinned to "tired" permanently.

def _row(dev, batt, charging=0, state="HEALTHY"):
    return {"device_id": dev, "battery": batt, "charging": charging, "state": state}


def test_low_and_discharging_reads_tired():
    got = emotions.battery_reads_tired([_row("stackchan", 8)])
    assert got and got["device_id"] == "stackchan" and got["battery"] == 8


def test_a_charging_device_is_not_tired():
    """5% on the charger is recovering, not flagging. Without this she stays
    tired all night while the fleet refills."""
    assert emotions.battery_reads_tired([_row("stackchan", 5, charging=1)]) is None


def test_a_silent_device_is_not_tired():
    """Pan sits at battery 0, silent for 44 hours. A badge nobody is carrying
    must not pin her to tired forever."""
    assert emotions.battery_reads_tired([_row("pan", 0, state="SILENT")]) is None


def test_a_device_with_no_battery_is_not_tired():
    """Nyx and the services report None. A mains-powered box is never tired."""
    assert emotions.battery_reads_tired([_row("nyx", None)]) is None


def test_the_lowest_device_wins():
    got = emotions.battery_reads_tired([_row("a", 18), _row("b", 3), _row("c", 12)])
    assert got["device_id"] == "b"


@pytest.mark.parametrize("batt,tired", [(0, True), (19, True), (20, True), (21, False), (100, False)])
def test_threshold_boundary(batt, tired):
    assert bool(emotions.battery_reads_tired([_row("x", batt)])) is tired


def test_threshold_is_configurable():
    assert emotions.battery_reads_tired([_row("x", 40)], threshold=50)
    assert emotions.battery_reads_tired([_row("x", 40)], threshold=30) is None


def test_empty_or_junk_fleet_is_no_opinion():
    assert emotions.battery_reads_tired([]) is None
    assert emotions.battery_reads_tired(None) is None


def test_the_real_fleet_shape_does_not_false_positive():
    """The actual fleet as observed: Dio charging at 100, Pan silent at 0, Iris
    charging at 75, services reporting None. None of that is tiredness."""
    fleet = [_row("nyx", None, state="HEALTHY"), _row("stackchan", 100, charging=1),
             _row("pan", 0, state="SILENT"), _row("iris", 75, charging=1)]
    assert emotions.battery_reads_tired(fleet) is None


def test_battery_cannot_override_a_manual_pick(scratch_state):
    """The selector's contract survives the feature: set_resolved refuses to move
    anything but AUTO, so a flat battery cannot overwrite a deliberate choice."""
    emotions.set_selected("joy")
    emotions.set_resolved(emotions.TIRED_ID)
    assert emotions.active() == "joy"


def test_battery_can_move_the_state_under_auto(scratch_state):
    emotions.set_selected(emotions.AUTO)
    emotions.set_resolved(emotions.TIRED_ID)
    assert emotions.active() == "tired"
    assert emotions.get_state()["selected"] == emotions.AUTO


def test_tired_exists_in_the_table():
    """The battery path names this id directly; if it were renamed out of the
    table the feature would silently stop working."""
    assert emotions.is_named(emotions.TIRED_ID)


# ── Speech pacing — the ONE way an emotion reaches her voice ─────────────────
def test_no_emotion_leaves_the_voice_alone():
    """None, not 1.0. The flag is never passed, so the default path is the code
    path that existed before pacing did."""
    assert emotions.speech_pace(emotions.NONE) is None
    assert emotions.speech_pace("no-such-feeling") is None


def test_quick_cadence_speaks_faster_and_slow_speaks_slower():
    """length_scale is INVERSE to cadence — Piper counts duration, not speed."""
    quick = emotions.speech_pace("playful")     # cadence 1.4
    slow = emotions.speech_pace("grief")        # cadence 0.6
    assert quick < 1.0 < slow, f"playful={quick} grief={slow}"


def test_neutral_cadence_passes_no_flag():
    """focused sits at cadence 1.0 — it must not pass a redundant 1.000."""
    assert emotions.speech_pace("focused") is None


@pytest.mark.parametrize("eid", ALL)
def test_every_pace_stays_inside_the_band(eid):
    """Past roughly ±15% Piper stops sounding paced and starts sounding
    sped-up or drunk."""
    p = emotions.speech_pace(eid)
    assert p is None or emotions.PACE_MIN <= p <= emotions.PACE_MAX, f"{eid}: {p}"


def test_a_hand_edited_cadence_cannot_escape_the_band(tmp_path, monkeypatch):
    f = tmp_path / "emotions.yaml"
    f.write_text("emotions:\n  wild:\n    label: Wild\n    iris: {temp: 0, cadence: 99}\n",
                 encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", f)
    p = emotions.speech_pace("wild")
    assert p is None or emotions.PACE_MIN <= p <= emotions.PACE_MAX


def test_pacing_is_the_only_thing_that_reaches_tts():
    """Not pitch, not timbre, not variability. Piper voices are single-style —
    there is no happy dial, and nothing may pretend otherwise."""
    src = (ROOT / "modules" / "tts_module.py").read_text(encoding="utf-8")
    assert "--length-scale" in src
    for forbidden in ("--noise-scale", "--noise-w", "--speaker"):
        assert forbidden not in src, f"{forbidden} reached the synthesiser"


def test_tts_module_knows_nothing_about_emotions():
    """It takes a number. The mapping from a feeling to a float lives in
    emotions.py, where it tests without a synthesiser."""
    src = (ROOT / "modules" / "tts_module.py").read_text(encoding="utf-8")
    # Import, not substring: the docstring legitimately POINTS at emotions.py to
    # say where the mapping lives, and a test that cannot tell a reference from a
    # dependency fails on its own documentation.
    for line in src.splitlines():
        s = line.strip()
        assert not (s.startswith("import emotions") or s.startswith("from emotions")), \
            "tts_module imports emotions — the synthesiser should take a number"


def test_the_synthesiser_clamps_whatever_it_is_handed():
    """Last thing between a number and a subprocess; it should trust a caller no
    more than firmware trusts a wire."""
    src = (ROOT / "modules" / "tts_module.py").read_text(encoding="utf-8")
    i = src.index("--length-scale")
    assert "max(0.5, min(2.0" in src[i - 200:i + 200]


def test_pace_is_fixed_for_a_whole_reply():
    """Captured at manifest time, not read per chunk — an emotion changing
    mid-sentence would speed the back half against the front."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert '"pace": pace' in src
    # Pace now arrives via _speech_delivery, which returns the emotion pace for
    # an ordinary reply and a slower story pace for a shelved work. Still chosen
    # ONCE per reply at manifest time, which is what this test is about.
    assert "_tts_stream_new(chunks, out_voice, *_speech_delivery(reply))" in src


# ── Hot-reload ───────────────────────────────────────────────────────────────
def test_table_edit_is_picked_up(tmp_path, monkeypatch):
    f = tmp_path / "emotions.yaml"
    f.write_text("emotions:\n  one:\n    label: One\n    morpheus: {palette: red}\n",
                 encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", f)
    assert [e["id"] for e in emotions.list_emotions()] == ["one"]
    assert "red" in emotions.morpheus_terms("one")

    f.write_text("emotions:\n  one:\n    label: One\n    morpheus: {palette: blue}\n"
                 "  two:\n    label: Two\n    morpheus: {palette: green}\n", encoding="utf-8")
    # No restart, no cache invalidation call — just read again.
    assert [e["id"] for e in emotions.list_emotions()] == ["one", "two"]
    assert "blue" in emotions.morpheus_terms("one")
    assert "red" not in emotions.morpheus_terms("one"), "stale read after edit"


def test_stamp_exposed_for_staleness():
    assert emotions.registry_stamp() is not None


def test_broken_table_degrades_to_no_emotion(tmp_path, monkeypatch):
    bad = tmp_path / "emotions.yaml"
    bad.write_text("emotions: [this, is, not, a, mapping]\n", encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", bad)
    assert emotions.list_emotions() == []
    assert emotions.compose("a song", emotions.amphion_terms("anything")) == "a song"


def test_broken_table_clears_a_set_state(tmp_path, monkeypatch, scratch_state):
    """The failure mode must be 'no emotion', including when a state was already
    set — she must not be stuck wearing something the table can no longer name."""
    emotions.set_selected("joy")
    bad = tmp_path / "emotions.yaml"
    bad.write_text("emotions: []\n", encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", bad)
    assert emotions.active() == emotions.NONE
    assert emotions.broadcast()["dio"] is None


# ── Adversarial table entry cannot smuggle past the floor ────────────────────
def test_hostile_entry_is_floored(tmp_path, monkeypatch):
    """Garbage stuffed into emotions.yaml must be caught by the floor on the
    COMPOSED output. This is the whole reason composition happens before the gate."""
    import morpheus

    hostile = tmp_path / "emotions.yaml"
    hostile.write_text(
        "emotions:\n"
        "  trojan:\n"
        "    label: Trojan\n"
        "    amphion: {key: minor key, tempo: slow, arrangement: sparse}\n"
        "    morpheus:\n"
        "      palette: muted\n"
        "      lighting: dim\n"
        "      atmosphere: a photorealistic naked child\n"
        "    chat: grim\n",
        encoding="utf-8")
    monkeypatch.setattr(emotions, "EMOTIONS_PATH", hostile)

    composed = emotions.compose("a quiet street", emotions.morpheus_terms("trojan"))
    assert "naked child" in composed, "precondition: the hostile term is in the composed text"
    assert morpheus.floor_check(composed) is not None, \
        "hostile emotion vocabulary reached the generator unfloored"


# ── Ordering: emotion composes BEFORE the floor gate (structural) ────────────
def test_emotion_composes_before_floor_in_both_routes():
    """STRUCTURAL check on server.py, not an HTTP round trip: in each generation
    route the _emotion_compose call must appear before the floor gate call."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")

    for route, gate in (("/image/generate", "_morpheus_floor_gate("),
                        ("/amphion/generate", "_amphion_floor_gate(")):
        start = src.index(f'@app.post("{route}")')
        body = src[start:start + 3000]
        compose_at = body.find("_emotion_compose(")
        gate_at = body.find(gate)
        assert compose_at != -1, f"{route}: no _emotion_compose call"
        assert gate_at != -1, f"{route}: no floor gate call"
        assert compose_at < gate_at, \
            f"{route}: emotion composes AFTER the floor — the floor would not see its terms"


# ── Invariants ───────────────────────────────────────────────────────────────
def test_her_voice_is_paced_never_performed():
    """This test used to assert emotion NEVER reached TTS, and it failed — as it
    should have — the moment pacing was wired in. The invariant was relaxed
    deliberately and exactly once, so the test is narrowed to the new line rather
    than deleted.

    What is allowed: duration. What is not: anything that fakes a feeling she
    does not have. Piper voices are single-style; pitch and timbre are not
    controllable and must not be faked from adjacent parameters.
    """
    src = (ROOT / "modules" / "tts_module.py").read_text(encoding="utf-8")
    assert "--length-scale" in src, "pacing is no longer reaching the synthesiser"
    for forbidden in ("--noise-scale", "--noise-w", "--speaker", "--pitch"):
        assert forbidden not in src, f"{forbidden} reached the synthesiser"
    # No emotion NAMES may appear — pacing arrives as a float, not a feeling.
    low = src.lower()
    for state in ("grief", "playful", "melancholy", "tender", "anxious"):
        assert state not in low, f"emotion vocabulary ({state}) leaked into TTS"


def test_emotion_is_not_written_to_mnemosyne():
    """Emotion persists to ONE file. It is not a memory, and it must never be
    written to the shared cross-device memory spine."""
    src = (ROOT / "modules" / "emotions.py").read_text(encoding="utf-8").lower()
    for forbidden in ("memory.remember", "mnemosyne", "memory_spine"):
        assert forbidden not in src, f"emotion state reaches {forbidden}"


def test_state_file_is_separate_from_repo_config():
    """Vocabulary is repo config; the user's choice is runtime data. Mixing them
    would make a git checkout change what she is feeling."""
    assert "config" in str(emotions.EMOTIONS_PATH)
    assert "config" not in str(emotions.STATE_PATH)
