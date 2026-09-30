"""No suite run may open the camera unless it was asked to.

2026-09-26, 09:02:06. A full-suite run I launched unattended sent "what do you
see right now?" to the live service. She did exactly what that question means:
Dio was offline, so she fell back to /dev/video0 and wrote a real frame of the
Captain's room to ~/ph3b3_data/captures. He asked where the photo came from and
whether she had taken it on her own. She had not — the trigger was a genuine user
turn whose "user" was my test harness.

Fixing that one test is not enough. The next live probe with a sight phrasing in
it would do the same thing, and the symptom is a photograph rather than a red
test. So this file is the standing guard: it reads every test that talks to the
LIVE service, finds every message those tests actually SEND, and asks the real
_vision_intercept whether it would open the camera.

A message that would is allowed only inside a test that takes the `vision_live`
fixture — the opt-in gate from conftest. Anything else fails here, at import
speed, without any hardware being touched.
"""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT))

TESTS = ROOT / "tests"

# The helpers a live test uses to speak to her. A new one must be added here, and
# the last test in this file is what makes sure it is.
_SENDERS = {"ask", "_live", "_ask_live", "post", "_post"}


def _live_test_files():
    """Files that talk to the RUNNING service over HTTP.

    In-process TestClient files are excluded: test_chat_smoke.py monkeypatches
    server.vision before posting, so its sight probes cannot reach hardware —
    that is the right pattern and it stays.
    """
    out = []
    for f in sorted(TESTS.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        if "/chat" in src and "requests" in src and "TestClient" not in src:
            out.append(f)
    return out


def _sent_messages(path: Path):
    """(message, enclosing function name, gated?) for every literal a test sends."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        gated = any(a.arg == "vision_live" for a in fn.args.args)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = (node.func.attr if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", ""))
            if name not in _SENDERS:
                continue
            lits = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            for kw in node.keywords:
                if kw.arg in ("json", "message") and isinstance(kw.value, ast.Constant):
                    lits.append(kw.value.value)
                if kw.arg == "json" and isinstance(kw.value, ast.Dict):
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if (isinstance(k, ast.Constant) and k.value == "message"
                                and isinstance(v, ast.Constant)):
                            lits.append(v.value)
            for lit in lits:
                found.append((lit, fn.name, gated))
    return found


def test_there_are_live_test_files_to_check():
    """Green-on-nothing guard: if the discovery breaks, this file would pass by
    checking zero messages."""
    files = _live_test_files()
    assert files, "no live-service test files found — the sweep is inspecting nothing"
    assert any(f.name == "test_persona_smoke.py" for f in files), \
        "the file that caused the incident is not being inspected"


def test_the_sweep_finds_messages_to_inspect():
    total = sum(len(_sent_messages(f)) for f in _live_test_files())
    assert total >= 10, f"only {total} sent messages found — the AST walk is missing them"


def test_no_ungated_live_test_sends_a_message_that_opens_the_camera():
    from agent import server
    offenders = []
    for f in _live_test_files():
        for msg, fn_name, gated in _sent_messages(f):
            if gated:
                continue
            if server._vision_intercept(msg, device="nyx"):
                offenders.append(f"{f.name}::{fn_name} sends {msg!r}")
    assert not offenders, (
        "these live tests would open the camera in a default run:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither take the `vision_live` fixture and skip without it, or stub "
          "the capture. `pytest tests/` must not photograph anybody's room.")


def test_the_one_gated_probe_is_still_gated_and_still_live():
    """The opt-in probe must keep BOTH properties: it needs the fixture, and it
    genuinely still asks a question that captures. A gate on a probe that no
    longer opens the camera would be a test of nothing."""
    from agent import server
    msgs = _sent_messages(TESTS / "test_persona_smoke.py")
    gated_sight = [m for m, _fn, gated in msgs
                   if gated and server._vision_intercept(m, device="nyx")]
    assert gated_sight, \
        "the live sight probe no longer sends a capturing message — the hardware " \
        "coverage --vision-live exists for has quietly gone"


def test_the_sweep_would_catch_a_new_offender(tmp_path, monkeypatch):
    """Teeth. Plant a live test file that sends a sight question with no gate and
    confirm the sweep goes red — without this, the sweep proves only that today's
    files happen to be clean."""
    from agent import server
    planted = tmp_path / "test_planted_live.py"
    planted.write_text(
        "import requests\n"
        "def test_x():\n"
        "    requests.post('/chat', json={'message': 'what do you see right now?'})\n",
        encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "TESTS", tmp_path)
    files = _live_test_files()
    assert files, "the planted file was not discovered as a live test"
    hits = [m for f in files for m, _fn, g in _sent_messages(f)
            if not g and server._vision_intercept(m, device="nyx")]
    assert hits, "a planted ungated sight probe was NOT caught — the sweep is blind"


def test_the_sender_list_covers_what_the_live_files_actually_call():
    """A live file that speaks through a helper this file does not know about is
    invisible to the sweep. Names every function that posts to /chat and checks
    the list knows it."""
    for f in _live_test_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            src = ast.unparse(fn)
            if "/chat" in src and "post" in src:
                # the helper itself, or a test that posts inline — either way the
                # name must be one the sweep follows
                assert (fn.name in _SENDERS
                        or any(n in src for n in _SENDERS)), \
                    (f"{f.name}::{fn.name} posts to /chat through a helper the "
                     f"sweep does not follow — add it to _SENDERS")
