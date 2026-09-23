"""
/chat smoke test — does the main conversational endpoint answer at all?

WHY THIS EXISTS. On 2026-08-31 a one-line change put `_vision_intercept(...,
device=device)` above the line that binds `device`, so `_run_chat_pipeline`
raised UnboundLocalError on EVERY request and /chat returned 500 to everything.
`pytest tests/` reported **1512 passed**. Not one test posts to the endpoint the
whole product is, so the suite was green while Phoebe could not answer a word.

That is the same shape as the floor probes that were green on nothing: a harness
that cannot see the thing it protects. The floor fix added a manifest test; this
is the equivalent for the chat path — cheap, deterministic, and it fails loudly
the moment the pipeline stops returning a reply.

Scope, deliberately: this asserts the pipeline RUNS and the frozen response shape
holds. It does not judge what she says — no model quality, no LLM call, no GPU.
Outbound inference and TTS are stubbed; the pipeline's own routing is real, which
is exactly the part that broke.

Run:  .venv/bin/python -m pytest tests/test_chat_smoke.py -v
"""
import base64
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))
sys.path.insert(0, str(REPO / "agent"))

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Stub everything that leaves the process, and redirect everything it writes.

    The camera stub matters for its own sake — a test suite must never be able to
    photograph the room it runs in.

    The STORE redirection matters just as much, and was missed on the first pass:
    /chat persists every turn to the real chat transcripts AND to Mnemosyne, the
    shared cross-device memory. Running this file wrote 51 junk transcripts and 54
    Mnemosyne rows into live data — where auto-recall would later feed test strings
    back as things the user had actually said. A test that pollutes the store it is
    testing is a test that lies to the next investigation.
    """
    import chats as _chats
    monkeypatch.setattr(server, "chat_log", _chats.ChatLog(tmp_path / "chats"))

    class _NullSpine:
        def remember(self, *a, **k): return None
        def recall(self, *a, **k):   return []
        def recent(self, *a, **k):   return []
    monkeypatch.setattr(server, "mem_spine", _NullSpine(), raising=False)
    async def _fake_chat_with_tools(messages, device="nyx", session_id="default"):
        return "stubbed reply", messages

    monkeypatch.setattr(server, "chat_with_tools", _fake_chat_with_tools)
    monkeypatch.setattr(server.tts, "synthesize_to_b64",
                        lambda *a, **k: "", raising=False)
    monkeypatch.setattr(server.vision, "describe_view",
                        lambda: "A stubbed description of the frame.", raising=False)
    monkeypatch.setattr(server.vision, "take_photo",
                        lambda: "Photo taken — saved to your captures.", raising=False)
    monkeypatch.setattr(server.vision, "look",
                        lambda prompt=None: "A stubbed Dio frame.", raising=False)

    # Triage must not reach a model. Fail OPEN, which is its own documented
    # behaviour on timeout — so a stubbed triage cannot mask a real hold.
    async def _fake_triage(user_text, context, manifest=None):
        return server._TriagePass()
    monkeypatch.setattr(server, "triage_gate", _fake_triage, raising=False)


def _post(msg, session="smoke"):
    return client.post("/chat", json={"message": msg, "session_id": session},
                       headers=HEADERS)


# ── the regression that started this ─────────────────────────────────────────
def test_chat_answers_at_all():
    """The exact failure a 1512-green suite missed: /chat 500s on every request."""
    r = _post("Hello")
    assert r.status_code == 200, f"/chat returned {r.status_code}: {r.text[:200]}"
    assert r.json().get("response"), "empty reply — the pipeline produced nothing"


def test_response_shape_is_frozen():
    """Iris and the web UI depend on {response, audio}. Named frozen in the code."""
    body = _post("Hello").json()
    assert "response" in body and "audio" in body
    assert isinstance(body["response"], str) and isinstance(body["audio"], str)


@pytest.mark.parametrize("msg", [
    "Hello",                       # ordinary turn
    "Can you see me now?",         # forced vision path (early, above triage)
    "what am I holding",           # forced vision path
    "Are you watching me?",        # no_watch: no capture, no completion
    "take a picture",              # forced photo path
    "what does Dio see",           # Dio-routed
])
def test_pipeline_survives_each_route(msg):
    """Every branch out of _run_chat_pipeline must return a reply, not a 500.

    Parametrised by ROUTE, not by phrasing quality: each of these enters the
    pipeline at a different place, and the UnboundLocalError sat upstream of all
    of them.
    """
    r = _post(msg, session=f"smoke-{abs(hash(msg))}")
    assert r.status_code == 200, f"{msg!r} -> {r.status_code}: {r.text[:200]}"
    assert r.json().get("response"), f"{msg!r} produced an empty reply"


# ── the honesty rule, at the HTTP layer ──────────────────────────────────────
def test_watching_question_takes_no_photo(monkeypatch):
    """"Are you watching me?" must not fire the camera, and must not claim sight."""
    fired = []
    monkeypatch.setattr(server.vision, "describe_view",
                        lambda: fired.append("describe_view") or "should not happen")
    monkeypatch.setattr(server.vision, "take_photo",
                        lambda: fired.append("take_photo") or "should not happen")

    body = _post("Are you watching me?", session="smoke-watch").json()
    assert not fired, f"a monitoring question fired {fired}"
    said = body["response"].lower()
    assert "watch" in said or "still" in said, f"unexpected reply: {body['response']!r}"


def test_sight_question_actually_captures(monkeypatch):
    """A sight question must reach the capture tool — not a chat completion.

    The inverse of the bug: the transcript that started this had her describing a
    book, a cup and a notebook with zero captures behind them.
    """
    fired = []
    monkeypatch.setattr(server.vision, "describe_view",
                        lambda: fired.append("describe_view") or "A stubbed description.")

    body = _post("Can you see me now?", session="smoke-see").json()
    assert fired == ["describe_view"], "sight question did not reach the camera tool"
    assert "stubbed description" in body["response"].lower()


def test_figure_of_speech_does_not_fire_the_camera(monkeypatch):
    """A camera firing on an idiom is a privacy bug, not a near-miss."""
    fired = []
    for name in ("describe_view", "take_photo", "look"):
        monkeypatch.setattr(server.vision, name,
                            (lambda n: (lambda *a, **k: fired.append(n) or "x"))(name))

    for phrase in ("do you see what I mean",
                   "look at this from my point of view",
                   "can you see why that's a problem"):
        _post(phrase, session=f"smoke-idiom-{abs(hash(phrase))}")
    assert not fired, f"an idiom fired the camera: {fired}"
