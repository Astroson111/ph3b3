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
