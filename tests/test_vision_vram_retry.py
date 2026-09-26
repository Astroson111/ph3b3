"""The vision retry has to change something, and only when it should.

LIVE FAILURE, 2026-09-26 15:04:16. "Can you take a picture with your camera and
see what you see?" came back:

    [I took a frame but couldn't describe it — the vision model failed
     (HTTP 500). I'm not guessing at what's in it.]

That answer is correct behaviour — a frame was taken, no scene was invented, the
audit logged ok=False. What failed was the model LOAD, and ollama said why:

    gpu memory: available="5.0 GiB" free="5.4 GiB"
    load request: GPULayers:29 ... ProjectorPath:...      <- accepted the fit
    allocating 966.92 MiB on device 0: cudaMalloc failed: out of memory
    llama runner terminated, error="exit status 2"
    [GIN] 500 | POST "/api/generate"

The chat brain was resident at 7.6 GB on top of the server's own ~4.5 GB of
Whisper and embeddings. The same signature appeared at 09:02:12 that morning, so
it is not a one-off — it is whatever the card holds at the moment someone asks.

TWO THINGS WERE WRONG, and this file pins both fixes:

  1. The camera lane made no VRAM headroom, while the UPLOAD lane already did
     (server.py: "GPU-swap: evict Hermes so LLaVA fits in VRAM"). One model, two
     lanes, one of which prepared the card.
  2. The retry re-ran the identical request under identical conditions. Its
     docstring claimed the crash itself frees the memory; measured, both attempts
     failed 3 seconds apart and a third after that. A retry that changes nothing
     is not a retry.

NO REAL VRAM IS MANUFACTURED HERE. Starving a real card inside a test suite would
be its own hazard — and the suite already has a history of card contention
producing false reds. The HTTP layer is stubbed instead, which is where the
evidence actually lives: what matters is that headroom is made BETWEEN the two
requests, and only for the failure shape that headroom can fix.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import vision_module  # noqa: E402


class _Resp:
    def __init__(self, code, text=""):
        self.status_code = code
        self._text = text

    def json(self):
        return {"response": self._text}


@pytest.fixture
def lane(monkeypatch):
    """A recorded timeline of what the vision lane did, in order.

    The ORDER is the whole assertion: a headroom call after both requests would
    be useless, and one before the first would be the eager behaviour this fix
    deliberately avoids.
    """
    timeline = []

    def _install(responses, headroom=True):
        seq = list(responses)

        def _post(url, **kw):
            timeline.append("request")
            r = seq.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(vision_module.requests, "post", _post)

        def _headroom():
            timeline.append("headroom")
            return True

        def _release():
            timeline.append("release")

        monkeypatch.setattr(vision_module, "make_headroom",
                            _headroom if headroom else vision_module._no_headroom)
        monkeypatch.setattr(vision_module, "release_headroom", _release)
        monkeypatch.setattr(vision_module.time, "sleep", lambda *_a: None)
        return timeline

    return _install


def _vision():
    """A VisionModule with nothing injected — only _analyze is under test."""
    return vision_module.VisionModule.__new__(vision_module.VisionModule)


# ── the incident, inverted ────────────────────────────────────────────────────
def test_a_500_frees_vram_and_the_second_attempt_succeeds(lane):
    t = lane([_Resp(500), _Resp(200, "A desk with a lamp on it.")])
    out = _vision()._analyze(b"jpegbytes", "describe this")
    assert out == "A desk with a lamp on it."
    assert t == ["request", "headroom", "request", "release"], \
        f"headroom was not made between the attempts and released after: {t}"


def test_the_first_attempt_is_never_preceded_by_an_eviction(lane):
    """Lazy, not eager. A quiet card must cost nothing — evicting the brain on
    every camera turn would make the common case expensive."""
    t = lane([_Resp(200, "A cat on a windowsill.")])
    assert _vision()._analyze(b"jpeg", "p") == "A cat on a windowsill."
    assert t == ["request"], f"something touched the card on a healthy turn: {t}"


def test_two_failures_still_raise_and_evict_only_once(lane):
    t = lane([_Resp(500), _Resp(500)])
    with pytest.raises(vision_module.VisionModelDown) as e:
        _vision()._analyze(b"jpeg", "p")
    assert "HTTP 500" in str(e.value)
    assert t.count("headroom") == 1, "the retry turned into an eviction loop"
    assert t == ["request", "headroom", "request", "release"], \
        "the brain was not put back after a failed call"


# ── the failure shapes headroom CANNOT fix ────────────────────────────────────
def test_an_empty_response_does_not_evict_anything(lane):
    """A model answering badly is not a full card. Evicting for it would be
    superstition — and would cost a brain reload for nothing."""
    t = lane([_Resp(200, ""), _Resp(200, "A desk.")])
    assert _vision()._analyze(b"jpeg", "p") == "A desk."
    assert "headroom" not in t, f"evicted the brain over an empty answer: {t}"


def test_an_unreachable_ollama_does_not_evict_anything(lane):
    import requests as _rq
    t = lane([_rq.exceptions.ConnectionError("refused"),
              _rq.exceptions.ConnectionError("refused")])
    with pytest.raises(vision_module.VisionModelDown) as e:
        _vision()._analyze(b"jpeg", "p")
    assert "unreachable" in str(e.value)
    assert "headroom" not in t, "tried to free VRAM for a dead server"


@pytest.mark.parametrize("code", [502, 503])
def test_other_5xx_codes_also_get_the_headroom_step(lane, code):
    t = lane([_Resp(code), _Resp(200, "A room.")])
    assert _vision()._analyze(b"jpeg", "p") == "A room."
    assert t == ["request", "headroom", "request", "release"]


def test_a_4xx_is_not_treated_as_a_full_card(lane):
    t = lane([_Resp(404), _Resp(404)])
    with pytest.raises(vision_module.VisionModelDown):
        _vision()._analyze(b"jpeg", "p")
    assert "headroom" not in t, "a 404 is a wrong model name, not a full card"


# ── the default keeps every uninjected caller identical ───────────────────────
def test_the_default_hook_frees_nothing_and_says_so():
    assert vision_module._no_headroom() is False


def test_with_no_injection_the_retry_still_happens(lane):
    t = lane([_Resp(500), _Resp(200, "A desk.")], headroom=False)
    assert _vision()._analyze(b"jpeg", "p") == "A desk."
    assert t == ["request", "request"], \
        "without an injected hook the lane must behave exactly as before"


# ── the invariant this must not break ─────────────────────────────────────────
def test_a_failed_description_is_still_a_refusal_not_prose(lane, monkeypatch, tmp_path):
    """The 2026-08-31 rule stands: no description without a capture, and an error
    string must never stand where an observation goes."""
    v = _vision()
    monkeypatch.setattr(v, "_local_capture", lambda: b"jpegbytes", raising=False)
    audits = []
    monkeypatch.setattr(vision_module, "_audit",
                        lambda ev, **kw: audits.append((ev, kw)))
    lane([_Resp(500), _Resp(500)])
    out = v.describe_view()
    assert "couldn't describe it" in out and "not guessing" in out
    assert "HTTP 500" in out
    ev, kw = audits[-1]
    assert ev == "describe_view" and kw["ok"] is False
    assert kw["nbytes"] == len(b"jpegbytes"), "the frame it did take went unlogged"


# ── structure: the asymmetry that caused this cannot come back quietly ────────
def test_both_vision_lanes_make_headroom():
    """The upload lane evicts before _analyze; the camera lane now does too. If
    either loses its step, this goes red — that difference is the whole bug."""
    server_src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    vision_src = (ROOT / "modules" / "vision_module.py").read_text(encoding="utf-8")

    i = server_src.index("async def _kadmos_vision")
    upload = server_src[i:i + 2500]
    assert "evict_hermes" in upload, "the upload lane lost its GPU swap"

    assert "make_headroom" in vision_src, "the camera lane lost its headroom step"
    assert "vision_module.make_headroom = _vision_headroom" in server_src, \
        "the camera lane's hook is no longer injected, so it frees nothing"


def test_the_camera_lane_never_evicts_whisper():
    """Hard constraint: VRAM headroom never comes from unloading STT. The vision
    module must not name it, and the injected hook goes through the chat-brain
    eviction path only."""
    # CODE only. The comments in that module quote the incident, which names
    # Whisper as one of the tenants holding the card — grepping raw source made
    # this test fail on its own explanation, which has now happened three times
    # in this suite.
    raw = (ROOT / "modules" / "vision_module.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in raw.splitlines()
                     if not ln.lstrip().startswith("#")).lower()
    for name in ("whisper", "faster_whisper", "unload_stt"):
        assert name not in code, \
            f"the vision lane references {name!r} — headroom must not come from STT"

    server_src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = server_src.index("def _vision_headroom")
    body_raw = server_src[i:server_src.index("\nvision_module.make_headroom", i)]
    body = "\n".join(ln for ln in body_raw.splitlines()
                     if not ln.lstrip().startswith("#")).lower()
    assert "evict_hermes" in body
    for name in ("whisper", "unload_stt", "free_stt"):
        assert name not in body, f"the hook touches {name!r}"


def test_the_hook_declines_on_the_event_loop():
    """It runs its own loop for the eviction, so being called FROM a loop would
    deadlock. It must return False instead — and the retry then reports honestly
    that nothing was freed."""
    import asyncio
    sys.path.insert(0, str(ROOT / "agent"))
    from agent import server

    async def _try():
        return server._vision_headroom()

    assert asyncio.run(_try()) is False


# ── THE RACE. This is what the first version of the fix got wrong ─────────────
# Measured live 2026-09-26 17:17: the hook warmed the brain back inside
# make_headroom(), so the card went to 9.9 GiB free and was refilled by the same
# call 0.5s before the retry needed the room. Attempt 2 OOMed in the identical
# band. Every test in this file passed while that happened, because none of them
# knew the restore existed. These do.
def test_the_brain_is_not_put_back_until_the_vision_call_is_done(lane):
    """Ordering is the whole fix: release must come AFTER the last request."""
    t = lane([_Resp(500), _Resp(200, "A lamp.")])
    _vision()._analyze(b"jpeg", "p")
    assert t.index("release") > t.index("request", t.index("headroom")), \
        f"the brain was reloaded while the vision model still needed the card: {t}"
    assert t[-1] == "release"


def test_nothing_is_released_when_nothing_was_borrowed(lane):
    """A healthy turn must not queue a pointless brain reload."""
    t = lane([_Resp(200, "A desk.")])
    _vision()._analyze(b"jpeg", "p")
    assert "release" not in t, f"released headroom it never took: {t}"


def test_nothing_is_released_after_a_non_vram_failure(lane):
    t = lane([_Resp(200, ""), _Resp(200, "A desk.")])
    _vision()._analyze(b"jpeg", "p")
    assert "release" not in t and "headroom" not in t


def test_the_eviction_hook_does_not_warm_the_brain_itself():
    """Structural guard on the race. The warm-up belongs in the RELEASE hook; in
    the eviction hook it refills the card it just cleared."""
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("def _vision_headroom")
    body = src[i:src.index("def _vision_release")]
    code = "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "warm_brain" not in code, \
        "the eviction hook warms the brain — that is the race, it refills the card"
    rel = src[src.index("def _vision_release"):]
    rel = rel[:rel.index("vision_module.make_headroom")]
    assert "warm_brain" in rel, "nothing puts the brain back at all"


def test_both_hooks_are_injected():
    src = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")
    assert "vision_module.make_headroom = _vision_headroom" in src
    assert "vision_module.release_headroom = _vision_release" in src, \
        "headroom is borrowed and never given back"
