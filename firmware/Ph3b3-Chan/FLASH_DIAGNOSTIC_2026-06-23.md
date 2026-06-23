# rung4 flash diagnostic — 2026-06-23

Two commits since last flash (main@c226315 → dad900a).
Both touch KaraokeApp only, except the TalkApp TLS fix.

---

## Changes in this build

### 1. TalkApp.h — TLS close timeout cap (c226315)

**What changed:** `_tls.setTimeout(500)` inserted before `_tls.stop()` in `exit()`.

**Why:** With `HTTPClient::setReuse(true)` the TLS socket stays live after each
conversation turn. The previous code called `stop()` with the default 30-second
timeout still set, so switching away from TalkApp after a conversation could
freeze the display for up to 30 seconds while the TCP FIN/ACK round-tripped
over Tailscale.

**Risk:** Low. 500ms is generous for a local Tailscale hop; if the socket is
already closed (or was never opened — e.g. you switch to Karaoke before
speaking) `stop()` returns immediately regardless of timeout.

**Verify:** Switch from TalkApp → Karaoke immediately after a conversation turn.
The menu should appear within ~1 second, not 5–30.

---

### 2. KaraokeApp.h — SD init moved + I2S settle delay (c226315)

**What changed:**
- `SD.begin(4)` moved from `_startPlayback()` (every tap) → `init()` (once per
  mode entry). `_sdMounted` flag guards subsequent calls.
- `delay(30)` added before `M5.Mic.begin()` in `init()` to let the shared
  BCK/WS I2S lines settle after TalkApp tears down the speaker bus.

**Why:** `SD.begin(4)` re-runs the full SPI card handshake (~200-500ms) every
time the user tapped. That blocked `loop()`, froze the display, and made the
device appear hung. The settle delay matches the pattern TalkApp already uses
internally in `_startAwaiting()`.

**Risk:** Low. One-time SD init cost moves from "on every tap" to "on mode
entry" — a brief pause when selecting Karaoke from the crescent menu is now
expected and acceptable.

**Verify:** Enter Karaoke mode — brief pause (~300-600ms total for SD init +
mic init) is normal. After that, tapping to play a track should be
instantaneous.

---

### 3. KaraokeApp.h — full track browser (dad900a)

**What changed:** STOPPED state replaced with BROWSING. `_scanTracks()` reads
`/karaoke/*.wav` on SD at init and builds a sorted `std::vector<String>` of
stems. New `_drawBrowser()` renders in the bottom 80px strip (face stays in
top 160px). Touch zones across full screen:

| Zone | Action |
|------|--------|
| Top third (y < 80) | Prev track (wraps) |
| Centre (80 ≤ y ≤ 160) | Play selected track |
| Bottom third (y > 160) | Next track (wraps) |

`_startPlayback()` now opens `/karaoke/<stem>.wav` and attempts
`/karaoke/<stem>.lrc` (silently skipped if absent — `.attribution.json` files
are ignored by the `.wav` filter).

**Risk:** Medium. This is the largest change. Three things to verify:

1. **SD scan returns the right files.** The ESP32 Arduino SD lib's `f.name()`
   behaviour differs across versions — it may return `"song.wav"` or
   `"/karaoke/song.wav"`. The code strips everything before the last `/`, but
   if a third SD lib variant exists this could produce malformed stems. Check
   Serial for `[KAR] found N track(s)` — if N is wrong, this is the culprit.

2. **Touch zone calibration on Core2 vs CoreS3.** `Display().height()` returns
   240 on both, so zone boundaries (80/160px) are the same. Verify taps in
   each zone do what they should — the crescent tab exclusion zone
   `!(tx < 60 && ty < 60)` is unchanged.

3. **Playback path matches what the web app pushes.** `mnemosyne.py` uses
   `_stem()` (lowercase, dashes, max 24 chars) and saves as
   `/karaoke/<stem>.wav`. The firmware scans case-insensitively and strips
   the extension. If a stem on SD differs from what `_scanTracks()` builds
   (e.g. wrong case, extra chars), the file won't open. Check Serial for
   `[karaoke] can't open /karaoke/<stem>.wav`.

---

## Serial output to watch on first boot

```
[KAR] KaraokeApp init enter
[KAR] face.begin(320,160) Xms
[KAR] SD.begin + scan Xms     ← should be 300-700ms total
[KAR] found N track(s)        ← N should match files on SD card
[KAR] Mic.begin Xms
[KAR] KaraokeApp init done Xms total
```

If `SD.begin + scan` line is missing or N=0 with tracks present → SD issue.
If `Mic.begin` hangs → I2S settle issue (try increasing delay(30) → delay(50)).

On play:
```
[karaoke] playing: <stem>
```

On bad WAV:
```
[karaoke] bad WAV header
```

---

## Files changed

| File | Commits |
|------|---------|
| `firmware/stackchan_rung4/KaraokeApp.h` | c226315, dad900a |
| `firmware/stackchan_rung4/TalkApp.h` | c226315 |

No changes to: AppBase.h, CrescentMenu.h, AppManager.h, TalkApp.h (beyond
TLS fix), stackchan_rung4.ino, GhostApp.h, NetworkApp.h.

---

## FQBN reminder

- **Core2**: `m5stack:esp32:m5stack_core2`
- **CoreS3**: `m5stack:esp32:m5stack_cores3`

Flash Core2 first (lower risk for SD lib behaviour verification).
