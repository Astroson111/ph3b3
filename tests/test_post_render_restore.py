"""A render evicts Ollama on the way in. Something has to put it back.

MEASURED 2026-09-25, single-model config, mixed traffic:

    render          2.0s   ps -> ph3b3-chat 5.2G
    next social     5.8s   ps -> NONE
                           "I can't reach my language model right now
                            (ph3b3-chat:latest). Is Ollama running?"
    recovery turn  26.5s   ps -> NONE   (cold reload)

release_card()'s docstring said "both directions" and honoured two: Whisper's
ears and ComfyUI's tail. There were three. This is the third, and it is the
same shape as the deafness incident that function already guards against, one
tenant over.

The old failure string broke the one-voice rule twice: it named the
implementation (ph3b3-chat:latest) and told the user to go check a service.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import morpheus as mx  # noqa: E402

SERVER_SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")

# Comments quote the retired string to explain WHY it is retired. An earlier
# version of this file grepped raw source and tripped over its own commentary —
# the same trap a memory-module test hit yesterday. Assert on CODE.
SERVER_CODE = "\n".join(l for l in SERVER_SRC.splitlines()
                        if not l.lstrip().startswith("#"))
MX_SRC = (ROOT / "modules" / "morpheus.py").read_text(encoding="utf-8")
HK_SRC = (ROOT / "modules" / "herakles.py").read_text(encoding="utf-8")


# ── the model is READ, never chosen ──────────────────────────────────────────
def test_the_brain_variable_is_read_not_hardcoded(monkeypatch):
    """A pending brain ruling must land on top of this with no rework."""
    monkeypatch.setenv("PH3B3_HEAVY_MODEL", "some-other-brain:latest")
    assert mx.brain_model() == "some-other-brain:latest"


# ── ordering: release, THEN restore ──────────────────────────────────────────
def test_the_restore_is_kicked_after_the_card_is_released():
    """Reloading weights while ComfyUI still holds ~11 GB is how she went deaf
    on 2026-09-22, so the order is the whole point: comfy_free, then
    release_card (which drops the tail and reloads her ears), and only then the
    brain."""
    i = MX_SRC.index("restore_brain_soon()", MX_SRC.index("could not release the card"))
    window = MX_SRC[:i]
    assert window.rindex("await herakles.release_card(") < i
    assert window.rindex("await comfy_free(http)") < i


def test_herakles_keeps_its_never_automatic_contract():
    """The restore lives in morpheus, NOT herakles. herakles is ruled "explicit
    ask only, never automatic" and tests/test_herakles.py enforces that by
    grepping for create_task. Putting a self-scheduling warm-up in there broke
    that ruling to fix a smaller thing; this test pins the decision."""
    assert "create_task" not in HK_SRC, "herakles can act without being asked again"
    assert "restore_brain_soon" not in HK_SRC


def test_the_restore_does_not_block_the_render_response():
    """Fire-and-forget: create_task, never awaited on the render path."""
    src = MX_SRC[MX_SRC.index("def restore_brain_soon("):]
    src = src[:src.index("async def await_brain")]
    assert "create_task" in src
    assert "await restore_brain_soon" not in MX_SRC
    i = MX_SRC.index("restore_brain_soon()", MX_SRC.index("could not release the card"))
    assert "await " not in MX_SRC[i - 30:i], "the render path waits on the warm-up"


# ── one lease, one restore ───────────────────────────────────────────────────
def test_a_second_kick_while_one_is_in_flight_is_a_no_op():
    """Batch case: many renders on one lease must not stack warm-ups."""
    async def _run():
        started = []

        async def _slow():
            started.append(1)
            await asyncio.sleep(0.2)
            return True

        mx._brain_task = None
        orig = mx.warm_brain
        mx.warm_brain = _slow
        try:
            assert mx.restore_brain_soon() is True
            assert mx.restore_brain_soon() is True     # still in flight
            assert mx.restore_brain_soon() is True
            await asyncio.sleep(0.4)
            assert len(started) == 1, f"{len(started)} warm-ups for one lease"
        finally:
            mx.warm_brain = orig
            mx._brain_task = None
    asyncio.run(_run())


def test_the_render_path_releases_once_per_lease():
    """The batch guarantee comes from morpheus calling release_card once, in a
    finally, guarded on the lease existing."""
    i = MX_SRC.index("await herakles.release_card(")
    window = MX_SRC[i - 700:i]
    assert "finally:" in window and "if lease is not None:" in window


# ── the failure path is honest and implementation-free ───────────────────────
def test_the_plumbing_string_is_retired():
    assert "Is Ollama running?" not in SERVER_CODE, "the plumbing string is back"
    assert "I can't reach my language model right now" not in SERVER_CODE


def test_no_cold_start_message_names_the_implementation():
    """One voice: behaviours, never model names or service names."""
    i = SERVER_SRC.index("[chat] brain unreachable")
    block = SERVER_SRC[i:i + 2200]
    spoken = [seg for seg in block.split('return (')[1:]]
    assert spoken, "no spoken returns found on the cold-start path"
    for seg in spoken:
        said = seg[:seg.index("), messages")].lower()
        for banned in ("ollama", "hermes", "ph3b3-chat", "heavy_model",
                       "model", ":latest", "gpu", "vram", "cuda"):
            assert banned not in said, f"the user is told about {banned!r}: {said[:90]}"


def test_the_waking_line_is_in_voice_and_invites_a_retry():
    i = SERVER_SRC.index("Give me a moment")
    line = SERVER_SRC[i:i + 200]
    assert "waking back up" in line
    assert "again" in line, "it does not tell them what to do next"


def test_the_turn_waits_for_the_warm_up_before_giving_up():
    i = SERVER_SRC.index("[chat] brain unreachable")
    block = SERVER_SRC[i:i + 1200]
    assert "await_brain" in block
    assert "timeout=" in block, "an unbounded wait would hang the turn"


# ── warm-up failure: loud, honest, no hang ───────────────────────────────────
def test_await_brain_returns_false_when_the_warm_up_fails_and_does_not_hang():
    async def _run():
        mx._brain_task = None
        orig = mx.warm_brain

        async def _fail():
            return False
        mx.warm_brain = _fail
        try:
            assert await asyncio.wait_for(mx.await_brain(timeout=5.0), timeout=8.0) is False
        finally:
            mx.warm_brain = orig
            mx._brain_task = None
    asyncio.run(_run())


def test_a_warm_up_that_raises_is_swallowed_into_false():
    async def _run():
        mx._brain_task = None
        orig = mx.warm_brain

        async def _boom():
            raise RuntimeError("card on fire")
        mx.warm_brain = _boom
        try:
            assert await asyncio.wait_for(mx.await_brain(timeout=5.0), timeout=8.0) is False
        finally:
            mx.warm_brain = orig
            mx._brain_task = None
    asyncio.run(_run())


def test_no_running_loop_is_reported_rather_than_crashing():
    mx._brain_task = None
    assert mx.restore_brain_soon() is False


# ── the live regression: today's repro, inverted ─────────────────────────────
# Marked smoke: it renders, which needs the real stack and the real card.
import os      # noqa: E402
import uuid    # noqa: E402

import requests  # noqa: E402
import urllib3   # noqa: E402

urllib3.disable_warnings()


def _env(name, default=""):
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(name, default)


_BASE = f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}"
_AUTH = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))


def _service_up():
    try:
        return requests.get(f"{_BASE}/ready", verify=False, auth=_AUTH,
                            timeout=5).status_code == 200
    except Exception:
        return False


@pytest.mark.smoke
@pytest.mark.skipif(not _service_up(), reason="ph3b3 service not reachable")
def test_a_social_turn_straight_after_a_render_never_shows_plumbing():
    """THE regression test for 2026-09-25. Render, then talk to her immediately.

    Before the fix this returned "I can't reach my language model right now
    (ph3b3-chat:latest). Is Ollama running?" — and the turn after it paid 26.5s.
    """
    r = requests.post(f"{_BASE}/image/generate", verify=False, auth=_AUTH, timeout=600,
                      json={"positive": "a small grey pebble on wet sand, overcast light"})
    assert r.status_code == 200, f"render failed ({r.status_code}) — cannot test the gap"

    # THE PRECONDITION. This test is worthless unless the render actually
    # evicted the brain — and it does not always. The first version of this
    # passed against a service that did NOT have the fix, because that run
    # happened not to evict. A regression test that can pass before the fix
    # exists is not a regression test.
    brain = _env("PH3B3_HEAVY_MODEL", "hermes3").split(":")[0]
    try:
        resident = [m["name"] for m in requests.get(
            "http://127.0.0.1:11434/api/ps", timeout=5).json().get("models", [])]
    except Exception:
        resident = []
    if any(brain in m for m in resident):
        pytest.skip(f"the render did not evict {brain} this time — the gap this "
                    "test covers was never opened, so passing would mean nothing")

    a = requests.post(f"{_BASE}/chat", verify=False, auth=_AUTH, timeout=300,
                      json={"message": "how was your morning",
                            "session_id": "pr-" + uuid.uuid4().hex[:8],
                            "text_only": True})
    a.raise_for_status()
    said = (a.json().get("response") or "").strip()
    assert said, "empty reply after a render"
    low = said.lower()
    for banned in ("ollama", "ph3b3-chat", "hermes3", ":latest",
                   "language model", "is ollama running"):
        assert banned not in low, (
            f"the user was shown plumbing after a render: {said[:160]}")
