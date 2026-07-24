# Barge-in — Phase 0 Recon

**Status:** findings only. No code changed, no device flashed.
**Scope:** the outbound speech pipeline end-to-end (Nyx server + Dio firmware + browser
surfaces), and what it would take to let the user cut Phoebe off mid-answer.
**Repos read:** `ph3b3_v2` @ `main` (server + browser UIs); `Dionysus/Ph3b3-Chan/` (Dio firmware).

> Line references are accurate as of the recon date and will drift as the code changes.
> Treat them as pointers, not guarantees — re-grep before relying on an exact line.

---

## TL;DR — three findings that reframe the original brief

1. **There is no live LLM token stream to tear down.** The model runs to **full completion**
   (`stream: False`, `agent/server.py:1168`) *before any audio exists*. `/chat/stream` streams
   already-finished **text**, sliced into TTS chunks the device pulls one at a time. The brief's
   stated "hard part" (cancelling a half-finished LLM stream + TTS chunker mid-sentence) largely
   does not apply to the current architecture.

2. **Tap-to-interrupt already exists on both devices.** Dio flushes audio on any touch during
   playback (`_bargeIn`), Iris on BtnA. The only playback surfaces with **zero** interrupt today
   are the two browsers (`static/panel.html`, `static/index.html`).

3. **The echo question is decisively answered: no self-echo today, because there is no live mic
   during playback.** Mic and speaker are strictly I2S-exclusive on the CoreS3 — the mic is fully
   `M5.Mic.end()`ed before Phoebe speaks. That same fact makes *voice* barge-in impossible without
   re-architecting to concurrent mic+speaker, and there is **no AEC anywhere in the firmware**.

---

## 1. The chain (LLM tokens → audio off the box)

Full-reply generation, then text chunking, then lazy per-chunk Piper synth, then client-pull delivery.

- **Generation (blocking, not streamed).** `_run_chat_pipeline` (`agent/server.py:1550`) produces the
  whole reply string. It calls `chat_with_tools` (`agent/server.py:1166`), a single blocking
  `await client.post` to Ollama `/api/chat` with `stream: False` (`:1168`). The tool loop
  (`while msg.get("tool_calls") and loop < 5`, `:1179`) can fire several sequential blocking calls
  before `content` is returned. No async generator, no `client.stream`, no `aiter_*` on the Ollama path.
- **Chunking.** `chat_stream_endpoint` (`:1941`) receives the finished `reply`, then
  `split_for_tts(reply)` (`modules/tts_chunker.py:115`) slices it. The chunker is pure text-in/list-out —
  no I/O, no stop hook.
- **Per-chunk synthesis.** `_tts_chunk_b64` (`:1892`) → `tts.synthesize_to_b64` (`modules/tts_module.py:314`),
  which runs Piper as a **blocking `subprocess.run(..., timeout=30)`** (`tts_module.py:328`) inside a
  `threading.Lock`, dispatched via `asyncio.to_thread`.
- **Delivery.** First chunk returns in the `/chat/stream` POST response; the rest are pulled by
  `GET /tts/chunk/{stream_id}/{n}` (`:1981`), lazily synthesized on demand.

**Wire protocol (per chunk):** `text` is emitted **before** `audio` (base64 WAV, 22050 Hz mono) so
firmware can caption in sync; `last` flags stream end; the first payload also carries the entire reply
text in `response`.

**On device:** `TalkApp::_doChatAndPlay` (`Dionysus/Ph3b3-Chan/TalkApp.h:858`) POSTs `/chat/stream`,
plays chunk 0, then loops `GET /tts/chunk/{sid}/{n}` for the rest. Playback is via **M5.Speaker
(M5Unified I2S)**, a double buffer `pcmBuf[2][2048]` (`:342`) plus a 2-deep DMA queue. **No FreeRTOS
audio queue** — the whole reply plays inline and blocks `loop()`.

**Buffers between stages:**
- `_TTS_STREAMS` (server, module-global dict, `:1878`): `sid → {chunks, audio{n}, ts, voice}`.
  15-min TTL GC. **No cancel/stop field.**
- M5.Speaker DMA queue (device, ≤2 buffers, flushable via `M5.Speaker.stop(0)`).
- `peek[6144]` HTTP head buffer (device).
- `Session.history` rolling 8-turn window (server, `:1264`).
- No `asyncio.Queue` anywhere on this path.

---

## 2. Cancellation surface (what exists to stop each stage today)

| Stage | Stoppable today? | Evidence |
|---|---|---|
| LLM generation | **No** | Single uncancellable `await client.post`, `stream:False`; no task handle / abort flag (`server.py:1166-1175`) |
| TTS chunker, between chunks | **No server hook** | Client-pull; server has no say/knowledge. `/tts/chunk` polls no flag (`:1981`) |
| TTS mid-chunk (Piper) | **No** | Blocking `subprocess.run` in a thread; no `Popen` handle / `.terminate()` (`tts_module.py:328`) |
| Audio playback (device) | **Yes — already** | `M5.Speaker.stop(0)` flushes DMA; wired to touch `_bargeIn` + 5s watchdog (`TalkApp.h:1008-1014`, `1000-1005`). Latency <100 ms |
| Client disconnect → server stop | **No** | Plain JSON POST/GET, not `StreamingResponse`; no `request.is_disconnected()`. Dropped conn just ages out of `_TTS_STREAMS` after 15 min |

**Reusable pattern:** the only in-flight cancel in the server is Kadmos PDF reads — a cooperative
between-unit flag (`_kadmos_cancel` + an `is_cancelled()` closure polled between chunks,
`server.py:911 / 948 / 965`) — and Morpheus renders (`:3741`). Good template, but scoped away from
speech; it would have to be **built** onto the speech path.

---

## 3. State machine + the re-arm defect

**The server has no conversation state machine and tracks no device state.** It is stateless per
request. `udp/7332` is **log-only** telemetry (`_DioStateProtocol`, `server.py:150-157`) — it writes
each Dio transition ping to the journal and never parses/stores/acts on it. All IDLE/LISTENING/SPEAKING
logic lives in **Dio firmware** (`Dionysus` repo).

**Device states:** `Phase { PH_IDLE, PH_AWAITING, PH_RECORDING, PH_DONE, PH_ERROR }`
(`TalkApp.h:369`). **There is no distinct SPEAKING phase** — `_phase` stays `PH_RECORDING` through
dispatch + playback; only the *face* renders a SPEAKING state.

**Post-reply transition** is owned by `_dispatch()` (`TalkApp.h:686-718`):
- Barge-in path (`:687-694`): `_startRecording()` → straight back to listening.
- Exit-word path (`:700-704`): `_endConversation()` → `_startAwaiting()` → **PH_AWAITING** (ambient).
- Continuous-loop path (`:708-714`): if `ok && _inConversation` → `_startRecording()` (intended re-arm).
- Fallthrough (`:716-718`): if `!ok` **or `!_inConversation`** → `PH_DONE`/`PH_ERROR`
  (`PH_DONE` re-arms to `PH_AWAITING` next tick).

**The "re-arm defect", precisely:** the *documented* landing after a reply is **PH_AWAITING (ambient
listening), not IDLE**. True `PH_IDLE` only happens on dead-air `_exitChatMode` (`:831-841`) or `exit()`.
The clean loop-back only fires while `_inConversation` is still true; that flag is cleared in several
places (short capture `:504`, junk transcript `:637-639`, idle-timeout `:538-543`, transcribe error
`:626`). **So "she drops to a non-listening rest state after replying" most likely traces to
`_inConversation` being cleared before the reply completes → fallthrough `:716-718`, not to a broken
re-arm call.**

**Does barge-in's "return to LISTENING not IDLE" share this path?**
- **Server:** no — there is no server-side transition code to share; a server `interrupt()` would be
  net-new surface.
- **Device:** yes — but Dio's existing barge-in already calls `_startRecording()` (`:687-694`), routing
  *around* the fallthrough. Any new interrupt should keep doing that.

---

## 4. Echo reality on Dio — honest verdict

**No self-echo today, because mic and speaker are never concurrent.** The I2S BCK/WS bus is single-owner,
enforced by begin/end pairing, not a mixer:

- `_stopRecordingAndDispatch` tears the mic down before any speaker use:
  `M5.Mic.end(); M5.Speaker.end(); M5.Speaker.begin();` (`TalkApp.h:497-499`).
- `_startRecording` reverses it: `M5.Speaker.stop(0); M5.Speaker.end(); delay(30);` then
  `M5.Mic.begin()` (`:476-485`), comment: "Ensure speaker I2S is fully released before mic claims the
  shared BCK/WS bus" (`:473`).
- During `_doChatAndPlay` playback the mic is **not** running (`M5.Mic.begin()` is never called inside it).
- Purr arbitration confirms the same rule: `micIdle()` = `_phase == PH_IDLE` (`:80`); `purr()` refuses if
  `M5.Speaker.isPlaying(0)` (`:85`). VadStream only reads a ring buffer — not a second I2S owner.

**Consequence for barge-in:** Dio's mic **cannot** capture its own speaker output — because the mic is
off while she speaks. But *voice* barge-in requires running the mic **during** playback, which the
firmware deliberately never does. Do that, and self-capture of the TTS becomes a real problem — and
there is **no AEC anywhere** (grep for `aec`/`echo`/`cancel` finds nothing). This is exactly the Phase 3
blocker, confirmed in code.

---

## 5. Scope — where Phoebe's speech plays back

Two TTS endpoints carry audio: **`/chat`** (whole reply as one base64 WAV in `{response, audio}`,
`server.py:1854-1868`) and **`/chat/stream`** (chunked manifest + `/tts/chunk/{id}/{n}`).
Comment at `server.py:1857`: *"Iris + web UI depend on [`/chat`] — do not change. Chunked delivery is
/chat/stream."*

| Surface | File / ref | Endpoint | Delivery | Interrupt today |
|---|---|---|---|---|
| **Portal** | `static/panel.html:2140, 2105-2122` | `/chat` | whole WAV, `new Audio()`, fire-and-forget | **None** |
| **Legacy index.html** | `static/index.html:461, 434-454` | `/chat` | whole WAV, Web Audio `BufferSource`, awaited | **None** |
| Iris combadge | firmware (not in repo); `docs/HACKSTER_UPDATE.md:17-19, 82-91` | `/chat` | whole WAV, firmware chunk-decodes | **Yes** — BtnA `M5.Speaker.stop()` |
| Dio (stack-chan) | `server.py:1941-1996`; `TalkApp.h:858` | `/chat/stream` | chunked TTS | **Yes** — touch `_bargeIn` |
| Nyx desktop UI | `agent/chat_ui.py:454-463` | `/chat` | ignores `audio` — never plays TTS | n/a |

**Design-once reality:** a single browser `interrupt()` covers **both** browsers (panel + index — both
`/chat` whole-WAV players with a local-const `Audio` object and no `AbortController`), but reaches
**neither** Iris nor Dio (those play and interrupt in firmware, and already have BtnA/touch interrupts).
So the only genuinely-unbuilt barge-in surface is **the two browsers**.

> Note: the Iris `device_command` `{"action":"stop"}` (`modules/device_commands.py:39-40`,
> `server.py:2203-2213`) stops the SD-card **music track**, not Phoebe's spoken reply — different path,
> do not conflate.

---

## The Mnemosyne question — answered, and narrower than feared

When a reply is interrupted, Phoebe generated more than the user heard. What gets written?

- **Mnemosyne (semantic cross-device recall) never stores Phoebe's replies** — only the user's message
  (`server.py:1823`; deliberate, comment `:1816-1819`: storing replies let refusals poison auto-recall).
  **Interrupted replies cannot poison recall. This store is barge-in-neutral.**
- **The full reply *is* written** to (a) the **Argus Chats transcript** (`chat_log.log_turn(..., "phoebe",
  response)`, `server.py:1837`) and (b) the **session history window** (`session.add("assistant",
  response)`, `:1809`) — **both before any audio is synthesized.** These are the records that would say
  "Phoebe said X" when the user only heard chunk 1.
- **The truncation point is structurally unknowable at write-time**, because those writes fire *before*
  `_TTS_STREAMS` even exists (chunking happens later, `:1965`). There is no "delivered up to N" accounting
  on `_TTS_STREAMS` today — only a `ts` touch and the presence of a cached-audio key.

**Recommendation:** record what was **spoken** with an explicit `interrupted` marker, and scope it to the
**transcript + session history only** — leave Mnemosyne as-is (already clean). This requires new
per-chunk delivered-count accounting plus deferring/rewriting those two writes until after playback.
**Decide this before any Phase 1 build.**

**Logging:** an interrupted turn is worth seeing distinctly — trigger source, elapsed playback time,
whether the LLM stream was cancelled (today: it wasn't — generation already completed). Argus is the
natural home.

---

## What this means for the phases

- **Phase 1 (stop machinery):** smaller than the brief assumed. The device path is already flushable;
  the server LLM-cancel problem is largely *moot* because generation finishes before audio exists. The
  genuine Phase-1 work is **(a)** a browser `interrupt()` for the two web surfaces and **(b)** the
  transcript/session "record-what-was-spoken + `interrupted` marker" change. Server-side LLM/TTS cancel
  is only worth building to stop *wasting compute* on an abandoned reply — real, but a separate
  optimization; the Kadmos flag pattern is the template.
- **Phase 2 (tap-to-interrupt):** **already shipped on Dio and Iris.** The only missing click/tap-to-stop
  is the browser. Worth a device re-verify, but likely no firmware change.
- **Phase 3 (voice barge-in):** blocked exactly as predicted, confirmed by code (no concurrent
  mic+speaker; no AEC). QM decision among: on-device AEC / reference-signal gating / keyword-only /
  accept half-duplex + tap. **No detection scheme was implemented in recon.**

## Two decisions before any Phase 1 work

1. **Memory-on-interrupt:** confirm "record spoken text + `interrupted` flag, transcript/session only,
   leave Mnemosyne untouched."
2. **Phase 1 scope:** target the **browser interrupt gap** (the only truly-unbuilt surface), and/or the
   **server-side compute-cancel** (stop the abandoned LLM/TTS to save GPU/CPU)?

## Out of scope / do not touch (per brief)

- The re-arm defect fix itself (separate brief); this doc only reports whether it shares a path — it does
  not (server), and Dio's barge-in already routes around it.
- VAD endpoint work (paused).
- Barge-in on surfaces beyond those mapped in §5.
- Alba config, the WireGuard block in `start.sh`, the content-safety floor, face render timing.

## Load-bearing files

`agent/server.py` (1166, 1550, 1809, 1821-1837, 1854-1868, 1878, 1892, 1941, 1981; 150-157;
911/948/965) · `modules/tts_module.py:314` · `modules/tts_chunker.py:115` · `agent/memory_spine.py:176`
· `modules/chats.py:41` · `static/panel.html` (2105-2122, 2140) · `static/index.html` (434-454, 461) ·
`Dionysus/Ph3b3-Chan/TalkApp.h` (369, 460-499, 686-718, 858-1117) · `docs/HACKSTER_UPDATE.md` (17-19,
82-91).
