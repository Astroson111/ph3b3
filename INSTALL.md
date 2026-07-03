# Ph3b3 — Installation Guide

## Hardware Requirements

| Component | Minimum | Tested on |
|-----------|---------|-----------|
| GPU | 8 GB VRAM (CUDA) | RTX 4060 Ti 16 GB |
| RAM | 16 GB | 32 GB |
| Storage | 40 GB free | 80 GB free |
| OS | Ubuntu 22.04 | Ubuntu 24.04 |
| Camera | Any V4L2 webcam at `/dev/video0` | OBSBOT Tiny |

A CUDA GPU is required. Hermes3 and LLaVA will not run usably on CPU.

---

## Software Prerequisites

### 1. Python 3.11 or newer

```bash
python3 --version
# If below 3.11:
sudo apt install python3.11 python3.11-venv
```

### 2. Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull hermes3
ollama pull llava          # required for vision tools
```

### 3. Piper TTS binary

```bash
sudo apt install pipx
pipx install piper-tts
# Verify:
piper --version
```

### 4. System audio and camera libraries

`setup.sh` handles these, but if you run into issues:

```bash
sudo apt install ffmpeg portaudio19-dev python3-pyaudio libsndfile1 v4l-utils
```

### 5. Tailscale (recommended for remote access)

Tailscale creates an encrypted mesh between your devices so Ph3b3 stays on
your LAN while your phone or laptop can reach her from anywhere — no port
forwarding, no public IP required.

```bash
# Install on the Ph3b3 host
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Get the mesh IP — always a 100.x.x.x address
tailscale ip -4

# Enable on boot
sudo systemctl enable --now tailscaled
```

Install the Tailscale app on each client device (phone, laptop) and sign in
with the same account. All devices on the account can reach each other over
the mesh automatically.

**Privacy note:** Tailscale's coordination servers handle key exchange, but
traffic between your devices is encrypted end-to-end and never passes through
Tailscale's infrastructure.

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/Astroson111/ph3b3 ph3b3_v2
cd ph3b3_v2
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env          # fill in your values — see .env.example for details
```

Key values to set:

| Variable | Required | Notes |
|---|---|---|
| `PH3B3_USER` | Yes | Username for web UI basic auth |
| `PH3B3_PASSWORD` | Yes | Password for web UI basic auth |
| `PH3B3_OWM_KEY` | For weather | OpenWeatherMap free tier |
| `PH3B3_SSL_CERT` / `PH3B3_SSL_KEY` | For HTTPS | See `.env.example` for `openssl` command |

### 3. Run setup

```bash
chmod +x setup.sh
./setup.sh
```

This creates a `.venv`, installs all Python dependencies, and installs system
packages via `apt`.

It also seeds `soul/soul.md` from `soul/soul_public.md` if the file doesn't
already exist. `soul/soul.md` is Ph3b3's identity document — gitignored and
never committed. Re-running `setup.sh` will not overwrite a `soul.md` you
have already customised.

### 4. Download the voice model

Ph3b3 uses Piper with the `en_GB-alba-medium` voice.

```bash
mkdir -p ~/ph3b3_data/voices
cd ~/ph3b3_data/voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json
```

To use a different voice, set `PH3B3_VOICE_MODEL` in `.env` to the full path
of your `.onnx` file.

### 5. Start the server

```bash
chmod +x start.sh
./start.sh
```

`start.sh` will:
- Check for a `.env` file and warn if missing
- Start Ollama if it isn't already running
- Activate the venv
- Launch `agent/server.py` on the configured host and port

On first run (before `~/ph3b3_data/setup_complete` exists), the server opens
a first-time setup wizard at `http://<host>:7331/setup`.

---

## Accessing the Web UI

Once the server is running, the recommended path is via Tailscale Serve
(see Remote Access below). For direct LAN access:

```
https://<host-ip>:7331/panel
```

If `PH3B3_PASSWORD` is set in `.env`, the browser will prompt for HTTP basic
auth. The username is whatever you set as `PH3B3_USER`.

To find your host IP:

```bash
hostname -I
```

`launch_ui.sh` launches a local desktop terminal chat window (not the server):

```bash
./launch_ui.sh
```

---

## Running as a systemd Service

For automatic startup on boot with restart-on-failure, install the included
service file.

> **Note:** `ph3b3.service` ships with placeholder paths
> (`User=youruser`, `WorkingDirectory=`, `EnvironmentFile=`). Edit these to match
> your username and clone location before copying. `ExecStart` references
> `${PH3B3_HOME}`, which systemd loads from the `EnvironmentFile`, so also set
> `PH3B3_HOME=` (your clone path) in your `.env`.

```bash
# Edit the service file for your paths first
nano ph3b3.service

# Install and enable
sudo cp ph3b3.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ph3b3
```

To allow managing the service without a password prompt (used internally by
Ph3b3):

```bash
# Edit 51-ph3b3.rules — replace "youruser" with your username
nano 51-ph3b3.rules
sudo cp 51-ph3b3.rules /etc/polkit-1/rules.d/
```

Check logs:

```bash
journalctl -u ph3b3 -f
```

---

## Remote Access via Tailscale

Once Tailscale is installed (§5 above), reach Ph3b3 from any device on your
mesh using the `100.x.x.x` address:

```
https://100.x.x.x:7331/panel
```

For a clean HTTPS experience without a cert warning, use **Tailscale Serve**
to front Ph3b3 with a Tailscale-managed certificate:

```bash
tailscale serve https / http://localhost:7331
```

This exposes Ph3b3 on your mesh at `https://<machine-name>.<tailnet>.ts.net`
with a valid cert — required for the panel's service worker to register
cleanly for Add to Home Screen.

---

## Verify It's Working

```bash
curl http://localhost:7331/health
```

Expected:

```json
{"status": "alive"}
```

For a richer readiness check (model loaded, soul, TTS, STT):

```bash
curl -u <user>:<pass> https://localhost:7331/ready
```

---

## Firmware: Dio (Ph3b3-Chan, M5Stack CoreS3)

Dio runs the **Ph3b3-Chan** firmware. The source lives in `firmware/Ph3b3-Chan/`.

> **Flash with Arduino IDE only.** A `platformio.ini` is present in `firmware/`
> but PlatformIO produces a truncated binary for this board. Do not use
> `pio run`.

### 1. Credentials

```bash
cp firmware/Ph3b3-Chan/secrets.example.h firmware/Ph3b3-Chan/secrets.h
```

Edit `secrets.h` and fill in:

| Define | Value |
|---|---|
| `SC_PH3B3_USER` | Your `PH3B3_USER` from `.env` |
| `SC_PH3B3_PASS` | Your `PH3B3_PASSWORD` from `.env` |

### 2. Server hostname

Ph3b3-Chan's server address is hardcoded in two places — edit both before
flashing to match your Tailscale hostname:

- `firmware/Ph3b3-Chan/TalkApp.h` — `TalkApp::HOST` (around line 876)
- `firmware/Ph3b3-Chan/Ph3b3-Chan.ino` — the `http.begin(...)` call (line 138)

Replace `ph3b3.<tailnet>.ts.net` with your own `<device>.<tailnet>.ts.net`.

### 3. WiFi

WiFi credentials can be provisioned two ways:
- **Before flash:** set `SC_WIFI_SSID` and `SC_WIFI_PASS` in `Ph3b3-Chan.ino`
  (lines 25–26)
- **After flash:** add networks from Ph3b3's Control Panel Networks tab — Dio
  pulls them from Ph3b3 automatically on next connect

### 4. Flash

Open `firmware/Ph3b3-Chan/Ph3b3-Chan.ino` in Arduino IDE.

Board: **M5Stack → M5Stack-CoreS3**

Add the M5Stack boards URL in Arduino IDE preferences if not already present:
```
https://static-cdn.m5stack.com/resource/arduino/package_m5stack_index.json
```

Required libraries (Arduino IDE Library Manager):

| Library | Manager name |
|---|---|
| M5Unified | `M5Unified` |
| ArduinoJson | `ArduinoJson` |
| StackChan-BSP | `StackChan-BSP` (by M5Stack) |

All other dependencies (`WiFiClientSecure`, `HTTPClient`, `Preferences`, `SD`,
`WebServer`, `DNSServer`) are bundled with the `m5stack:esp32` core and require
no separate install.

Flash via Sketch → Upload.

---

## Firmware: Iris (M5StickS3)

Iris is a **separate project** — her source lives at `~/Arduino/Iris/` and is
**not included in this repository**.

### Install arduino-cli (one-time)

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=~/.local/bin sh
~/.local/bin/arduino-cli config init
~/.local/bin/arduino-cli config add board_manager.additional_urls \
    https://static-cdn.m5stack.com/resource/arduino/package_m5stack_index.json
~/.local/bin/arduino-cli core update-index
~/.local/bin/arduino-cli core install m5stack:esp32
~/.local/bin/arduino-cli lib install M5Unified M5GFX "M5Stack_Avatar" "WiFiManager"
```

### Credentials

```bash
cp ~/Arduino/Iris/secrets.example.h ~/Arduino/Iris/secrets.h
```

Edit `secrets.h` and fill in:

| Define | Value |
|---|---|
| `PH3B3_AUTH_USER` | Your `PH3B3_USER` from `.env` |
| `PH3B3_AUTH_PASS` | Your `PH3B3_PASSWORD` from `.env` |

### Compile and flash

Put Iris into download mode: hold the side button ~2 seconds until the green
LED blinks.

```bash
~/.local/bin/arduino-cli compile --fqbn m5stack:esp32:m5stack_sticks3 ~/Arduino/Iris
~/.local/bin/arduino-cli upload --fqbn m5stack:esp32:m5stack_sticks3 -p /dev/ttyACM0 ~/Arduino/Iris
```

---

## Morpheus / Image Generation

Morpheus generates images locally via ComfyUI running on the same GPU as
Ph3b3. Ph3b3 starts and stops ComfyUI on demand — it does **not** run at all
times.

### Prerequisites

ComfyUI must be installed at `~/Desktop/comfyui` with its own Python venv
(this is where `comfyui.service` expects it). Full ComfyUI setup — model
download, SDXL checkpoint, custom nodes — is covered by the upstream ComfyUI
documentation. Confirm `python main.py --listen 127.0.0.1 --port 8188` runs
cleanly there before installing the service.

### Install the service

Edit `comfyui.service` to set your username and verify the `WorkingDirectory`
path, then:

```bash
nano comfyui.service       # update User= and WorkingDirectory=
sudo cp comfyui.service /etc/systemd/system/
sudo systemctl daemon-reload
# Do NOT enable for auto-start — Ph3b3 manages the lifecycle on demand
```

Install the polkit rule so Ph3b3 can start/stop the service without sudo:

```bash
# Edit to replace "youruser" with your username
nano 50-comfyui.rules
sudo cp 50-comfyui.rules /etc/polkit-1/rules.d/
```

### Verify

```bash
systemctl start comfyui
curl http://localhost:8188/system_stats    # should return JSON
systemctl stop comfyui
```

---

## Troubleshooting

**Ollama not responding** — run `ollama serve` in a separate terminal and
check `ollama list` shows `hermes3`.

**No audio output** — check `pactl list short sinks` for your speaker's name.
Set `PH3B3_SPEAKER_SINK` in `.env` to a unique substring of the sink name.

**Camera not found** — check `ls /dev/video*`. If the webcam isn't at
`/dev/video0`, vision tools will fail silently.

**Spotify tools not working** — Spotify integration is currently
**experimental and non-functional** (credentials need re-setup after a token
rotation). Do not rely on it.

**Soul: missing on the status panel** — `soul/soul.md` is gitignored and not
included in the repo. Run `./setup.sh` to seed it automatically, or copy
manually:

```bash
cp soul/soul_public.md soul/soul.md
```

**Dio / Ph3b3-Chan not connecting** — check the serial monitor at 115200 baud
for `[wifi]` and `[http]` log lines. Confirm `SC_PH3B3_USER` / `SC_PH3B3_PASS`
in `secrets.h` match your `.env`, and that the hardcoded Tailscale hostname in
`TalkApp.h` is correct for your tailnet.

**Iris not connecting** — check serial at 115200. If she opens `Iris-Setup`
(captive portal), connect to that AP and provision her Ph3b3 address and
credentials. If she shows a sad expression after a previously working
configuration, verify Ph3b3's `/health` endpoint is reachable from the same
network.
