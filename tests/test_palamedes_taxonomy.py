"""Mode and Engine each answer ONE question.

Mode = what comes out (Image / Clip). Engine = what makes it (SDXL / Qwen).

They used to both claim the model name — "Image — SDXL" sitting beside
"SDXL — sd_xl_base_1.0" — which is how the engine dropdown ended up decorative:
two controls apparently setting the same thing, and no obvious place for a
second image engine to go. Retrofitting taxonomy onto live wiring is what
produces that, so the naming lands before the wiring does.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HTML = (REPO / "static" / "panel.html").read_text(encoding="utf-8")


def _options(select_id):
    m = re.search(rf'<select id="{select_id}".*?>(.*?)</select>', HTML, re.S)
    assert m, f"#{select_id} not found in panel.html"
    return re.findall(r'<option value="([^"]+)"([^>]*)>(.*?)</option>', m.group(1), re.S)


# ---------- Mode answers "what comes out" --------------------------------
def test_image_mode_does_not_claim_an_engine():
    """The duplication that started this. Engine names the maker, not Mode."""
    opts = {v: label.strip() for v, _attrs, label in _options("morphModeSel")}
    assert "image" in opts, "the image mode disappeared"
    for engine in ("SDXL", "Qwen", "FLUX", "sd_xl"):
        assert engine.lower() not in opts["image"].lower(), (
            f"Mode's image option still claims the engine {engine!r}: "
            f"{opts['image']!r}")


def test_mode_values_did_not_move():
    """Relabelling must not re-route. isClip() keys on these values, and the
    Edit tab mirrors this list by cloning it."""
    assert [v for v, _a, _l in _options("morphModeSel")] == \
        ["image", "ltx-fast", "wan-fast"]


def test_clip_rows_still_name_their_maker():
    """Not an oversight. For clips the engine row is HIDDEN (setMode), so the
    mode label is the only place LTX and Wan appear. Giving clips a real engine
    selector is a video-lane change, not a relabelling."""
    opts = {v: label for v, _a, label in _options("morphModeSel")}
    assert "LTX" in opts["ltx-fast"] and "Wan" in opts["wan-fast"]


# ---------- Engine answers "what makes it" -------------------------------
def test_engine_offers_a_maker_per_option():
    opts = {v: (attrs, label.strip()) for v, attrs, label in _options("morphEngSel")}
    assert set(opts) >= {"sdxl", "qwen"}, f"engine options are {set(opts)}"
    assert "sd_xl_base_1.0" in opts["sdxl"][1], \
        "the SDXL option stopped naming the actual checkpoint"


def test_qwen_ships_disabled():
    """qwen_enabled=false is the default (house pattern). The disabled
    attribute is a courtesy; the endpoint refusal is the guard."""
    opts = {v: attrs for v, attrs, _l in _options("morphEngSel")}
    assert "disabled" in opts["qwen"], \
        "the Qwen option is enabled in the markup — the switch defaults OFF"


def test_engine_row_is_image_only():
    """An engine selector under a clip mode would be a lie: clips route by mode."""
    assert "engRow.style.display = clip ? 'none' : ''" in HTML
