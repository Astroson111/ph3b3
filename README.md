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

## Control Panel (`/panel`)

Ph3b3 ships a mobile-first PWA served at `https://<nyx>:7331/panel`. It is the local control plane — designed to live on your phone's home screen so you can reach Ph3b3 without opening a terminal.

**What it is:**
The panel is a single self-contained HTML page (CSS and JS fully inline, zero external CDNs or fonts). Everything runs inside your LAN. Nothing phones home. The page is served behind the same basic auth as the rest of Ph3b3.

**Three panes:**
- **Status** — polls `/health` and `/ready` every 10 s. Shows live model name, soul load state, TTS/STT readiness, and boot count.
- **Chat + Voice** — text box → `POST /chat` → displays Ph3b3's reply text and decodes + plays the base64 WAV audio (Alba's voice via Piper). One endpoint, one tap.
- **Devices** — lightweight in-memory last-seen roster. Any authenticated request carrying an `X-Ph3b3-Device` header (e.g. `iris`, `stackchan`) updates the roster. Header-less traffic lands in the `unidentified` bucket. Raw UTC timestamps are shown — no fake "online" badge.

**PWA / Add to Home Screen:**
The panel ships a web manifest (`/static/panel.webmanifest`) and a service worker (`/sw.js`) so Android Chrome will offer "Add to Home Screen". The SW uses network-first for API routes and cache-first for static assets.

**How to open it:**
```
https://<nyx-ip>:7331/panel
```
Accept the self-signed cert warning on first open. Enter your `astroson` credentials when the browser prompts. The browser caches those credentials for the origin, so all subsequent panel fetches are transparent — no credentials hardcoded in the page.

**Service worker note:**
SW registration requires HTTPS. Over a self-signed LAN cert it will register in most Android Chrome versions but may be blocked in stricter browser profiles. The panel loads and works fully even if the SW fails to register — it just won't be installable as a home-screen app in that case.

## Responsible Use

Ph3b3 includes network scanning and cybersecurity tools intended for use on networks you own or have explicit permission to scan.

- Never run network scans on networks you don't own
- nmap OS detection requires root and should only be used on your own network
- Cybersecurity modules are defensive tools, not offensive ones
- Voice and camera data stays local — be mindful of others' privacy

This project is a work in progress. Use it responsibly.
