"""
Edit + Clip (i2v from a staged upload) — verify suite.

WHAT CHANGED AND WHY IT NEEDED A TEST. /morpheus/video used to accept exactly one
kind of source: a gallery render UUID. That was not an oversight — the comment
said so plainly, "the input-image floor gate for arbitrary uploads is Phase 4" —
because a gallery render was floor-passed when it was created, and an upload has
been through nothing. /image/edit/upload checks that a file decodes and is not
too big. It never looks at what is in it.

So adding source_upload_id IS a new branch, and what makes it safe is not that
the bytes arrived from the Edit tab — it is that the same describe-then-judge
pass /image/edit/run runs is attached to it, pre-lock, before anything queues.

These tests hold that seam:
  - an upload is checked, and the check is the same function
  - a refusal costs no GPU and no queue slot
  - "the check could not run" stays distinguishable from "refused"
  - the gallery path is untouched

Run:  .venv/bin/python -m pytest tests/test_clip_from_upload.py -v
"""
import base64
import sys
import uuid
from pathlib import Path

import pytest
from PIL import Image

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
def staged(tmp_path, monkeypatch):
    """A staged upload, as /image/edit/upload would leave one."""
    monkeypatch.setattr(server, "EDIT_SCRATCH", tmp_path)
    monkeypatch.setattr(server, "_edit_lane_gate", lambda: None)
    uid = uuid.uuid4().hex
    Image.new("RGB", (64, 64), (30, 40, 60)).save(tmp_path / f"{uid}.png")
    return uid


@pytest.fixture
def no_gpu(monkeypatch):
    """Nothing here may reach a card or queue real work."""
    queued = []
    monkeypatch.setattr(morpheus, "prepare_video_source",
                        lambda path, job_id: f"prepared:{Path(path).name}")

    async def _noop(job_id, params):
        queued.append((job_id, params))
    monkeypatch.setattr(morpheus, "run_video", _noop)
    monkeypatch.setattr(server, "_morpheus_floor_gate", lambda p, n, r: None)
    return queued


def _body(**kw):
    b = {"positive": "slow push in, water rippling", "preset": "ltx-fast"}
    b.update(kw)
    return b


# ── the upload is checked, by the same function ──────────────────────────────

def test_a_clean_upload_becomes_the_conditioning_frame(staged, no_gpu, monkeypatch):
    seen = []
    monkeypatch.setattr(morpheus, "source_minor_check",
                        lambda raw: seen.append(len(raw)) or False)
    r = client.post("/morpheus/video", json=_body(source_upload_id=staged), headers=H)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mode"] == "i2v" and j["source"] == "upload"
    assert seen, "the upload reached the GPU path without being looked at"
    assert no_gpu and "_comfy_image" in no_gpu[0][1]


def test_it_is_the_same_check_the_edit_lane_runs():
    """Not a parallel implementation that can drift. One function, two callers."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    assert src.count("morpheus.source_minor_check") == 2, (
        "the clip path should call the SAME check as /image/edit/run — "
        "no more, no fewer")


def test_a_blocked_upload_is_refused_and_queues_nothing(staged, no_gpu, monkeypatch):
    """A refusal must cost no GPU and no queue slot — the check runs pre-lock."""
    monkeypatch.setattr(morpheus, "source_minor_check", lambda raw: True)
    r = client.post("/morpheus/video", json=_body(source_upload_id=staged), headers=H)
    assert r.status_code == 403
    assert no_gpu == [], "a refused clip still queued a job"


def test_a_real_verdict_destroys_the_upload(staged, no_gpu, monkeypatch, tmp_path):
    monkeypatch.setattr(morpheus, "source_minor_check", lambda raw: True)
    client.post("/morpheus/video", json=_body(source_upload_id=staged), headers=H)
    assert not (server.EDIT_SCRATCH / f"{staged}.png").exists()


def test_a_check_that_could_not_run_is_not_a_refusal(staged, no_gpu, monkeypatch):
    """503 + Retry-After, the upload KEPT, and wording that does not send the
    operator hunting a safety bug when the real problem is VRAM."""
    def unavailable(raw):
        raise morpheus.SafetyCheckUnavailable("llava could not load")
    monkeypatch.setattr(morpheus, "source_minor_check", unavailable)
    r = client.post("/morpheus/video", json=_body(source_upload_id=staged), headers=H)
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "30"
    assert "not a refusal" in r.json()["detail"].lower()
    assert (server.EDIT_SCRATCH / f"{staged}.png").exists(), \
        "the upload was destroyed, so the retry it was told to make is impossible"
    assert no_gpu == []


# ── the id cannot be used to reach outside the scratch dir ───────────────────

@pytest.mark.parametrize("bad", [
    "../../etc/passwd", "not-hex-at-all", "abc", "a" * 31, "a" * 33,
    "../" + "a" * 29, "AAAA" + "a" * 28,
])
def test_a_malformed_upload_id_is_refused(bad, no_gpu, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "EDIT_SCRATCH", tmp_path)
    monkeypatch.setattr(server, "_edit_lane_gate", lambda: None)
    monkeypatch.setattr(morpheus, "source_minor_check", lambda raw: False)
    r = client.post("/morpheus/video", json=_body(source_upload_id=bad), headers=H)
    assert r.status_code in (400, 404), f"{bad!r} returned {r.status_code}"
    assert no_gpu == []


def test_a_missing_upload_says_re_upload(no_gpu, monkeypatch, tmp_path):
    monkeypatch.setattr(server, "EDIT_SCRATCH", tmp_path)
    monkeypatch.setattr(server, "_edit_lane_gate", lambda: None)
    r = client.post("/morpheus/video",
                    json=_body(source_upload_id=uuid.uuid4().hex), headers=H)
    assert r.status_code == 404 and "re-upload" in r.json()["detail"]


def test_two_sources_at_once_is_refused(staged, no_gpu, monkeypatch):
    monkeypatch.setattr(morpheus, "source_minor_check", lambda raw: False)
    r = client.post("/morpheus/video",
                    json=_body(source_upload_id=staged,
                               source_job_id=str(uuid.uuid4())), headers=H)
    assert r.status_code == 400 and "not both" in r.json()["detail"]


# ── the gallery path is untouched ────────────────────────────────────────────

def test_a_gallery_source_still_skips_the_upload_check(no_gpu, monkeypatch, tmp_path):
    """A render was floored at creation. Re-judging it would be a second VRAM
    cost for a verdict that already exists."""
    monkeypatch.setattr(morpheus, "IMAGE_DIR", tmp_path)
    job = str(uuid.uuid4())
    Image.new("RGB", (64, 64)).save(tmp_path / f"{job}.png")
    called = []
    monkeypatch.setattr(morpheus, "source_minor_check",
                        lambda raw: called.append(1) or False)
    r = client.post("/morpheus/video", json=_body(source_job_id=job), headers=H)
    assert r.status_code == 200 and r.json()["source"] == "render"
    assert called == [], "a gallery render was re-judged"


def test_text_only_is_still_t2v(no_gpu):
    r = client.post("/morpheus/video", json=_body(), headers=H)
    assert r.status_code == 200
    assert r.json()["mode"] == "t2v" and r.json()["source"] is None


# ── the panel actually shows and downloads what it made ──────────────────────
# The first version of this wiring reused the still-image poll and download, so
# a finished clip displayed nothing and downloaded nothing: /image/status has no
# video job, an <img> cannot render an mp4, and /image/file has no mp4 to serve.

PANEL = (REPO / "static" / "panel.html").read_text(encoding="utf-8")


def _fn(name, ends_at):
    """The source of one function, bounded at the next one.

    A fixed-size slice ran past pollClip into the still poll() that follows it,
    which legitimately uses /image/status — the test failed on correct code.
    """
    start = PANEL.index(name)
    return PANEL[start:PANEL.index(ends_at, start)]


def test_the_clip_result_polls_the_video_job_not_the_image_job():
    seg = _fn("async function pollClip", "async function poll(jobId)")
    assert "/morpheus/jobs/" in seg
    assert "/image/status/" not in seg, "the clip poll asks the image endpoint"


def test_the_clip_result_is_shown_in_a_video_element():
    assert 'id="editAfterVid"' in PANEL and "<video" in PANEL
    seg = _fn("async function pollClip", "async function poll(jobId)")
    assert "afterVid.src = '/morpheus/video/file/'" in seg


def test_the_clip_downloads_from_the_video_route():
    # There are two dlBtn handlers — Generate's and Edit's. The Edit one is the
    # last, and it is the one the clip branch shares.
    seg = PANEL[PANEL.rindex("dlBtn.addEventListener"):][:700]
    assert "/morpheus/video/file/" in seg and "download=1" in seg
    assert "clipMode" in seg, "the download button cannot tell the two apart"


def test_a_still_after_a_clip_does_not_leave_the_video_showing():
    """Switching back to an image edit must stop and hide the previous clip, or
    the After pane keeps playing the last video under a new result."""
    seg = _fn("async function poll(jobId)", "async function run()")
    assert "afterVid.style.display = 'none'" in seg
    assert "afterVid.removeAttribute('src')" in seg


def test_edit_mode_options_are_cloned_from_generate_not_duplicated():
    """One source of truth: a mode added to the Generate selector has to appear
    in Edit with no second edit. Two hard-coded lists would drift."""
    assert PANEL.count('<option value="ltx-fast"') == 1, \
        "the mode list exists in more than one place"
    assert "Array.from(gen.options)" in PANEL
