# Dio Full Audit

**Date:** 2026-07-04 · **Discipline:** investigation only — no fixes/flashes/config changes; fix list awaits approval. Companion to Iris's `iris_audit.md` (same method). Device was in **download mode** on USB (esptool works; no runtime, no I2C probe). SD card mounted separately on Nyx.

Instrument note: Dio's **runtime USB-Serial-JTAG serial is silent** on this unit (esptool flashes/reads fine; `Serial.printf` doesn't surface over USB). Evidence below is from **flash reads (esptool), the mounted SD, source, and the live server** — not runtime serial. His screen is the runtime instrument when he's booted.

---

## 1. State-divergence table — running vs source

**On-device flash** (esptool `read_flash 0x10000`): app descriptor tags `arduino-lib-builder` / IDF `v5.5.2` → an **Arduino-core build (production Ph3b3-Chan)**, NOT the ESP-IDF `dio_spike` (v5.3.3) that briefly overwrote it. Flashed app ≈ **1,385,168 B**. Latest source build = **1,385,440 B** (adds the LISTENING cue). Partition layout: `nvs@0x9000 (20K)`, `app0@0x10000 (3M)`, `app1@0x310000 (3M)` — OTA.

| Feature | On-device flash | Accumulated source | Verdict |
|---|---|---|---|
| Production Stack-Chan (face/karaoke/servo/chat) restored | ✅ (Arduino build, spike gone) | ✅ git HEAD `ff65ef3` | **shipped** |
| Iris lessons: LAN `192.168.x.x:7331`, `setInsecure`, atomic NVS server record, target line, cause-diff status, portal host/port | ✅ (in the flashed 1.385 M binary) | ✅ | **shipped** |
| Purple **LISTENING** LED cue (`_listenLeds()`) | ❌ not in flashed binary | ✅ in source, build-verified | **in-source, awaiting flash** |
| Si12T head-pat | ❌ | ❌ no `Si12T`/`0x6F`/head-pat code anywhere (only a color-contract *comment* + karaoke *display* touch-zones) | **never implemented** |

So the device runs production + Iris lessons; the only firmware delta pending is the LISTENING cue.

---

## 2. Chat path — unverified, not regressed

Stages (TalkApp.h): **mic capture** (`M5.Mic.record`) → **`POST /transcribe`** → **`POST /chat`** (stream) → **TTS playback** (`M5.Speaker`) → **face/mouth** (state → mouthRY).

Call-sites vs the **current live server** — all correct:
- **Endpoints:** `/transcribe`, `/chat` (same the server serves; Iris uses them and round-trips).
- **TLS:** `_tls.setInsecure()` (TalkApp.h:60) — correct for the mkcert LAN cert.
- **Target:** `gSrvHost:gSrvPort` (runtime NVS) = `192.168.x.x:7331` (confirmed in NVS, §5).
- **Auth:** `setAuthorization(gSrvUser, gSrvPass)` → NVS `srv_user = a***1` (masked `a***1`) — the Iris username disease is **absent** here; `a***1` returns **200** against live `/health` (verified this session). The a***1 value is present in this tree's `secrets.h` seed.
- Old memory symptoms (choppy audio, mic I2S contention) were **missing-fix** states on the *old* pre-restore binary; git HEAD `ff65ef3` **contains** those fixes, so the current flash shouldn't exhibit them.

**Which stage fails?** — **None, per evidence.** The path is complete and correctly wired. But **Phase-1 end-to-end was never completed since the production restore**, so chat is **UNVERIFIED**, not regressed. There is no evidence of a failing stage; there is only an untested round-trip. The correct action is to *verify* (crescent-tap/voice after the flash), not to "fix."

---

## 3. Pet/touch (Si12T) — never shipped

- **Hardware truth:** **not checkable now** — Dio is in download mode; an I2C probe of `0x6F` needs a *running* device. Checkable only after a normal boot (then `i2c` scan or a firmware probe).
- **Source truth:** **no Si12T code exists** — zero matches for `Si12T` / `0x6F` / `head-pat` / touch-zone-to-LED/eyes. The only "touch" is KaraokeApp's **display** touch-zones (prev/play/next), unrelated to a head sensor.
- **Verdict: never-implemented** (expected finding confirmed). The color contract (listening=purple, **pat=pink**) is reserved but no pat code exists.

---

## 4. SD card (mounted on Nyx)

**Device:** `/dev/sdb1` → `/media/$USER/6566-3235`. **exFAT, 239 GB, 41 MB used (1%), healthy** (mounts clean, readable). *(Second mount `/mnt/ph3b3snd` is an empty stale dir on the NVMe — not the SD.)*

**Layout / library** (`/karaoke/`):
- `track.wav`, `track.lrc` (the demo track + synced lyrics)
- `lofi-chillout-hip-hop-be.wav`
- `System Volume Information/`, `.Trash-1000/` (housekeeping)

**Read vs stream:** firmware **reads songs from the SD card** — `SD.begin(4, SPI, 20000000)` (uses M5's existing SPI bus — **not** the `SPI.begin` landmine), scans `/karaoke/` for `.wav`, reads `.lrc`, `_streamAudio()` streams from the card. **Nothing streams from Nyx.** → **Song uploads belong on the SD `/karaoke/` folder** (a file copy, not firmware). Free space is effectively unlimited (238 GB free).

---

## 5. NVS / config — creds persist; the "portal drop" explained

NVS dump (`0x9000`, ns `"sc"`) contains: **`ssid0`, `ssid1`, `ssid2`** (+ `pass*`), **`srv_host = 192.168.x.x`**, **`srv_user = a***1`** (masked), and **`wiped_v1` = set**. (`srv_port`/`srv_pass` are stored too — `srv_port` is an int blob, invisible to `strings`.) Three WiFi SSIDs present (masked `A***`, `G***`, `A***`) = the portal-seeded network + `_syncNetworks()` pulls.

**Reconciliation of "connected-then-portal":** the culprit is the **one-time NVS wipe** in `setup()` (`sPrefs.clear()` gated by `wiped_v1`). Timeline:
1. Spike had replaced NVS → on the **first production boot**, `wiped_v1` was absent → the one-time wipe ran → cleared WiFi creds → Dio dropped to the **Dio-Setup portal**.
2. You set WiFi in the portal → `/save` wrote `ssid0` + the atomic server record → reboot → Dio **connected** (MAC-verified `44:1b:f6:xx:xx:xx @ 192.168.x.x → 7331`), then `_syncNetworks()` added `ssid1/ssid2`.
3. `wiped_v1` is **now set** → the wipe never fires again.

**Does evidence support creds not persisting? — No.** Creds persist (they're in NVS now, `wiped_v1` set). The portal drop was a **one-shot, now-spent** wipe, not a persistence bug.
**Latent caveat (noted, not a fix):** the one-time wipe does `sPrefs.clear()` on the whole `"sc"` namespace — so a *future* `erase_flash` (which clears `wiped_v1`) would wipe a user-customized **server record** too, not just WiFi, on the next boot. Acceptable for a fresh-start, but worth knowing before any future erase.

---

## 6. Verdict + one ordered fix list

Dio is **largely healthy**: production restored, Iris lessons shipped, reaching Nyx over the LAN mkcert path, creds persistent. This audit is a state-map, not a failure post-mortem. Findings ranked by what the next flash should carry:

1. **LISTENING cue not yet on device** — in-source, build-verified (§1). *Ship it.*
2. **Chat unverified since restore** (§2) — no failing stage found; needs an e2e run, **not a code fix**. *Verify after flash.*
3. **Si12T head-pat** (§3) — never implemented **and** not hardware-verifiable in download mode. *Keep scoped; do NOT put an unverified new feature in the fix flash.*
4. **Songs** (§4) — belong on SD `/karaoke/`. *File copy, not firmware.*
5. **One-time-wipe caveat** (§5) — documented; no action this cycle.

### The ONE flash (minimal, low-risk)
`arduino-cli compile --upload --fqbn m5stack:esp32:m5stack_cores3 firmware/Ph3b3-Chan` — the current source (production + Iris lessons + **purple LISTENING cue**), 1.385 M. Regular upload preserves NVS (WiFi + server record survive). **Delta vs device = the LISTENING cue only** — everything else is already shipped, so this is a small, safe flash.

**Explicitly NOT in this flash:** Si12T head-pat (scoped, unverified). **Rides alongside as a file op:** copying new song `.wav`/`.lrc` into `/media/$USER/6566-3235/karaoke/`.

### Post-flash verification (the open loop)
Boot Dio → screen target line `192.168.x.x:7331` + status **`online`** → **crescent-tap/voice chat round-trip** (closes §2's unverified chat) → confirm LISTENING LEDs go **purple** while recording. Then, on a *running* device, an I2C scan can finally settle §3 (is a Si12T even present at `0x6F`?) before any head-pat work is scheduled.

---

## Rails honored during this audit
No fixes, no flashes, no config changes. `SPI.begin` landmine untouched (and confirmed the SD path doesn't trip it). Servo/VAD(700ms)/face-timing/boot-greeting unread-for-change. Color contract intact (listening=purple, pat=pink). Spike tree (`~/spikes/dio-tailnet`) untouched.
