# Integrations

This folder is where third-party device and service integrations live.

Each subfolder contains the code, config, and documentation for connecting that device or service to Ph3b3. Integrations are optional — the core system runs without any of them.

## Current

| Integration | Status |
|-------------|--------|
| flipper_zero | Planned |

## Adding an integration

Create a subfolder with the device or service name. Include at minimum:
- A `README.md` describing what it does and how to set it up
- Any scripts or modules needed to make it work

If the integration adds new tools to Ph3b3, follow the module pattern in `modules/` and wire them into `agent/server.py`.
