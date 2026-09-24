"""The gate can be switched off, and when it breaks it says so out loud.

2026-09-24 incident: the context manifest made triage hold EVERY turn on an
empty context — the first message of any fresh conversation — so she asked for
clarification forever and was unusable. Two separate faults made that an outage
rather than a bug:

  1. There was no way to switch the guard off without editing code and
     restarting her mid-incident. The gate sits in front of all of chat.
  2. The day before, the opposite failure (the 2 s cap silently disabling the
     guard) was invisible for the mirror-image reason: the only line that knew
     sat at INFO.

Both are the same defect — a guard whose state is not operable and not audible.
These tests hold that shut. They never reach a model.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import triage  # noqa: E402


@pytest.fixture
def caplogs():
    got: list[tuple[int, str]] = []

    class _Cap(logging.Handler):
        def emit(self, r):
            got.append((r.levelno, r.getMessage()))

    h = _Cap()
    triage.log.addHandler(h)
    old = triage.log.level
    triage.log.setLevel(logging.DEBUG)
    yield got
    triage.log.removeHandler(h)
    triage.log.setLevel(old)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point the switch at a scratch file; never touch the real config."""
    p = tmp_path / "triage.json"
    monkeypatch.setattr(triage, "_CONFIG_PATH", str(p))
    monkeypatch.delenv("PH3B3_TRIAGE", raising=False)

    def _write(obj):
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return p, _write


# ── the switch ───────────────────────────────────────────────────────────────
def test_default_is_enabled_when_there_is_no_file(cfg):
    p, _ = cfg
    assert not p.exists()
    assert triage.gate_enabled() is True, "a missing config silently disabled a guard"


def test_enabled_false_switches_the_gate_off(cfg):
    _, write = cfg
    write({"enabled": False})
    assert triage.gate_enabled() is False


def test_the_switch_is_read_per_call_so_no_restart_is_needed(cfg):
    """The whole point. During an incident there is no time to restart her, and
    a control you cannot operate is not a control."""
    _, write = cfg
    write({"enabled": True});  assert triage.gate_enabled() is True
    write({"enabled": False}); assert triage.gate_enabled() is False, "needed a restart"
    write({"enabled": True});  assert triage.gate_enabled() is True


def test_a_malformed_config_leaves_the_gate_ENABLED_and_warns(cfg, caplogs):
    """A typo must never silently disable a guard — that is the failure this
    whole file exists about, pointing the other way."""
    _, write = cfg
    write("{ not json at all")
    assert triage.gate_enabled() is True
    assert any(lv >= logging.WARNING and "TRIAGE_CONFIG_UNREADABLE" in m
               for lv, m in caplogs), "a broken config was swallowed silently"


def test_the_env_var_forces_it_off_and_beats_the_file(cfg, monkeypatch):
    """For when she will not start well enough to serve a request at all."""
    _, write = cfg
    write({"enabled": True})
    for val in ("off", "0", "false", "no"):
        monkeypatch.setenv("PH3B3_TRIAGE", val)
        assert triage.gate_enabled() is False, f"PH3B3_TRIAGE={val} did not switch it off"


def test_the_chat_path_skips_the_judge_entirely_when_off():
    """Off must mean NO judge call — not a call whose answer is ignored."""
    src = (REPO / "agent" / "server.py").read_text(encoding="utf-8")
    i = src.index("if not gate_enabled():")
    j = src.index("_triage = (_TriagePass()", i)
    window = src[i:j]
    assert "_TriagePass()" in window, "the off branch does not short-circuit"
    assert "await triage_gate" not in window, "the judge is still called with the gate off"
    assert src.index("if not gate_enabled():") < src.index("await triage_gate("), \
        "the switch is checked after the judge has already been asked"


# ── fail-open, loud ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("cause", ["TIMEOUT", "PARSE", "CONN", "EVICTED"])
def test_every_error_path_fails_OPEN_and_says_so_at_warning(cause, caplogs):
    """Fail-open was never the sin; fail-open SILENT was.

    Do not 'fix' this by failing closed: a dead judge plus fail-closed holds
    every turn forever, which is the same outage from the other side — and is
    exactly what the 2026-09-24 incident felt like to use.
    """
    before = dict(triage.FAILOPEN_COUNTS)
    r = triage._fail_open(cause)
    assert r.answerable is True, f"{cause} held the turn — the guard broke her"
    assert r.question is None
    assert any(lv >= logging.WARNING and f"TRIAGE_FAILOPEN_{cause}" in m
               for lv, m in caplogs), f"{cause} fail-open was not audible"
    assert triage.FAILOPEN_COUNTS[cause] == before.get(cause, 0) + 1, \
        "the Argus-visible counter did not move"


def test_a_wedged_judge_still_lets_turns_through():
    """The judge sleeps past the cap. Every turn must still flow."""
    class _Resp:
        def __init__(self, d): self._d = d
        def json(self): return self._d

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, timeout=None):
            return _Resp({"models": [{"name": triage.HERMES_MODEL}]})
        async def post(self, url, json=None, timeout=None):
            await asyncio.sleep(triage._TRIAGE_TIMEOUT + 2)   # wedged
            return _Resp({"message": {"content": '{"answerable": false}'}})

    old_client, old_cap = triage.httpx.AsyncClient, triage._TRIAGE_TIMEOUT
    triage.httpx.AsyncClient = _Client
    triage._TRIAGE_TIMEOUT = 0.2                    # keep the test quick
    try:
        for _ in range(3):
            r = asyncio.run(triage.triage_gate("hello", ""))
            assert r.answerable is True, "a wedged judge held the turn"
    finally:
        triage.httpx.AsyncClient, triage._TRIAGE_TIMEOUT = old_client, old_cap


def test_the_counter_is_exposed_for_argus():
    assert isinstance(triage.FAILOPEN_COUNTS, dict), \
        "'the guard is not guarding' must be a number something can read"


# ── the manifest switch ──────────────────────────────────────────────────────
def test_the_manifest_is_OFF_by_default(cfg):
    """Default set by measurement, not preference.

    The manifest fixed capability questions and broke every other turn whenever
    CONTEXT was empty — the first message of any fresh conversation. Four
    wordings were tested, including one giving the judge no instruction at all;
    all failed identically, so the block's presence is the problem rather than
    its phrasing. If this default flips back to True without the numbers in
    manifest_enabled() being re-measured on the current judge, the 2026-09-24
    outage comes back exactly as it was.
    """
    p, _ = cfg
    assert not p.exists()
    assert triage.manifest_enabled() is False


def test_the_manifest_can_be_switched_back_on_for_a_rematch(cfg):
    """Switchable, not deleted — so a bigger judge can be measured against it
    without reviving the code from a diff."""
    _, write = cfg
    write({"enabled": True, "manifest": True})
    assert triage.manifest_enabled() is True
    write({"enabled": True, "manifest": False})
    assert triage.manifest_enabled() is False


def test_the_shipped_config_has_the_gate_on_and_the_manifest_off():
    """What she actually boots with."""
    import json as _json
    cfg = _json.loads((REPO / "config" / "triage.json").read_text(encoding="utf-8"))
    assert cfg["enabled"] is True, "the guard ships disabled"
    assert cfg["manifest"] is False, "the manifest that caused the outage ships on"
