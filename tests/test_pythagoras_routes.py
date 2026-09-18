"""
Pythagoras HTTP surface — verify suite.

The routes are thin on purpose: build, export, return. What is worth testing at
this layer is that refusals survive the trip as refusals (a 400 with the reason,
not a 500 or an empty 200), and that the deferred figure refuses through the API
exactly as it does in the module.

Run:  .venv/bin/python -m pytest tests/test_pythagoras_routes.py -v
"""
import base64
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "modules"))

import server                                   # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402

pythagoras = server.pythagoras
client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}


def test_the_catalogue_lists_what_is_ready_and_what_is_not():
    r = client.get("/pythagoras/figures", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "metatrons_cube" in j["figures"]
    assert "sri_yantra" not in j["figures"]
    assert j["deferred"]["sri_yantra"] == "deferred-v1.1"
    assert j["size"] == {"min": 512, "max": 2048, "step": 64, "default": 1024}


def test_render_returns_svg_inline():
    r = client.post("/pythagoras/render",
                    json={"figure": "metatrons_cube", "width": 512, "height": 512},
                    headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j["mime"] == "image/svg+xml" and j["data"].startswith("<svg")
    assert j["shapes"] == 13 + 78
    assert j["params"]["vertices"] == 13


def test_render_png_comes_back_base64():
    r = client.post("/pythagoras/render",
                    json={"figure": "vesica", "width": 512, "height": 512,
                          "format": "png"}, headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j["encoding"] == "base64"
    assert base64.b64decode(j["data"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_deferred_figure_refuses_through_the_api_too():
    """A 400 that says why — not a 500, and not an empty success."""
    r = client.post("/pythagoras/render", json={"figure": "sri_yantra"},
                    headers=HEADERS)
    assert r.status_code == 400
    assert "yantra" in r.json()["error"].lower()


@pytest.mark.parametrize("body,needle", [
    ({"figure": "mandala"}, "mandala"),
    ({"figure": "vesica", "width": 500}, "width"),
    ({"figure": "vesica", "palette": "neon"}, "neon"),
    ({"figure": "vesica", "format": "gif"}, "gif"),
    ({"figure": "flower_of_life", "ring_count": 99}, "ring_count"),
])
def test_bad_input_is_a_400_naming_the_thing(body, needle):
    r = client.post("/pythagoras/render", json=body, headers=HEADERS)
    assert r.status_code == 400, f"{body} returned {r.status_code}"
    assert needle in r.json()["error"]


def test_compose_maps_or_asks_over_http():
    r = client.post("/pythagoras/compose",
                    json={"text": "flower of life with five rings"}, headers=HEADERS)
    assert r.json() == {"figure": "flower_of_life", "params": {"ring_count": 5}}
    r = client.post("/pythagoras/compose", json={"text": "something pretty"},
                    headers=HEADERS)
    j = r.json()
    assert j["figure"] is None and "which figure" in j["question"].lower()


def test_frames_returns_an_animated_svg_and_says_frames_are_unstamped():
    r = client.post("/pythagoras/frames",
                    json={"figure": "seed_of_life", "width": 512, "height": 512},
                    headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j["frames"] == 7
    assert j["animated_svg"].count("<animate") == 7
    assert "ffmpeg" in j["ffmpeg"]
    assert "not stamped" in j["watermark"]


def test_every_pythagoras_route_requires_a_human():
    assert client.get("/pythagoras/figures").status_code in (401, 403)
    for path in ("/pythagoras/render", "/pythagoras/frames", "/pythagoras/compose"):
        r = client.post(path, json={"figure": "vesica"})
        assert r.status_code in (401, 403), f"{path} answered {r.status_code}"


# ── the panel card is folded away by default ─────────────────────────────────
# It is an occasional tool in a pane that gets scrolled past constantly, so it
# earns its height only when opened.

PANEL = (REPO / "static" / "panel.html").read_text(encoding="utf-8")


def test_the_pythagoras_card_is_collapsed_by_default():
    seg = PANEL[PANEL.index('class="card pyth-card"'):]
    seg = seg[:seg.index("</details>")]
    assert '<details class="pyth-fold">' in seg
    assert "<summary" in seg
    # An `open` attribute would defeat the point.
    assert '<details class="pyth-fold" open' not in PANEL


def test_the_controls_and_preview_live_inside_the_fold():
    """Collapsing only the title would save no space at all."""
    start = PANEL.index('<details class="pyth-fold">')
    end = PANEL.index("</details>", start)
    inside = PANEL[start:end]
    for control in ('id="pythFigure"', 'id="pythPreview"', 'id="pythSvgBtn"',
                    'id="pythFramesBtn"', 'id="pythParams"'):
        assert control in inside, f"{control} is outside the fold"


def test_nothing_renders_until_the_card_is_opened():
    """A collapsed card that still POSTs a figure on every page load is not
    actually free — the comment claims it costs nothing while shut, so it has
    to be true."""
    assert "buildParams(); draw();" not in PANEL, \
        "the preview still renders on page load"
    assert 'fold.addEventListener("toggle"' in PANEL
