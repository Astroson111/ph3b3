# Future Goals

What's shipped, what's active, what's next. Only things that actually run on `main` land in **Shipped** — no aspirational claims in that section.

> Every capability that touches privacy, truth, safety, or autonomy has a recorded guardrail in the [values-audit trail](docs/VALUES_AUDIT.md) — added *before* the capability ships.

---

## Shipped

- **Metis — web search.** Phoebe's first deliberate step outside the machine — and it stays *off* until you flip it on in the Status tab. When on, every search is announced with the query shown, and answers are cited from the *actual* result URLs, so a search-shaped answer can never come from the model's imagination. Web pages are untrusted input: summarized with no tools (a page can't make Phoebe *do* anything), safety holds on both the query and the summary, and a dead backend says so out loud instead of inventing an answer. SearXNG runs in a localhost-only container with a DuckDuckGo fallback; watched by Argus, drilled for container death.
- **Rhea — backup & restore.** Nightly encrypted, deduplicated snapshots to a dedicated external drive; a fire-drilled restore script; watched by Argus so a failed backup is *visible*, not silent.
- **Argus — fleet observability.** Per-device heartbeats with cadence contracts (sleep-aware, so battery devices aren't false alarms), authenticated check-ins, a captures feed, chat history, and firmware-hash drift detection.
- **Photo tools — `take_photo` / `describe_view`.** Explicit-ask only; every capture announced and logged to Argus.
- **Dio native photo loop.** Her own camera, drawn to her own screen, described aloud. (Yes, the colors were briefly psychedelic. Fixed.)
- **STT hallucination gate.** Silence is no longer transcribed into phantom whispers.
- **Language & voice.** One setting in the Status tab and Phoebe both *responds* and *speaks* in eight languages — English, Spanish (four regional voices), French, German, Mandarin (Hanzi), Italian, Polish, and Russian (Cyrillic) — each a real native Piper voice, never romanization. New voices install hash-pinned and are reviewed *by ear* in the portal before they can be picked, so a wrong-accent model never ships silently; adding a language or voice is a registry entry plus a one-time model download, not code. Safety refusals hold in every language. Absorbs the old "Multilingual TTS" goal.
- **Text-only languages.** A language with no voice that clears the quality bar is still selectable — labeled "text only" — and Phoebe answers in text, synthesizing nothing (declared design, never silent-by-surprise; Alba is never assigned to it). Japanese, Korean, Hindi, and Indonesian ship this way today.
- **Portal localization.** The interface itself — tabs, buttons, cards — renders in the selected language via locale files with English fallback. Live for English, Spanish, French, German, Mandarin, Italian, Polish, and Russian; Polish and Russian await a native polish pass, and Japanese/Korean chrome falls back to English until translated.

---

## Active

- **Mnemosyne — persistent local memory spine.** Growing into retrieval over long-term memory (this absorbs the old "RAG memory backend" goal). Same guarantee as everything else here: embeddings are generated and stored locally, nothing leaves.

---

## Future

- **Chronos — a sense of time.** A local scheduler for reminders, briefs, and "you've been at this four hours."
- **Aura — a sense of the room.** Environmental sensing — temperature, humidity, air quality — as a fleet device.
- **Argus phase two — immunity.** Continuous config-hash self-checks; noticing changes no PR made.
- **Voices for the text-only languages (JA / KO / HI / ID).** Japanese, Korean, **Hindi, and Indonesian** are offered today as text-only (Phoebe writes, doesn't speak) — hugely popular languages, but official Piper has no medium-or-better voice for them, and no low-quality substitute is worth shipping. Voicing them requires a second local TTS engine (VITS-class) behind the existing voice registry — no cloud, no quality compromise.
- **Agent orchestration.** Goal-directed multi-step tool chaining across the full function set, instead of single-shot invocation.
- **Integrations pattern.** A repeatable shape for new capabilities: a subfolder under `integrations/`, its own README, wired into `agent/server.py`.
