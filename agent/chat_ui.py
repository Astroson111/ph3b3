#!/usr/bin/env python3
"""Ph3b3 Chat UI — dark purple terminal for the local AI companion."""

import base64
import collections
import datetime
import os
import queue
import tempfile
import threading
import time

# Ensure a display is set before tkinter tries to connect.
# Defaults to :0 (the physical desktop) if nothing is in the environment.
os.environ.setdefault("DISPLAY", ":0")

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
import tkinter as tk
from tkinter import font as tkfont

SERVER      = "http://localhost:7331"
SAMPLE_RATE = 16000
CHUNK_MS    = 80        # stream read chunk length

# ── Voice activity detection (AUTO mode) ──────────────────────────────────────
VAD_THRESH    = 0.018   # RMS above this = speech (overridden by calibration)
VAD_SILENCE   = 1.4     # seconds of silence to end an utterance
VAD_MIN_SPEAK = 0.4     # discard utterances shorter than this
VAD_PRE_ROLL  = 0.4     # seconds of audio to keep before first speech frame

# ── Colour palette ─────────────────────────────────────────────────────────────
BG_ROOT  = "#0a0a14"
BG_CHAT  = "#0d0d1c"
BG_INPUT = "#0f0f22"
BG_PANEL = "#0c0c1e"
FG_MAIN  = "#e2d9f3"
FG_DIM   = "#5b5280"
FG_USER  = "#a78bfa"
FG_PH3B3 = "#c084fc"
FG_TS    = "#3d3660"
ACCENT   = "#7c3aed"
GLOW     = "#a855f7"
SEP      = "#2a1f4a"

# Mic circle – HOLD palette
MIC_H_REST  = "#1e1730"
MIC_H_REC   = "#4c1d95"
RING_H_REST = "#4a3880"
RING_H_REC  = GLOW

# Mic circle – AUTO palette
MIC_A_WAIT  = "#071510"
MIC_A_CAP   = "#14532d"
RING_A_WAIT = "#166534"
RING_A_CAP  = "#22c55e"

# Mode button colours
BTN_ACTIVE_HOLD = ACCENT
BTN_ACTIVE_AUTO = "#15803d"
BTN_LIVE_AUTO   = "#22c55e"
BTN_INACTIVE    = "#18182e"

STATUS_FG = {
    "Idle":      "#3d3660",
    "Listening": "#22c55e",
    "Thinking":  "#f59e0b",
    "Speaking":  "#38bdf8",
}


class Ph3b3UI:
    # ── Init ────────────────────────────────────────────────────────────────────
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()          # hide from WM until we've set our geometry
        self.root.title("Ph3b3")
        self.root.configure(bg=BG_ROOT)
        self.root.resizable(True, True)
        self.root.geometry("1000x750")
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))
        self.root.minsize(640, 520)

        self._status    = "Idle"
        self._mode      = "hold"      # "hold" | "auto"
        self._recording = False       # HOLD: currently recording
        self._capturing = False       # AUTO: capturing an utterance
        self._auto_on   = False       # AUTO loop running
        self._busy      = False       # chat request in-flight
        self._stop_rec  = threading.Event()
        self._stop_auto = threading.Event()
        self._pulse_n   = 0
        # Error dedup: track last message + when it was shown
        self._last_err:   str   = ""
        self._last_err_t: float = 0.0
        # Thread-safe UI queue: background threads put callables here;
        # _drain() processes them on the main thread.
        self._main_q: queue.Queue = queue.Queue()

        self._build_fonts()
        self._build_ui()

    # ── Fonts ────────────────────────────────────────────────────────────────────
    def _build_fonts(self):
        self.f_chat   = tkfont.Font(family="Monospace", size=12)
        self.f_bold   = tkfont.Font(family="Monospace", size=12, weight="bold")
        self.f_input  = tkfont.Font(family="Monospace", size=15)
        self.f_small  = tkfont.Font(family="Monospace", size=11)
        self.f_mode   = tkfont.Font(family="Monospace", size=11, weight="bold")
        self.f_status = tkfont.Font(family="Monospace", size=11, weight="bold")
        self.f_tiny   = tkfont.Font(family="Monospace", size=10)
        self.f_mic    = tkfont.Font(family="Monospace", size=30)
        self.f_italic = tkfont.Font(family="Monospace", size=10, slant="italic")

    # ── Top-level layout ─────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        tk.Frame(self.root, bg=ACCENT, height=1).pack(fill="x")
        self._build_chat()
        tk.Frame(self.root, bg=SEP, height=1).pack(fill="x")
        self._build_inputbar()

    # ── Status bar ───────────────────────────────────────────────────────────────
    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG_PANEL, height=42)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._dot = tk.Label(
            bar, text="●", fg=STATUS_FG["Idle"], bg=BG_PANEL, font=self.f_status
        )
        self._dot.pack(side="left", padx=(16, 6))

        self._status_lbl = tk.Label(
            bar, text="Idle", fg=FG_DIM, bg=BG_PANEL, font=self.f_small
        )
        self._status_lbl.pack(side="left")

    # ── Chat area ────────────────────────────────────────────────────────────────
    def _build_chat(self):
        frame = tk.Frame(self.root, bg=BG_CHAT)
        frame.pack(fill="both", expand=True)

        sb = tk.Scrollbar(
            frame, troughcolor=BG_CHAT, bg=BG_PANEL, width=8, relief="flat", bd=0
        )
        sb.pack(side="right", fill="y")

        self._chat = tk.Text(
            frame, bg=BG_CHAT, fg=FG_MAIN, font=self.f_chat,
            wrap=tk.WORD, state="disabled", cursor="arrow",
            relief="flat", bd=0, padx=20, pady=16,
            spacing1=5, spacing3=5,
            selectbackground=ACCENT, insertbackground=GLOW,
            yscrollcommand=sb.set,
        )
        self._chat.pack(side="left", fill="both", expand=True)
        sb.config(command=self._chat.yview)

        self._chat.tag_configure("ts",       foreground=FG_TS,    font=self.f_tiny)
        self._chat.tag_configure("user_hd",  foreground=FG_USER,  font=self.f_bold)
        self._chat.tag_configure("user_txt", foreground=FG_USER,  font=self.f_chat)
        self._chat.tag_configure("bot_hd",   foreground=FG_PH3B3, font=self.f_bold)
        self._chat.tag_configure("bot_txt",  foreground=FG_PH3B3, font=self.f_chat)
        self._chat.tag_configure("sys",      foreground=FG_DIM,   font=self.f_italic)

    # ── Input bar ────────────────────────────────────────────────────────────────
    def _build_inputbar(self):
        outer = tk.Frame(self.root, bg=BG_INPUT)
        outer.pack(fill="x")

        # ── Left column: text entry + control row ───────────────────────────────
        left = tk.Frame(outer, bg=BG_INPUT)
        left.pack(side="left", fill="both", expand=True, padx=(14, 8), pady=12)

        # Large text entry
        entry_wrap = tk.Frame(left, bg="#13132c",
                              highlightthickness=2,
                              highlightbackground=SEP,
                              highlightcolor=GLOW)
        entry_wrap.pack(fill="x")

        self._entry = tk.Entry(
            entry_wrap, bg="#13132c", fg=FG_MAIN, font=self.f_input,
            insertbackground=GLOW, relief="flat", bd=0,
        )
        self._entry.pack(fill="x", ipady=14, padx=10)
        self._entry.bind("<Return>",   self._on_send)
        self._entry.bind("<KP_Enter>", self._on_send)
        self._entry.bind("<FocusIn>",  lambda _: entry_wrap.config(highlightbackground=GLOW))
        self._entry.bind("<FocusOut>", lambda _: entry_wrap.config(highlightbackground=SEP))
        self._entry.focus_set()

        # Control row: SEND + mode toggle
        ctrl = tk.Frame(left, bg=BG_INPUT)
        ctrl.pack(fill="x", pady=(10, 0))

        self._send_btn = tk.Button(
            ctrl, text="SEND", bg=ACCENT, fg="white", font=self.f_mode,
            relief="flat", bd=0, padx=22, pady=9, cursor="hand2",
            activebackground=GLOW, activeforeground="white",
            command=self._on_send,
        )
        self._send_btn.pack(side="left", padx=(0, 14))

        # Mode toggle: [AUTO] [HOLD]
        mode_box = tk.Frame(ctrl, bg=BG_INPUT)
        mode_box.pack(side="left")

        self._btn_auto = tk.Button(
            mode_box, text="AUTO", font=self.f_mode,
            relief="flat", bd=0, padx=18, pady=9, cursor="hand2",
            command=lambda: self._set_mode("auto"),
        )
        self._btn_auto.pack(side="left", padx=(0, 3))

        self._btn_hold = tk.Button(
            mode_box, text="HOLD", font=self.f_mode,
            relief="flat", bd=0, padx=18, pady=9, cursor="hand2",
            command=lambda: self._set_mode("hold"),
        )
        self._btn_hold.pack(side="left")

        self._refresh_mode_buttons()

        # ── Right column: circular mic button ───────────────────────────────────
        right = tk.Frame(outer, bg=BG_INPUT)
        right.pack(side="right", padx=(0, 16), pady=12)

        MIC_SIZE = 120
        self._mic_cv = tk.Canvas(
            right, width=MIC_SIZE, height=MIC_SIZE,
            bg=BG_INPUT, highlightthickness=0
        )
        self._mic_cv.pack()

        r = 54
        cx = cy = MIC_SIZE // 2
        self._cx, self._cy, self._r = cx, cy, r

        # outer glow ring
        self._c_ring = self._mic_cv.create_oval(
            cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
            fill="", outline=RING_H_REST, width=3
        )
        # filled circle
        self._c_fill = self._mic_cv.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=MIC_H_REST, outline=""
        )
        # emoji label
        self._c_text = self._mic_cv.create_text(
            cx, cy, text="🎤", font=self.f_mic, fill=FG_DIM
        )

        self._mic_cv.bind("<ButtonPress-1>",   self._mic_press)
        self._mic_cv.bind("<ButtonRelease-1>", self._mic_release)

        self._mic_lbl = tk.Label(
            right, text="hold to speak", fg=FG_DIM, bg=BG_INPUT, font=self.f_tiny
        )
        self._mic_lbl.pack(pady=(6, 0))

    # ── Mode switching ───────────────────────────────────────────────────────────
    def _set_mode(self, mode: str):
        if mode == self._mode:
            if mode == "auto" and self._auto_on:
                self._stop_auto_loop()
            elif mode == "auto":
                self._start_auto_loop()
            return
        if self._mode == "auto" and self._auto_on:
            self._stop_auto_loop()
        self._mode = mode
        self._refresh_mode_buttons()
        self._reset_mic_visuals()
        if mode == "hold":
            self._ui(lambda: self._mic_lbl.config(text="hold to speak"))
        else:
            self._ui(lambda: self._mic_lbl.config(text="tap to start"))

    def _refresh_mode_buttons(self):
        """Paint mode buttons to reflect current _mode and whether auto is live."""
        if self._mode == "auto":
            auto_bg = BTN_LIVE_AUTO if self._auto_on else BTN_ACTIVE_AUTO
            auto_fg = "black" if self._auto_on else "white"
            self._btn_auto.config(bg=auto_bg, fg=auto_fg)
            self._btn_hold.config(bg=BTN_INACTIVE, fg=FG_DIM)
        else:
            self._btn_auto.config(bg=BTN_INACTIVE, fg=FG_DIM)
            self._btn_hold.config(bg=BTN_ACTIVE_HOLD, fg="white")

    def _reset_mic_visuals(self):
        """Return mic canvas to the idle state for the current mode."""
        if self._mode == "auto":
            fill, ring = MIC_A_WAIT, RING_A_WAIT
        else:
            fill, ring = MIC_H_REST, RING_H_REST
        self._mic_cv.itemconfig(self._c_fill, fill=fill)
        self._mic_cv.itemconfig(self._c_ring, outline=ring)
        self._mic_cv.itemconfig(self._c_text, fill=FG_DIM)

    # ── Thread-safe UI dispatch ──────────────────────────────────────────────────
    def _ui(self, cb) -> None:
        """Schedule a UI callback from any thread.
        From the main thread the callback runs immediately; from a worker thread
        it is queued and picked up by _drain() on the next tick."""
        if threading.current_thread() is threading.main_thread():
            cb()
        else:
            self._main_q.put(cb)

    def _drain(self) -> None:
        """Empty the inter-thread UI queue. Runs on the main thread at ~60 fps.
        Each callback is isolated so one exception cannot kill the loop."""
        while True:
            try:
                cb = self._main_q.get_nowait()
            except queue.Empty:
                break
            try:
                cb()
            except Exception:
                pass
        self.root.after(16, self._drain)

    # ── Status label ─────────────────────────────────────────────────────────────
    def _set_status(self, s: str):
        c = STATUS_FG.get(s, FG_DIM)
        def _do():
            self._status = s
            self._dot.config(fg=c)
            self._status_lbl.config(text=s, fg=c)
        self._ui(_do)

    # ── Pulse animation ──────────────────────────────────────────────────────────
    def _pulse_loop(self):
        active = self._status in ("Listening", "Thinking", "Speaking")
        if active:
            self._pulse_n = (self._pulse_n + 1) % 20
            hi  = self._pulse_n < 10
            col = STATUS_FG.get(self._status, FG_DIM)
            self._dot.config(fg=col if hi else FG_DIM)

            if self._status == "Listening":
                if self._mode == "hold":
                    # Purple pulse when recording
                    fill = MIC_H_REC  if hi else MIC_H_REST
                    ring = RING_H_REC if hi else RING_H_REST
                    txt  = "white"    if hi else FG_DIM
                elif self._capturing:
                    # Bright green flash when speech captured
                    fill = MIC_A_CAP  if hi else MIC_A_WAIT
                    ring = RING_A_CAP if hi else RING_A_WAIT
                    txt  = "#86efac"  if hi else FG_DIM
                else:
                    # Slow dim green when waiting for speech
                    fill = MIC_A_WAIT
                    ring = RING_A_WAIT if hi else "#0d2b1a"
                    txt  = FG_DIM
                self._mic_cv.itemconfig(self._c_fill, fill=fill)
                self._mic_cv.itemconfig(self._c_ring, outline=ring)
                self._mic_cv.itemconfig(self._c_text, fill=txt)

        self.root.after(130, self._pulse_loop)

    # ── Chat message helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _ts() -> str:
        return datetime.datetime.now().strftime("%H:%M:%S")

    def _append(self, *parts):
        def _do():
            self._chat.config(state="normal")
            for text, tag in parts:
                self._chat.insert("end", text, tag)
            self._chat.config(state="disabled")
            self._chat.see("end")
        self._ui(_do)

    _ERR_COOLDOWN = 15.0  # seconds before the same error text may appear again

    def _show_error(self, msg: str):
        """Write msg to chat, but swallow duplicates within _ERR_COOLDOWN seconds."""
        now = time.monotonic()
        if msg == self._last_err and now - self._last_err_t < self._ERR_COOLDOWN:
            return
        self._last_err   = msg
        self._last_err_t = now
        self._sys(msg)

    def _sys(self, text: str):
        self._append((f"\n  ·  {text}\n", "sys"))

    def _user_msg(self, text: str):
        ts = self._ts()
        self._append(
            (f"\n{ts}  ", "ts"),
            ("You",         "user_hd"),
            (f"  {text}\n", "user_txt"),
        )

    def _bot_msg(self, text: str):
        ts = self._ts()
        self._append(
            (f"\n{ts}  ", "ts"),
            ("Ph3b3",        "bot_hd"),
            (f"  {text}\n",  "bot_txt"),
        )

    # ── Health / boot count ──────────────────────────────────────────────────────
    def _fetch_health(self):
        def _run():
            try:
                r = requests.get(f"{SERVER}/health", timeout=3)
                d = r.json()
                boot  = d.get("boot", "?")
                model = d.get("model", "?")
                self._ui(lambda b=boot: self.root.title(f"Ph3b3 — Boot #{b}"))
                self._sys(f"Connected · Boot #{boot} · {model}")
            except Exception:
                self._ui(lambda: self.root.title("Ph3b3 — offline"))
                self._sys("Server offline — launch Ph3b3 first")
        threading.Thread(target=_run, daemon=True).start()

    # ── Text send ────────────────────────────────────────────────────────────────
    def _on_send(self, _event=None):
        text = self._entry.get().strip()
        if not text or self._busy:
            return
        self._entry.delete(0, "end")
        self._lock_text()
        self._user_msg(text)
        threading.Thread(target=self._do_chat, args=(text,), daemon=True).start()

    def _lock_text(self):
        self._entry.config(state="disabled")
        self._send_btn.config(state="disabled")

    def _unlock_text(self):
        self._entry.config(state="normal")
        self._send_btn.config(state="normal")
        self._entry.focus_set()

    # ── Core chat round-trip ─────────────────────────────────────────────────────
    def _do_chat(self, message: str):
        """Send message, display response. Blocks caller thread until done."""
        self._busy = True
        self._set_status("Thinking")
        try:
            r = requests.post(
                f"{SERVER}/chat",
                json={"message": message, "session_id": "ui"},
                timeout=180,
            )
            r.raise_for_status()
            resp = r.json().get("response", "(no response)")
            self._bot_msg(resp)
            self._set_status("Speaking")
            time.sleep(0.8)
        except requests.exceptions.ConnectionError:
            self._show_error("Cannot reach server — is Ph3b3 running?")
        except Exception as e:
            self._show_error(f"Error: {e}")
        finally:
            self._busy = False
            self._set_status("Idle")
            self._ui(self._unlock_text)

    # ── Audio transcription helper ───────────────────────────────────────────────
    def _transcribe(self, frames: list) -> str | None:
        audio = np.concatenate(frames, axis=0)
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp = f.name
            sf.write(tmp, audio, SAMPLE_RATE)
            with open(tmp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            os.unlink(tmp)
            r = requests.post(f"{SERVER}/transcribe", json={"audio": b64}, timeout=60)
            if r.status_code == 404:
                self._show_error("Transcribe endpoint not found — restart Ph3b3 server")
                return None
            r.raise_for_status()
            data = r.json()
            text = (data.get("text") or "").strip()
            if not text and data.get("error"):
                self._show_error(f"Transcription error: {data['error'][:120]}")
                return None
            return text or None
        except requests.exceptions.ConnectionError:
            self._show_error("Cannot reach server — is Ph3b3 running?")
            return None
        except Exception as e:
            self._show_error(f"Transcription error: {e}")
            return None

    # ── HOLD mode ────────────────────────────────────────────────────────────────
    def _mic_press(self, _event=None):
        if self._mode == "hold":
            if not self._recording and not self._busy:
                threading.Thread(target=self._do_hold, daemon=True).start()
        else:
            # AUTO mode: click toggles loop on/off
            if self._auto_on:
                self._stop_auto_loop()
            else:
                self._start_auto_loop()

    def _mic_release(self, _event=None):
        if self._mode == "hold" and self._recording:
            self._stop_rec.set()

    def _do_hold(self):
        self._recording = True
        self._stop_rec.clear()
        self._set_status("Listening")
        self._ui(lambda: self._mic_lbl.config(text="recording…"))

        chunk_frames = int(SAMPLE_RATE * CHUNK_MS / 1000)
        frames = []

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
                while not self._stop_rec.is_set():
                    data, _ = stream.read(chunk_frames)
                    frames.append(data.copy())
        except Exception as e:
            self._show_error(f"Mic error: {e}")
            self._recording = False
            self._set_status("Idle")
            self._ui(lambda: self._mic_lbl.config(text="hold to speak"))
            self._ui(self._reset_mic_visuals)
            return

        self._recording = False

        if not frames:
            self._set_status("Idle")
            self._ui(lambda: self._mic_lbl.config(text="hold to speak"))
            self._ui(self._reset_mic_visuals)
            return

        self._set_status("Thinking")
        self._ui(lambda: self._mic_lbl.config(text="transcribing…"))

        text = self._transcribe(frames)
        if not text:
            self._sys("(no speech detected)")
            self._set_status("Idle")
            self._ui(lambda: self._mic_lbl.config(text="hold to speak"))
            self._ui(self._reset_mic_visuals)
            return

        self._user_msg(text)
        self._ui(self._lock_text)
        self._do_chat(text)
        self._ui(lambda: self._mic_lbl.config(text="hold to speak"))
        self._ui(self._reset_mic_visuals)

    # ── AUTO mode ────────────────────────────────────────────────────────────────
    def _start_auto_loop(self):
        if self._auto_on:
            return
        self._auto_on = True
        self._stop_auto.clear()
        self._set_status("Listening")
        self._ui(self._refresh_mode_buttons)
        self._ui(lambda: self._mic_lbl.config(text="calibrating…"))
        threading.Thread(target=self._auto_loop, daemon=True).start()

    def _stop_auto_loop(self):
        self._stop_auto.set()
        self._auto_on = False
        self._capturing = False
        self._set_status("Idle")
        self._ui(self._refresh_mode_buttons)
        self._ui(lambda: self._mic_lbl.config(text="tap to start"))
        self._ui(self._reset_mic_visuals)

    def _auto_loop(self):
        """
        VAD-based continuous listen loop.
        Calibrates noise floor, then waits for speech, captures the utterance,
        transcribes, chats, and loops back to listening.
        """
        chunk_frames  = int(SAMPLE_RATE * CHUNK_MS / 1000)
        pre_n         = int(VAD_PRE_ROLL * 1000 / CHUNK_MS)
        silence_limit = int(VAD_SILENCE  * 1000 / CHUNK_MS)
        pre_buf       = collections.deque(maxlen=pre_n)
        thresh        = VAD_THRESH

        # ── Noise calibration ─────────────────────────────────────────────────
        try:
            cal = sd.rec(int(SAMPLE_RATE * 0.7), samplerate=SAMPLE_RATE,
                         channels=1, dtype="float32")
            sd.wait()
            noise = float(np.sqrt(np.mean(cal ** 2)))
            thresh = max(VAD_THRESH, noise * 3.5)
            self._sys(f"Auto · noise {noise:.4f} · threshold {thresh:.4f}")
        except Exception:
            self._sys(f"Auto · using default threshold {thresh:.4f}")

        self._ui(lambda: self._mic_lbl.config(text="listening…"))

        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32") as stream:
                while not self._stop_auto.is_set():

                    # Drain + wait while busy (server is talking)
                    if self._busy:
                        stream.read(chunk_frames)
                        pre_buf.clear()
                        time.sleep(0.04)
                        continue

                    # ── Wait for speech onset ─────────────────────────────
                    data, _ = stream.read(chunk_frames)
                    rms = float(np.sqrt(np.mean(data ** 2)))
                    pre_buf.append(data.copy())

                    if rms < thresh:
                        continue

                    # ── Capture utterance ─────────────────────────────────
                    self._capturing = True
                    frames = list(pre_buf)
                    silence_n = 0

                    while not self._stop_auto.is_set() and not self._busy:
                        data, _ = stream.read(chunk_frames)
                        frames.append(data.copy())
                        rms = float(np.sqrt(np.mean(data ** 2)))
                        if rms < thresh:
                            silence_n += 1
                            if silence_n >= silence_limit:
                                break
                        else:
                            silence_n = 0

                    self._capturing = False
                    pre_buf.clear()

                    if self._stop_auto.is_set() or self._busy:
                        continue

                    speech_secs = len(frames) * CHUNK_MS / 1000
                    if speech_secs < VAD_MIN_SPEAK:
                        continue

                    # ── Transcribe + chat ─────────────────────────────────
                    self._ui(lambda: self._mic_lbl.config(text="transcribing…"))
                    self._set_status("Thinking")

                    text = self._transcribe(frames)

                    if text and not self._stop_auto.is_set():
                        self._user_msg(text)
                        self._ui(self._lock_text)
                        self._do_chat(text)         # blocks until response received
                        self._ui(self._unlock_text)
                    elif not text and not self._stop_auto.is_set():
                        # Transcription failed or returned empty; back off briefly
                        # before resuming to avoid hammering a down/404 endpoint.
                        time.sleep(2.0)

                    if not self._stop_auto.is_set():
                        self._set_status("Listening")
                        self._ui(lambda: self._mic_lbl.config(text="listening…"))

        except Exception as e:
            self._show_error(f"Auto loop error: {e}")

        # Loop exited cleanly or by error
        self._auto_on   = False
        self._capturing = False
        self._ui(self._refresh_mode_buttons)
        self._ui(self._reset_mic_visuals)
        self._set_status("Idle")

    # ── Run ──────────────────────────────────────────────────────────────────────
    def run(self):
        # Centre on screen, then force the WM to place the window on the
        # active workspace.  Setting the type hint before the withdraw/deiconify
        # cycle ensures Mutter/GNOME assigns _NET_WM_DESKTOP correctly.
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - 1000) // 2
        y = (screen_h - 750) // 2
        self.root.geometry(f"1000x750+{x}+{y}")
        self.root.wm_attributes('-type', 'normal')   # hint: normal desktop window
        self.root.withdraw()                          # ensure withdrawn state
        self.root.deiconify()                         # map onto current workspace
        self.root.after(1, lambda: self.root.lift())
        self.root.focus_force()
        # Start background services now that mainloop is about to run.
        self._drain()
        self._pulse_loop()
        self._fetch_health()
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    Ph3b3UI().run()
