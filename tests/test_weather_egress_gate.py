"""Weather answers to the egress master switch.

The switch sat on the Status card next to web search while weather shelled out to
`curl wttr.in` regardless — three call paths (_answer_weather, the weather_current
tool, weather_ghost_hunting) all reached the socket without consulting it. These
tests assert the thing that actually matters: with the switch OFF, NO PROCESS IS
SPAWNED. Asserting only on the returned string would pass just as happily if the
fetch still fired and the text were swapped afterwards.
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))
sys.path.insert(0, str(REPO))

import weather_module as W


@pytest.fixture
def spy(monkeypatch):
    """Record every subprocess.run; a call is a packet."""
    calls = []

    def _fake_run(*a, **kw):
        calls.append(a[0] if a else kw.get("args"))
        class R:  # pragma: no cover - shape only
            stdout = "Somewhere: ☀️ Clear, +70°F"
            returncode = 0
        return R()

    monkeypatch.setattr(W.subprocess, "run", _fake_run)
    return calls


def _egress(monkeypatch, on):
    monkeypatch.setattr(W, "_egress_ok", lambda: on)


@pytest.mark.parametrize("method", ["current", "forecast", "good_for_ghost_hunting"])
def test_switch_off_spawns_no_process(method, spy, monkeypatch):
    _egress(monkeypatch, False)
    out = getattr(W.WeatherModule(), method)("Boston")
    assert out == W._EGRESS_OFF
    assert not spy, f"{method} egressed with the switch OFF: {spy}"


@pytest.mark.parametrize("method", ["current", "forecast", "good_for_ghost_hunting"])
def test_switch_on_still_fetches(method, spy, monkeypatch):
    """Guards the guard: a gate that never opens would pass the test above."""
    _egress(monkeypatch, True)
    monkeypatch.setattr(W, "DEFAULT_LOCATION", "Boston")
    getattr(W.WeatherModule(), method)("Boston")
    assert spy, f"{method} made no fetch with the switch ON — gate stuck closed"
    assert any("wttr.in" in " ".join(map(str, c)) for c in spy)


def test_gate_fails_closed_when_switch_unreadable(spy, monkeypatch):
    """An unreadable switch means no packets, not 'probably fine'."""
    class Boom:
        @staticmethod
        def egress_enabled():
            raise RuntimeError("egress.json unreadable")

    monkeypatch.setattr(W, "metis", Boom)
    assert W._egress_ok() is False
    assert W.WeatherModule().current("Boston") == W._EGRESS_OFF
    assert not spy


def test_gate_fails_closed_when_metis_missing(spy, monkeypatch):
    monkeypatch.setattr(W, "metis", None)
    assert W._egress_ok() is False
    assert W.WeatherModule().current("Boston") == W._EGRESS_OFF
    assert not spy


def test_refusal_does_not_look_like_a_source_failure():
    """server.py routes a GENUINE source failure to the Metis fallback — which is
    itself egress. The refusal must not match that pattern, or 'web access is off'
    would be answered by going to the web."""
    fail_re = re.compile(r"weather error|could not get (?:weather|forecast)", re.I)
    assert not fail_re.search(W._EGRESS_OFF)


def test_refusal_states_the_reason_and_the_remedy():
    """OFF must refuse with a stated reason — never a silent empty answer."""
    assert "off" in W._EGRESS_OFF.lower()
    assert "status" in W._EGRESS_OFF.lower()
