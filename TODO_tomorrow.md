# Ph3b3 — TODO Tomorrow
_Generated 2026-06-14 end-of-day. Audit only — no code changed._

---

## CRITICAL

| # | Description | Location | Notes |
|---|-------------|----------|-------|
| C1 | **Audio routing — hardware decision required before code can proceed** | `modules/tts_module.py · _resolve_audio_device()` | USB Audio card (vendor MSI 0x0db0 · `alsa_card.usb-Generic_USB_Audio-00`) exposes only iec958/digital profiles; every analog profile reports `available: no`. `_resolve_audio_device()` correctly finds the USB sink but it's S/PDIF — inaudible on most speakers. Current PipeWire default has drifted back to HDMI (`alsa_output.pci-0000_01_00.1.hdmi-stereo`). **Decision needed:** (a) confirm what's physically plugged into what — USB jack, HDMI, or mobo 3.5 mm? (b) pick the target sink by stable name; (c) once chosen, set `PH3B3_AUDIO_DEVICE` in `.env` to lock it. Code is ready — blocked on hardware answer only. |
| C2 | **Piper binary not in PATH under systemd service launch** | `modules/tts_module.py:140,156` | `piper` lives at `.venv/bin/piper` but `shell=True` subprocess invokes it bare (`piper --model …`). The venv is never activated by systemd, so `piper: not found` fires every TTS call when the service manages the process. Boot log confirms: `piper: not found`. Fix: replace `piper` with the absolute path `str(Path(__file__).parent.parent / ".venv" / "bin" / "piper")` or export `PATH` in the `.service` `Environment=` line. |

---

## HIGH

| # | Description | Location | Notes |
|---|-------------|----------|-------|
| H1 | **`tts.soul_line()` undefined — crashes any chat containing "soul"** | `agent/server.py:590,614` | `TTSModule` has no `soul_line` method. Both call sites trigger `AttributeError` the moment a user message includes the word "soul", killing that request. Add the method or remove the calls. |
| H2 | **`synthesize_to_b64` subprocess has no timeout** | `modules/tts_module.py:157` | `subprocess.run(cmd, shell=True, capture_output=True)` — no `timeout=` argument. If piper or the shell hangs, `tts._lock` is held indefinitely, blocking all subsequent TTS (including `/chat` audio synthesis). Audit fixed `_speak_now` but missed this path. Add `timeout=30`. |
| H3 | **Port 7331 bind conflict at next reboot** | `ph3b3.service` | Service is `enabled` (starts at boot) but Ph3b3 is also being launched manually. At next reboot both will race for port 7331; one crashes. Decide: commit to service-only launch (`systemctl start ph3b3`) or `systemctl disable ph3b3` and use `start.sh`. Whichever wins, the other must go. |

---

## MEDIUM

| # | Description | Location | Notes |
|---|-------------|----------|-------|
| M1 | **gcalcli not installed — calendar tool silently broken** | `modules/calendar_module.py:__init__` | Boot log: `gcalcli not found`. All four calendar tools return the install-prompt string at runtime. `pip install gcalcli && gcalcli init` (opens browser for Google OAuth). |
| M2 | **Spotify in MOCK mode — all Spotify tools return fake responses** | `modules/spotify_module.py:__init__` / `.env` | `SPOTIPY_CLIENT_ID` absent from `.env`. Every `spotify_play`, `spotify_control`, `spotify_now_playing` call returns `[MOCK] …` silently. Add Spotify API credentials to `.env` when ready. |
| M3 | **`_resolve_audio_device()` side-effects at import time** | `modules/tts_module.py:109` | Called at module level; fires `pactl set-default-sink` as a side-effect before the server is fully up. On a headless or PipeWire-absent boot the call silently fails and falls back to `"default"`, routing audio nowhere. Move sink-pinning into `TTSModule.__init__` so it runs after logging is live and can report success/failure properly. |
| M4 | **`Requires=ollama.service` but no API readiness check** | `ph3b3.service` | systemd marks ollama "active" when the process starts, not when the HTTP API accepts connections. First `/chat` after reboot can wait up to 120 s (httpx timeout) while hermes3 loads into VRAM. Add an `ExecStartPre=/bin/sh -c 'until curl -sf http://localhost:11434/api/tags; do sleep 2; done'` or reduce the httpx timeout and handle retries gracefully. |

---

## LOW

| # | Description | Location | Notes |
|---|-------------|----------|-------|
| L1 | **Hermes3 tool-loop has no per-tool call cap** | `agent/server.py:chat_with_tools()` | Global loop limit is 5 iterations across all tools, but a single tool can still be called 5× before the fallback fires. The `analyze_screenshot` fix (speak-and-ack) solved that tool specifically; the pattern could recur for any new vision or long-output tool. Consider per-tool call counting. |
| L2 | **`@app.on_event("startup")` deprecation** | `agent/server.py` | Already migrated to `lifespan` — no active issue. Confirm no third-party module registers a stale `on_event` handler (check installed FastAPI plugin versions if warning appears in future logs). |
| L3 | **`ph3b3.service` missing restart guard** | `ph3b3.service` | `Restart=on-failure` with `RestartSec=10` but no `StartLimitIntervalSec` / `StartLimitBurst`. A persistent crash (e.g. CUDA OOM) will restart indefinitely, thrashing the GPU. Add `StartLimitIntervalSec=60` and `StartLimitBurst=3`. |
| L4 | **`start.sh` Ollama launch race** | `start.sh:17-20` | `ollama serve & sleep 3` — 3-second fixed sleep before Ph3b3 starts. On a cold boot with large models this is too short; on a warm boot it's wasted time. Replace with a readiness poll (`until curl -sf localhost:11434/api/tags; do sleep 1; done`). |

---

## Verified Good (ship-state at EOD)

- `/health` → `{"status":"alive"}` — static, no I/O, safe for boot monitoring ✓  
- `/ready` → `boot`, `model`, `soul`, `whisper`, `tts`, `suggestions` all present ✓  
- Web UI boot number displays correctly; suggestion pills render and fire ✓  
- Boot greeting signature "Made with Soul, baby." spoken + logged as single phrase ✓  
- `_speak_now` timeout=30 s, `aplay -l` timeout=5 s — audit fixes intact ✓  
- `tell_joke`, `roast`, `speak` tool handlers all `blocking=False` — event-loop safe ✓  
- Whisper medium loads on CUDA in background thread (~4 s), does not block startup ✓  
