# Future Goals

What's shipped, what's active, what's next. Only things that actually run on `main` land in **Shipped** — no aspirational claims in that section.

---

## Shipped

- **Rhea — backup & restore.** Nightly encrypted, deduplicated snapshots to a dedicated external drive; a fire-drilled restore script; watched by Argus so a failed backup is *visible*, not silent.
- **Argus — fleet observability.** Per-device heartbeats with cadence contracts (sleep-aware, so battery devices aren't false alarms), authenticated check-ins, a captures feed, chat history, and firmware-hash drift detection.
- **Photo tools — `take_photo` / `describe_view`.** Explicit-ask only; every capture announced and logged to Argus.
- **Dio native photo loop.** Her own camera, drawn to her own screen, described aloud. (Yes, the colors were briefly psychedelic. Fixed.)
- **STT hallucination gate.** Silence is no longer transcribed into phantom whispers.

---

## Active

- **Mnemosyne — persistent local memory spine.** Growing into retrieval over long-term memory (this absorbs the old "RAG memory backend" goal). Same guarantee as everything else here: embeddings are generated and stored locally, nothing leaves.

---

## Future

- **Chronos — a sense of time.** A local scheduler for reminders, briefs, and "you've been at this four hours."
- **Aura — a sense of the room.** Environmental sensing — temperature, humidity, air quality — as a fleet device.
- **Argus phase two — immunity.** Continuous config-hash self-checks; noticing changes no PR made.
- **Multilingual TTS.** Per-language Piper voices, swapped to match the detected language — native accents, not romanization read with an English mouth.
- **Agent orchestration.** Goal-directed multi-step tool chaining across the full function set, instead of single-shot invocation.
- **Integrations pattern.** A repeatable shape for new capabilities: a subfolder under `integrations/`, its own README, wired into `agent/server.py`.
