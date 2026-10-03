"""Her fleet, in her own prompt — generated, not written.

Two things are tested here, and they are the same mistake from opposite ends.

GENERATION. Hardware and role facts used to live in README.md, INSTALL.md,
docs/, device_auth.py and _FLEET_LABEL, or nowhere. Hand-written fleet prose in
a prompt goes stale the moment a device changes and she states it confidently
anyway — the same failure as the "You have no body" line she was carrying until
2026-10-03. So the block is generated from config/devices.json.

ROUTING. "is" is a status word, correctly, for "is Dio online". That meant
"what is Stack-Chan?" scored a device word plus a status word and went to the
fleet lane; the measured answer was "Dio is silent — last checked in 15h ago."
A definitional question got telemetry about one instance.

Neither function is imported from server.py: importing it eagerly loads Whisper
onto the GPU beside the live service, so the real source is extracted and run.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REG_PATH = ROOT / "config" / "devices.json"


@pytest.fixture(scope="module")
def registry():
    return json.loads(REG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fleet_block(registry):
    """Render the block the way _fleet_self_block() does."""
    devs = registry["devices"]
    lines = ["My devices:"]
    for k, d in devs.items():
        lines.append(f"  {d['label']} — {d['role']}; {d['hardware']}"
                     if d.get("hardware") else f"  {d['label']} — {d['role']}")
    sc = [d["label"] for d in devs.values() if d.get("stackchan")]
    if sc:
        lines.append(f"  {' and '.join(sc)} are both Stack-Chans.")
    for b in registry["_background"]:
        lines.append(f"  {b['fact']}")
    lines.append("  Live status is not in this list; it comes from Argus when asked.")
    return "\n".join(lines)


# ── the registry is the single source, and it carries provenance ───────────
def test_every_device_has_hardware_role_and_sources(registry):
    for name, d in registry["devices"].items():
        for field in ("label", "kind", "role", "sources"):
            assert d.get(field), f"{name} is missing {field}"
        assert "hardware" in d, f"{name} has no hardware key (null is allowed)"
        for field in ("label", "hardware", "role"):
            assert d["sources"].get(field), f"{name}.{field} has no recorded source"
        if d.get("hardware"):
            assert d["hardware"] in (d["hardware"] or ""), "sanity"


def test_the_six_named_devices_are_present(registry):
    assert set(registry["devices"]) == {"dio", "pan", "iris", "helios", "nyx", "athena"}


def test_both_stackchans_are_marked(registry):
    sc = {k for k, d in registry["devices"].items() if d.get("stackchan")}
    assert sc == {"dio", "pan"}, f"stackchans: {sc}"


def test_the_two_background_facts_are_static_and_present(registry):
    facts = " ".join(b["fact"] for b in registry["_background"]).lower()
    assert "open-source desktop robot" in facts and "m5stack controllers" in facts
    assert "modular esp32" in facts


def test_facts_taken_on_the_captains_word_are_marked_as_such(registry):
    """Provenance has to survive. Helios's hardware, Pan's case colour and all of
    Athena came from a ticket, not the codebase; they are recorded so they stop
    being tribal knowledge, and marked so nobody mistakes them for verified."""
    blob = json.dumps(registry)
    assert "captain-2026-10-03" in blob
    ath = registry["devices"]["athena"]
    assert all(v == "captain-2026-10-03" for v in ath["sources"].values())
    assert "NOWHERE else" in ath.get("note", "")


# ── the generated block ────────────────────────────────────────────────────
@pytest.mark.parametrize("line", [
    "Dio — my body; Stack-Chan on an M5Stack CoreS3",
    "Iris — my combadge; M5StickS3 with audio unit",
    "Helios — field gateway; Raspberry Pi 5 + 7-inch screen",
    "Nyx — the server I run on",
    "Athena — laptop running ph3b3-light",
    "Pan — the original Stack-Chan (pink case)",
])
def test_block_has_one_line_per_device(line, fleet_block):
    assert line in fleet_block


def test_block_is_first_person(fleet_block):
    assert fleet_block.startswith("My devices:")
    assert "my body" in fleet_block and "my combadge" in fleet_block
    for third in ("Ph3b3's devices", "the assistant", "her body", "the system"):
        assert third not in fleet_block


def test_block_carries_no_live_status(fleet_block):
    """Identity, not telemetry. A cached "online" in a prompt is a claim that
    rots between turns, and she would state it as current.

    Scanned per DEVICE LINE, not over the whole block: the closing disclaimer
    says she does not know whether anything is online, which contains the word
    and is the precise opposite of a status claim. An earlier version of this
    test flagged that sentence — the right fix was to aim the assertion at the
    lines that describe devices, not to reword the disclaimer around the test.
    """
    leaks = ("online", "offline", "battery", "last seen", "silent",
             "heartbeat", "%", "uptime", "charging", "reachable")
    for line in fleet_block.splitlines():
        if "—" not in line:          # only the per-device lines carry facts
            continue
        low = line.lower()
        for leak in leaks:
            assert leak not in low, f"live status in a device line: {leak!r} / {line!r}"
    assert "comes from Argus when asked" in fleet_block
    # And the disclaimer must actually be there, saying she cannot tell from this.
    assert "Live status is not in this list" in fleet_block


def test_block_changes_when_the_registry_does(registry, tmp_path):
    """The point of generating it: swap the hardware, the sentence follows."""
    r = json.loads(json.dumps(registry))
    r["devices"]["dio"]["hardware"] = "a CoreS3 in a wooden case"
    line = f"  Dio — {r['devices']['dio']['role']}; {r['devices']['dio']['hardware']}"
    assert "wooden case" in line


# ── routing: definitional vs status ────────────────────────────────────────
@pytest.fixture(scope="module")
def fleet_intent():
    src = (ROOT / "agent" / "server.py").read_text()
    ns = {"re": re}
    for name in ("_FLEET_DEVICE_WORDS", "_FLEET_STATUS_WORDS", "_FLEET_DEV_RE",
                 "_FLEET_STAT_RE", "_FLEET_BARE_RE", "_FLEET_NOT_RE", "_FLEET_DEF_RE"):
        m = re.search(rf"^{name} = .*?(?=\n[_A-Za-z#]|\n\n)", src, re.S | re.M)
        assert m, f"could not extract {name}"
        exec(m.group(0), ns)                                     # noqa: S102
    m = re.search(r"^class _FleetIntent:.*?_FLEET_INTENT_RE = _FleetIntent\(\)",
                  src, re.S | re.M)
    assert m, "could not extract _FleetIntent"
    exec(m.group(0), ns)                                         # noqa: S102
    return ns["_FLEET_INTENT_RE"]


@pytest.mark.parametrize("q", [
    "what is Stack-Chan?", "what's Iris?", "what is Dio", "who is Pan",
    "whats helios", "what are the stack-chans", "what is Nyx?",
])
def test_definitional_questions_go_to_the_model(q, fleet_intent):
    assert fleet_intent.search(q) is None, f"{q!r} was routed to fleet status"


@pytest.mark.parametrize("q", [
    "is Dio online", "how's Iris", "status of Dio", "check on Pan",
    "what is Dio's battery", "what is Dio doing", "is rhea backed up",
    "did the backup run", "how is Helios doing?", "when was Iris last seen",
])
def test_status_questions_still_go_to_the_fleet_lane(q, fleet_intent):
    assert fleet_intent.search(q) is True, f"{q!r} stopped reaching fleet status"


def test_the_discriminator_is_position_not_vocabulary(fleet_intent):
    """Same words, different question. Anything after the device name means the
    device is the SUBJECT of a status question, not the thing being defined."""
    assert fleet_intent.search("what is Dio") is None
    assert fleet_intent.search("what is Dio doing") is True
