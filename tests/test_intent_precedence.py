"""Weather beats Metis: dedicated-module intent precedence over forced search.

The bug this guards: Metis's search-intent detector matched weather phrasing and
force-routed those turns to the open web. These tests pin the fix — every weather
wording resolves to the weather module (so the router hands it off BEFORE the
search-intent check runs), while genuine search queries still route to Metis.

Pure-logic tests: no server, no network. Importing weather_module triggers its
self-registration in intent_registry.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import intent_registry          # noqa: E402
import weather_module           # noqa: E402  (import → registers the weather claim)
import metis                    # noqa: E402


# Every phrasing the brief says MUST hit the weather module — including the two
# that read like explicit search requests.
WEATHER_PHRASES = [
    "What's the weather",
    "what's the weather?",
    "weather tomorrow",
    "search the weather for me",
    "look up the forecast",
    "how's the weather in Chicago",
    "is it going to rain today",
    "what's the temperature outside",
    "give me the forecast for tomorrow",
    "how hot is it going to be",
]

# Genuine search queries — must NOT be claimed by weather (they belong to search,
# not the weather module).
SEARCH_PHRASES = [
    "who won the game last night",
    "search the web for the latest news",
    "look up the price of bitcoin",
    "what's the latest headlines",
]

# The subset that trips Metis's server-side FORCED gate (is_search_intent). Bare
# factual phrasings ("who won…") are handled by LLM tool-calling, not this gate —
# so they aren't listed here. The invariant: my change must not shrink this set.
FORCED_SEARCH_PHRASES = [
    "search the web for the latest news",
    "look up the price of bitcoin",
    "what's the latest headlines",
]


def test_all_weather_phrasings_claimed_by_weather():
    for p in WEATHER_PHRASES:
        claim = intent_registry.resolve(p)
        assert claim is not None, f"weather phrasing not claimed: {p!r}"
        assert claim.module == "weather", f"{p!r} claimed by {claim.module}, expected weather"


def test_weather_wins_before_metis_even_when_worded_as_search():
    # The router checks intent_registry.resolve() BEFORE metis.is_search_intent().
    # These phrasings ARE search-intent positive (the exact ones Metis was hijacking)
    # yet must be intercepted by the weather module first.
    for p in ("look up the forecast", "current weather", "what is the weather today", "weather now"):
        assert metis.is_search_intent(p), f"precondition: {p!r} should trip the search gate"
        assert intent_registry.resolve(p) is not None, f"weather must intercept {p!r} first"


def test_genuine_search_not_claimed_by_weather():
    for p in SEARCH_PHRASES:
        assert intent_registry.resolve(p) is None, f"search query wrongly claimed: {p!r}"


def test_forced_search_gate_not_regressed():
    for p in FORCED_SEARCH_PHRASES:
        assert intent_registry.resolve(p) is None, f"forced-search query wrongly claimed: {p!r}"
        assert metis.is_search_intent(p), f"forced-search gate regressed for {p!r}"


def test_hardware_temperature_not_stolen_by_weather():
    # "temperature" is shared vocab; hardware temps belong to system_module.
    for p in ("what's the cpu temperature", "gpu temp right now", "system temps"):
        claim = intent_registry.resolve(p)
        assert claim is None or claim.module != "weather", f"weather stole hardware temp: {p!r}"


def test_weather_output_carries_both_units():
    # °F primary, °C derived numerically at the data layer — not left to the model.
    dual = weather_module._dual_units
    assert dual("It's 78°F right now") == "It's 78°F (26°C) right now"
    assert dual("32°F") == "32°F (0°C)"
    assert dual("-4°F") == "-4°F (-20°C)"


def test_weather_module_has_no_apology_language():
    # Zero apology language in the weather module's own output surface.
    src = (REPO / "modules" / "weather_module.py").read_text()
    for bad in ("sorry", "apolog", "unfortunately", "i'm afraid"):
        assert bad not in src.lower(), f"apology language {bad!r} present in weather output"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
