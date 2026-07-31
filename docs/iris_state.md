# Iris — device state & the "going in circles" trap

**Verdict (Captain, 2026-07-19): Iris works. She sends fine. The problems were
server-side.**

When Iris seems broken, **look server-side first.** The combadge captures and
POSTs reliably — the device and its firmware are not where the recurring problems
live. Every hour lost to Iris was lost chasing the device when the fix was on the
server.

## Why we kept going in circles

Every Iris symptom *looks* like a device bug — garbled audio, a dropped
connection, no response — so the instinct is to chase the firmware (cert bundle,
mic capture, power). That instinct is the circle. The substantive, recurring
problems landed **server-side** (transcription / STT handling, the endpoints),
not on the combadge. Default posture:

> **Iris sent it. Check what the server did with it.**

## Settled on the device — do not re-open

- Firmware is flashed and working, **including** the mic-capture hardening
  (`8390ddf` — capture-from-press prime + tanh soft-limiter). Argus shows her on
  `iris-8390ddf` with clean firmware-drift. The device side is **done.**
- Combadge is live (Reddit-shipped); push-to-talk round-trip works.

## Testing conditions (these are *how to test her*, not bugs)

- **Serial is dead** (USB-JTAG) — the **screen** is the instrument, never serial logs.
- **Test on BATTERY, not the Nyx USB port.** On Nyx USB she can brown out during
  WiFi association — a *power* condition, not an Iris fault. On battery the radio
  has the current it needs and the flakiness disappears.
- Before any re-flash, check her **MAC** (recorded outside the repo). She and Dio are
  both ESP32-S3; a wrong-device flash has happened before.

## Current state (audit 2026-07-19)

- **SILENT in Argus** — she deep-discharged to 0% on July 18. Charge her; she
  should re-associate WiFi and flip back to **HEALTHY** on her own. The *only*
  device-side thing worth checking is whether the WiFi creds survived the deep
  discharge (re-provision if not) — but **power comes first**, and it's almost
  certainly just the battery.

## Reconciliation note

Earlier session notes framed the one-time mic-garble as a firmware fix ("server
exonerated"). That fix is real and **flashed (`8390ddf`)** — so the device side is
closed. Both statements hold: the single firmware fix is done, and the **standing
verdict** is that the recurring problems were server-side. When in doubt: the
device is good — audit the server.
