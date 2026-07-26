# Ph3b3

> ## In memory of Peach
> The best dog in the world — who went to everyone.
> Ph3b3 is built with the love she gave so freely.
> Rest easy, good girl.

---

If you ever see this darlin', I got her.

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

Ph3b3 is a FastAPI application that runs entirely on **your own machine** — the reference build is a desktop with a Ryzen 9 7950X and an RTX 4060 Ti (16 GB). The full stack is local:

- **Brain:** Hermes3 via Ollama
- **Voice (TTS):** Piper — **Alba** (en_GB) by default, plus native voices across **fifteen languages** (Latin, Hanzi, Cyrillic, and Arabic RTL scripts), selectable per language; Japanese, Korean, Hindi & Indonesian run text-only. New voice candidates install gated as *unreviewed* and only reach the picker once approved by ear in the Status tab — adding a language or voice is a registry entry plus a hash-pinned download, not code.
- **Hearing (STT):** Whisper, running on CUDA
- **Server:** FastAPI over HTTPS, basic-auth protected
- **Modules:** 32 capability modules (plus 16 infrastructure modules — paths, auth, routing, STT/TTS plumbing. *Capability* means a thing she can DO for you; the split is what makes the number checkable rather than a vibe, and it had drifted before)
- **Tools:** 89 callable functions she can invoke

Her range is wide for a single-author build:

- **Voice conversation, in eight languages — and text in more** — she speaks through Piper TTS, defaulting to the **Alba** voice (English, Scottish). Pick a language in the Status tab and she both *responds* and *speaks* in it — **English, Spanish, French, German, Mandarin, Italian, Polish, or Russian** — each in a real native voice (Mandarin in Hanzi, Russian in Cyrillic, never romanization read with an English mouth). Languages without a quality voice yet — **Japanese, Korean** — are offered *text-only*: she writes in them and stays silent rather than faking an accent, by declared design. The portal UI localizes too. **More can be added**: a new language or voice is a registry entry plus a one-time, hash-pinned model download, reviewed by ear before it goes live — not a code change. One setting, applied everywhere she talks — portal, Dio, Iris. Her **safety refusals hold in every language** (the "the filter only speaks English" hole, closed). Push-to-talk capture, with a server-side silence gate so quiet is never transcribed into phantom words.
- **Sight on request** — she takes photos and describes what she sees, through a webcam or Dio's own camera, **only when you ask**. Never ambient, never silent: every capture is announced and logged.
- **Image generation** — Morpheus (SDXL via ComfyUI), fully local.
- **Song generation** — Amphion (ACE-Step 1.5 via ComfyUI): full songs from a text prompt, with optional lyrics, fully local.
- **Web search** — Metis, her first step outside the machine, **off by default** and flipped on in the Status tab. Every search is announced and answers are cited from the *actual* result URLs; web pages are treated as untrusted input (summarized with no tools, safety-checked both ways), and a dead backend says so rather than inventing an answer. SearXNG in a localhost-only container, DuckDuckGo fallback.
- **Argus** — fleet observability: heartbeats from every device, a captures feed (photos, audio, transcripts), and browsable chat history, all in one watchtower tab.
- **Rhea** — nightly encrypted backups to a dedicated external drive, versioned, with a tested one-script restore. If the server dies tonight, she survives.
- **32 modules** — ghost hunting, translation, cybersecurity, film, anime, D&D, weather, music, notes, karaoke, a local song generator (Amphion), a local photo editor (Apelles), web search (Metis), a resume analyzer (Ariadne), an on-page utility tray (timer, calc, converter, scratchpad, QR, dice, world clock) and more.
- **Persistent memory across sessions** — Mnemosyne, in active development toward full retrieval.
- **Reflective learning loop.**
- **Web UI** accessible over Tailscale from anywhere.

### Honest limits

This matters more than the feature list. Ph3b3 runs on an **8 GB VRAM ceiling** — large frontier models do not fit, and a single desktop cannot do what a hyperscale facility does at the frontier. That's the trade. What you get in exchange is an assistant that is *yours*: no subscription, no rate limit, no terms that change under you, no model deprecated out from under you, and no data on someone else's server. For the household assistant use case, that trade is the entire point.

---

## The body she's growing

Ph3b3 started as one box you typed at. She's becoming an ecosystem — and every device in it is a client of *her* local API. None of them touch the cloud, and none of them talk to each other; they all talk to her.

- **Iris** — an M5StickS3 voice combadge, described below.
- **Stack-chan body (Dio)** — a CoreS3 companion wearing her face: a camera with photo-on-face display (she shows you what she captured while describing it), a touchscreen, a fleet heartbeat, and a face that reacts — a head-pat gets a smile and a soft purr.
- **The Control Panel** — a local control-plane PWA, served by Ph3b3 herself, described below.

This is the privacy thesis extended to the remote: even the thing that *commands* her is local, also hers, served from the same box.

---

## Iris

Iris is a wearable voice combadge built on the **M5StickS3** — a device smaller than a lighter, worn like a Star Trek badge. She is a fully autonomous client of Ph3b3: she connects to the network, manages her own WiFi, speaks, listens, and responds, all through Ph3b3's local API.

### What Iris does

**Push-to-talk voice round-trip.** Hold BtnA and speak. Iris records in 16 kHz mono PCM, wraps it in a WAV header, and POSTs it to Ph3b3's `/transcribe` endpoint (Whisper on CUDA). The transcript flows directly to `/chat` (Hermes3 + her soul). Ph3b3 responds in text *and* streams back a TTS audio payload (Piper, Alba voice). Iris decodes and plays it in real time.

**Chunked TTS streaming — long stories play whole.** Ph3b3 splits a reply at sentence boundaries and serves it as a manifest plus per-chunk audio (`POST /chat/stream`, then lazy `GET /tts/chunk/{id}/{n}` synthesised on demand with read-ahead). Iris plays the first chunk while fetching the next, decoding each with a double-buffer — buffer A plays while buffer B fills from the TLS stream, then they swap — for clean continuous speech even over a hotspot. Because every request is short-lived, a five-minute recitation streams end to end; the earlier single-WAV response couldn't sustain a multi-minute reply and cut off mid-story. An inter-chunk watchdog resets on every byte and tears down a genuinely stalled stream without ever capping a long one, and playback state transitions fire only when the audio buffer actually drains.

**Interrupt.** Press BtnA mid-sentence and she stops immediately. She listens; she can be interrupted. The decode loop and the playback tail both respond to the button.

**Animated face.** A custom M5GFX renderer draws her face on the 135×240 display — blinking, gaze-drift, breath bob, lip-sync tied to speaking amplitude, state-colored eyes. No `m5avatar` library: the renderer is built from scratch and fits entirely in SRAM.

**Multi-network WiFi.** Iris stores up to five SSIDs in NVS. At boot she scans and connects to whichever known network has the strongest signal. If she loses the connection, a non-blocking supervisor ticks every 12 seconds and tries each network in rotation — no blocking scan, buttons stay responsive. When she reconnects, she defers a sync call to Ph3b3 to pull the latest network list, so the server is always the source of truth for her credentials.

**No captive portal in the field.** Networks are managed entirely through the Control Panel's **Iris tab** (see below) and synced to the device automatically. The portal exists as a fallback for first-time setup; in practice you never touch it again.

Iris's firmware lives in its own repository — **[astroson111/iris](https://github.com/astroson111/iris)**.

---

## The Control Panel

A self-contained control-plane web app, served by Ph3b3 from her own FastAPI at **`/panel`**. No external CDNs, no fonts pulled from the web, no cloud — fully local, which is the whole point. Source lives in this repo under [`static/`](https://github.com/astroson111/ph3b3/tree/main/static).

From any phone on the network it gives you:

- **System status** — live health from `/health` and `/ready` (model loaded, soul, TTS, STT, boot count), polled continuously.
- **Chat + voice in one** — type to her; she answers in text *and* speaks the reply in Alba's voice. Both come back from a single `/chat` call (`{response, audio}`), so the voice you hear is her real reply running through Hermes3, not a parrot reading your own words back.
- **Argus — fleet observability.** Every device — Nyx, Iris, Stack-chan, and the **Rhea** backup drive — checks in on the same authenticated `X-Ph3b3-Device` path with a tiny heartbeat, and Argus derives a live state (**HEALTHY / SICK / SILENT**) from a per-device *cadence contract* rather than guessing from a raw last-seen. A badge silent past its window reads SILENT; one reporting a bad value — low battery, low heap, or the backup drive over 80 % full — reads SICK. It's strictly read-only: Argus watches and records, never acts, and keeps its own dedicated store separate from Phoebe's memory. The same tab carries the **captures feed** (every device photo and recording, paired with its transcript) and full **chat transcript history**. Contracts are plain JSON (`config/argus_contracts.json`), reloaded per read — editable without a restart.
- **Web access (Metis).** A master switch, **off by default**, that governs whether Phoebe may reach the internet at all — no toggle, no packets. With it on, a *search-intent* message is routed to `web_search` server-side and answered fail-closed: the query is announced, results come from a localhost-only SearXNG container (DuckDuckGo fallback), and the reply is cited from the **actual** retrieved URLs, so a search-shaped answer can never be conjured. Fetched pages are untrusted — summarized with no tools available and safety-gated on both the query and the summary — and a dead backend reports itself out loud instead of fabricating. Watched by Argus; SSRF-guarded so it can never reach a private, loopback, or tailnet address.
- **Iris networks** — add, remove, and manage the WiFi credentials stored on Iris. Changes are synced to the device automatically on next connect; no USB cable, no portal page, no reflash.

It installs as a real standalone PWA (manifest + service worker), with Ph3b3's face as the app icon — themed in her identity: violet face, magenta-pink accents, cyan-and-magenta circuit lines.

---

## Morpheus

Ph3b3 generates images locally through Morpheus, a txt2img module running on the same single GPU as everything else. Because one card can't hold two minds at once, Morpheus parks the chat model, takes the card, renders, frees it, and hands it back — no second machine, no cloud, no prompt ever leaving the box.

Morpheus does more than stills now. It can **edit** an image you point it at, and it can **make short video** — from a text description, or by animating a still it already generated. Video comes in three tiers on that same single card: a fast lane for quick clips, and two higher-quality lanes that trade minutes for richer, longer motion (a clip runs anywhere from under two minutes to about half an hour, depending on the tier). Because a render holds the whole GPU for that stretch, Ph3b3 treats it as a background job — ask her, in conversation, to make a video and she starts it, tells you the estimate, and steps away from chat until it's done, letting you know she's rendering rather than falling silent.

Every generation passes through a safety floor that runs locally before anything renders and cannot be disabled by any setting. It refuses content involving minors, non-consensual material, and sexualized or compromising depictions of real, identifiable people — categorically, on every request. The floor covers video exactly as it covers images: the prompt, and for image-to-video the source image too, are checked before a single frame renders. Local generation doesn't mean no guardrails. The line is enforced on your hardware, by default, with no off switch.

---

## Amphion

Amphion writes songs. Describe what you want — a genre, the instruments, a tempo, the feeling — hand her lyrics if you have them or leave them blank for an instrumental, and she composes a full track locally, in seconds, on the same single card as everything else. She's Morpheus's sibling and works the same way: park the chat model, take the GPU, generate, hand it back — nothing leaves the box, and there's **no cost per song**, so you run it as many times as it takes to land the one you want.

Every song is kept as one lossless master you can play in the panel and export on demand — a lossless **FLAC**, a phone-friendly **320 kbps MP3**, or a **WAV** in the format the karaoke player wants — each peak-normalized on the way out so it never clips a small speaker into distortion. You set the length, from a short loop to a few minutes, and she shows an honest estimate of how long the render will take before you start it — and warns you if the lyrics you pasted are too long for the time you chose.

She will not clone a voice or imitate a named artist, by design: the same content floor that governs Morpheus runs here too — on the **prompt and the lyrics both**, before a single note is generated — and there is no voice-training path in her at all. Lives in the Control Panel's **Amphion** tab, beside Karaoke.

---

## Karaoke

Ph3b3 has a karaoke corner. Pick a track, the lyrics roll in time with the music, and Phoebe follows along — a moon cue tracks the active line so you always know where you are in the song. It runs in the same local panel as the rest of the system: your music, your machine, no streaming account required.

Built for the room it lives in — when it's not screening calls or generating images, Ph3b3 is good company.

---

## Ariadne

Ariadne is Ph3b3's résumé toolkit — a private ATS reader and builder for job-seekers. Paste your résumé (or drop a `.txt`, `.docx`, or `.pdf`; a scanned image-PDF is flagged rather than mis-read), and she scores how cleanly an applicant-tracking system can parse it — tables, multi-column layouts, non-standard headers, and content stranded in headers or footers are each called out with the line they're on, alongside a section-completeness check. Add the job description — pasted, or fetched from a URL (Greenhouse, Lever, Workday, most career pages; login-walled sites like LinkedIn simply ask you to paste the text) — and she maps the keyword gap in two honest buckets: the terms you already demonstrate under different words, and the ones you'd have to genuinely earn.

Ask her to build and she rebuilds the résumé as a single-column, ATS-safe `.docx` — standard headers, plain bullets, no tables or text-boxes — and returns a before/after diff so you approve every change before using the file. She only ever inserts a keyword you already back up, tagged to the real line that justifies it; the rest are reported, never written in. That's the rule she runs on: **align truthful experience to ATS vocabulary, never fabricate qualifications.** Like everything else, it stays local — your résumé is analyzed on your machine and never leaves it; the only outbound call is fetching a job-post URL you hand her. Lives in the Control Panel's **Ariadne** tab.

---

## Ph3b3-Chan

Stack-chan runs **Ph3b3-Chan**, a custom firmware built on the M5Stack CoreS3.
It is a fully autonomous client of Ph3b3 — connecting over WiFi, speaking
responses through the CoreS3 speaker, and rendering Ph3b3's animated face on
the 320×240 display. Like Iris, it never touches the cloud: every request
flows to Ph3b3's local API over HTTPS.

The onboard app framework supports hot-swappable apps (Talk, Karaoke,
Ghost, Network) navigated from a crescent swipe menu. When in Talk mode
the face expresses live state — LISTENING, THINKING, SPEAKING — driven by
the same M5GFX face engine as Iris.

Like Iris, Stack-chan consumes the chunked `/chat/stream` API, so long
recitations play through to the end. An activity-based session watchdog —
where an arriving chunk, playing audio, detected speech, or a head-pat all
count as activity — keeps her awake mid-story and drops to idle only on a
genuine stall or true dead air, never on a fixed timer. "Response complete"
means her local playback buffer has drained, not that the network stream
closed.

Firmware lives in its own repository —
**[astroson111/Dionysus](https://github.com/astroson111/Dionysus)** —
extracted from this repo so Ph3b3 stays server-only. Build with `arduino-cli`
targeting `m5stack:esp32:m5stack_cores3`; copy `secrets.example.h` to
`secrets.h` and fill in your WiFi and server credentials.

---

## Roadmap

Where she's going next:

- **More languages & voices** — multilingual voice + response ships today (eight voiced languages, Japanese/Korean text-only). The bench stays open: any medium-or-better Piper voice drops in through the registry and a by-ear review, no code change. The next real step is *voicing* Japanese and Korean — official Piper has nothing that clears the bar, so it needs a second local TTS engine (VITS-class) behind the same registry.
- **Agent orchestration** — multi-step autonomous tool chaining: give her a goal, she plans and sequences her own tool calls (across the existing 89 functions) instead of single-shot invocation.
- **RAG memory backend** — vector-store retrieval over her long-term memory so recall scales past what fits in context, with the same local-only guarantee (embeddings generated and stored locally, nothing leaves).
- **Integrations pattern** — a repeatable shape for new capabilities: a subfolder under `integrations/`, its own README and scripts, wired into `server.py`.

Accessibility is the through-line for all of it — every addition is measured against whether it makes her more usable for the people she's built for, not less.

---

## Running her

### Requirements

- Ubuntu 24.04 (reference build: Ryzen 9 7950X / RTX 4060 Ti)
- Ollama with Hermes3 pulled
- Piper TTS with the Alba `en_GB-alba-medium` voice
- Whisper (CUDA build)
- Python dependencies — install with `pip install -r requirements.txt`

> **Lighter deployment — Ph3b3-Light (Windows/WSL2 solo):** the reference build assumes a CUDA GPU. A leaner "solo" port for machines without one — Morpheus-lite image generation plus a gallery web view, tuned for Windows/WSL2 — is in progress on the [`windows` branch](https://github.com/astroson111/ph3b3/tree/windows). Same local-only guarantee, smaller footprint.

### First-time setup

```bash
./setup.sh      # one-time: installs system deps, creates the venv, pip installs
```

`setup.sh` also downloads the Piper voice models once (zero runtime network fetches — a house privacy law). Every model is **hash-pinned**: its sha256 is recorded at selection time and verified on install, so a mismatch aborts rather than silently seating a swapped model.

#### Voice models — disk cost

Most models are ~60–110 MB (`.onnx` + `.onnx.json`). A voice is either **approved** (in the picker) or an **unreviewed candidate** (installed and synth-checked, but reachable only through the Status-tab review flow until the Captain approves it by ear). Rejecting a candidate deletes its model from disk. Only voices for a language in the picker are installed — no orphan models for languages Phoebe can't be set to.

| Voice model | Name | Language | Tier | Size | Status |
|-------------|------|----------|------|-----:|--------|
| `en_GB-alba-medium` | **Alba** | English (Scottish) | strong | 60 MB | approved |
| `es_ES-davefx-medium` | Davefx | Español (España) | strong | 60 MB | approved |
| `fr_FR-siwis-medium` | Siwis | Français (France) | strong | 60 MB | approved |
| `de_DE-thorsten-medium` | Thorsten | Deutsch (Deutschland) | strong | 60 MB | approved |
| `zh_CN-huayan-medium` | Huayan | 中文 (普通话) | functional | 60 MB | approved |
| `es_MX-ald-medium` | Ald | Español (México) | functional | 60 MB | approved |
| `es_ES-sharvard-medium` | Sharvard | Español (España) | strong | 74 MB | approved |
| `es_MX-claude-high` | Claude | Español (México) | strong | 61 MB | approved |
| `de_DE-thorsten-high` | Thorsten HD | Deutsch (Deutschland) | strong | 109 MB | approved |
| `it_IT-paola-medium` | Paola | Italiano (Italia) | strong | 61 MB | approved |
| `pl_PL-gosia-medium` | Gosia | Polski (Polska) | strong | 61 MB | approved |
| `ru_RU-irina-medium` | Irina | Русский (Россия) | strong | 61 MB | approved |
| `vi_VN-vais1000-medium` | Vais1000 | Tiếng Việt (Việt Nam) | strong | 61 MB | approved |
| `ar_JO-kareem-medium` | Kareem | العربية (الأردن) — RTL | strong | 61 MB | approved |
| `tr_TR-dfki-medium` | DFKI | Türkçe (Türkiye) | strong | 61 MB | approved |
| `nl_NL-pim-medium` | Pim | Nederlands (Nederland) | strong | 61 MB | approved |
| `uk_UA-ukrainian_tts-medium` | Ukrainian TTS | Українська (Україна) | strong | 74 MB | approved |
| `cs_CZ-jirka-medium` | Jirka | Čeština (Česko) | strong | 61 MB | approved |
| `sv_SE-nst-medium` | NST | Svenska (Sverige) | strong | 61 MB | approved |

**Total: ~1.2 GB** for all nineteen. **Fifteen languages are voiced** — across Latin, Hanzi, Cyrillic, and Arabic (the first right-to-left language) scripts. New voices always arrive `unreviewed` and join the picker only once approved by ear. (Dutch: `pim` chosen over `mls` — a cleaner single-speaker voice — a flagged substitution.)

**Text-only languages.** A language with no *approved* voice is still selectable — labeled "— text only" — and Phoebe answers in that language as **text**, synthesizing nothing (declared design, never silent-by-surprise; Alba is never assigned to it). **Japanese, Korean, Hindi, and Indonesian** are offered this way today: hugely popular languages, but official Piper has no voice that clears the quality bar, and no low-quality substitute is worth shipping (voicing them needs a second local TTS engine — see [FUTURE_GOALS](FUTURE_GOALS.md)). The text-only state derives from the registry, so the day a language gains an approved voice the label drops off with zero code change.

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

Once she's running, the recommended path is via [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve):

```
https://<your-tailnet-name>.ts.net/panel
```

Tailscale Serve provides a trusted HTTPS certificate and a clean, stable hostname — the service worker registers cleanly, the PWA installs as a real standalone app (full-screen, Ph3b3's face as the icon), and there are no port numbers or cert warnings. Tailscale's stable name means she's reachable across networks without reconfiguration — tested working from outside home WiFi with no changes needed.

**On the LAN (without Tailscale)?** Direct access also works:

```
https://<ph3b3-host>:7331/panel
```

The panel loads fully; your browser warns once about the self-signed cert. The service worker may not register in all browsers over a self-signed cert, so the PWA install experience is better via Tailscale Serve.

On a phone, use your browser's **Add to Home Screen** or install prompt to add the panel as a standalone app.

Auth is the existing basic auth — the browser holds it once you've loaded the page, so the panel never stores credentials of its own.

For Tailscale Serve setup, see `INSTALL.md`.

---

## License

MIT. See [LICENSE](LICENSE).

---

*Made with soul.*

<!-- PROTECTED: do not edit, remove, or "clean up" the lines below. Memorial text — exact wording matters. -->
*"Eat your num num and drink your wet wet." — Beans*

*For Briana. She kept the builder fed.*
