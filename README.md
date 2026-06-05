# Ph3b3
*pronounced "Phoebe"*

A fully local AI assistant. No cloud. No data centers. No subscriptions.

Ph3b3 runs entirely on your own hardware. Every conversation, every memory, every tool call stays on your machine. She speaks out loud, watches the room through a camera, remembers what you tell her, and connects to Stack-chan — a small Japanese-designed robot that gives her a physical presence.

**Built by Alexander Jordan Olson (Astroson)**
Built in Pennsylvania. Started as a Spotify fix for a robot. Became something larger.

Made with soul. Built through conversation, iteration, and stubbornness. Not despite being a first-timer — because of it.

## What she can do

- Voice conversation — speaks through Piper TTS with a Welsh accent
- Camera vision — describes what she sees through a connected webcam
- 23 modules — ghost hunting, translation, cybersecurity, film, anime, D&D, weather, music, notes, timers and more
- Persistent memory across sessions
- Reflective learning loop
- Web UI accessible over WireGuard from anywhere
- Stack-chan firmware with touchscreen mode selector

## Why local?

Because your conversations are yours. Because privacy matters. Because you shouldn't need a subscription to talk to your own AI.

Ph3b3 is a work in progress. That's the point.

## Remote Access (Portability)

Ph3b3 runs on your home machine, but you don't have to be home to use her.

**The problem:** Home networks are usually behind NAT, and many ISPs now use CGNAT or IPv6-only addressing — meaning there's no public IPv4 to forward ports to. Traditional port forwarding won't work in those environments.

**The solution:** [Tailscale](https://tailscale.com) creates an encrypted mesh network between your devices. Ph3b3's server and your phone/laptop join the same virtual network. No port forwarding required. No public IP required. Works on cell data, hotel WiFi, anywhere.

### Server setup (run once on Nyx)

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh

# Authenticate — opens a browser link; sign in with your Tailscale account
sudo tailscale up

# Get the mesh IP assigned to this machine (a 100.x.x.x address)
tailscale ip -4

# Enable tailscaled to start on boot
sudo systemctl enable --now tailscaled
```

### Client devices (phone, laptop, etc.)

Install the Tailscale app on each device and sign in with the same account. All devices on the account can reach each other over the mesh automatically.

### Reaching Ph3b3

Once both sides are on Tailscale, access the web UI from any device on your mesh:

```
http://100.x.x.x:7331
```

Replace `100.x.x.x` with the Tailscale IP shown by `tailscale ip -4` on the server.

### Privacy note

Tailscale's coordination servers handle key exchange and device discovery, but **traffic between your devices is encrypted end-to-end** and never passes through Tailscale's infrastructure. If you prefer zero third-party involvement, [NetBird](https://netbird.io) is a fully self-hostable alternative with the same WireGuard-based mesh model.

## Responsible Use

Ph3b3 includes network scanning and cybersecurity tools intended for use on networks you own or have explicit permission to scan.

- Never run network scans on networks you don't own
- nmap OS detection requires root and should only be used on your own network
- Cybersecurity modules are defensive tools, not offensive ones
- Voice and camera data stays local — be mindful of others' privacy

This project is a work in progress. Use it responsibly.
