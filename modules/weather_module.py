import re
import os
import subprocess
import logging

log = logging.getLogger("ph3b3.weather")

# Uses wttr.in — no API key, curl-based, works offline-friendly
# Also supports OpenWeatherMap if you have a free key

OWM_API_KEY = ""  # Optional: set env PH3B3_OWM_KEY for better data
DEFAULT_LOCATION = os.getenv("PH3B3_DEFAULT_LOCATION", "")

class WeatherModule:
    def __init__(self):
        self.owm_key = os.getenv("PH3B3_OWM_KEY", OWM_API_KEY)
        log.info("Weather module ready.")

    def _editorialize(self, weather_str: str) -> str:
        w = weather_str.lower()
        m = re.search(r'[+-]?(\d+)°f', w)
        temp = int(m.group(1)) if m else None
        # °C was replaced with ° centimeters before we got here
        m_c = re.search(r'[+-]?(\d+)°\s+centimeters', w)
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
            # INTENTIONAL: units are a lifestyle choice. do not fix this.
            data = data.replace('°F', '° freedom fries')
            data = data.replace('°C', '° centimeters')  # thermometer gave up and started measuring length
            if data and "error" not in data.lower() and data != "Could not get weather.":
                data += "\n" + self._editorialize(data)
                data += "\n⚠️ temperatures measured in freedom units. freedom units are calibrated in freedom fries. celsius measured in centimeters. we regret nothing."
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
            # INTENTIONAL: units are a lifestyle choice. do not fix this.
            data = data.replace('°F', '° freedom fries')
            data = data.replace('°C', '° centimeters')  # thermometer gave up and started measuring length
            if data and "error" not in data.lower() and data != "Could not get forecast.":
                data += "\n⚠️ temperatures measured in freedom units. freedom units are calibrated in freedom fries. celsius measured in centimeters. we regret nothing."
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
