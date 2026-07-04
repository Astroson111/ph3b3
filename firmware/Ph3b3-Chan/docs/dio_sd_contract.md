# Dio SD / karaoke contract

Derived from source (`KaraokeApp.h`) — what a card must satisfy to be a drop-in for Dio's karaoke. No firmware changes; this is the read.

## Interface
- `SD.begin(4, SPI, 20000000)` — CS pin 4, **reuses M5's existing SPI bus** (not a bare `SPI.begin` — landmine avoided), 20 MHz clock (conservative).
- **exFAT is proven** — Dio's 239 GB card is exFAT and the firmware reads it, so the ESP32 SD/FatFs layer here has exFAT enabled. FAT32 would also work. **No SDHC-vs-SDXC assumption** in the scanner: 16 GB (SDHC) and 239 GB (SDXC) both go through the same `SD.begin`; the 20 MHz SPI clock handles either.

## Layout contract (`_scanTracks`, `_startTrack`)
| Rule | Detail |
|---|---|
| Root dir | **`/karaoke`** at card root (must be a directory) |
| Scan | flat `openNextFile()` over `/karaoke` — **subfolders are NOT recursed** (only entries whose name ends in `.wav` become tracks) |
| Track file | **`<stem>.wav`** — stem = filename minus the last 4 chars |
| `.wav` detection | **case-insensitive** (name is lowercased before the `.wav` test) |
| Playback open | constructs `"/karaoke/" + stem + ".wav"` (lowercase ext) — fine on exFAT/FAT (case-insensitive, case-preserving) |
| Lyrics | **`<stem>.lrc`** (same stem) — **OPTIONAL**. Missing `.lrc` ⇒ song plays with **no synced lyrics** (`_loadLyrics` just returns empty). Not a failure. |
| LRC format | lines `[mm:ss.xx]text`; lines <9 chars or not starting with `[` are skipped |
| Index file | **none** — pure directory scan, sorted alphabetically |
| Other files | anything not ending `.wav` (e.g. `*.attribution.json`) is **ignored** — harmless |
| Filenames | LFN via exFAT — spaces/unicode/long names OK; no 8.3 limit on exFAT. (Our library uses ascii + hyphens, no spaces.) |

## WAV requirement (`_parseWavHeader`)
- Must be **RIFF/WAVE**, **`audioFmt == 1` (PCM)**, **`bitsPerSample == 16`**. These are the hard checks.
- `sampleRate` and `channels` are **read and adapted** (playback uses the file's rate; `_stereo = channels==2`), so mono/other rates technically play — but the **known-good / canonical spec is `pcm_s16le, 44100 Hz, stereo, 16-bit`** (matches `track.wav` and every staged song). Author to that spec for consistency.

---

## Card audit — DIO-BACKUP (16 GB) vs the contract  *(2026-07-04)*

| Check | Result |
|---|---|
| Filesystem | **exFAT** ✅ (matches the proven 239 GB card) |
| `/karaoke` at root, flat | ✅ |
| `.wav` files | 9, **all `pcm_s16le/44100/2/16`** ✅ (ffprobe'd; 0 violations) |
| Pairing | 2 songs have `.lrc` (`into-the-sky`, `lofi-chillout-hip-hop-be`); the other **7 have no `.lrc`** → they **play without lyrics** (contract-legal, just noted) |
| Extra files | 9 `*.attribution.json` — **ignored** by scanner, harmless (and document noncopyright licensing) |
| Filenames | ascii + hyphens, no spaces, well under limits ✅ |
| Deltas vs 239 GB card | backup has the **noncopyright song library**; it does **not** carry Dio's demo `track.wav/.lrc` (those stay on the primary/source card). Not a violation — the backup is its own valid library. |

**Verdict: DIO-BACKUP satisfies the contract — a valid drop-in.** Only note: 7 songs will play without synced lyrics until `.lrc` files are added.

**✅ CERTIFIED 2026-07-04 — swap test PASSED.** Dio powered off → 239 GB out, DIO-BACKUP in → boot → Karaoke browser showed **`1 / 9`** and a track **played**. The 16 GB exFAT backup is a proven drop-in spare for Dio's karaoke. Intake for either card via `scripts/add_song.sh <dest> <song.wav> [<song.lrc>]`.
