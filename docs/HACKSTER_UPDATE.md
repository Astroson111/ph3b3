# Hackster.io Update — Iris voice combadge milestone

*Content for updating the Ph3b3 / Iris project article. Paste into the relevant sections.*

---

## Story update — what's new

### Iris is fully operational

The combadge works. You hold the button, you talk, and she answers — in her own voice, on a device smaller than a lighter, worn on your wrist like a badge from a sci-fi show you grew up watching. Here's what it took to get there.

---

### The voice round-trip

Hold BtnA: Iris opens the microphone (M5StickS3's ES8311 codec, 16 kHz mono 16-bit PCM), shows the LISTENING state on her animated face, and records until you release. On release she wraps the audio in a standard WAV header and POSTs it to Ph3b3 over HTTPS — to `/transcribe`, where Whisper on CUDA transcribes it in seconds. The transcript goes directly to `/chat`, which runs it through Hermes3 with her full soul and system prompt intact. Ph3b3 responds with a JSON payload containing both the text reply and a base64-encoded TTS audio clip (Piper, Alba en_GB voice).

Iris streams the audio back to the speaker as it arrives. She doesn't wait for the full response — she decodes and plays it in chunks.

### Clean audio: double buffering

The M5StickS3 has one speaker and one codec. The first audio implementation used a single static PCM buffer: the TLS decoder wrote into it from position zero while the speaker was reading from position zero. It worked most of the time — until it didn't, producing audible cuts and glitches.

The fix is a double buffer. Two buffers, same size. Buffer A plays. While it plays, the decoder fills buffer B from the incoming TLS stream. When A finishes, playback switches to B and the decoder starts filling A again. The speaker never reads a buffer being written; the decoder never writes a buffer being read. The audio is now clean.

### Interrupt

She talks a lot. That's fine — but you need to be able to stop her.

Press BtnA mid-sentence and she stops immediately. The button check runs inside the decode loop (between byte reads from the TLS stream) and inside the final playback wait. No polling delay; no waiting for the current chunk to finish. She stops.

This closes a natural interaction loop: she speaks, you interrupt, you speak. Push-to-talk *and* push-to-interrupt on the same button.

### Multi-network WiFi, managed from the app

Iris stores up to five WiFi networks in her NVS (non-volatile storage). At boot she scans and connects to whichever known SSID has the strongest signal — so she automatically picks the home network at home and the hotspot in the field without any intervention.

If she loses the connection, a non-blocking supervisor ticks every 12 seconds and tries each stored network in rotation. The supervisor never calls `WiFi.scanNetworks()` — that blocks the main loop for several seconds and swallows button events. It just alternates slots with a 200 ms settle delay between attempts.

Networks are managed through the Control Panel web app — a new Iris tab lets you add or remove SSIDs from any phone on the network. When Iris reconnects, she pulls the current list from Ph3b3 and updates her NVS automatically. You never need to flash her or open a captive portal to change her networks.

### A certificate story

Two days before this demo, Iris stopped talking. Every request — `/chat`, `/transcribe`, everything — returned `err -1`. Heap was fine (155 KB free). WiFi was fine. Ph3b3 was running. The panel worked from a browser.

The cause: Let's Encrypt renewed the server certificate overnight and switched from the RSA certificate chain (ISRG Root X1) to an ECDSA chain (ISRG Root X2, intermediate YE2). The firmware had only Root X1 pinned. Every TLS handshake failed silently.

The fix is a concatenated PEM bundle — Root X1 and Root X2 together, passed to `tls.setCACert()`, which accepts a multi-cert string and validates against any of them. Future renewals won't matter which chain Let's Encrypt chooses.

---

## Hardware

No change from the original build:

- M5StickS3 (ESP32-S3FN8, 8 MB flash, no PSRAM, ES8311 codec, 135×240 display)
- Worn as a badge

The ESP32-S3 has 268 KB of free heap at runtime. The audio pipeline at peak occupies: 96 KB (PTT recording buffer) + up to 128 KB (base64 JSON buffer) + ~72 KB (TLS stack). Timing the heap operations so these don't overlap simultaneously was a significant part of the engineering work.

---

## Code highlights

**Double buffer:**
```cpp
static const int CHUNK_SAMPLES = 1024;   // ~46 ms @ 22050 Hz
static int16_t pcmBuf[2][CHUNK_SAMPLES];
int fillIdx = 0;

auto flushChunk = [&]() {
  if (chunkPos == 0) return;
  while (M5.Speaker.isPlaying()) delay(1);
  if (!keepGoing) return;
  M5.Speaker.playRaw(pcmBuf[fillIdx], chunkPos, 22050, false, 1, 0);
  fillIdx ^= 1;   // swap
  chunkPos = 0;
};
```

**Interrupt:**
```cpp
while (keepGoing && millis() < deadline) {
  M5.update();
  if (M5.BtnA.wasPressed()) { M5.Speaker.stop(); keepGoing = false; break; }
  int c = raw->read();
  if (c < 0) { delay(1); continue; }
  feedCh((char)c);
}
```

**Multi-network boot scan:**
```cpp
int pickBestNetwork(const String ssids[], int netCount) {
  int n = WiFi.scanNetworks();
  int bestSlot = -1, bestRssi = -999;
  for (int i = 0; i < n; i++)
    for (int s = 0; s < netCount; s++)
      if (ssids[s].length() && WiFi.SSID(i) == ssids[s])
        if (WiFi.RSSI(i) > bestRssi) { bestRssi = WiFi.RSSI(i); bestSlot = s; }
  WiFi.scanDelete();
  return bestSlot;
}
```

---

## What's next

- Wake word (always-listening, no button required) — TFLite Micro on the S3's second core
- External speaker element — the ES8311 codec is clean; the onboard speaker is the bottleneck
- Word wrap on the reply overlay — long responses currently clip at the screen edge

---

## Morpheus — local image generation

The cloud is just someone else's computer. Morpheus isn't that. Every image is made on one graphics card in one room and never touches a network — no watermark stamped in by a service you don't control, no prompt logged to someone's server, no terms that change next quarter.

Running it locally was the point. So was drawing a hard line and welding it shut. Morpheus will not generate sexual content involving minors, non-consensual imagery, or compromising depictions of real people — and that floor isn't a preference you can toggle, it's built into the thing itself. Privacy and responsibility aren't opposites. You can own your compute and still refuse to make the worst of it.

---

## Karaoke

Not everything she does has to be serious. The karaoke corner started as proof that a privacy-first local assistant doesn't have to feel like a server with a face — it can also just be fun. Lyrics sync to the track, a moon follows the line you're on, and the whole thing runs offline on the same hardware doing the real work.

A robot you actually want in the room is a different kind of useful than a robot that just answers questions. This is the part that makes her hers.
