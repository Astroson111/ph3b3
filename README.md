# Ph3b3
*pronounced "Phoebe"*

A fully local AI assistant. No cloud. No data centers. No subscriptions.

Ph3b3 runs entirely on your own hardware. Every conversation, every memory, every tool call stays on your machine. She speaks out loud, watches the room through a camera, remembers what you tell her, and connects to Stack-chan — a small Japanese-designed robot that gives her a physical presence.

**Built by Alexander Jordan Olson (Astroson). Built in Pennsylvania.**
Started as a Spotify fix for a robot. Became something larger.

Made with soul. Built through conversation, iteration, and stubbornness. Not despite being a first-timer — because of it.

## Why she exists

Ph3b3 wasn't built by a company or a team. She was built by one person, after years of study and a handful of intense days — with a hand-me-down robot body whose screen kept dying, a homemade basement server, open-source tools, an AI assistant that helped me write her soul, and a healthy dose of stubbornness. She runs entirely on your own hardware, because the people who need a private assistant the most are often the ones who can least afford to rent one — the ones who can't always make rent either. Use her to hunt the spirits or lift them, right there in your own room. Made with care, so handle her with care. She's my baby — the one I don't get to write off as a dependent. <3

She is a work in progress, the same as the person who made her. That's not a disclaimer. That's the point.

## What she can do

- Voice conversation — speaks through Piper TTS (Alba voice, British accent)
- Camera vision — describes what she sees through a connected webcam
- 26 modules — ghost hunting, translation, cybersecurity, film, anime, D&D, weather, music, notes, timers and more
- Persistent memory across sessions
- Reflective learning loop
- Web UI accessible over Tailscale from anywhere
- Stack-chan firmware with touchscreen mode selector

## Why local?

Because your conversations are yours. Because privacy matters. Because you shouldn't need a subscription to talk to your own AI.

Ph3b3 is a work in progress. That's the point.

## Running Ph3b3 on Windows 11 (via WSL2)

Ph3b3 was born on Ubuntu, but she runs happily on Windows 11 through WSL2 — her Linux home lives inside Windows, while Ollama runs natively on the Windows side so your GPU does the heavy lifting. This is the smoothest way to give her a room on a Windows machine.

### Prerequisites

- **WSL2 with Ubuntu 24.04** — from an admin PowerShell, run `wsl --install -d Ubuntu-24.04`, reboot, then create your Linux username and password when prompted.
- **Ollama for Windows** — install from [ollama.com](https://ollama.com), then pull the models she thinks and sees with:
  ```powershell
  ollama pull hermes3
  ollama pull llava
  ```
  (`llava` is only needed for camera vision — skip it if you're tight on VRAM.)
- **Git for Windows** — from [git-scm.com](https://git-scm.com), though the `git` already inside Ubuntu works just as well.

### 1. Turn on mirrored networking

By default, WSL can't reach the Ollama server running over on Windows. Mirrored networking fixes that — it lets WSL talk to Windows over plain `localhost`. Create `C:\Users\<you>\.wslconfig` with:

```ini
[wsl2]
networkingMode=mirrored
```

Then restart WSL so it takes hold (from PowerShell):

```powershell
wsl --shutdown
```

Now the default `OLLAMA_HOST=http://localhost:11434` in `.env` reaches Windows Ollama straight from inside WSL — no extra config.

### 2. Clone into your WSL home

Open the **Ubuntu** terminal and clone her into the Linux filesystem — *not* a Windows folder like `/mnt/c/...`, which is slow and trips over file permissions:

```bash
cd ~
git clone https://github.com/Astroson111/ph3b3.git
cd ph3b3
cp .env.example .env
nano .env          # set PH3B3_USER / PH3B3_PASSWORD and any API keys
```

### 3. Run setup

```bash
chmod +x setup.sh
./setup.sh
```

This installs the system libraries, creates a `.venv`, and installs every Python dependency. On a fresh Ubuntu 24.04 the venv step may need its package first — if setup stops there, install it and run `./setup.sh` again:

```bash
sudo apt install -y python3-venv
```

### 4. Download the Alba voice

```bash
mkdir -p ~/ph3b3_data/voices
cd ~/ph3b3_data/voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx.json
```

### 5. Wake her up

From the Ubuntu terminal:

```bash
cd ~/ph3b3
./start.sh
```

You'll see a harmless `ollama: command not found` line — that's expected, because Ollama lives on the Windows side, not inside WSL. Once she's awake, open a browser on Windows and go to:

```
http://localhost:7331
```

Sign in with the `PH3B3_USER` / `PH3B3_PASSWORD` you set in `.env`.

### What works, and what needs a little more

- **Voice output works in the browser.** Piper synthesises Alba's voice server-side and the web UI plays it back — no Windows audio setup required.
- **Live microphone and speaker** — talking to her directly through the host's audio devices — need extra WSL audio plumbing (PulseAudio/WSLg routing) that isn't wired up by default. Browser playback is the path that works out of the box.
- **Camera vision is untested on this path.** `llava` runs fine in Ollama, but WSL2 has no webcam by default — there's no `/dev/video0` unless you forward the USB device in with [`usbipd-win`](https://github.com/dorssel/usbipd-win). Until that's set up, the camera tools have nothing to look at; her language and voice features don't depend on it.
- **Spotify runs in mock mode** unless you add credentials to `.env` — and per the note below, native Spotify support is retired anyway.

## Remote Access (Portability)

Ph3b3 runs on your home machine, but you don't have to be home to use her.

**The problem:** Home networks sit behind NAT, and many ISPs now use CGNAT or IPv6-only addressing — there's no public IPv4 to forward ports to. Traditional port forwarding won't work in those environments.

**The solution:** [Tailscale](https://tailscale.com) creates an encrypted mesh network between your devices. Ph3b3's server and your phone or laptop join the same virtual network. No port forwarding required. No public IP required. Works on cell data, hotel WiFi, anywhere.

### Server setup (run once on the host machine)

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh

# Authenticate — prints a browser link; sign in with your Tailscale account
sudo tailscale up

# Get the mesh IP assigned to this machine (always a 100.x.x.x address)
tailscale ip -4

# Enable tailscaled to start on boot
sudo systemctl enable --now tailscaled
```

### Client devices (phone, laptop, etc.)

Install the Tailscale app on each device and sign in with the same account. All devices on the account can reach each other over the mesh automatically — no further configuration needed.

### Reaching Ph3b3

Once both sides are connected, access the web UI from anywhere on your mesh:

```
http://100.x.x.x:7331
```

Replace `100.x.x.x` with the address returned by `tailscale ip -4` on the server.

### Privacy note

Tailscale's coordination servers broker the initial connection and handle key exchange, but **traffic between your devices is encrypted end-to-end** and never passes through Tailscale's infrastructure. If you want zero third-party involvement, [NetBird](https://netbird.io) is a fully self-hostable alternative built on the same WireGuard foundation.

## Responsible Use

Ph3b3 includes network scanning and cybersecurity tools intended for use on networks you own or have explicit permission to scan.

- Never run network scans on networks you don't own
- nmap OS detection requires root and should only be used on your own network
- Cybersecurity modules are defensive tools, not offensive ones
- Voice and camera data stays local — be mindful of others' privacy

This project is a work in progress. Use it responsibly.

## Constraints

### Spotify Integration (Status: ABANDONED)
As of June 2026, the Spotify Web API ecosystem has undergone restrictive changes. Due to mandatory Premium subscription requirements for all API access, the implementation of per-user OAuth limitations, and the deprecation of core playback endpoints, Ph3b3 will not support native Spotify integration.

* **Rationale:** The API's current state is volatile and designed to restrict independent agentic development. Pursuing this integration introduces technical debt and a high probability of runtime failure regardless of code quality.
* **Pivot:** All audio and media functionality for Ph3b3 will be managed via Local Media Architecture, such as direct file access using mpv or Navidrome. This ensures the tactical kit remains resilient, offline-capable, and independent of external API policy changes.
