import subprocess
import logging
import requests
from datetime import datetime

log = logging.getLogger("ph3b3.weather")

# Uses wttr.in — no API key, curl-based, works offline-friendly
# Also supports OpenWeatherMap if you have a free key

OWM_API_KEY = ""  # Optional: set env PH3B3_OWM_KEY for better data
DEFAULT_LOCATION = "Shippensburg,PA"

class WeatherModule:
    def __init__(self):
        import os
        self.owm_key = os.getenv("PH3B3_OWM_KEY", OWM_API_KEY)
        log.info("Weather module ready.")

    def current(self, location=None):
        loc = location or DEFAULT_LOCATION
        try:
            result = subprocess.run(
                ["curl", "-s", f"wttr.in/{loc.replace(' ','+')}?format=3"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip() or "Could not get weather."
        except Exception as e:
            return f"Weather error: {e}"

    def forecast(self, location=None):
        loc = location or DEFAULT_LOCATION
        try:
            result = subprocess.run(
                ["curl", "-s", f"wttr.in/{loc.replace(' ','+')}?format=%l:+%c+%t+%h+humidity+%w+wind"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip() or "Could not get forecast."
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
