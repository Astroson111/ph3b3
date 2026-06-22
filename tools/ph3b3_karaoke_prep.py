#!/usr/bin/env python3
"""
Ph3b3 Karaoke Prep — drag-drop a LOCAL audio file, get a Stack-Chan karaoke track.

  • Converts any audio (mp3/m4a/flac/wav/…) → PCM WAV in Stack-Chan's format
  • Generates a .lrc lyric stub (won't clobber an existing one)
  • Optionally copies both straight to the SD card's /karaoke/ folder

Clean-source only: feed it files you downloaded legally (YouTube Audio Library
direct downloads, Incompetech, Free Music Archive, Pixabay, your own audio).
No URL ripping — this works on files already on disk.

Firmware reads: /karaoke/track.wav  and  /karaoke/track.lrc  (hardcoded paths).
Keep the output name as "track" unless the firmware is updated.

Run:  python3 ph3b3_karaoke_prep.py
Drag-drop needs the optional 'tkinterdnd2' package; without it, use the Browse
button (always works).  ffmpeg must be installed (sudo apt install ffmpeg).
"""

import json
import os
import pathlib
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog

# optional drag-and-drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:
    _DND = False

PRESETS = {
    "voice  (16kHz mono — smaller file, lower quality)": (16000, 1),
    "cd  (44.1kHz stereo — recommended for music)": (44100, 2),
}

LRC_STUB = """[ti:{title}]
[ar:Artist]
[00:00.00] (intro)
[00:05.00] first line of lyrics here
[00:10.00] next line here
[00:15.00] [mm:ss.xx] one timestamp per line
"""

CONFIG_FILE = pathlib.Path.home() / ".config" / "ph3b3" / "karaoke_prefs.json"


def _load_prefs():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def _save_prefs(prefs):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(prefs, indent=2))


class App:
    def __init__(self, root):
        self.root = root
        root.title("☽ Ph3b3 Karaoke Prep")
        root.geometry("560x540")
        self._prefs = _load_prefs()
        self.infile = tk.StringVar()
        self.basename = tk.StringVar(value="track")
        self.preset = tk.StringVar(value=list(PRESETS)[1])  # default: cd preset
        self.copy_sd = tk.BooleanVar(value=False)
        self.sd_path = tk.StringVar(value=self._prefs.get("last_sd_path", ""))
        self._build()
        self._check_ffmpeg()

    def _build(self):
        pad = {"padx": 10, "pady": 4}

        # drop zone
        drop = tk.Label(
            self.root,
            text="⬇  Drag an audio file here\n(or use Browse)" if _DND
                 else "Use Browse to pick an audio file\n(install tkinterdnd2 for drag-drop)",
            relief="ridge", borderwidth=2, height=4, fg="#444",
        )
        drop.pack(fill="x", **pad)
        if _DND:
            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", self._on_drop)

        row = tk.Frame(self.root); row.pack(fill="x", **pad)
        tk.Entry(row, textvariable=self.infile).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse…", command=self._browse).pack(side="left", padx=6)

        # basename — locked to "track" because firmware reads /karaoke/track.wav
        r2 = tk.Frame(self.root); r2.pack(fill="x", **pad)
        tk.Label(r2, text="Output name:").pack(side="left")
        tk.Entry(r2, textvariable=self.basename, width=12).pack(side="left", padx=6)
        tk.Label(r2, text=".wav + .lrc").pack(side="left")
        tk.Label(r2, text="  ⚠ firmware reads track.wav / track.lrc",
                 fg="#888", font=("", 8)).pack(side="left", padx=4)

        # preset
        r3 = tk.LabelFrame(self.root, text="Format"); r3.pack(fill="x", **pad)
        for label in PRESETS:
            tk.Radiobutton(r3, text=label, variable=self.preset, value=label).pack(anchor="w")

        # SD copy
        r4 = tk.LabelFrame(self.root, text="Copy to SD card (optional)"); r4.pack(fill="x", **pad)
        tk.Checkbutton(r4, text="Also copy to the SD /karaoke/ folder",
                       variable=self.copy_sd, command=self._toggle_sd).pack(anchor="w")
        self.sd_row = tk.Frame(r4)
        tk.Entry(self.sd_row, textvariable=self.sd_path).pack(side="left", fill="x", expand=True)
        tk.Button(self.sd_row, text="Pick folder…", command=self._pick_sd).pack(side="left", padx=6)
        # Restore SD row visibility if a path was remembered
        if self.sd_path.get():
            self.copy_sd.set(True)
            self.sd_row.pack(fill="x", pady=4)

        # go
        self.go = tk.Button(self.root, text="Convert + Prep", height=2,
                            command=self._run_threaded, bg="#2b6", fg="white")
        self.go.pack(fill="x", **pad)

        # log
        self.log = tk.Text(self.root, height=9, bg="#111", fg="#ddd", wrap="word")
        self.log.pack(fill="both", expand=True, **pad)

    # ── helpers ──────────────────────────────────────────────────────────
    def _w(self, msg):
        self.log.insert("end", msg + "\n"); self.log.see("end"); self.root.update_idletasks()

    def _check_ffmpeg(self):
        if shutil.which("ffmpeg"):
            self._w("✓ ffmpeg found. Ready.")
        else:
            self._w("✗ ffmpeg NOT found — install it:  sudo apt install ffmpeg")
            self.go.config(state="disabled")

    def _browse(self):
        f = filedialog.askopenfilename(
            title="Pick an audio file",
            filetypes=[("Audio", "*.mp3 *.m4a *.flac *.wav *.ogg *.aac *.opus"), ("All", "*.*")])
        if f:
            self.infile.set(f)

    def _on_drop(self, e):
        path = e.data.strip().strip("{}")  # tkdnd wraps paths with spaces in braces
        self.infile.set(path)
        self._w(f"dropped: {path}")

    def _toggle_sd(self):
        self.sd_row.pack(fill="x", pady=4) if self.copy_sd.get() else self.sd_row.pack_forget()

    def _pick_sd(self):
        d = filedialog.askdirectory(title="Pick the SD card's /karaoke/ folder")
        if d:
            self.sd_path.set(d)

    def _run_threaded(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.go.config(state="disabled")
        try:
            self._do()
        except Exception as ex:
            self._w(f"✗ ERROR: {ex}")
        finally:
            self.go.config(state="normal")

    def _do(self):
        src = self.infile.get().strip()
        base = self.basename.get().strip() or "track"
        if not src or not os.path.isfile(src):
            self._w("✗ pick a valid audio file first."); return

        rate, ch = PRESETS[self.preset.get()]
        out_dir = os.path.dirname(src)
        wav = os.path.join(out_dir, f"{base}.wav")
        lrc = os.path.join(out_dir, f"{base}.lrc")

        self._w(f"→ converting → {base}.wav  ({rate}Hz, {'stereo' if ch == 2 else 'mono'}, 16-bit PCM)")
        subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-ar", str(rate), "-ac", str(ch),
             "-c:a", "pcm_s16le", wav],
            check=True, capture_output=True, text=True)
        self._w(f"✓ wrote {wav}")

        if not os.path.exists(lrc):
            with open(lrc, "w") as fh:
                fh.write(LRC_STUB.format(title=base))
            self._w(f"✓ wrote {lrc} stub — edit timestamps to match the song")
        else:
            self._w(f"• {lrc} already exists, left alone")

        if self.copy_sd.get() and self.sd_path.get().strip():
            dest = self.sd_path.get().strip()
            os.makedirs(dest, exist_ok=True)
            shutil.copy(wav, dest); shutil.copy(lrc, dest)
            self._w(f"✓ copied both to {dest}")
            # Persist the SD path for next time
            self._prefs["last_sd_path"] = dest
            _save_prefs(self._prefs)

        self._w("Done.  ▶ test it in Karaoke mode on Stack-Chan.")


def main():
    root = (TkinterDnD.Tk() if _DND else tk.Tk())
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
