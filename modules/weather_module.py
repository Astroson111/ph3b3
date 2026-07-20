import re
import os
import subprocess
import logging

try:
    import intent_registry
except ImportError:
    from modules import intent_registry

log = logging.getLogger("ph3b3.weather")

# ── Intent claim (precedence over Metis forced search) ────────────────────────
# The weather module OWNS weather/forecast/temperature phrasing. A claimed turn is
# answered here, full stop — even worded as "search the weather" / "look up the
# forecast", which Metis's search-intent detector would otherwise hijack to the
# open web. `exclude` steps this claim aside for HARDWARE temperature (cpu/gpu/
# system temps → system_module), which shares the word but not the domain.
_WEATHER_INTENT_RE = re.compile(
    r"\bweather\b|\bforecast\b|\bhumidity\b|"
    r"\bhow (?:hot|cold|warm|windy) (?:is|will|does|it)\b|"
    r"\bis it (?:going to |gonna )?(?:rain|snow|sleet|storm|hail)\w*\b|"
    r"\bis it (?:hot|cold|sunny|cloudy|windy|raining|snowing|freezing|chilly|warm)\b|"
    r"\b(?:temperature|temp) (?:outside|out there|today|tomorrow|tonight|right now|out)\b|"
    r"\bwhat'?s the (?:temperature|temp)\b|"
    r"\bhow'?s the weather\b",
    re.I,
)
# Hardware temperature is a DIFFERENT domain (system_module). Don't let the weather
# claim swallow "cpu temp" / "gpu temperature" / "system temps".
_HARDWARE_TEMP_RE = re.compile(
    r"\b(?:cpu|gpu|processor|graphics card|system|server|nyx|drive|disk|nvme|battery)\b"
    r"[\w\s]*\btemp\w*\b|\btemp\w*\b[\w\s]*\b(?:cpu|gpu|processor|system|nvme)\b",
    re.I,
)
intent_registry.register("weather", "weather_current", _WEATHER_INTENT_RE,
                         exclude=_HARDWARE_TEMP_RE)

# Uses wttr.in — no API key, curl-based, works offline-friendly
# Also supports OpenWeatherMap if you have a free key

OWM_API_KEY = ""  # Optional: set env PH3B3_OWM_KEY for better data
DEFAULT_LOCATION = os.getenv("PH3B3_DEFAULT_LOCATION", "")

# wttr.in is queried with &u (USCS), so °F is the authoritative reading. °C is
# derived HERE — numeric, rounded to whole degrees — so the LLM never does the
# arithmetic in the hot path. F→C is (F−32)·5/9 (not the ·9/5 reverse direction).
_TEMP_RE = re.compile(r'([+-]?\d+)°F')

def _f_to_c(f: int) -> int:
    return round((f - 32) * 5 / 9)

def _dual_units(text: str) -> str:
    """Rewrite every 'N°F' as 'N°F (M°C)' with M converted numerically."""
    def repl(m):
        f = int(m.group(1))
        return f"{f}°F ({_f_to_c(f)}°C)"
    return _TEMP_RE.sub(repl, text)


class WeatherModule:
    def __init__(self):
        self.owm_key = os.getenv("PH3B3_OWM_KEY", OWM_API_KEY)
        log.info("Weather module ready.")

    def _editorialize(self, weather_str: str) -> str:
        w = weather_str.lower()
        m = re.search(r'[+-]?(\d+)°f', w)
        temp = int(m.group(1)) if m else None
        m_c = re.search(r'[+-]?(\d+)°c', w)
        temp_c = int(m_c.group(1)) if m_c else None

        if any(x in w for x in ("thunderstorm", "thunder", "lightning")):
            return "Fantastic day to be indoors with good Wi-Fi."
        if any(x in w for x in ("tornado", "hurricane", "cyclone")):
            return "Nature is making a point. Stay inside."
        if any(x in w for x in ("blizzard", "heavy snow")):
            return "It's the kind of day that tests your commitment to leaving the house."
        if "freezing rain" in w or "ice pellet" in w:
            return "Everything outside is a trap today."
        if "snow" in w or "sleet" in w:
            return "Great weather if you enjoy suffering quietly."
        if temp is not None and temp >= 95:
            return "Stay hydrated, that's not a suggestion."
        if temp is not None and temp >= 85:
            return "Hot enough that all decisions feel wrong."
        if temp_c is not None and 33 <= temp_c <= 37:
            return "Maybe I should just live in a walk-in fridge."
        if "fog" in w or "mist" in w:
            return "Visibility is optional today. Drive like you know that."
        if any(x in w for x in ("rain", "drizzle", "shower")):
            return "Not ideal, not catastrophic. Just wet."
        if temp is not None and temp <= 20:
            return "That's not cold, that's personal."
        if temp is not None and temp <= 38:
            return "It's the kind of cold that has opinions."
        if any(x in w for x in ("sunny", "clear")):
            if temp is not None and 60 <= temp <= 80:
                return "Good day. Don't waste it."
            return "Nice enough to be almost suspicious."
        if any(x in w for x in ("overcast", "cloudy")):
            return "The sky is doing the absolute bare minimum."
        if "wind" in w:
            return "It's breezy in a way that takes it personally."
        return "Weather exists. You're in it."

    def current(self, location=None):
        loc = location or DEFAULT_LOCATION
        if not loc:
            return "I don't know your location — tell me where you are, or set PH3B3_DEFAULT_LOCATION in .env."
        try:
            result = subprocess.run(
                ["curl", "-s", f"wttr.in/{loc.replace(' ','+')}?format=%l:+%c+%C,+%t&u"],
                capture_output=True, text=True, timeout=10
            )
            data = result.stdout.strip() or "Could not get weather."
            if data and "error" not in data.lower() and data != "Could not get weather.":
                data = _dual_units(data)          # °F primary, °C derived numerically
                data += "\n" + self._editorialize(data)
            return data
        except Exception as e:
            return f"Weather error: {e}"

    def forecast(self, location=None):
        loc = location or DEFAULT_LOCATION
        if not loc:
            return "I don't know your location — tell me where you are, or set PH3B3_DEFAULT_LOCATION in .env."
        try:
            result = subprocess.run(
                ["curl", "-s", f"wttr.in/{loc.replace(' ','+')}?format=%l:+%c+%C,+%t+%h+humidity+%w+wind&u"],
                capture_output=True, text=True, timeout=10
            )
            data = result.stdout.strip() or "Could not get forecast."
            if data and "error" not in data.lower() and data != "Could not get forecast.":
                data = _dual_units(data)          # °F primary, °C derived numerically
            return data
        except Exception as e:
            return f"Weather error: {e}"

    def good_for_ghost_hunting(self, location=None):
        current = self.current(location)
        advice = []
        w = current.lower()
        if "rain" in w or "storm" in w:
            advice.append("Rain can affect EMF equipment. Protect your gear.")
        if "fog" in w:
            advice.append("Fog creates orb false positives on camera. Note this in your log.")
        if "clear" in w or "sunny" in w:
            advice.append("Good visibility conditions. Minimal interference expected.")
        if "wind" in w:
            advice.append("Wind may cause audio contamination in EVP sessions.")
        base = f"Current: {current}"
        if advice:
            base += "\n\nField notes:\n" + "\n".join(advice)
        return base
