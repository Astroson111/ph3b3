# Ph3b3

**A fully local AI assistant. No cloud. No data centers. Built in a basement in Pennsylvania.**

Ph3b3 (*Phoebe*) runs entirely on hardware you own. No cloud, no API calls leaving your network, no telemetry. You talk to her — by text or by voice — and every word stays inside your walls. The intelligence is *present*, not rented.

---

## Why she exists

The industry is building a continent of power-hungry infrastructure to deliver something most people wanted to fit on one desk.

Data centers consumed roughly **415 TWh in 2024 — about 1.5% of the world's electricity — and that's been growing about 12% a year.** One widely-cited projection has them approaching **1,050 TWh by 2026**: if data centers were a country, they'd be the fifth-largest electricity consumer on Earth, between Japan and Russia. In some places the strain is already local — data centers drew about **26% of Virginia's electricity in 2023**, against a grid mostly built decades ago. The communities near these facilities are the ones living with the noise, the substations, and the water draw.

Ph3b3 is the opposite shape. The same capable assistant — voice round-trip, ask-her-anything, real tools — answers on a **single desktop you already own and already power**, with nothing leaving the room.

She is not a smaller data center. She's proof that, for this job, you never needed one. The frontier models will keep living in big facilities, and that's fine — but the *household assistant* doesn't have to. It can be a lamp in your own house — to make sure it isn't haunted.

**Privacy here is architecture, not a policy page.** A cloud assistant asks you to *trust* a promise. Ph3b3 removes the wire the data would travel on. She physically cannot leak what she never sends.

---

## Who she's for

Ph3b3 isn't built for benchmark scores. She's built for the people in the room.

The design standard is simple and non-negotiable: **the community has to be in the room before anything ships.** Accessibility — for elderly users, for autistic users, for anyone the industry tends to design last — is a first-class direction for this project, not a checkbox. But it's held honestly: I don't yet know whether the current voice is comfortable to those users, whether the interaction patterns work, or where the rough edges are. Those answers come from the people themselves, not from assumptions. What I can commit to is the standard — a local assistant that stays patient, stays private, and stays *home*, built and tested *with* the people it's meant to serve rather than *for* them at a distance.

That's the direction: capable, private help, shaped by the people the industry usually designs last.

---

## What she is, today

Ph3b3 is a FastAPI application running on **Nyx** — a desktop with a Ryzen 9 7950X and an RTX 4060. The full stack is local:

- **Brain:** Hermes3 via Ollama
- **Voice (TTS):** Piper, speaking in the **Alba** en_GB voice
- **Hearing (STT):** Whisper, running on CUDA
- **Server:** FastAPI over HTTPS, basic-auth protected
- **Modules:** 30 capability modules
- **Tools:** 88 callable functions she can invoke

Her range is wide for a single-author build — she spans security, household, creative, and investigative work:

| Domain | Modules |
|---|---|
| **Security** | cybersec, scam_detector, network |
| **Vision** | camera, screenshot, vision, vision_stream, evening_capture |
| **Voice I/O** | tts, stt |
| **Household & productivity** | calendar, reminders, notes, timer, weather, recipes, resume |
| **Media & creative** | anime, film, jokes, stories, spotify |
| **Investigation / paranormal** | investigation, occult |
| **Comms** | bluetooth, translation |
| **Other** | dnd, search, memory, system |

### Honest limits

This matters more than the feature list. Ph3b3 runs on an **8 GB VRAM ceiling** — large frontier models do not fit, and a single desktop cannot do what a hyperscale facility does at the frontier. That's the trade. What you get in exchange is an assistant that is *yours*: no subscription, no rate limit, no terms that change under you, no model deprecated out from under you, and no data on someone else's server. For the household assistant use case, that trade is the entire point.

---

## The body she's growing

Ph3b3 started as one box you typed at. She's becoming an ecosystem — and every device in it is a client of *her* local API. None of them touch the cloud, and none of them talk to each other; they all talk to her.

- **Iris** — an M5StickS3 voice combadge. A wrist-worn terminal that shows a themed avatar face reflecting her connection state. Push-to-talk to Ph3b3 over the LAN.
- **Stack-chan** — a CoreS3 companion wearing her face.
- **The Control Panel** *(latest milestone)* — a local control-plane PWA, served by Ph3b3 herself, described below.

This is the privacy thesis extended to the remote: even the thing that *commands* her is local, also hers, served from the same box.

---

## The Control Panel

A self-contained control-plane web app, served by Ph3b3 from her own FastAPI at **`/panel`**. No external CDNs, no fonts pulled from the web, no cloud — fully local, which is the whole point.

From any phone on the network it gives you:

- **System status** — live health from `/health` and `/ready` (model loaded, soul, TTS, STT, boot count), polled continuously.
- **Chat + voice in one** — type to her; she answers in text *and* speaks the reply in Alba's voice. Both come back from a single `/chat` call (`{response, audio}`), so the voice you hear is her real reply running through Hermes3, not a parrot reading your own words back.
- **Device roster** — a lightweight last-seen registry keyed on an `X-Ph3b3-Device` header. Iris and Stack-chan surface here as they check in; unidentified traffic lands in its own bucket. It shows the raw last-seen timestamp rather than overclaiming a hard "online" state — passive last-seen means *last active*, not *powered-on-right-now*.

It installs to your home screen as a PWA (manifest + service worker), themed in Ph3b3's identity — violet face, magenta-pink accents, cyan-and-magenta circuit lines.

---

## Roadmap

Where she's going next:

- **Multilingual TTS** — per-language Piper voice models, swapped to match the detected target language, so translated output is spoken in a native accent instead of Alba reading romanization.
- **Flipper Zero integration** — voice-triggered Flipper actions ("Ph3b3, run the sub-GHz scan"), signal-capture data logged to her memory, the Flipper as a hardware key / physical trigger, and her responses shown on the Flipper screen. Lives in `integrations/flipper_zero/` when work starts.
- **Integrations pattern** — a repeatable shape for new capabilities: a subfolder under `integrations/`, its own README and scripts, wired into `server.py`.

Accessibility is the through-line for all of it — every addition is measured against whether it makes her more usable for the people she's built for, not less.

---

## Running her

### Requirements

- Ubuntu 24.04 (tested on Nyx: Ryzen 9 7950X / RTX 4060)
- Ollama with Hermes3 pulled
- Piper TTS with the Alba `en_GB-alba-medium` voice
- Whisper (CUDA build)
- Python dependencies — install with `pip install -r requirements.txt`

### First-time setup

```bash
./setup.sh      # one-time: installs system deps, creates the venv, pip installs
```

### Start her

```bash
./start.sh      # sources .env, starts Ollama if needed, activates the venv, runs the server
```

For persistent boot via systemd:

```bash
sudo cp ph3b3.service /etc/systemd/system/
sudo systemctl enable --now ph3b3
```

(`launch_ui.sh` is a separate, optional local terminal chat UI — not the server.)

### Open the panel

Once she's running, open the control panel in a browser on the same network:

```
https://<ph3b3-host>:7331/panel
```

On a phone, use your browser's **Add to Home Screen** to install it as a standalone app. Over a trusted certificate (e.g. fronted by Tailscale Serve) the service worker registers and you get a real install; over the LAN self-signed cert it still loads fully, though some browsers won't register the service worker for offline use.

Auth is the existing basic auth — the browser holds it once you've loaded the page, so the panel never stores credentials of its own.

**Away from home?** Ph3b3 stays on your network by default. For remote access she's reachable over [Tailscale](https://tailscale.com), which keeps her private while letting your own devices reach her from anywhere — see `INSTALL.md` for setup.

---

## License

MIT. See [LICENSE](LICENSE).

---

*Made with soul.*
