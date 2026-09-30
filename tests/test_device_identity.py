"""Capability is granted on PROVEN identity, never on a claimed header.

AUDIT, 2026-09-30. `X-Ph3b3-Device` is a string any authed LAN client can send.
The auth middleware already separates the two:

    request.state.auth_kind = auth_kind
    request.state.device = dev_name if auth_kind == "device" else None

so `request.state.device` is set ONLY when the caller proved it with its own
per-device key. The codebase already knew the difference in two places — dio_host
refuses to adopt an IP until it verifies a real camera server there, and the
Argus heartbeat rejects a "stackchan" beat from any IP but the verified one — but
five other sites routed hardware or shaped the prompt from the header alone:

    echo guard (stackchan)      dropped turns as self-echo
    device commands (iris)      skipped the model, ran a device intent
    _vision_intercept           CHOSE WHICH CAMERA to point
    _DEVICE_NOTES               injected "you are speaking through <body>"
    native photo loop           told a Stack-Chan to run its capture loop

Three of those are a camera firing in somebody's room on the strength of a
header. This file holds the line.

LABELLING IS DELIBERATELY STILL HEADER-DERIVED — chat-log source tags, [DBG-MIC]
lines, the VAD roster. Mislabelling a log entry is not the same class of problem
as pointing a lens, and forcing those to verified identity would make an
unverified device's turns anonymous in the transcript for no safety gain.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "agent"))

from agent import server  # noqa: E402

SRC = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")


class _State:
    def __init__(self, device=None, auth_kind=None):
        self.device = device
        self.auth_kind = auth_kind


class _Req:
    """A request that CLAIMS one identity and PROVED another (or none)."""
    def __init__(self, claimed=None, proved=None):
        self.headers = {"X-Ph3b3-Device": claimed} if claimed else {}
        self.state = _State(device=proved,
                            auth_kind="device" if proved else "human")

    def __class_getitem__(cls, _):
        return cls


def _req(claimed=None, proved=None):
    r = _Req(claimed, proved)
    # headers.get must behave like Starlette's
    r.headers = type("H", (), {"get": staticmethod(
        lambda k, d="": ({"X-Ph3b3-Device": claimed} if claimed else {}).get(k, d))})()
    return r


# ── the helper itself ────────────────────────────────────────────────────────
def test_a_proven_device_is_returned():
    assert server.verified_device(_req(claimed="stackchan", proved="stackchan")) == "stackchan"


def test_a_claimed_but_unproven_device_is_none():
    """THE SPOOF. An authed human client sending the header must not be Dio."""
    assert server.verified_device(_req(claimed="stackchan", proved=None)) is None
    assert server.verified_device(_req(claimed="iris", proved=None)) is None


def test_a_plain_browser_is_none():
    assert server.verified_device(_req()) is None


def test_the_helper_never_reads_the_header():
    i = SRC.index("def verified_device(")
    body = SRC[i:SRC.index("def claimed_device(")]
    assert "headers" not in body, "verified_device consults the header"


def test_claimed_device_is_available_for_labels_and_says_so():
    assert server.claimed_device(_req(claimed="stackchan")) == "stackchan"
    i = SRC.index("def claimed_device(")
    body = SRC[i:i + 400]
    assert "never capability" in body.lower()


# ── every capability site takes the verified value ───────────────────────────
# The CALL site, not the definition — anchored on the exact guard line so the
# test cannot pass by finding the function that implements the capability.
CAPABILITY_SITES = [
    ('if _looks_like_self_echo(', 'echo guard drops turns'),
    ('and device_commands.is_device_intent(user_msg):', 'device intent skips the model'),
    ('user_msg, device=(verified_device(request) or "nyx"))', 'camera routing'),
    ('if device in _DEVICE_NOTES:', 'prompt injection naming the body'),
    ('in device_auth.STACKCHAN_DEVICES', 'native on-device capture loop'),
]


@pytest.mark.parametrize("needle,what", CAPABILITY_SITES)
def test_the_capability_site_is_gated_on_verified_identity(needle, what):
    assert SRC.count(needle) == 1, f"{needle!r} is no longer a unique anchor"
    i = SRC.index(needle)
    window = SRC[max(0, i - 700):i + 200]
    code = "\n".join(ln for ln in window.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "verified_device(request)" in code, \
        f"{what} is still decided from a header claim"


def test_no_capability_site_reads_the_header_directly():
    """Every remaining header read must be a label. Named explicitly so a new
    one cannot be added without this test being updated deliberately."""
    allowed_labels = {
        577,    # the auth middleware itself — this is where the claim is judged
    }
    offenders = []
    for n, line in enumerate(SRC.splitlines(), 1):
        if "X-Ph3b3-Device" not in line or line.lstrip().startswith("#"):
            continue
        if n in allowed_labels:
            continue
        # a capability read is one whose value feeds routing, not a log/label
        if re.search(r"(_vision_intercept|_looks_like_self_echo|STACKCHAN_DEVICES"
                     r"|_DEVICE_NOTES|is_device_intent)", line):
            offenders.append(f"line {n}: {line.strip()[:90]}")
    assert not offenders, "a capability is still gated on a header:\n  " + "\n  ".join(offenders)


# ── the two precedents that were already right stay right ────────────────────
def test_the_argus_heartbeat_keeps_its_ip_check():
    assert "rejected spoofed heartbeat" in SRC, \
        "the Argus heartbeat lost its spoof guard"


def test_dio_host_adoption_still_verifies_before_adopting():
    assert "try_set_dio_host" in SRC
    vision = (ROOT / "modules" / "vision_module.py").read_text(encoding="utf-8")
    assert "spoofed X-Ph3b3-Device" in vision, \
        "the dio_host verification comment/logic is gone"


# ── labelling is intentionally untouched ─────────────────────────────────────
def test_the_chat_log_still_labels_by_claim():
    """Not a bug: an unverified device's turns should still be attributable in
    the transcript. Pinned so nobody 'fixes' it into anonymity."""
    assert '_src = request.headers.get("X-Ph3b3-Device", "")' in SRC


# ── BEHAVIOURAL spoof tests ──────────────────────────────────────────────────
# The greps above are a tripwire: they prove the call sites READ the verified
# value. These prove what actually HAPPENS for the four printed cases, by driving
# the real decision functions with fake request objects. A tripwire can be
# satisfied by code that reads the right variable and then ignores it; this
# cannot.
_CASES = [
    ("real Dio",            "stackchan", "stackchan", "stackchan"),
    ("spoofed Dio",         "stackchan", None,        None),
    ("real Iris",           "iris",      "iris",      "iris"),
    ("spoofed Iris",        "iris",      None,        None),
    ("plain browser",       None,        None,        None),
    ("spoofed Pan",         "pan",       None,        None),
]


@pytest.mark.parametrize("label,claimed,proved,expect", _CASES)
def test_identity_resolution_per_case(label, claimed, proved, expect):
    assert server.verified_device(_req(claimed, proved)) == expect, label


@pytest.mark.parametrize("label,claimed,proved,expect", _CASES)
def test_camera_routing_per_case(label, claimed, proved, expect):
    """The camera the turn would be routed to. A spoofed Dio must get the local
    webcam ("nyx"), never Dio's lens."""
    routed = server.verified_device(_req(claimed, proved)) or "nyx"
    assert routed == (expect or "nyx"), label
    if claimed == "stackchan" and proved is None:
        assert routed == "nyx", "a spoofed header pointed Dio's camera"


@pytest.mark.parametrize("label,claimed,proved,expect", _CASES)
def test_the_body_note_is_only_given_to_a_proven_body(label, claimed, proved, expect):
    """_DEVICE_NOTES tells her which body she is speaking through. A spoofed
    header must not be able to tell her she is Dio."""
    device = server.verified_device(_req(claimed, proved)) or ""
    gets_note = device in ("iris", "stackchan")
    assert gets_note == (expect in ("iris", "stackchan")), label
    if proved is None:
        assert not gets_note, f"{label}: a header claim shaped her self-description"


def test_the_echo_guard_only_fires_for_a_proven_dio():
    """It DROPS turns. A spoofed header must not be able to silence a client."""
    for claimed, proved, should_fire in [("stackchan", "stackchan", True),
                                         ("stackchan", None, False),
                                         (None, None, False)]:
        fires = server.verified_device(_req(claimed, proved)) == "stackchan"
        assert fires is should_fire


def test_the_device_intent_lane_only_fires_for_a_proven_iris():
    """It skips the model and runs a device intent."""
    for claimed, proved, should_fire in [("iris", "iris", True),
                                         ("iris", None, False)]:
        fires = server.verified_device(_req(claimed, proved)) == "iris"
        assert fires is should_fire


def test_the_native_capture_loop_only_fires_for_a_proven_stackchan():
    """This one tells a robot to run its camera. The strictest of the five."""
    import device_auth
    for claimed, proved, should_fire in [("stackchan", "stackchan", True),
                                         ("stackchan", None, False),
                                         ("pan", None, False)]:
        v = server.verified_device(_req(claimed, proved))
        fires = v in device_auth.STACKCHAN_DEVICES
        assert fires is should_fire, f"claimed={claimed} proved={proved}"
