# Future Goals

What's shipped, what's active, what's next. Only things that actually run on `main` land in **Shipped** — no aspirational claims in that section.

> Every capability that touches privacy, truth, safety, or autonomy has a recorded guardrail in the [values-audit trail](docs/VALUES_AUDIT.md) — added *before* the capability ships.

---

## Shipped

- **Metis — web search.** Phoebe's first deliberate step outside the machine — and it stays *off* until you flip it on in the Status tab. When on, every search is announced with the query shown, and answers are cited from the *actual* result URLs, so a search-shaped answer can never come from the model's imagination. Web pages are untrusted input: summarized with no tools (a page can't make Phoebe *do* anything), safety holds on both the query and the summary, and a dead backend says so out loud instead of inventing an answer. SearXNG runs in a localhost-only container with a DuckDuckGo fallback; watched by Argus, drilled for container death.
- **Rhea — backup & restore.** Nightly encrypted, deduplicated snapshots to a dedicated external drive; a fire-drilled restore script; watched by Argus so a failed backup is *visible*, not silent.
- **Argus — fleet observability.** Per-device heartbeats with cadence contracts (sleep-aware, so battery devices aren't false alarms), authenticated check-ins, a captures feed, chat history, and firmware-hash drift detection.
- **Apelles — local photo editor.** Crop, straighten, rotate, flip, exposure, contrast, saturation, temperature, levels, sharpen, denoise and aspect presets (TikTok, Etsy, LinkedIn, YouTube), plus batching a whole folder through a saved pipeline with a dry run that shows the real destination paths before a byte is written. **Metadata is stripped on export by default** — GPS, camera make, serial and timestamps don't travel with the picture, and keeping them takes a deliberate toggle that says what's being kept. Originals are never modified (verified by re-stat and sha256, not by promise). It *edits* photos and never generates one from nothing — that's Morpheus — and face replacement is refused permanently rather than being a setting.
  - **Cutout suite.** Background removal with a real alpha channel, composited onto white, any solid colour, or left transparent. Edge erode and feather are on by default — that's the halo fix, and shipping it off by default would just mean shipping the fringe of old wall around the subject.
  - **Scan restoration, non-generative.** Dust and scratch removal, age colour-cast correction, fade recovery (CLAHE) and Wiener deconvolution sharpening. No model, no learned prior: every output pixel derives from input pixels, so it recovers what is in the picture and **cannot invent a face that isn't the person's**. On a simulated aged scan it lifts PSNR 14.9 → 21.1 dB; on a photo that's already fine it says so rather than flattering itself. It also reports how many specks it removed, because at two pixels across a freckle and a dust speck are the same object and the count is your warning.
  - **Background blur.** Subject blur (binary — you sharp, everything else blurred) works today off the matting model. Depth blur (graduated by distance) is a *separate* capability, listed separately, because handing someone the flat version when they asked for depth is exactly the kind of quiet substitution this project keeps refusing.
  - **Chat tools.** Crop, resize, adjust, convert format, restore a scan, run a batch pipeline, and report what she can actually do — all by voice or text. Capability answers are read from the machine, never improvised.
  - **Honest capability map.** Every operation Apelles knows about appears in the UI; unavailable ones are **disabled with the specific reason and how to fix it**, so "not installed" never masquerades as "broken". Crucially it distinguishes *no model* from *not built*: upscale and depth blur are written and light up the moment you drop a model file in (proven by test, both directions), while object removal, outpaint and generative face restoration are honestly marked **not built yet** rather than claimed because the underlying model happens to be present.

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
- **Apelles tier three — the model-gated three.** *Object removal* and *outpainting* have their models and nodes already here; only the code is missing. *Generative face restoration* is the harder one and is deliberately scoped before it is built (`docs/apelles-face-restore-scope.md`): the risk there isn't identity substitution — that's closed by shape, since nothing in Apelles accepts a second image — it's **invention**, because a learned prior asked to restore a badly damaged face produces a convincing face that may not be theirs. It ships only with clamped fidelity, mandatory before/after, provenance marking, and a refusal below the face size where invention dominates.
- **Strip vocals, inside Orpheus.** Amphion carried a disabled *Strip vocals — karaoke* button from before separation existed; it was never wired, and it was removed on 2026-09-06 rather than left promising something it could not do. The capability itself shipped with Orpheus — `orpheus.separate()` splits any render on the GPU — and reaches it per song, from the library row. What is missing is the gesture the old button implied: strip the take you just made, from the render controls, without going to find it in the library first. Rebuild it there, where a song is already in hand and "which one" is not a question.
- **Agent orchestration.** Goal-directed multi-step tool chaining across the full function set, instead of single-shot invocation.
- **Integrations pattern.** A repeatable shape for new capabilities: a subfolder under `integrations/`, its own README, wired into `agent/server.py`.
