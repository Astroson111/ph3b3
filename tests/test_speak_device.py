"""speak never plays on Nyx for a turn that came from a device (ruling, 2026-10-07).

22:01 that day: "Phoebe, can you hear me?" to Dio. The model called speak, which
plays on NYX's speaker (the HDMI sink), and then the turn's reply played on Dio —
the same answer twice, once on the desktop. And only "Tool: speak" was logged, so
nobody could say what the desktop had said. Now: refused on device turns at the
call site (and on the leaked-text path), and every speak that plays logs its text.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_capture_opt_in import _fake_client          # noqa: E402

SPEAK = [{"message": {"role": "assistant", "content": "",
                      "tool_calls": [{"function": {"name": "speak",
                                                   "arguments": {"text": "Yes, I can hear you."}}}]}}]


@pytest.fixture
def rig(monkeypatch):
    from agent import server
    ran = []

    async def spy(name, args, device="nyx", session_id=""):
        ran.append((name, device))
        return "spoken"
    monkeypatch.setattr(server, "execute_tool", spy)
    return server, ran


def _turn(server, device, text="Phoebe, can you hear me?"):
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": text}]
    return asyncio.run(server.chat_with_tools(msgs, device=device, session_id="t"))


@pytest.mark.parametrize("device", ["stackchan", "dio", "iris", "pan"])
def test_speak_is_refused_on_a_device_turn(rig, monkeypatch, device, caplog):
    server, ran = rig
    monkeypatch.setattr(server.httpx, "AsyncClient", _fake_client([dict(SPEAK[0])]))
    with caplog.at_level(logging.WARNING):
        reply, _ = _turn(server, device)
    assert not [r for r in ran if r[0] == "speak"], f"speak played on Nyx for a {device} turn"
    assert reply, "she went silent instead of answering on the device"
    assert "Yes, I can hear you." in caplog.text, "the refused text was not logged"


def test_speak_still_works_at_the_desk(rig, monkeypatch):
    server, ran = rig
    monkeypatch.setattr(server.httpx, "AsyncClient", _fake_client([dict(SPEAK[0])]))
    _turn(server, "nyx", "say good morning out loud")
    assert ("speak", "nyx") in ran


def test_a_leaked_speak_on_a_device_turn_is_refused(rig, monkeypatch):
    server, ran = rig
    leak = json.dumps({"name": "speak", "arguments": {"text": "Yes, I can hear you."}})
    monkeypatch.setattr(server.httpx, "AsyncClient",
                        _fake_client([{"message": {"role": "assistant", "content": leak}}]))
    _turn(server, "stackchan")
    assert not [r for r in ran if r[0] == "speak"]


def test_speak_logs_what_it_says(monkeypatch, caplog):
    from agent import server
    monkeypatch.setattr(server.tts, "speak", lambda text, blocking=True, voice=None: "ok")
    with caplog.at_level(logging.INFO):
        asyncio.run(server.execute_tool("speak", {"text": "Good morning, Captain."}, "nyx", "t"))
    assert "Good morning, Captain." in caplog.text, "speak played without logging its text"


# ── the sweep: every tool that plays on Nyx follows the same rule ────────────
@pytest.fixture
def spoken(monkeypatch):
    from agent import server
    said = []
    monkeypatch.setattr(server.tts, "speak",
                        lambda text, blocking=True, voice=None: said.append(text) or "ok")
    return server, said


@pytest.mark.parametrize("name,args", [("tell_joke", {"category": "any"}),
                                       ("roast", {"topic": "security"})])
def test_jokes_and_roasts_stay_off_the_desktop_on_a_device_turn(spoken, name, args):
    server, said = spoken
    result = asyncio.run(server.execute_tool(name, args, "stackchan", "t"))
    assert not said, f"{name} played on Nyx for a Dio turn"
    assert result, f"{name} lost its text — the device has nothing to say"


def test_jokes_still_play_at_the_desk(spoken):
    server, said = spoken
    asyncio.run(server.execute_tool("tell_joke", {"category": "any"}, "nyx", "t"))
    assert said, "a desk turn lost its spoken joke"


@pytest.mark.parametrize("device,plays", [("stackchan", False), ("iris", False),
                                          ("nyx", True), ("", True)])
def test_the_joke_lane_follows_the_rule(spoken, device, plays):
    server, said = spoken
    joke = server._answer_joke("tell me a joke", device)
    assert joke
    assert bool(said) is plays, f"joke lane on a {device or 'panel'} turn"


def test_every_local_speech_in_execute_tool_is_guarded():
    """A new tool that calls tts.speak without the rule fails here, by name."""
    src = (ROOT / "agent" / "server.py").read_text()
    start = src.index("async def execute_tool(")
    body = src[start:src.index("\nasync def ", start + 10)]
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if "tts.speak(" in line and not line.lstrip().startswith("#"):
            ctx = "\n".join(lines[max(0, i - 3):i + 1])
            exempt = "hearing stalled" in line or "voice recognition failed" in ctx \
                or 'name == "speak"' in "\n".join(lines[max(0, i - 6):i])
            assert exempt or "_plays_locally(" in ctx, \
                f"unguarded local speech in execute_tool: {line.strip()[:80]}"


# ── motion: the camera moves only when asked ─────────────────────────────────
def _motion_script():
    return [{"message": {"role": "assistant", "content": "",
                         "tool_calls": [{"function": {"name": "camera_move",
                                                      "arguments": {"pan": 30}}}]}}]


@pytest.mark.parametrize("text", ["how was your morning", "can you see the door?",
                                  "I moved the camera yesterday"])
def test_the_camera_never_moves_on_her_own_initiative(rig, monkeypatch, text):
    server, ran = rig
    monkeypatch.setattr(server.httpx, "AsyncClient", _fake_client(_motion_script()))
    _turn(server, "nyx", text)
    assert not [r for r in ran if r[0] == "camera_move"], f"camera moved on {text!r}"


def test_an_explicit_ask_still_moves_it(rig, monkeypatch):
    server, ran = rig
    monkeypatch.setattr(server.httpx, "AsyncClient", _fake_client(_motion_script()))
    _turn(server, "nyx", "pan the camera to the left")
    assert ("camera_move", "nyx") in ran
