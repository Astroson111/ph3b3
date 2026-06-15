# Ph3b3 Session Log

---

## Session: 2026-06-15 (Nyx — Ubuntu 24.04)

### DONE

**Remote access: WireGuard → Tailscale (complete)**
- Tailscale installed and active on Nyx. Node reachable at `100.x.x.x:7331`.
- WireGuard fully swept: private/public keys deleted, `wg0.conf` removed, `wg0` interface torn down, UFW rule for port 51820 removed.
- HTTPS enabled. Certificate lives at `~/ph3b3_data/ssl/cert.pem`.

**Code: TTS device resolution rewrite (`modules/tts_module.py`)**
- `_resolve_audio_device()` now uses PipeWire-native path first (`pactl list short sinks`), matching by stable sink name fragment `USB_Audio`, excluding fifine/Microphone.
- Legacy ALSA fallback (`aplay -l`) retained for non-PipeWire environments.
- Added `timeout=30` to `_speak_now` subprocess and `timeout=5` to ALSA scan.
- Fallback chain documented in docstring.

**Code: server.py cleanup and `/ready` endpoint**
- Boot greeting consolidated to single `tts.speak()` call; "Made with Soul, baby." appended inline.
- All `tts.speak()` calls in tool handlers converted to `blocking=False`.
- `/health` simplified to `{"status":"alive"}` — static, no I/O, safe for monitors.
- `/ready` added: returns `boot`, `model`, `soul`, `whisper`, `tts`, and `suggestions` list.
- `hermes3` empty-content fallback: when the model exits the tool loop without synthesising text, a lightweight re-prompt is issued against `HEAVY_MODEL` to produce a plain-English summary.
- `analyze_screenshot` handler now speaks the analysis result and returns an ack string (prevents tool-loop spin).

**Code: UI suggestion pills (`static/index.html`)**
- On successful `/ready` response, horizontal scroll row of suggestion buttons rendered below connection message.
- Clicking a pill populates the input and fires send (no-op when busy).

---

### OPEN / UNRESOLVED

**Boot-time audio sink hijack — FIXED (2026-06-15, post-reboot confirmed)**

`pactl get-default-sink` → `alsa_output.pci-0000_01_00.1.hdmi-stereo` after cold reboot. ✅

Fix that worked: `/etc/wireplumber/main.lua.d/51-default-sink.lua` (requires sudo write).
Key lesson: WirePlumber 0.4.17 on Ubuntu 24.04 **ignores** `~/.config/wireplumber/main.lua.d/` entirely. The `/etc/wireplumber/` path is the correct user-override location.

Systemd service audio dependency is now unblocked. Next: tackle C2 (Piper not in PATH).

~~**Boot-time audio sink hijack — NOT FIXED**~~

Problem: USB "Generic USB Audio" IEC958 (S/PDIF) device grabs the PipeWire default sink at every boot. HDMI sink (`alsa_output.pci-0000_01_00.1.hdmi-stereo`) is correct; S/PDIF is silent. User must manually flip the sink back in Sound Settings after every reboot.

Three attempts this session — none persisted:

| Attempt | Method | Result |
|---------|--------|--------|
| 1 | `wpctl set-default` + WirePlumber state | Survived restart, reverted after reboot |
| 2 | `~/.config/wireplumber/main.lua.d/51-default-sink.lua` — deprioritize USB IEC958 (`priority.session = 500`), raise HDMI (`priority.session = 1300`) | **File never loaded** — WirePlumber 0.4 on Ubuntu ignores user `main.lua.d/`; confirmed by HDMI priority remaining 696 |
| 3 | Same file with `device.disabled = true` + `node.disabled = true` (belt-and-suspenders) | Same result — file not loaded, sink still appears |

Root cause of config not loading: WirePlumber 0.4.17 on this Ubuntu 24.04 build does not merge `~/.config/wireplumber/main.lua.d/` into its Lua load path. The correct override path is `/etc/wireplumber/main.lua.d/` (requires sudo). File was written there (`/etc/wireplumber/main.lua.d/51-default-sink.lua`) at end of session — **not yet verified** after reboot.

Attempted rule (archived here for reference):
```lua
-- /etc/wireplumber/main.lua.d/51-default-sink.lua
table.insert(alsa_monitor.rules, {
  matches = {{ { "device.name", "equals", "alsa_card.usb-Generic_USB_Audio-00" } }},
  apply_properties = { ["device.disabled"] = true },
})
table.insert(alsa_monitor.rules, {
  matches = {{ { "node.name", "equals", "alsa_output.usb-Generic_USB_Audio-00.iec958-stereo" } }},
  apply_properties = { ["node.disabled"] = true },
})
table.insert(alsa_monitor.rules, {
  matches = {{ { "node.name", "equals", "alsa_output.pci-0000_01_00.1.hdmi-stereo" } }},
  apply_properties = { ["priority.session"] = 1300 },
})
```

---

### NEXT LEADS (start here tomorrow)

**(a) Verify wireplumber version precisely**
```bash
wireplumber --version
```
- If **0.5.x**: the `main.lua.d/` Lua rule system is deprecated/inert. Rules must be rewritten as `.conf` fragments under `~/.config/wireplumber/wireplumber.conf.d/`. Different syntax entirely.
- If **0.4.x**: the `/etc/wireplumber/main.lua.d/51-default-sink.lua` file written at end of session should be the right path — reboot and test.

**(b) Identify what the "Generic USB Audio" device physically is**
- It is **not** the Fifine microphone (that's a separate device: `alsa_card.usb-3142_fifine_Microphone-00`).
- Suspected candidates: Elgato HD60 S+ capture card, or a USB→optical (S/PDIF) adapter.
- Check: `lsusb | grep -i "0db0\|audio\|elgato"` or physically unplug USB devices one at a time.
- **If you can identify and unplug it permanently**, the entire WirePlumber problem goes away. Simplest fix.

**(c) Fallback if Lua rules still don't work: udev disable**
- Match by USB path/VID:PID in `/etc/udev/rules.d/` to set `ALSA_IGNORE=1`.
- Requires knowing the VID:PID from `lsusb`.

---

### DEPENDENCY (blocked)

**Ph3b3 systemd USER service — audio session inheritance**

The future `ph3b3.service` (Type=user) must have `PIPEWIRE_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` available so that `pactl` / `aplay -D default` resolve to the same PipeWire instance as the desktop session. Without those env vars, TTS will route to whatever PipeWire picks at service start time — which may not be HDMI if the audio sink problem is unsolved.

**This service work is blocked until the boot-time default sink is confirmed stable.**

Do not enable the service until:
1. Reboot → `pactl get-default-sink` shows `alsa_output.pci-0000_01_00.1.hdmi-stereo` without manual intervention.
2. TTS audio plays from monitor speakers without `PH3B3_AUDIO_DEVICE` override.

---

### Outstanding code bugs (see TODO_tomorrow.md for full detail)

| ID | Summary | Severity |
|----|---------|----------|
| C1 | Audio routing — hardware decision (see above) | CRITICAL |
| C2 | Piper binary not in PATH under systemd | CRITICAL |
| H1 | `tts.soul_line()` undefined — AttributeError on "soul" messages | HIGH |
| H2 | `synthesize_to_b64` missing timeout | HIGH (partially fixed this session) |
| H3 | Port 7331 bind conflict: service + manual launch race | HIGH |
| M1 | gcalcli not installed | MEDIUM |
| M2 | Spotify in MOCK mode | MEDIUM |
| M3 | `_resolve_audio_device()` side-effects at import time | MEDIUM |
| M4 | Ollama readiness check missing from service | MEDIUM |
