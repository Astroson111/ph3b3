"""The incident repro, inverted: seat the judge, ask something social, get an answer.

This is the regression test for the whole 2026-09-25 outage. With the model
seated the gate runs, and before Fix 2 it held "what did you have for
breakfast?" with missing=['your breakfast'] — which meant the brain was never
invoked, and the verdict refreshed the model's keep_alive lease, so the trap
re-armed on every clarification the user offered.

Skips cleanly when the service or ollama is down.
"""
import os
import sys
import uuid

import pytest
import requests
import urllib3

urllib3.disable_warnings()
pytestmark = pytest.mark.smoke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "modules"))

OLLAMA = "http://127.0.0.1:11434"


def _env(name, default=""):
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8"):
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv(name, default)


BASE = f"https://127.0.0.1:{_env('PH3B3_PORT', '7331')}"
AUTH = (_env("PH3B3_USER", "admin"), _env("PH3B3_PASSWORD"))
JUDGE = _env("PH3B3_HEAVY_MODEL", "ph3b3-chat:latest")


def _up(fn):
    try:
        return fn()
    except Exception:
        return False


needs_service = pytest.mark.skipif(
    not _up(lambda: requests.get(f"{BASE}/ready", verify=False, auth=AUTH,
                                 timeout=5).status_code == 200),
    reason="ph3b3 service not reachable")
needs_ollama = pytest.mark.skipif(
    not _up(lambda: requests.get(f"{OLLAMA}/api/tags", timeout=5).status_code == 200),
    reason="ollama not reachable")


def _seat_the_judge():
    """Arm the trap deliberately — this is the condition the outage needed."""
    requests.post(f"{OLLAMA}/api/chat", timeout=300, json={
        "model": JUDGE, "messages": [{"role": "user", "content": "potato"}],
        "stream": False, "options": {"num_predict": 1}})


def _resident():
    try:
        return [m["name"] for m in
                requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", [])]
    except Exception:
        return []


def _ask(q):
    r = requests.post(f"{BASE}/chat", verify=False, auth=AUTH, timeout=240,
                      json={"message": q, "session_id": "fx2-" + uuid.uuid4().hex[:8],
                            "text_only": True})
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


def _is_clarifier(a):
    return a.rstrip().endswith("?") and len(a) < 260


@needs_service
@needs_ollama
@pytest.mark.parametrize("question", [
    "what did you have for breakfast",
    "how was your morning",
    "what do you think about social media",
])
def test_a_social_turn_flows_with_the_judge_seated(question):
    _seat_the_judge()
    assert any(JUDGE.split(":")[0] in m for m in _resident()), \
        "could not seat the judge — the trap condition is not set up"
    a = _ask(question)
    assert a, "empty response"
    assert not _is_clarifier(a), (
        "the gate held a social turn with the judge seated — this is the outage:\n"
        f"  asked: {question!r}\n  got:   {a}")


@needs_service
@needs_ollama
def test_a_genuinely_fetchable_hold_still_holds_and_names_it():
    """The other direction. Overruling everything would be the same bug
    inverted — a guard that never guards."""
    _seat_the_judge()
    a = _ask("summarize the document")
    assert a, "empty response"
    assert not any(w in a.lower() for w in ("in summary", "the document states",
                                            "this document covers")), \
        f"she summarised a document that does not exist:\n{a}"
