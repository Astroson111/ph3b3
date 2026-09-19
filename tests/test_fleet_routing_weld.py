"""
Fleet routing + the no-claims weld.

THE FAILURE THIS CLOSES. Asked "How is Rhea doing?", Phoebe answered:

    "Rhea is currently stable and resting comfortably. Her vitals are within
     normal ranges... The doctors are pleased with her progress. Would you like
     me to take a photo of her?"

She invented a patient. Not because the data was missing — Argus had it — but
because the query never reached the code that holds it. The old intent pattern
matched a hand-list of exact phrasings; six of nine natural ones fell through to
a model with no fleet tool, and a model with nothing to say says something.

So two changes, and the second is the one that generalises:

  Phase 1  intent, not phrasing — a device alias plus a status-shaped word.
           Loose on purpose: a fleet answer to a borderline question is a small
           cost, fiction about a real subsystem is not.

  Phase 2  THE WELD. If the intercept fires and holds no datum, she says so.
           Third time this rule has been needed, so it is doctrine: no claims of
           sight without a capture, no claims of scripture without a retrieved
           passage, no claims of state without telemetry.

Run:  .venv/bin/python -m pytest tests/test_fleet_routing_weld.py -v
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "modules"))

import server           # noqa: E402
import rhea_status      # noqa: E402

R = server._FLEET_INTENT_RE

# The nine phrasings from the audit. These ARE the floor — all nine must route.
NINE = [
    "How is Rhea doing?", "When did Rhea last back up?", "Is Rhea okay?",
    "Did the backup run?", "How's the backup drive?", "Rhea status",
    "is rhea online", "what's Dio's battery", "fleet status",
]


# ── Phase 1: routing ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", NINE)
def test_all_nine_audit_phrasings_route(q):
    """Six of these used to fall through to the model and get invented answers."""
    assert R.search(q), f"{q!r} still falls through to the LLM"


@pytest.mark.parametrize("q", [
    "did the backup work last night", "was the backup ok", "has the backup run yet",
    "is helios up", "helios status", "when did iris last check in",
    "is dio still asleep", "how is metis", "are the badges online",
    "what's the state of comfyui", "has nyx been responding",
])
def test_natural_phrasings_route(q):
    assert R.search(q), f"{q!r} does not route"


@pytest.mark.parametrize("q", [
    "nyx, make me a picture of a cat", "write a song about Iris",
    "draw dio as a cartoon", "tell me a joke", "back up the file for me",
    "generate an image of a lighthouse",
])
def test_ordinary_requests_are_not_hijacked(q):
    """Erring toward intercepting must not mean eating every mention of a
    device. A request to DO something is not a question about state."""
    assert not R.search(q), f"{q!r} was wrongly claimed by the fleet intercept"


# ── Phase 2: the weld ────────────────────────────────────────────────────────

def test_a_named_device_with_no_telemetry_says_so():
    """Helios has never enrolled in Argus. The honest answer names that, rather
    than substituting a whole-fleet summary that dodges the question."""
    a = server._answer_fleet("is helios up")
    low = a.lower()
    assert "helios" in low
    assert "don't have a reading" in low or "no reading" in low
    assert "never had a heartbeat" in low
    # it must NOT quietly answer about everything else instead
    assert "fleet status:" not in low


def test_the_weld_does_not_invent_a_state():
    """The specific failure: no vitals, no doctors, no improvisation."""
    a = server._answer_fleet("How is Helios doing?").lower()
    for invented in ("stable", "resting", "vitals", "comfortable", "doctors",
                     "progress", "healthy"):
        assert invented not in a, f"the weld still improvises: {invented!r}"


def test_an_empty_fleet_is_reported_as_empty(monkeypatch):
    """If Argus returns nothing at all, say that — do not summarise a void."""
    monkeypatch.setattr(server.argus_store, "fleet", lambda *_a, **_k: [])
    a = server._answer_fleet("how's the fleet").lower()
    assert "don't have a reading" in a and "guessing" in a


def test_a_real_device_still_gets_its_real_reading():
    """The weld must not make her cagey about data she actually has."""
    a = server._answer_fleet("is nyx online").lower()
    assert "nyx" in a
    assert "don't have a reading" not in a


# ── Phase 3: the backup voice ────────────────────────────────────────────────

def test_a_backup_question_gets_backup_facts_not_a_heartbeat_age():
    """'When did Rhea last back up' answered with 'Rhea is healthy as of 5h ago'
    is technically true and not the answer to the question."""
    a = server._answer_fleet("When did Rhea last back up?")
    assert "backup" in a.lower()
    assert any(c.isdigit() for c in a), "no timestamp in a 'when' answer"


def test_the_backup_answer_admits_the_drill_has_never_run():
    """The uncomfortable fact is the one most worth stating."""
    a = rhea_status.spoken().lower()
    if not rhea_status._drill()["ever"]:
        assert "never been" in a or "no restore drill" in a
        assert "unproven" in a


def test_status_returns_facts_or_nothing_never_guesses():
    s = rhea_status.status()
    for key in ("last_run", "heartbeat", "drill", "drive_mounted"):
        assert key in s
    # every field is either a real datum or an explicit None
    assert s["last_run"]["result"] in (None, "ok", "failed")
    assert s["heartbeat"]["ts"] is None or isinstance(s["heartbeat"]["ts"], int)


def test_the_module_cannot_restore():
    """Restore overwrites live data. The one thing worse than an untested backup
    is a restore that can be triggered by a sentence."""
    # Checked as CAPABILITY, not as vocabulary. The first version flagged the
    # sentence "No restore drill has ever been completed" — prose telling the
    # truth, which is the opposite of the thing being guarded against.
    import ast
    src = (REPO / "modules" / "rhea_status.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        # no function that restores
        if isinstance(n, ast.FunctionDef):
            assert "restore" not in n.name.lower(), f"defines {n.name}"
        # no subprocess call carrying a restore verb
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr in ("run", "Popen", "call", "check_output"):
            argv = ast.unparse(n).lower()
            for verb in ("restore", "forget", "prune", "unlock", "rm "):
                assert verb not in argv, f"shell call can {verb.strip()}: {argv[:60]}"
    assert "def restore" not in src


def test_the_tool_tells_the_model_it_cannot_restore():
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index('"name":"backup_status"')
    desc = src[i:i + 700]
    assert "CANNOT restore" in desc or "cannot restore" in desc
