"""A device that is still booting must not lose its camera for five minutes.

MEASURED END TO END, 2026-10-02. The server and Dio restarted together. Her first
check-in triggered the dio_host verification probe while her ESP32 was still
bringing up the camera and the core-0 VAD task — her HTTP server is
single-threaded and did not answer inside the 2 s timeout. The failure was cached
under a FLAT 300 s cooldown, and for those five minutes:

    [head] down -> I couldn't reach Dio — I don't have her address right now
    dio_host 192.168.0.16 unverified: no camera server at :8080

…while she answered that exact endpoint in 0.1 s, measured five times running:

    GET :8080/cam/status -> 200 {"camera":true,"monitor":false}  in 0.09–0.26 s

Both the head commands and the photos were blocked by the cached failure, not by
anything wrong with the robot.

WHAT IS KEPT. The window exists for two real reasons — don't flood the log, and
don't let a spoofed X-Ph3b3-Device header make us probe on every request. Neither
is given up: only the SHAPE changes. Quick retries while "still booting" is a
plausible explanation, escalating to the original 300 s for a host that keeps
failing. A spoofer still reaches five minutes; a rebooting robot is back in
seconds.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import vision_module as vm  # noqa: E402


class _Resp:
    def __init__(self, code=200, text='{"camera":true}'):
        self.status_code = code
        self.text = text


@pytest.fixture
def vis(monkeypatch):
    v = vm.VisionModule.__new__(vm.VisionModule)
    v.dio_host = None
    v._dio_verify_fail = {}
    return v


def _fail(*a, **k):
    raise OSError("refused")


# ── the schedule itself ──────────────────────────────────────────────────────
def test_the_backoff_escalates_and_ends_at_the_original_window():
    assert vm.DIO_VERIFY_BACKOFF[0] <= 5, "the first retry is not quick"
    assert list(vm.DIO_VERIFY_BACKOFF) == sorted(vm.DIO_VERIFY_BACKOFF), \
        "the backoff is not monotonic"
    assert vm.DIO_VERIFY_BACKOFF[-1] == vm.DIO_VERIFY_COOLDOWN, \
        "a persistently failing host no longer settles at the original cooldown"


# ── the bug, inverted ────────────────────────────────────────────────────────
def test_a_booting_device_is_retried_within_seconds(vis, monkeypatch):
    """THE REGRESSION. One failed probe must not cost five minutes."""
    monkeypatch.setattr(vm.requests, "get", _fail)
    assert vis.try_set_dio_host("10.0.0.5") is False

    # it answers a moment later, as a booted device does.
    # NOTE: capture the real clock BEFORE patching — a lambda that calls
    # time.time() after the patch calls itself.
    _now = time.time()
    monkeypatch.setattr(vm.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(vm.time, "time",
                        lambda: _now + vm.DIO_VERIFY_BACKOFF[0] + 0.1)
    assert vis.try_set_dio_host("10.0.0.5") is True
    assert vis.dio_host == "10.0.0.5"


def test_an_immediate_reprobe_is_still_refused(vis, monkeypatch):
    """The flood guard survives: back-to-back requests do not each probe."""
    monkeypatch.setattr(vm.requests, "get", _fail)
    assert vis.try_set_dio_host("10.0.0.5") is False
    calls = []
    monkeypatch.setattr(vm.requests, "get",
                        lambda *a, **k: calls.append(1) or _Resp())
    assert vis.try_set_dio_host("10.0.0.5") is False, "re-probed with no wait"
    assert not calls, "the probe ran inside the backoff window"


def test_a_persistently_absent_host_reaches_the_long_window(vis, monkeypatch):
    """A spoofer gets the original five-minute treatment, just not immediately."""
    monkeypatch.setattr(vm.requests, "get", _fail)
    base = time.time()
    for i in range(len(vm.DIO_VERIFY_BACKOFF) + 2):
        monkeypatch.setattr(vm.time, "time", lambda: base + i * 10000)
        vis.try_set_dio_host("10.0.0.9")
    _last, strikes = vis._dio_verify_fail["10.0.0.9"]
    wait = vm.DIO_VERIFY_BACKOFF[min(strikes, len(vm.DIO_VERIFY_BACKOFF) - 1)]
    assert wait == vm.DIO_VERIFY_COOLDOWN, \
        f"a repeatedly failing host settled at {wait}s, not the full cooldown"


def test_success_clears_the_strikes(vis, monkeypatch):
    monkeypatch.setattr(vm.requests, "get", _fail)
    vis.try_set_dio_host("10.0.0.5")
    assert "10.0.0.5" in vis._dio_verify_fail
    _now = time.time()
    monkeypatch.setattr(vm.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(vm.time, "time", lambda: _now + 99)
    assert vis.try_set_dio_host("10.0.0.5") is True
    assert "10.0.0.5" not in vis._dio_verify_fail, "strikes survived a success"


# ── the verification itself is unchanged ─────────────────────────────────────
def test_a_host_that_is_not_her_camera_is_still_refused(vis, monkeypatch):
    """The spoof guard is the point of this function and must not soften."""
    monkeypatch.setattr(vm.requests, "get",
                        lambda *a, **k: _Resp(200, "hello, I am a web server"))
    assert vis.try_set_dio_host("10.0.0.7") is False
    assert vis.dio_host is None


def test_a_non_200_is_refused(vis, monkeypatch):
    monkeypatch.setattr(vm.requests, "get", lambda *a, **k: _Resp(404, "camera"))
    assert vis.try_set_dio_host("10.0.0.7") is False


def test_the_same_host_is_not_reprobed_once_adopted(vis, monkeypatch):
    vis.dio_host = "10.0.0.5"
    calls = []
    monkeypatch.setattr(vm.requests, "get",
                        lambda *a, **k: calls.append(1) or _Resp())
    assert vis.try_set_dio_host("10.0.0.5") is False
    assert not calls


# ── the probe timeout, which is what actually failed ─────────────────────────
# The backoff turned a five-minute outage into seconds, but the probe was still
# FAILING. Measured on Dio 2026-10-02, twelve consecutive probes: eleven answered
# in 0.06-0.29 s, one took 3.50 s. Her ESP32 HTTP server is single-threaded and
# shares the chip with the camera and the core-0 VAD task. At a 2 s timeout that
# is roughly one spurious failure in twelve — concentrated on the first probe
# after a joint restart, when she is busiest and the answer matters most.
def test_the_probe_timeout_clears_the_measured_worst_case():
    assert vm.DIO_VERIFY_TIMEOUT >= 5.0, (
        f"probe timeout is {vm.DIO_VERIFY_TIMEOUT}s; Dio was measured at 3.50s "
        "under load, and 2s was failing ~8% of probes")


def test_the_probe_timeout_is_still_bounded():
    """Not unbounded: a genuinely dead host must fail, not hang the backoff."""
    assert vm.DIO_VERIFY_TIMEOUT <= 15.0


def test_the_probe_actually_uses_the_constant(vis, monkeypatch):
    seen = {}
    def _get(url, timeout=None, **k):
        seen["timeout"] = timeout
        return _Resp()
    monkeypatch.setattr(vm.requests, "get", _get)
    vis.try_set_dio_host("10.0.0.5")
    assert seen["timeout"] == vm.DIO_VERIFY_TIMEOUT, \
        "the probe hardcodes a timeout instead of reading the constant"


# ── hearing from her beats waiting on a timer ────────────────────────────────
def test_contact_clears_the_backoff(vis, monkeypatch):
    """A device that was legitimately away must not stay locked out after it
    comes back. Dio was in download mode; her probes failed correctly, escalated
    to the 300 s window, and she was still refused her own camera and neck after
    returning — while answering /cam/status in 0.1 s."""
    monkeypatch.setattr(vm.requests, "get", _fail)
    for _ in range(4):
        vis._dio_verify_fail["10.0.0.5"] = (0.0, 9)   # deep in the long window
        vis.try_set_dio_host("10.0.0.5")
    assert "10.0.0.5" in vis._dio_verify_fail

    vis.note_device_alive("10.0.0.5")
    assert "10.0.0.5" not in vis._dio_verify_fail, "contact did not clear the wait"

    monkeypatch.setattr(vm.requests, "get", lambda *a, **k: _Resp())
    assert vis.try_set_dio_host("10.0.0.5") is True, "probe still blocked after contact"


def test_contact_does_not_adopt_or_skip_verification(vis, monkeypatch):
    """Clearing the WAIT must not weaken the spoof guard: /cam/status still has
    to answer and still has to say 'camera'."""
    vis.note_device_alive("10.0.0.9")
    assert vis.dio_host is None, "contact alone adopted a host"
    monkeypatch.setattr(vm.requests, "get",
                        lambda *a, **k: _Resp(200, "<html>router admin</html>"))
    assert vis.try_set_dio_host("10.0.0.9") is False
    assert vis.dio_host is None


def test_contact_from_an_unknown_host_is_harmless(vis):
    vis.note_device_alive("10.0.0.77")      # never failed, nothing to clear
    assert vis._dio_verify_fail == {}
