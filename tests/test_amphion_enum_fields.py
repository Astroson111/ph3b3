"""A closed enum never sits behind a free-text box.

THE BUG, 2026-09-26. Key field "d minor" (lowercase), 90 BPM, 4/4, instrumental,
80s. ComfyUI rejected the whole workflow, and the captured node_errors named the
cause exactly:

  {"5": {"class_type": "TextEncodeAceStepAudio1.5",
         "errors": [{"type": "value_not_in_list",
                     "details": "keyscale: 'd minor' not in (list of length 34)",
                     "extra_info": {"input_name": "keyscale",
                                    "received_value": "d minor"}}]}}

"D minor" is one of the 34 options. "d minor" is not. The panel's Key field was
an <input type="text">, so 33 of every 34 plausible spellings killed the render —
and the user only found out after being told it had started, in a message that
said "Value not in list" and named neither the field nor the value.

Three things are checked here, one per part of the fix:

  1. the node's COMBO inputs are SELECTORS, filled from /object_info — the panel
     cannot express an invalid value, and case-normalisation is only the fallback
     for the API and her own tool path
  2. a rejection names the field, the value, and the nearest legal spelling
  3. every exit from a generation ends the running state — status failed, Cancel
     gone, Generate live again
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import amphion   # noqa: E402
import morpheus  # noqa: E402

PANEL = (ROOT / "static" / "panel.html").read_text(encoding="utf-8")

# The response captured from the real repro, byte for byte.
REPRO_REJECTION = {
    "error": {"type": "prompt_outputs_failed_validation",
              "message": "Prompt outputs failed validation", "details": "",
              "extra_info": {}},
    "node_errors": {"5": {
        "errors": [{"type": "value_not_in_list", "message": "Value not in list",
                    "details": "keyscale: 'd minor' not in (list of length 34)",
                    "extra_info": {"input_name": "keyscale", "input_config": None,
                                   "received_value": "d minor"}}],
        "dependent_outputs": ["10"],
        "class_type": "TextEncodeAceStepAudio1.5"}},
}


# ── 1a. the values themselves ────────────────────────────────────────────────
def test_the_repro_value_normalises_to_the_one_the_node_takes():
    assert amphion.normalise_keyscale("d minor") == "D minor"


@pytest.mark.parametrize("raw,want", [
    ("D minor", "D minor"),
    ("d minor", "D minor"),
    ("  D   MINOR  ", "D minor"),
    ("c major", "C major"),
    ("bb minor", "Bb minor"),
    ("f# MAJOR", "F# major"),
])
def test_case_and_spacing_are_forgiven(raw, want):
    assert amphion.normalise_keyscale(raw) == want


@pytest.mark.parametrize("raw", ["Dm", "D-minor", "dorian", "D", "minor", "", "  ", None, 7])
def test_anything_that_is_not_a_key_returns_none(raw):
    """NOT a music parser on purpose. Guessing at a key conditions the whole
    track on the wrong scale and tells nobody — worse than naming the options."""
    assert amphion.normalise_keyscale(raw) is None


def test_every_option_round_trips_through_its_own_lowercase():
    for opt in amphion.node_options()["keyscale"]:
        assert amphion.normalise_keyscale(opt.lower()) == opt


# ── 1b. the workflow cannot carry a value the node rejects ───────────────────
JUNK = ["d minor", "Dm", "dorian", "", None, "C MAJOR", 42, "d  MINOR"]


@pytest.mark.parametrize("junk", JUNK)
def test_build_workflow_never_emits_an_invalid_keyscale(junk):
    wf = amphion.build_workflow("t", {"tags": "x", "seed": 1, "seconds": 30.0,
                                      "keyscale": junk})
    got = wf["5"]["inputs"]["keyscale"]
    assert got in amphion.node_options()["keyscale"], \
        f"{junk!r} produced {got!r}, which ComfyUI would reject"


@pytest.mark.parametrize("junk", ["xx", "english", "", None, "EN", 5])
def test_build_workflow_never_emits_an_invalid_language(junk):
    wf = amphion.build_workflow("t", {"tags": "x", "seed": 1, "seconds": 30.0,
                                      "language": junk})
    assert wf["5"]["inputs"]["language"] in amphion.node_options()["language"]


@pytest.mark.parametrize("junk", ["4/4", "7/8", "", None, "four", 4])
def test_build_workflow_never_emits_an_invalid_timesignature(junk):
    wf = amphion.build_workflow("t", {"tags": "x", "seed": 1, "seconds": 30.0,
                                      "timesig": junk})
    assert wf["5"]["inputs"]["timesignature"] in amphion.TIMESIG_OPTIONS


def test_the_repro_now_builds_a_workflow_the_node_accepts():
    """The exact repro: "d minor", 90 BPM, 4/4, instrumental, 80s."""
    wf = amphion.build_workflow("repro", {
        "tags": "instrumental, ambient", "lyrics": "", "seed": 12345, "bpm": 90,
        "seconds": 80.0, "timesig": "4/4", "language": "en", "keyscale": "d minor"})
    i = wf["5"]["inputs"]
    assert i["keyscale"] == "D minor"
    assert i["timesignature"] == "4"
    assert i["language"] == "en"


# ── 1c. the options come from the node, and say so when they don't ───────────
def test_the_options_are_read_from_the_node_not_hardcoded():
    src = (ROOT / "modules" / "amphion.py").read_text(encoding="utf-8")
    i = src.index("def node_options")
    body = src[i:src.index("def options_source")]
    assert "object_info" in body, "the options are not read from ComfyUI at all"


def test_it_falls_back_to_the_pinned_tables_when_comfyui_is_down(monkeypatch):
    """A selector built from a stale list still cannot produce "d minor"."""
    amphion._options_cache.clear()
    monkeypatch.setattr(amphion.httpx, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("refused")))
    opts = amphion.node_options()
    assert opts["keyscale"] == list(amphion.KEYSCALE_OPTIONS)
    assert amphion.options_source() == "fallback"
    assert amphion.normalise_keyscale("d minor") == "D minor", \
        "normalisation must still work with ComfyUI down"
    amphion._options_cache.clear()


def test_the_pinned_fallback_agrees_with_the_live_node():
    """The offline list is only trustworthy if it matches the node it stands in
    for. Skips rather than failing when ComfyUI is not running."""
    amphion._options_cache.clear()
    live = amphion.node_options()
    if amphion.options_source() != "comfyui":
        amphion._options_cache.clear()
        pytest.skip("ComfyUI not reachable — cannot compare the fallback to it")
    assert live["keyscale"] == list(amphion.KEYSCALE_OPTIONS), \
        "the pinned key list has drifted from the installed node"
    assert live["timesignature"] == list(amphion.TIMESIG_OPTIONS)
    assert live["language"] == list(amphion.LANGUAGE_OPTIONS)


# ── 2. the rejection is readable ─────────────────────────────────────────────
def test_the_rejection_names_the_field_and_the_value(monkeypatch):
    monkeypatch.setattr(morpheus, "_node_enum_options", lambda *a: None)
    msg = morpheus.explain_rejection(REPRO_REJECTION)
    assert "keyscale" in msg
    assert "'d minor'" in msg
    assert "node 5" in msg and "TextEncodeAceStepAudio1.5" in msg


def test_the_rejection_offers_the_nearest_legal_value(monkeypatch):
    monkeypatch.setattr(morpheus, "_node_enum_options",
                        lambda *a: list(amphion.KEYSCALE_OPTIONS))
    msg = morpheus.explain_rejection(REPRO_REJECTION)
    assert "D minor" in msg, f"no suggestion offered:\n{msg}"


def test_the_old_message_named_nothing_and_is_gone():
    """Regression on the report itself: "Value not in list" alone is what the
    Captain saw, and it names neither field nor value."""
    monkeypatch_free = morpheus.explain_rejection(REPRO_REJECTION)
    assert monkeypatch_free.strip() != "Value not in list"
    assert "keyscale" in monkeypatch_free


def test_a_rejection_with_no_extra_info_still_says_something():
    bare = {"node_errors": {"9": {"class_type": "VAEDecodeAudio",
                                  "errors": [{"message": "Required input is missing",
                                              "details": "vae"}]}}}
    msg = morpheus.explain_rejection(bare)
    assert "node 9" in msg and "Required input is missing" in msg and "vae" in msg


def test_an_unrecognised_shape_falls_back_to_the_raw_response():
    msg = morpheus.explain_rejection({"something": "else"})
    assert msg, "an unreadable rejection produced an empty reason"


# ── 1d. the panel cannot express the bad value ───────────────────────────────
def test_the_key_field_is_a_selector_not_a_text_box():
    assert '<select id="ampKey"' in PANEL, "Key is not a selector"
    assert 'id="ampKey" class="ari-url" value=' not in PANEL
    assert '<input type="text" id="ampKey"' not in PANEL, \
        "the free-text Key field is back — 33 wrong spellings for every right one"


def test_the_panel_fills_the_selectors_from_the_node():
    assert "/amphion/options" in PANEL, "the panel never asks the node for its options"
    assert "ampLoadOptions" in PANEL


def test_the_panel_sends_the_selector_value_verbatim():
    assert "keyscale: (($('ampKey')||{}).value || 'C major')" in PANEL, \
        "the submit no longer reads the selector"


def test_a_stale_option_list_is_disclosed():
    assert "ampKeyNote" in PANEL and "unreachable" in PANEL, \
        "a fallback list is shown as though it came from the running node"


# ── 3. no exit leaves the panel generating ───────────────────────────────────
def test_cancel_starts_hidden():
    i = PANEL.index('id="ampCancel"')
    tag = PANEL[PANEL.rindex("<button", 0, i):i + 200]
    assert "display:none" in tag, "Cancel is visible before anything is running"


def test_every_failure_path_ends_the_run():
    """Each early return in the submit handler must go through ampEndedWith, and
    none may re-enable Generate by hand — that is how one path gets forgotten."""
    i = PANEL.index("$('ampGenerate').addEventListener('click'")
    handler = PANEL[i:PANEL.index("$('ampCancel').addEventListener", i)]
    assert "$('ampGenerate').disabled=false" not in handler, \
        "a hand-rolled re-enable bypasses the single exit"
    assert handler.count("ampEndedWith") >= 4, \
        "not every failure path ends the running state"


def test_the_terminal_states_all_end_it():
    i = PANEL.index("async function poll()")
    poll = PANEL[i:i + 1400]
    for state in ("done", "error", "cancelled"):
        assert state in poll
    assert "ampEndedWith" in poll, "the poll does not end the running state"


def test_ending_the_run_hides_cancel_and_frees_generate():
    i = PANEL.index("function ampSetRunning")
    fn = PANEL[i:i + 400]
    assert "ampCancel" in fn and "display" in fn
    assert "ampGenerate" in fn and "disabled" in fn
