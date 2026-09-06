"""
Orpheus — karaoke: stems, word-timed lyrics, the stage.

Run:  .venv/bin/python -m pytest tests/test_orpheus.py

No GPU, no Demucs, no Whisper. Separation and transcription are injected, so
this suite runs on a machine with neither and still checks the things that
actually break: what may reach audio, what happens when the GPU is taken, and
whether a lyric word can ever be handed a time earlier than the word before it.

WHAT IS BEING GUARDED, hardest first:

  * THE IMPORT POLICY. Orpheus reaches audio through an Amphion job id and
    nothing else. No path, no url, no upload, on any route. That single property
    is what makes Astro's stream strike-proof, and it is one careless convenience
    parameter away from being gone. test_no_route_accepts_a_path enumerates the
    live routes and fails on any that would take one.
  * NO FLOOR ON THIS SURFACE. Playback is not generation. The floor is not
    imported here, and the test asserts the module object has no handle on it.
  * GPU ETIQUETTE. A separation that queues silently behind a ten-minute video
    render is indistinguishable from one that hung.
  * MONOTONIC TIMING. A karaoke highlight survives bad timing. It does not
    survive timing that goes backwards.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import server                                  # noqa: E402
from fastapi.testclient import TestClient      # noqa: E402

morpheus = server.morpheus
amphion = server.amphion
orpheus = server.orpheus

import base64                                  # noqa: E402
client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}

LYRICS = "[Verse]\nEvery town out here wears the same face\nfour roads, one steeple, same rain"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Songs, cache and setlist all under tmp. Orpheus writes instrumentals BESIDE
    the master, so a test that used the real directory would drop files into
    Astro's library — and the batch test would try to separate forty of them."""
    songs = tmp_path / "songs"
    monkeypatch.setattr(amphion, "SONGS_DIR", songs)
    monkeypatch.setattr(orpheus, "SONGS_DIR", songs)
    monkeypatch.setattr(orpheus, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(orpheus, "SETLIST_FILE", tmp_path / "setlist.json")
    amphion._reserved_slugs.clear()
    morpheus.jobs.clear()
    amphion.jobs.clear()
    yield
    morpheus.jobs.clear()
    amphion.jobs.clear()


def _song(job_id="abc123", lyrics=LYRICS, title="A Light in Every Home", **extra):
    d = amphion._songs_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{job_id}.flac").write_bytes(b"\x00" * 64)
    side = {"job_id": job_id, "title": title, "slug": amphion.slugify(title),
            "lyrics": lyrics, "seed": 7, "seconds": 180.0,
            "created_at": "2026-08-01T10:00:00+00:00", **extra}
    (d / f"{job_id}.json").write_text(json.dumps(side))
    return job_id, side


def _fake_separated(job_id, side=None):
    """Pretend Demucs already ran: the two files it writes, and the sidecar block."""
    side = side or amphion._sidecar_for(job_id)
    orpheus.instrumental_path(job_id, side).write_bytes(b"\x00" * 32)
    orpheus._cache_dir()
    orpheus.vocal_stem_path(job_id).write_bytes(b"\x00" * 32)


# ══ 1. The import policy — the strike-proof property ═════════════════════════
def test_no_route_accepts_a_path():
    """Enumerated from the LIVE app, not from a list someone remembers to update.
    A future route that takes a filename fails here the day it is added."""
    banned = {"path", "file", "filepath", "url", "src", "source", "audio", "upload"}
    for r in server.app.routes:
        p = getattr(r, "path", "")
        if not p.startswith("/orpheus"):
            continue
        params = set(getattr(r, "param_convertors", {}) or {})
        assert not (params & banned), f"{p} takes {params & banned}"
        fn = getattr(r, "endpoint", None)
        names = set(getattr(fn, "__code__", None).co_varnames[:fn.__code__.co_argcount]) if fn else set()
        assert not (names & banned), f"{p} takes {names & banned}"


@pytest.mark.parametrize("bad", ["../../etc/passwd", "not-hex", "abc123/../x", ""])
def test_audio_route_refuses_anything_that_is_not_a_job_id(bad):
    r = client.get(f"/orpheus/audio/{bad}", headers=HEADERS)
    assert r.status_code in (400, 404, 405)


def test_library_only_lists_amphion_renders():
    """A stray audio file in the songs directory has no sidecar, so it is not a
    song Orpheus will play. This is the whole 'no arbitrary audio' rule, tested
    from the outside."""
    _song("abc123")
    (amphion._songs_dir() / "somebody-elses-hit.flac").write_bytes(b"\x00")
    got = {s["job_id"] for s in orpheus.library()}
    assert got == {"abc123"}


def test_orpheus_does_not_import_the_floor():
    """Playback is not generation. If a floor call ever appears on this surface it
    will be because someone added the import — so the import is what is asserted."""
    assert not hasattr(orpheus, "floor_check")
    assert not hasattr(orpheus, "morpheus")          # not imported at module level
    src = (REPO / "modules" / "orpheus.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "floor_check" not in code


# ══ 2. GPU etiquette ═════════════════════════════════════════════════════════
def test_gpu_free_reads_none():
    assert orpheus.gpu_busy_with() is None


@pytest.mark.parametrize("state", ["queued", "loading", "generating", "generating 2/4", "stitching"])
def test_an_amphion_render_in_flight_is_named(state):
    amphion.jobs["deadbeef"] = {"state": state}
    who = orpheus.gpu_busy_with()
    assert who and "deadbeef" in who and state in who


def test_a_morpheus_render_in_flight_is_named():
    morpheus.jobs["cafe01"] = {"state": "generating"}
    assert "cafe01" in (orpheus.gpu_busy_with() or "")


@pytest.mark.parametrize("state", ["done", "error", "cancelled"])
def test_a_finished_job_does_not_hold_the_gpu(state):
    amphion.jobs["deadbeef"] = {"state": state}
    assert orpheus.gpu_busy_with() is None


def test_separate_refuses_loudly_while_a_render_runs():
    _song("abc123")
    amphion.jobs["deadbeef"] = {"state": "generating"}
    with pytest.raises(orpheus.Busy) as e:
        orpheus.separate("abc123")
    assert "GPU busy" in str(e.value) and "deadbeef" in str(e.value)


def test_the_prepare_route_returns_409_naming_the_job():
    """Acceptance 5. 409 not 500: it is a conflict, and the message must carry the
    name of the job so he knows what he is waiting for."""
    _song("abc123")
    morpheus.jobs["cafe01"] = {"state": "generating"}
    r = client.post("/orpheus/prepare/abc123", headers=HEADERS)
    assert r.status_code == 409
    assert "cafe01" in r.json()["detail"]


def test_a_busy_gpu_stops_the_batch_rather_than_fighting_it(monkeypatch):
    """The batch re-checks between songs. A render that starts halfway through
    stops it at the next boundary — it does not queue forty jobs behind a video."""
    _song("aaa111", title="One")
    _song("bbb222", title="Two")
    calls = []

    def _prep(job_id, force=False):
        calls.append(job_id)
        amphion.jobs["deadbeef"] = {"state": "generating"}   # a render starts now
        return {}

    monkeypatch.setattr(orpheus, "prepare", _prep)
    r = client.post("/orpheus/batch", json={}, headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert len(calls) == 1                       # stopped after the first
    assert d["failed"] and "GPU busy" in d["failed"][0]["why"]


# ══ 3. Lyrics, alignment, timing ═════════════════════════════════════════════
def test_section_markers_are_lines_but_never_take_a_word():
    lines = orpheus.lyric_lines("[Verse]\nEvery town out here\n\n[Chorus]\nSo I left a light")
    assert [l["section"] for l in lines] == [True, False, True, False]
    assert lines[0]["words"] == [] and lines[1]["words"][0] == "Every"


def test_alignment_is_monotonic_even_when_whisper_is_a_mess():
    """The one property a sweep cannot survive losing. Whisper here mishears half
    the words, which is the normal case on singing."""
    lines = orpheus.lyric_lines("Every town out here wears the same face")
    heard = [{"word": "every", "start": 1.0, "end": 1.4},
             {"word": "clown", "start": 1.4, "end": 1.8},     # misheard
             {"word": "out",   "start": 1.8, "end": 2.0},
             {"word": "hair",  "start": 2.0, "end": 2.3},     # misheard
             {"word": "wears", "start": 2.3, "end": 2.7},
             {"word": "the",   "start": 2.7, "end": 2.8},
             {"word": "same",  "start": 2.8, "end": 3.1},
             {"word": "face",  "start": 3.1, "end": 3.6}]
    out = orpheus.align(lines, heard)
    ts = [w["start"] for l in out for w in l["words"] if w["start"] is not None]
    assert len(ts) == 8
    assert ts == sorted(ts), "timing went backwards"


def test_unmatched_words_are_spread_across_the_gap_not_dropped():
    """'Interpolate rather than trust garbage'. A line that matches on two words
    out of five still sweeps across all five."""
    lines = orpheus.lyric_lines("alpha bravo charlie delta echo")
    heard = [{"word": "alpha", "start": 0.0, "end": 1.0},
             {"word": "echo",  "start": 5.0, "end": 6.0}]
    out = orpheus.align(lines, heard)
    words = out[0]["words"]
    assert all(w["start"] is not None for w in words)
    mid = [w["start"] for w in words[1:4]]
    assert mid == sorted(mid)
    assert 1.0 <= mid[0] < mid[-1] <= 5.0


def test_words_whisper_never_reached_still_get_no_time_rather_than_a_wrong_one():
    out = orpheus.align(orpheus.lyric_lines("alpha bravo"), [])
    assert all(w["start"] is None for w in out[0]["words"])


def test_a_line_snaps_onto_a_real_vocal_onset():
    """Whisper put the first word 0.5s early; the stem says singing starts at
    23.45s. The stem wins — it does not have opinions."""
    lines = [{"text": "a b", "section": False,
              "words": [{"word": "a", "start": 22.95, "end": 23.4},
                        {"word": "b", "start": 23.4, "end": 23.9}],
              "start": 22.95, "end": 23.9}]
    assert orpheus.snap_to_onsets(lines, [18.3, 23.45, 31.5]) == 1
    assert abs(lines[0]["start"] - 23.45) < 0.01
    assert abs(lines[0]["words"][0]["start"] - 23.45) < 0.01   # the line moved as one


def test_a_snap_that_would_cross_a_neighbour_is_dropped():
    """Clamping would produce a line starting exactly when the last one ended,
    which looks deliberate and is not."""
    lines = [{"text": "one", "section": False, "start": 10.0, "end": 12.0,
              "words": [{"word": "one", "start": 10.0, "end": 12.0}]},
             {"text": "two", "section": False, "start": 12.2, "end": 14.0,
              "words": [{"word": "two", "start": 12.2, "end": 14.0}]}]
    assert orpheus.snap_to_onsets(lines, [11.9]) == 0
    assert lines[1]["start"] == 12.2


def test_onset_detection_ignores_separation_bleed(tmp_path):
    """The real trap: this track has a burst of bleed at 18s, five seconds before
    the first word. An absolute threshold calls that singing and every line lands
    five seconds early."""
    import numpy as np, soundfile as sf
    sr = 8000
    x = np.random.default_rng(0).normal(0, 0.001, sr * 30).astype("float32")   # floor
    x[int(sr * 18.0):int(sr * 19.0)] *= 12                                     # bleed
    x[int(sr * 23.0):int(sr * 27.0)] = np.random.default_rng(1).normal(0, 0.15, int(sr * 4))
    p = tmp_path / "voc.flac"
    sf.write(str(p), x, sr)
    onsets = orpheus.vocal_onsets(p)
    assert onsets, "no onset found at all"
    assert any(22.5 <= o <= 23.6 for o in onsets), onsets
    assert not any(17.5 <= o <= 19.5 for o in onsets), f"bleed read as singing: {onsets}"
