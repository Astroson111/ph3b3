"""__smoke__ sessions: every lane runs, no actuator fires.

WHY. On 2026-10-03 a 168-turn smoke battery sent "read Genesis" as a live /chat
turn. The Thoth read lane does not merely route — it reads aloud and keeps
going. She recited Genesis in the Captain's room, unasked, from an unattended
test; it was stopped at Genesis 1:25. That was the SECOND test run of mine to
reach the physical world through her (the first opened the webcam).

THE GUARANTEE IS AT THE ACTUATOR, NOT THE LANE. A per-lane opt-out is a list
someone forgets to extend. These tests assert the property at the last function
before something happens in the room — and at the HTTP routes that hand a
device something to play, which is how Dio gets sound at all.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "agent"))

import sandbox          # noqa: E402


@pytest.fixture(autouse=True)
def clean_context():
    """No test may leave the flag set — that is the failure that would silence a
    real conversation."""
    yield
    assert not sandbox.active(), "a test leaked the sandbox flag"


# ── the prefix contract ────────────────────────────────────────────────────
@pytest.mark.parametrize("sid,expected", [
    ("__smoke__abc123", True),
    ("__smoke__", True),
    ("default", False),
    ("", False),
    (None, False),
    ("smoke", False),                 # near-miss must NOT count
    ("x__smoke__y", False),           # prefix, not substring
    ("__argus_probe__", False),       # the other reserved prefix is not this one
])
def test_only_the_reserved_prefix_counts(sid, expected):
    assert sandbox.is_smoke_session(sid) is expected


# ── enter / leave, and no leak ─────────────────────────────────────────────
def test_enter_and_leave_are_paired_and_restore_exactly():
    assert sandbox.active() is False
    t1 = sandbox.enter("__smoke__one")
    assert sandbox.active() is True
    t2 = sandbox.enter("default")          # nested, non-smoke
    assert sandbox.active() is False
    sandbox.leave(t2)
    assert sandbox.active() is True, "leaving the inner scope lost the outer one"
    sandbox.leave(t1)
    assert sandbox.active() is False


def test_a_normal_session_is_unaffected_after_a_smoke_session():
    """The leak that matters: a battery turn must not silence the next real one."""
    t = sandbox.enter("__smoke__x")
    assert sandbox.suppress("speak", "hello") is True
    sandbox.leave(t)
    t2 = sandbox.enter("default")
    assert sandbox.suppress("speak", "hello") is False, "real session was silenced"
    sandbox.leave(t2)


def test_suppress_outside_any_session_does_nothing():
    assert sandbox.suppress("speak", "hello") is False


# ── every actuator is guarded, asserted by reading the source ─────────────
# Deliberately a source assertion rather than a behavioural one: the point of
# this design is that the guard sits in a specific place. A behavioural test
# would pass if someone moved the check up into one lane and left the actuator
# open to the next lane.
@pytest.mark.parametrize("path,func,action", [
    ("modules/tts_module.py", "def speak(", "speak"),
    ("modules/tts_module.py", "def _play_pcm(", "play audio"),
    ("modules/dio_head.py", "def send(", "move head"),
    ("modules/vision_module.py", "def capture(", "capture image"),
    ("modules/vision_module.py", "def take_photo(", "take photo"),
    ("modules/camera_module.py", "def move(", "move camera"),
    ("modules/memory_module.py", "def remember_fact(", "remember fact"),
    # Added after the sandbox leaked a REAL side effect: a __smoke__
    # "read Genesis" served zero audio bytes and still ran the reader thread,
    # which synthesised a chapter on the GPU and advanced the Captain's bookmark
    # from Genesis 1:25 to 1:5. Suppressing the sound is not suppressing the act.
    ("modules/thoth/reader.py", "def start(", "read aloud"),
    ("modules/thoth/reader.py", "def save_position(", "move bookmark"),
])
def test_each_actuator_checks_the_sandbox_first(path, func, action):
    src = (ROOT / path).read_text()
    i = src.index(func)
    window = src[i:i + 1400]
    assert "sandbox." in window, f"{path}:{func} does not consult the sandbox"
    assert action in window, f"{path}:{func} does not log what it would do"


def test_memory_spine_checks_the_session_id_too():
    """A queued write can lose the request context, so the spine checks both."""
    src = (ROOT / "agent" / "memory_spine.py").read_text()
    i = src.index("def remember(")
    window = src[i:i + 1200]
    assert "sandbox.active()" in window and "is_smoke_session" in window


# ── the device-serve routes: text yes, audio never ────────────────────────
def test_the_stream_record_carries_the_sandbox_flag():
    """/tts/chunk/{sid}/{n} is a separate request with NO session id, so a
    contextvar cannot reach it. The only thing that survives the gap is the
    stream record, captured when the session was still known."""
    src = (ROOT / "agent" / "server.py").read_text()
    i = src.index("def _tts_stream_new(")
    window = src[i:i + 1200]
    assert '"sandbox"' in window, "stream record does not carry the flag"


def test_the_chunk_route_returns_text_and_no_audio():
    src = (ROOT / "agent" / "server.py").read_text()
    i = src.index("async def tts_chunk_endpoint(")
    window = src[i:i + 1600]
    assert 'st.get("sandbox")' in window, "chunk route does not check the stream flag"
    m = re.search(r'if st\.get\("sandbox"\):(.*?)\n\s*audio = await', window, re.S)
    assert m, "no sandbox branch before synthesis"
    branch = m.group(1)
    assert '"audio": ""' in branch, "sandbox branch still serves audio"
    assert '"text"' in branch, "sandbox branch drops the caption"


def test_chat_stream_reads_the_session_id_not_the_contextvar():
    """This test used to assert sandbox.active() here. That WAS the bug.

    The contextvar is entered around _run_chat_pipeline and left when it
    returns, but /chat/stream synthesises audio AFTER the pipeline. Measured
    2026-10-03: a __smoke__ turn was correctly flagged inside the pipeline and
    then served 152,140 bytes, because the flag was gone by the time synthesis
    ran. Ambient state is only true where it is entered; the session id is true
    everywhere in the request.
    """
    src = (ROOT / "agent" / "server.py").read_text()
    i = src.index("async def chat_stream_endpoint(")
    head = src[i:i + 1600]
    assert "sandbox.is_smoke_session(body.get(\"session_id\"))" in head, \
        "the route does not derive the sandbox flag from the session id"
    j = src.index("sid = _tts_stream_new(chunks, out_voice")
    window = src[j:j + 900]
    assert "sandboxed=_sbx_on" in window, "the flag is not stored on the stream"
    assert "if _sbx_on:" in window, "synthesis is not gated on the explicit flag"
    assert 'audio0 = ""' in window, "chunk 0 audio is still synthesised"


def test_the_floor_is_not_suppressible_by_a_session_id():
    """A sandbox that skipped the floor would measure a system that does not
    exist, and the floor must never be switchable from the outside."""
    for mod in ("morpheus.py", "triage.py"):
        src = (ROOT / "modules" / mod).read_text()
        assert "sandbox" not in src, f"{mod} consults the sandbox — the floor must not"


def test_a_silent_actuator_is_still_an_actuator():
    """The lesson from the leak, written down as a test.

    Audio suppression alone let a sandboxed reading run the thread, spend GPU on
    a chapter nobody would hear, and move a bookmark on disk. Anything that
    CHANGES STATE or SPENDS A RESOURCE counts, not only things that make a
    noise — so the guard sits at the start of the act, not at its output.
    """
    src = (ROOT / "modules" / "thoth" / "reader.py").read_text()
    i = src.index("    def start(")
    # the guard must come BEFORE the thread is created, or it guards nothing
    window = src[i:i + 2000]
    g = window.index("sandbox.suppress")
    t = window.find("Thread(")
    assert t == -1 or g < t, "the sandbox check runs after the thread is started"
