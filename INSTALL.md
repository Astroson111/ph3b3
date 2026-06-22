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

> **Running on a Windows laptop?** Use the **Windows + WSL2 (Solo)** runbook just
> below — it runs the whole stack self-contained on one machine (validated on an
> ASUS ROG Zephyrus G14, RTX 2060 Max-Q 6 GB). The Linux/native instructions
> further down are for the dedicated "Nyx" box.

---

## Windows + WSL2 (Solo Deployment)

Runs the entire stack self-contained on **one Windows laptop** — no second
machine, no remote inference. Validated on an RTX 2060 Max-Q (6 GB VRAM).

**Architecture on Windows:**
- **Ollama runs on the Windows host** (native CUDA), reached from WSL at
  `http://localhost:11434`.
- **FastAPI, Whisper (whisper.cpp, CPU), and Piper/Alba TTS run inside WSL2 Ubuntu.**
- **WSL2 mirrored networking** makes WSL share the host's LAN IP, so the
  Stack-chan on the network can reach the server.

> **6 GB VRAM reality:** Hermes3 at `num_ctx 8192` already ~saturates 6 GB and
> spills ~29 % to CPU. **Keep Whisper on CPU** (this path uses whisper.cpp via
> `pywhispercpp`, CPU-only) so it never competes with Hermes3 for VRAM. Do **not**
> try to run `medium` Whisper on a 6 GB GPU alongside Hermes3 — it won't fit.

### 0. Host prerequisites (Windows 11)
1. Install WSL2 + Ubuntu: in an elevated PowerShell, `wsl --install -d Ubuntu`.
2. Install the latest **NVIDIA Windows driver** for your GPU. That alone gives
   CUDA inside WSL — **do not** install a CUDA toolkit inside WSL.
3. Install **Ollama for Windows** (<https://ollama.com/download>), then pull models:
   ```powershell
   ollama pull hermes3
   ollama pull llava        # required for vision tools
   ```

### 1. Gate 0 — confirm GPU passthrough (inside WSL)
```bash
wsl -d Ubuntu
nvidia-smi          # must list the GPU and its VRAM
```
If the GPU is **not** listed, stop and fix the host NVIDIA driver — nothing below
works on CPU.

### 2. Enable WSL2 mirrored networking
Create/edit `C:\Users\<you>\.wslconfig` on the **Windows** side:
```ini
[wsl2]
networkingMode=mirrored
```
Then `wsl --shutdown` and reopen Ubuntu. Verify the host IP is shared:
```bash
ip -brief addr      # an ethN should show your host's LAN IP, e.g. 192.168.0.23
```
Mirrored mode means **no `netsh portproxy` is needed**.
*Caveat:* mirrored mode occasionally falls back to `none` on boot (you'll see a
warning). If the device later can't reach the server, `wsl --shutdown` and reopen.

### 3. Clone + Python environment (inside WSL)
```bash
git clone <repo-url> ph3b3 && cd ph3b3
git checkout athena-solo            # the solo-on-Windows branch
sudo apt update && sudo apt install -y ffmpeg     # whisper.cpp decodes audio via ffmpeg
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt         # includes pywhispercpp (prebuilt wheel, no compiler)
```

### 4. Piper + Alba voice (inside WSL)
```bash
sudo apt install -y pipx && pipx install piper-tts
mkdir -p ~/ph3b3_data/voices && cd ~/ph3b3_data/voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json
```

### 5. Configure `.env` (inside WSL)
```bash
cd ~/ph3b3 && cp .env.example .env && nano .env
```
- Set `PH3B3_USER` / `PH3B3_PASSWORD`.
- **`PH3B3_CORS_ORIGINS` must include `file://`** (already in `.env.example`). The
  Stack-chan firmware sends `Origin: file://`; without it the WebSocket handshake
  is rejected (`Rejected WS handshake (origin='file://')`).
- Set `PH3B3_VOICE_MODEL` to the Alba `.onnx` path.
- `PH3B3_WHISPER_MODEL=medium` runs on CPU (~10 s/turn at 16 threads on this CPU
  class). Drop to `small` (~3 s) for speed at some accuracy cost.
  Optional: `PH3B3_WHISPER_THREADS` (defaults to all cores).

### 6. Open the firewall (elevated PowerShell, on the host)
Mirrored mode shares the host IP, but the **Hyper-V firewall blocks inbound by
default**. In an **Administrator** PowerShell:
```powershell
New-NetFirewallRule -DisplayName "Ph3b3 7331" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7331
New-NetFirewallHyperVRule -DisplayName "Ph3b3 7331 mirrored" -Direction Inbound -Action Allow -Protocol TCP -LocalPorts 7331 -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}'
```
The `VMCreatorId` is WSL's; confirm yours with
`Get-NetFirewallHyperVVMSetting -PolicyStore ActiveStore`.

### 7. Start the server (inside WSL)
```bash
cd ~/ph3b3
CUDA_VISIBLE_DEVICES= .venv/bin/python agent/server.py
```
`CUDA_VISIBLE_DEVICES=` keeps the FastAPI process off the GPU (Whisper is CPU;
Ollama on the host owns the GPU). Verify:
```bash
curl -u <user>:<pass> http://localhost:7331/health
```
> You'll see harmless `aplay ... exit 127` / `BrokenPipe` errors at boot — WSL has
> no audio device. The device turn-loop is unaffected: `/chat` returns audio as
> base64 for the device to play; `aplay` is only for server-local playback.

### 8. Flash the Stack-chan (M5Stack CoreS3) — from Windows
Use **PlatformIO on Windows**. **Build OUTSIDE OneDrive** — OneDrive locks files
mid-build and causes `Permission denied` on a random header. Copy `firmware/` to a
local path first, e.g. `C:\pio\ph3b3-fw`.
```powershell
pip install platformio
# In firmware/src/main.cpp set: PH3B3_HOST=<host LAN IP>, WIFI_SSID, WIFI_PASSWORD
python -m platformio run -d C:\pio\ph3b3-fw                 # build
python -m platformio run -d C:\pio\ph3b3-fw -t upload       # flash
```
- Use a **USB-C data cable** (charge-only cables enumerate nothing). The CoreS3
  shows up as a native USB serial device (VID `303A`). If you see only Bluetooth
  COM ports, the cable/port isn't carrying data.
- If upload can't connect, hold the **reset button** to enter download mode.

### 9. Verify end-to-end
- Device boots, joins WiFi, opens the WebSocket to `<host IP>:7331/ws/stackchan`.
  Its screen shows `nyx online` (cosmetic label — it's connected to *this* box).
- Server log shows `Stack-chan connected`.
- Speak → `/transcribe` (whisper.cpp) → `/chat` (Hermes3) → Alba TTS → device plays.

### Windows/WSL troubleshooting
- **`Rejected WS handshake (origin='file://')`** → add `file://` to
  `PH3B3_CORS_ORIGINS` in `.env`, restart the server.
- **Device won't enumerate for flashing** → charge-only cable; use a data cable,
  plug straight into the laptop. Only Bluetooth COM ports present = no data link.
- **PlatformIO `Permission denied` on a header mid-build** → you're building inside
  OneDrive; build from a local path (`C:\pio\...`).
- **Device can't reach the server** → mirrored networking fell back to `none`
  (`wsl --shutdown`, reopen, recheck `ip -brief addr`), or the firewall rule is
  missing.
- **`host → 192.168.x.x:7331` fails from the host itself but the device works** →
  self-hairpin quirk; test reachability from the device, not from the host.

---

## Software Prerequisites (Linux / native — the Nyx box)

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
