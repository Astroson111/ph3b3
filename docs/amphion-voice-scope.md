# SCOPE — Amphion: singing in your own voice

Requested 2026-07-26. **This is a scope, not a decision.** It exists because both
prior briefs settled this as out of scope, and reversing that deserves the brief
they said it needed rather than a quiet implementation.

---

## 1. What was actually asked

> "an option for voice samples for your own"

Read as: *I record myself, Amphion sings in my voice.* Not "clone an artist" —
the operator's own voice, on their own machine.

---

## 2. Technical reality, measured on this rig

**ACE-Step 1.5 has no voice input.** Querying the node returns **zero optional
inputs**; the controls are `tags`, `lyrics`, `seed`, `bpm`, `duration`,
`timesignature`, `language`, `keyscale`, and sampler knobs. There is no speaker
embedding, no reference-audio slot, nothing to attach a sample to. **A voice
cannot be supplied at inference time.** The only mechanism is training a LoRA
adapter and loading it alongside the base model.

**What exists here already:**
- ComfyUI has LoRA nodes, including `TrainLoraNode`, `LoraSave`,
  `LoraLoaderModelOnly`. These are built for image diffusion; whether they train
  usefully against an ACE-Step audio DiT is **unverified and should not be
  assumed**.
- **No ACE-Step training tooling is installed.** No `acestep` package, no `peft`,
  no `accelerate`, no `bitsandbytes`, no `datasets`.

**VRAM.** 16,380 MiB total, 6,315 MiB resident at idle (Whisper 4,536 + ComfyUI
222). Training would contend with five existing tenants and would need Whisper
evicted, not just Hermes3 — a swap the current orchestration does not perform.

**Data.** Voice adaptation on a music model wants *sung* audio with matching
lyrics — commonly cited at 10+ minutes of clean, isolated vocal. Not a 20-second
sample.

**Honest unknowns.** I have not trained an ACE-Step LoRA on this hardware. Time
per voice is plausibly hours, not minutes, and quality on 10 minutes of amateur
recording is genuinely uncertain. Anyone promising a number here is guessing.

---

## 3. The problem that actually decides this

**An audio input cannot verify whose voice it is.** A field that accepts *your*
voice accepts *any* voice. That is why the existing line is architectural — no
upload control was built — rather than a rule that could be relaxed.

This is not solved by intent. It is solved, partially, by making a *pre-existing
recording* unusable as enrolment input:

**Challenge-phrase enrolment (recommended).** The system generates a random
phrase — nonsense words, a random number sequence — and the enroller must sing
*that*, live, through the microphone. A Johnny Cash record cannot sing a phrase
invented five seconds ago. This is ordinary anti-replay: it does not prove
identity, but it makes casual laundering of a released recording fail, and it
does so mechanically rather than on trust.

Layered with:
- **Live capture only, no file path.** Same discipline as the sung-lyrics work:
  a microphone, never a file picker. Removes drag-a-track-in entirely.
- **Multiple challenges across a session**, so a long enrolment cannot be
  assembled from one stolen clip.
- **Explicit attestation**, recorded with the voice model: who enrolled it, when,
  and that they affirmed it is their own voice.

None of this is airtight. Someone determined can play a record at a microphone
and sing along. The honest claim is *raises the cost from trivial to deliberate*,
which is a real improvement over an upload box and should not be oversold as
consent verification.

---

## 4. What a trained voice IS, once it exists

A portable file that reproduces a human voice. It outlives the session, can be
copied off the machine, and carries none of the enrolment context unless we put
it there. Therefore:

- Voice models are **marked** with enrolment metadata and the attestation.
- Any track generated with one carries that in its provenance chain, alongside
  the Amphion provenance already embedded in exports.
- The existing floor still applies to lyrics and prompts. A legitimately enrolled
  voice does not unlock content the floor refuses.
- **Open question for the operator:** should a voice model be exportable at all?
  Keeping it non-exportable makes the machine the boundary; allowing export makes
  it a distributable artifact.

---

## 5. Options

**A. Do not build it.** Keeps the current architecture, which is coherent and
verified. The descriptor controls plus seed-locking already give deliberate
control over the singer, without a voice model existing at all. *Cost: nothing.*

**B. Build enrolment + training, gated.** Challenge-phrase live capture, local
training, voice models marked and non-exportable, provenance chained.
*Cost: real — training pipeline, deps, a VRAM swap that evicts Whisper, model
management UI, a values pass, and an unknown number of hours per voice with
uncertain quality.* Multi-day, not an afternoon.

**C. Prove the engine first (recommended next step, cheap).** Before any UI or
enrolment design, answer the one question everything else depends on: *can an
ACE-Step 1.5 LoRA meaningfully carry a voice on this hardware, at all?* One
throwaway experiment, existing recordings, no product surface, no enrolment
flow, nothing shipped. If the answer is no, B evaporates and A stands on
technical grounds rather than policy ones.

---

## 6. Recommendation

**C, then re-decide.** The safety design in §3 is only worth building if §2 turns
out to work, and §2 is currently an assumption. A spike costs a few hours and
either kills the project honestly or gives the enrolment work something real to
attach to.

If the spike succeeds, B needs its own values-audit row before any of it ships —
the input surface is the centrepiece, exactly as the remix ruling was.

---

## 7. Verify (for B, if it is ever built)

1. Enrolment accepts live microphone capture only; no file picker exists.
2. A pre-recorded clip fails the challenge phrase.
3. A voice model carries enrolment metadata and attestation.
4. Tracks made with a voice model say so in their provenance chain.
5. The content floor still fires on prompts and lyrics with a voice model loaded.
6. Named-artist refusal still fires — a voice model does not create a bypass.
7. Training evicts and restores the GPU tenants cleanly; no partial model on
   failure.
8. Voice models are not exportable (or are, if that decision changes — but
   deliberately, and recorded).
