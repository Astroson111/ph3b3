# Ph3b3 — Installation Guide

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | RTX 3060 8 GB VRAM | RTX 4060+ |
| RAM | 16 GB | 32 GB |
| Storage | 40 GB free | 80 GB free |
| OS | Ubuntu 22.04 | Ubuntu 24.04 |
| Camera | Any V4L2 webcam at `/dev/video0` | OBSBOT Tiny |

A GPU is required. Hermes3 and LLaVA will not run usably on CPU.

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
sudo apt install ffmpeg portaudio19-dev python3-pyaudio libsndfile1 v4l-utils aplay
```

### 5. WireGuard (optional — for remote access)

```bash
sudo apt install wireguard
# Place your wg0.conf in /etc/wireguard/
sudo wg-quick up wg0
```

---

## Installation

### 1. Clone the repo

```bash
git clone <repo-url> ph3b3_v2
cd ph3b3_v2
```

### 2. Configure environment

```bash
cp .env.example .env
nano .env          # fill in your values — see .env.example for details
```

### 3. Run setup

```bash
chmod +x setup.sh
./setup.sh
```

This creates a `.venv`, installs all Python dependencies, and installs system packages via `apt`.

### 4. Download the voice model

Ph3b3 uses Piper with the `en_GB-alba-medium` voice.

```bash
mkdir -p ~/ph3b3_data/voices
cd ~/ph3b3_data/voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json
```

To use a different voice, set `PH3B3_VOICE_MODEL` in `.env` to the full path of your `.onnx` file.

### 5. Start the server

```bash
chmod +x start.sh
./start.sh
```

On first run, `start.sh` will:
- Bring up WireGuard (`wg0`) if configured
- Start Ollama if it isn't running
- Activate the venv
- Launch `agent/server.py` on the configured host and port

---

## Accessing the Web UI

Once the server is running, open a browser and go to:

```
http://<nyx-ip>:7331
```

If `PH3B3_PASSWORD` is set in `.env`, the browser will prompt for HTTP basic auth. Username is `astroson`.

To find Nyx's IP:

```bash
hostname -I
```

The web UI (`launch_ui.sh`) can also be launched as a local desktop window:

```bash
./launch_ui.sh
```

---

## Verify It's Working

```bash
curl http://localhost:7331/health
```

Expected response:

```json
{"status": "alive", "model": "hermes3", "soul": true, "boot": 0}
```

---

## Stack-chan (M5Stack CoreS3)

The firmware lives in `firmware/`. Flash it with PlatformIO:

```bash
cd firmware
pio run -e m5stack-cores3 --target upload
```

The robot connects to Ph3b3 over WebSocket at `ws://<nyx-ip>:7331/ws/stackchan`. Edit `firmware/src/main.cpp` to set `PH3B3_HOST`, `WIFI_SSID`, and `WIFI_PASSWORD` before flashing.

---

## Troubleshooting

**Ollama not responding** — run `ollama serve` in a separate terminal and check `ollama list` shows `hermes3`.

**No audio output** — check `aplay -l` for your device. Set `ALSA_DEFAULT_DEVICE` if needed.

**Camera not found** — check `ls /dev/video*`. If the webcam isn't at `/dev/video0`, vision tools will fail silently.

**Spotify tools not working** — Spotify credentials must be set in `.env`. On first use, a browser window will open to complete OAuth. Run the server in a terminal with a display available (`DISPLAY=:0`).

**Permission denied on `wg-quick`** — WireGuard needs sudo. Either run `start.sh` with sudo or add a sudoers rule for `wg-quick`.
