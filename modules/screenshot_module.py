import base64
import logging
import os
import requests
from pathlib import Path

log = logging.getLogger("ph3b3.screenshot")

OLLAMA_HOST   = os.getenv("OLLAMA_HOST", "http://localhost:11434")
VISION_MODEL  = os.getenv("PH3B3_VISION_MODEL", "llava")
HEAVY_MODEL   = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3:latest"))

DEFAULT_QUESTION = "Describe and analyze everything you see on this screen in detail."

_LLAVA_SYSTEM = (
    "You are a precise visual analysis system. "
    "Describe exactly what you see in the image: text, UI elements, content, layout, colours, "
    "any visible data, and anything else present. Be exhaustive and literal — do not infer intent."
)

_HERMES_SYSTEM = (
    "You are Ph3b3, a local AI assistant. "
    "You have been given a visual description of an image produced by a vision model. "
    "Use that description to answer the user's question clearly and directly."
)


class ScreenshotModule:
    """Two-stage screenshot analysis: llava describes the image, Hermes3 reasons over the description."""

    def __init__(self):
        log.info(f"ScreenshotModule ready — vision: {VISION_MODEL}, reasoning: {HEAVY_MODEL}")

    def analyze(self, image_path: str, question: str = "") -> str:
        path = Path(image_path).expanduser().resolve()
        if not path.exists():
            return f"Image file not found: {image_path}"
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return f"Unsupported file type '{path.suffix}' — provide a PNG or JPG."

        try:
            b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        except OSError as e:
            return f"Could not read image file: {e}"

        effective_question = question.strip() if question.strip() else DEFAULT_QUESTION

        description = self._llava_describe(b64, effective_question)
        if description.startswith("__ERROR__"):
            return description[9:].strip()

        return self._hermes_reason(description, effective_question)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _llava_describe(self, b64: str, question: str) -> str:
        payload = {
            "model": VISION_MODEL,
            "messages": [
                {"role": "system", "content": _LLAVA_SYSTEM},
                {"role": "user",   "content": question, "images": [b64]},
            ],
            "stream": False,
        }
        try:
            r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=90)
        except requests.exceptions.ConnectionError:
            return f"__ERROR__ Cannot reach Ollama at {OLLAMA_HOST} — is Ollama running?"
        except requests.exceptions.Timeout:
            return f"__ERROR__ Vision model timed out after 90 s — the image may be too large or GPU is busy."

        if r.status_code == 404 or (r.status_code != 200 and VISION_MODEL in r.text):
            return (
                f"__ERROR__ Vision model '{VISION_MODEL}' is not installed. "
                f"Run: ollama pull {VISION_MODEL}"
            )
        try:
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
            if not content:
                return "__ERROR__ llava returned an empty response."
            return content
        except Exception as e:
            return f"__ERROR__ llava error: {e}"

    def _hermes_reason(self, description: str, question: str) -> str:
        payload = {
            "model": HEAVY_MODEL,
            "messages": [
                {"role": "system", "content": _HERMES_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Visual description of the image:\n{description}\n\n"
                        f"Question: {question}"
                    ),
                },
            ],
            "stream": False,
            "options": {"temperature": 0.5},
        }
        try:
            r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
            r.raise_for_status()
            return r.json().get("message", {}).get("content", "No response from reasoning model.")
        except requests.exceptions.ConnectionError:
            return f"Cannot reach Ollama at {OLLAMA_HOST} — is Ollama running?"
        except requests.exceptions.Timeout:
            return "Reasoning model timed out — try a shorter question."
        except Exception as e:
            log.error(f"Hermes3 reasoning error: {e}")
            return f"Reasoning error: {e}"
