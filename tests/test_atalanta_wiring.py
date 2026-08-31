"""Atalanta's wiring into the server: advertised set, dispatch, fail-loud.

Separate from test_atalanta.py because these import the whole server; the module
tests stay fast and import-light.
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "modules"))

import server                                   # noqa: E402

atalanta = server.atalanta
SPORTS = {"get_scores", "get_standings", "get_schedule"}


def _names(tools):
    return {t["function"]["name"] for t in tools}


def test_sports_tools_are_advertised_when_egress_is_on(monkeypatch):
    monkeypatch.setattr(atalanta, "egress_ok", lambda: True)
    assert SPORTS <= _names(server.tools_for_turn())


def test_sports_tools_are_ABSENT_when_egress_is_off(monkeypatch):
    """OFF means absent from the menu, not merely refused on use: a tool she can
    see is a tool she will offer."""
    monkeypatch.setattr(atalanta, "egress_ok", lambda: False)
    names = _names(server.tools_for_turn())
    assert not (SPORTS & names), f"sports tools still advertised with egress off: {SPORTS & names}"


def test_turning_egress_off_removes_only_the_sports_tools(monkeypatch):
    monkeypatch.setattr(atalanta, "egress_ok", lambda: True)
    on = _names(server.tools_for_turn())
    monkeypatch.setattr(atalanta, "egress_ok", lambda: False)
    off = _names(server.tools_for_turn())
    assert on - off == SPORTS, f"filtering removed something else too: {(on - off) - SPORTS}"


def test_toggle_takes_effect_without_restart(monkeypatch):
    """tools_for_turn() is evaluated per turn, so the switch is live."""
    monkeypatch.setattr(atalanta, "egress_ok", lambda: False)
    assert not (SPORTS & _names(server.tools_for_turn()))
    monkeypatch.setattr(atalanta, "egress_ok", lambda: True)
    assert SPORTS <= _names(server.tools_for_turn())


# ── handler behaviour ────────────────────────────────────────────────────────
def test_backend_broken_says_so_and_invents_nothing(monkeypatch):
    def boom(*a, **kw):
        raise atalanta.SportsBroken("shape changed")
    monkeypatch.setattr(atalanta, "get_scores", boom)
    out = server._tool_sports("scores", {"league": "mlb"})
    assert "can't reach" in out.lower()
    assert "won't guess" in out.lower()
    assert not any(ch.isdigit() for ch in out), "a broken backend produced digits"


def test_rate_cap_is_reported_honestly(monkeypatch):
    def busy(*a, **kw):
        raise atalanta.SportsBusy("cap")
    monkeypatch.setattr(atalanta, "get_scores", busy)
    out = server._tool_sports("scores", {"league": "mlb"})
    assert "moment" in out.lower()


def test_unlisted_league_refused_by_name_through_the_handler():
    out = server._tool_sports("scores", {"league": "formula 1"})
    assert "don't cover" in out.lower() and "formula 1" in out.lower()


def test_handler_announces_the_fetch(monkeypatch):
    monkeypatch.setattr(atalanta, "get_scores", lambda *a, **kw: {
        "ok": True, "announce": "Checking MLB results for 2026-08-29.",
        "league": "mlb", "rows": [], "unsettled": [], "from_cache": False,
        "empty_reason": "No games in MLB that day."})
    out = server._tool_sports("scores", {"league": "mlb"})
    assert out.startswith("Checking MLB results"), "fetch was not announced"


def test_argus_contract_exists():
    import json
    c = json.loads((REPO / "config" / "argus_contracts.json").read_text())
    assert "atalanta" in c["devices"]
    assert c["devices"]["atalanta"]["type"] == "service"


# ── intent claim ─────────────────────────────────────────────────────────────
import intent_registry  # noqa: E402


@pytest.mark.parametrize("msg", [
    "What were last night's MLB scores?",
    "Show me the NBA standings",
    "who won the hockey game last night",
    "what were the college football results",
])
def test_result_questions_are_claimed(msg):
    c = intent_registry.resolve(msg)
    assert c is not None and c.module == "atalanta", f"not claimed: {msg!r}"


@pytest.mark.parametrize("msg", [
    "Why is it called a safety in football?",
    "What are the rules of offside in soccer?",
    "Explain the history of the NFL",
    "what is a safety in football",
    "Who should I bet on in the NBA tonight?",
    "What are the odds on the MLB game",
    "Tell me a joke",
])
def test_explanations_odds_and_unrelated_are_NOT_claimed(msg):
    """Rules, terminology, history and betting must cost no packets at all."""
    c = intent_registry.resolve(msg)
    assert not (c and c.module == "atalanta"), f"wrongly claimed: {msg!r}"


def test_claimed_turn_without_a_league_falls_through():
    """No league named → fall through to normal routing, never guess a sport."""
    out = asyncio.run(server._answer_sports("what were the scores last night"))
    assert out is None, "guessed a league instead of falling through"


@pytest.mark.parametrize("msg,kind,league", [
    ("show me the NBA standings", "standings", "nba"),
    ("what were last night's MLB scores", "scores", "mlb"),
    ("what's the NHL schedule this week", "schedule", "nhl"),
])
def test_claimed_turn_routes_to_the_right_kind(msg, kind, league, monkeypatch):
    seen = {}
    def fake(k, args, for_model=True):
        seen.update(kind=k, for_model=for_model, **args)
        return "ok"
    monkeypatch.setattr(server, "_tool_sports", fake)
    asyncio.run(server._answer_sports(msg))
    assert seen["kind"] == kind and seen["league"] == league
    assert seen["for_model"] is False, "claim path must return user-facing text"


# ── uncovered leagues are refused BY NAME, not left to improvisation ─────────
@pytest.mark.parametrize("msg,token", [
    ("What were the F1 results last weekend?", "f1"),
    ("Who won the UFC fight last night?", "ufc"),
    ("what were the tennis scores today", "tennis"),
])
def test_uncovered_league_is_claimed_and_refused_by_name(msg, token):
    c = intent_registry.resolve(msg)
    assert c is not None and c.module == "atalanta", f"not claimed: {msg!r}"
    out = asyncio.run(server._answer_sports(msg))
    assert out is not None, "fell through instead of refusing by name"
    assert token in out.lower() and "don't cover" in out.lower()


@pytest.mark.parametrize("msg", [
    "Why is it called a safety in football?",
    "Who should I bet on in F1?",
    "explain the rules of cricket",
])
def test_exclusions_still_win_over_the_uncovered_claim(msg):
    c = intent_registry.resolve(msg)
    assert not (c and c.module == "atalanta"), f"wrongly claimed: {msg!r}"


def test_refusal_names_what_is_covered():
    out = asyncio.run(server._answer_sports("what were the F1 results"))
    for league in ("NFL", "NBA", "MLB", "NHL"):
        assert league in out
