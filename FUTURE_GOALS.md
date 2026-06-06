# Future Goals

This file tracks planned integrations, features, and ideas that are not yet implemented.

---

## Integrations

This section was previously housed in `integrations/`. Third-party device and service integrations live here as plans. Each entry describes what it would do and how it would connect to Ph3b3. Integrations are optional — the core system runs without any of them.

### Adding an integration (when ready)

Create a subfolder under `integrations/` with the device or service name. Include at minimum:
- A `README.md` describing what it does and how to set it up
- Any scripts or modules needed to make it work

If the integration adds new tools to Ph3b3, follow the module pattern in `modules/` and wire them into `agent/server.py`.

---

## Voice

### Multilingual TTS

Multilingual TTS — add per-language Piper voice models so Ph3b3 pronounces translations in a native accent (e.g. a Mandarin voice for Chinese output) instead of Alba reading romanization with an English mouth. Swap the voice model based on detected target language.

---

## Flipper Zero Integration

**Status: Planned**

This integration will connect a Flipper Zero to Ph3b3, allowing her to send commands to and receive data from the device over USB or Bluetooth.

### Ideas under consideration

- Trigger Flipper actions via voice command ("Ph3b3, run the subghz scan")
- Receive signal capture data from Flipper and log it to Ph3b3's memory
- Use Flipper as a hardware key or physical trigger for Ph3b3 actions
- Display Ph3b3 responses or alerts on the Flipper screen

### Notes

Nothing is built yet. When work starts, it will live in an `integrations/flipper_zero/` folder alongside any required modules and wiring into `agent/server.py`.

Flipper Zero serial protocol docs: https://docs.flipper.net
