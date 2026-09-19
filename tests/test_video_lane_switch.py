"""
Video lane kill-switch — verify suite.

Astro's ruling, 19 Sept: DEFAULT ON. The original brief said default-off, but
that predates the lane shipping and it is now in daily use — a flag that turns a
working feature off at next boot is a trap, not a safeguard. This is something to
reach for when the card is wanted elsewhere, not a speed bump on the normal path.

OFF semantics follow the standing pattern already used for Atalanta and the
camera: the tool is ABSENT from what Phoebe is offered, and the endpoint refuses
with a stated reason. Never a 404 — "it does not exist" is false and sends the
caller hunting a routing bug.

Run:  .venv/bin/python -m pytest tests/test_video_lane_switch.py -v
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

morpheus = server.morpheus
client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
H = {"Authorization": f"Basic {_auth}"}


@pytest.fixture
def lane_off(monkeypatch):
    monkeypatch.setattr(server, "VIDEO_LANE_ENABLED", False)
    monkeypatch.setattr(morpheus, "video_lane_open", lambda: False)


@pytest.fixture
def lane_on(monkeypatch):
    monkeypatch.setattr(server, "VIDEO_LANE_ENABLED", True)
    monkeypatch.setattr(morpheus, "video_lane_open", lambda: True)


# ── default ──────────────────────────────────────────────────────────────────

def test_the_lane_is_on_by_default():
    """Shipping reality wins. An unset flag must not disable a feature in use."""
    import os
    assert os.getenv("PH3B3_VIDEO_LANE") in (None, ""), \
        "this test asserts the DEFAULT; the env var is set, so it proves nothing"
    assert server.VIDEO_LANE_ENABLED is True


@pytest.mark.parametrize("val,expected", [
    ("0", False), ("false", False), ("no", False), ("off", False), ("OFF", False),
    ("1", True), ("true", True), ("on", True), ("", True), ("anything", True),
])
def test_the_flag_reads_the_documented_values(val, expected):
    got = val.strip().lower() not in ("0", "false", "no", "off")
    assert got is expected


# ── off: absent, then refused ────────────────────────────────────────────────

def test_off_removes_the_tool_from_what_she_is_offered(lane_off):
    """A tool she can see is a tool she will mention. 'I could make you a clip
    but it's switched off' is the answer the absence exists to prevent."""
    names = {t["function"]["name"] for t in server.tools_for_turn()}
    assert "generate_video" not in names


def test_on_leaves_the_tool_advertised(lane_on):
    names = {t["function"]["name"] for t in server.tools_for_turn()}
    assert "generate_video" in names


def test_off_refuses_with_a_stated_reason_not_a_404(lane_off):
    r = client.post("/morpheus/video",
                    json={"positive": "a slow push in", "preset": "ltx-fast"},
                    headers=H)
    assert r.status_code == 403, f"expected 403, got {r.status_code}"
    d = r.json()["detail"]
    assert "switched off" in d.lower()
    assert "PH3B3_VIDEO_LANE" in d, "the refusal should name the switch"
    assert "gpu was not touched" in d.lower() or "nothing was queued" in d.lower()


def test_the_refusal_is_never_a_404(lane_off):
    """404 says the capability does not exist. It exists and is off — different
    sentences, and the wrong one sends you hunting a routing bug."""
    r = client.post("/morpheus/video", json={"positive": "x"}, headers=H)
    assert r.status_code != 404


def test_off_refuses_before_reading_the_body(lane_off):
    """Nothing is validated, floored or queued when the lane is shut."""
    r = client.post("/morpheus/video", json={}, headers=H)   # no prompt at all
    assert r.status_code == 403, \
        "an empty body got past the lane gate to prompt validation"


# ── on: untouched ────────────────────────────────────────────────────────────

def test_on_behaves_exactly_as_before(lane_on, monkeypatch):
    queued = []
    monkeypatch.setattr(server, "_morpheus_floor_gate", lambda p, n, r: None)
    monkeypatch.setattr(morpheus, "prepare_video_source", lambda p, j: "prepared")

    async def _noop(job_id, params):
        queued.append(job_id)
    monkeypatch.setattr(morpheus, "run_video", _noop)
    r = client.post("/morpheus/video",
                    json={"positive": "a slow push in", "preset": "ltx-fast"},
                    headers=H)
    assert r.status_code == 200
    assert r.json()["mode"] == "t2v"


def test_a_bad_preset_still_fails_on_its_own_terms_when_on(lane_on, monkeypatch):
    monkeypatch.setattr(server, "_morpheus_floor_gate", lambda p, n, r: None)
    r = client.post("/morpheus/video",
                    json={"positive": "x", "preset": "nope"}, headers=H)
    assert r.status_code == 400 and "unknown preset" in r.json()["detail"]


# ── mid-render flip ──────────────────────────────────────────────────────────

def test_a_flip_is_seen_by_a_render_already_in_flight():
    """A kill-switch that only takes effect on the NEXT render is not a
    kill-switch. morpheus reads a callable, not a bool captured at import."""
    src = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    assert "video_lane_open = lambda: True" in src, "no injectable reader"
    body = src[src.index("async def run_video"):]
    body = body[:body.index("\n\nasync def ") if "\n\nasync def " in body else len(body)]
    assert body.count("if not video_lane_open():") == 2, \
        "the flip must be checked both on the lock and mid-render"


def test_the_flip_leaves_a_clean_state_and_frees_vram():
    """Same exit as a user cancel: state cancelled, reason stated, and the
    finally that frees VRAM still runs."""
    src = (REPO / "modules" / "morpheus.py").read_text(encoding="utf-8")
    body = src[src.index("async def run_video"):]
    seg = body[:body.index("finally:")]
    assert 'state="cancelled"' in seg
    assert "switched off" in seg
    # the finally is downstream of both checks, so comfy_free always runs
    assert body.index("finally:") > body.rindex("if not video_lane_open():")
    assert "comfy_free(http)" in body[body.index("finally:"):]


def test_the_server_injects_the_reader_into_morpheus():
    """morpheus cannot import server (server imports morpheus), so the flag
    reader is injected rather than looked up."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    assert "morpheus.video_lane_open = lambda: VIDEO_LANE_ENABLED" in src


def test_the_posture_is_stated_at_boot():
    """An audit should read the journal, not probe the endpoint."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    assert '"[video] clip lane %s%s"' in src


def test_the_status_card_toggle_was_not_smuggled_in():
    """Explicitly deferred — config only for now."""
    panel = (REPO / "static" / "panel.html").read_text(encoding="utf-8")
    assert "PH3B3_VIDEO_LANE" not in panel
    assert "videoLaneSel" not in panel
