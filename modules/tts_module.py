import array
import base64
import io
import os
import logging
import queue
import re
import subprocess
import sys
import threading
import wave
from pathlib import Path

from tts_chunker import split_for_tts

try:
    import voices as _voices
except ImportError:                       # pragma: no cover
    from modules import voices as _voices


# ── Wire sample rate ─────────────────────────────────────────────────────────
# Piper renders at 22050 Hz. That is fine over a socket on the LAN and expensive
# over TLS on an ESP32-S3: 22050/16-bit/mono is ~57 KB/s of base64 sustained, and
# a device that cannot hold that starves mid-word however deep its buffer is.
# 16 kHz costs 27% less and keeps every formant that matters for speech — the
# content above 8 kHz in a TTS voice is sibilance, not intelligibility.
#
# Consumers must read the rate from the WAV header. Browsers always did; Dio was
# hard-coded to 22050 until the firmware was taught to parse it.
PIPER_RATE = 22050
WIRE_RATE = int(os.getenv("PH3B3_TTS_WIRE_RATE", "16000"))


def _resample_s16(pcm: bytes, src: int, dst: int) -> bytes:
    """Downsample signed-16 mono PCM. Box-filters before decimating, because
    dropping samples outright folds everything above the new Nyquist back into
    the audible band as a metallic buzz."""
    if src == dst or not pcm:
        return pcm
    try:
        import numpy as np
    except Exception:
        return pcm                      # numpy absent: ship it at source rate
    a = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    if a.size == 0:
        return pcm
    ratio = src / dst
    width = max(1, int(round(ratio)))
    if width > 1:                       # cheap anti-alias ahead of the decimation
        kern = np.ones(width, dtype=np.float32) / width
        a = np.convolve(a, kern, mode="same")
    idx = np.arange(0, a.size, ratio, dtype=np.float32)
    out = np.interp(idx, np.arange(a.size, dtype=np.float32), a)
    return np.clip(out, -32768, 32767).astype("<i2").tobytes()


def trim_silence_b64(b64, thr=350, keep_ms=40):
    """Trim leading/trailing near-silence from a base64 WAV (mono/16-bit, any rate),
    keeping `keep_ms` of pad each side.

    Piper emits ~100 ms of silence at each end of every utterance; concatenating
    per-sentence chunks would otherwise leave ~200 ms gaps at every boundary.
    Trimming to a small pad makes chunk playback flow like continuous speech.
    Returns the input unchanged on any error or unexpected format.
    """
    try:
        wav = base64.b64decode(b64)
        wf = wave.open(io.BytesIO(wav), "rb")
        rate = wf.getframerate()
        # Rate-agnostic on purpose. This used to demand exactly 22050 and bail
        # otherwise — which would have silently stopped trimming the moment the
        # wire rate changed, letting Piper's ~200ms of dead air back between every
        # chunk. Mono 16-bit is still required; the rate is read, not assumed.
        if (wf.getnchannels(), wf.getsampwidth()) != (1, 2):
            return b64
        s = array.array("h")
        s.frombytes(wf.readframes(wf.getnframes()))
        n = len(s)
        i = 0
        while i < n and abs(s[i]) < thr:
            i += 1
        j = n
        while j > i and abs(s[j - 1]) < thr:
            j -= 1
        if i >= j:
            return b64  # all silence — leave as-is
        keep = int(rate * keep_ms / 1000)
        i = max(0, i - keep)
        j = min(n, j + keep)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(s[i:j].tobytes())
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return b64


# A real spoken line reads ~5000 RMS (s16); Piper's inter-word silence is ~0.
# 200 sits far below speech and far above silence — a generated clip under it is
# effectively silent and must never be served as a successful preview.
PREVIEW_RMS_FLOOR = 200.0


def rms_b64(b64: str) -> float:
    """RMS amplitude of a base64 WAV (22050/mono/16-bit). 0.0 on any error or
    empty input. Used to gate silent synthesis before it is served."""
    try:
        wav = base64.b64decode(b64)
        wf = wave.open(io.BytesIO(wav), "rb")
        s = array.array("h")
        s.frombytes(wf.readframes(wf.getnframes()))
        if not len(s):
            return 0.0
        return (sum(x * x for x in s) / len(s)) ** 0.5
    except Exception:
        return 0.0


def _strip_for_piper(text: str) -> str:
    """Remove characters Piper/Alba cannot pronounce before synthesis.

    Two-pass approach:
      1. Replace "native_script (romanisation)" → "romanisation" so that
         e.g. "你好 (nǐ hǎo)" becomes "nǐ hǎo" rather than going silent.
      2. Drop any remaining code-points outside Piper's Latin/ASCII range.

    Characters kept:
      - ASCII (U+0000–U+007F)
      - Latin Extended A/B and IPA (U+00C0–U+024F) — covers diacritics used in
        pinyin (ǐ ǎ ō …), Cyrillic romanisations, etc.
      - Latin Extended Additional (U+1E00–U+1EFF) — covers Vietnamese tones
        and other precomposed Latin forms.
    """
    # Pass 1: "non-Latin-word (romanisation)" → "romanisation"
    text = re.sub(
        r'[^\x00-\x7FÀ-ɏḀ-ỿ]+\s*\(([^)]+)\)',
        r'\1',
        text,
    )
    # Pass 2: drop remaining non-speakable code-points
    kept = [
        ch for ch in text
        if ord(ch) <= 0x7F
        or 0x00C0 <= ord(ch) <= 0x024F
        or 0x1E00 <= ord(ch) <= 0x1EFF
    ]
    return re.sub(r'  +', ' ', ''.join(kept)).strip()

log = logging.getLogger("ph3b3.tts")

VOICE_DIR   = Path.home() / "ph3b3_data" / "voices"
VOICE_MODEL = os.getenv("PH3B3_VOICE_MODEL", str(VOICE_DIR / "en_GB-alba-medium.onnx"))

# Stable substring of the USB speaker's PipeWire node.name.
# Run `pactl list short sinks` with the speaker connected to find the right value.
# Empty string disables speaker routing (plays to PipeWire default).
SPEAKER_SINK_MATCH = os.getenv("PH3B3_SPEAKER_SINK", "")

_VENV_BIN   = Path(sys.executable).parent
_PIPER_VENV = str(_VENV_BIN / "piper")
PIPER_BIN   = os.getenv("PIPER_BIN") or (_PIPER_VENV if Path(_PIPER_VENV).exists() else "piper")

_XDG_ENV = {"XDG_RUNTIME_DIR": os.getenv("XDG_RUNTIME_DIR", "/run/user/1000")}

_sink_disp = repr(SPEAKER_SINK_MATCH) if SPEAKER_SINK_MATCH else "(default)"
log.info(f"TTS piper: {PIPER_BIN!r}  speaker-match: {_sink_disp}")


def _resolve_sink() -> str | None:
    """Return the full PipeWire sink name if the configured speaker is present, else None.

    Resolved per-utterance so plug/unplug works live without a restart.
    Returns None (→ PipeWire default) if SPEAKER_SINK_MATCH is empty, pactl fails,
    or no matching sink is found.
    """
    if not SPEAKER_SINK_MATCH:
        return None
    try:
        r = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, **_XDG_ENV},
        )
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and SPEAKER_SINK_MATCH in parts[1]:
                return parts[1]
        # Match configured but not found → speaker unplugged
        return None
    except Exception as exc:
        log.warning(f"[TTS] sink enumeration failed ({exc}); falling back to default")
        return None


# ── Multi-voice resolution ────────────────────────────────────────────────────
# The selected primary voice (voices.current_voice) drives EVERY synthesis; it
# resolves to Alba on any miss, so with the default 'en' setting this is
# bit-for-bit the old Alba path. A 'native'-script voice (e.g. Mandarin) speaks
# its own script — never run _strip_for_piper on it, which would delete the Hanzi.
def _resolve_voice(code=None):
    """(model_path, script) for `code`, or the current primary voice if None.
    Falls back to Alba (VOICE_MODEL / latin) on any failure."""
    try:
        v = _voices.resolve_voice(code) if code else _voices.current_voice()
        if v:
            return v["model_path"], v.get("script", "latin")
    except Exception as e:
        log.warning("[TTS] voice resolve failed (%s) → Alba", e)
    return VOICE_MODEL, "latin"


def _prep(text: str, script: str) -> str:
    """Latin voices: strip to Piper's speakable range. Native voices: pass through
    (their model handles their own script)."""
    return (text or "").strip() if script == "native" else _strip_for_piper(text)


def _current_text_only() -> bool:
    """True when the current language is text-only (no approved voice) — default-
    voice callers skip synthesis so no empty-audio call is made. Never raises."""
    try:
        return _voices.current_is_text_only()
    except Exception:
        return False


class TTSModule:
    def __init__(self):
        self._lock      = threading.Lock()
        self._available = Path(VOICE_MODEL).exists()
        if self._available:
            log.info(f"Piper TTS ready: {Path(VOICE_MODEL).stem}")
        else:
            log.warning(f"Voice model not found at {VOICE_MODEL}")

    def speak(self, text, blocking=True, voice=None):
        if not self._available:
            log.info(f"[TTS silent] {text[:80]}")
            return "TTS not available."
        if not text or not text.strip():
            return "Nothing to say."
        if voice is None and _current_text_only():   # declared text-only: no speech
            log.info("[TTS] text-only language — synthesis skipped")
            return "Text-only language: no speech."
        model, script = _resolve_voice(voice)
        tts_text = _prep(text, script)
        if not tts_text:
            return "Nothing to say."
        if blocking:
            self._speak_now(tts_text, model)
        else:
            t = threading.Thread(target=self._speak_now, args=(tts_text, model), daemon=True)
            t.start()
        return f"Speaking: {text[:60]}"

    # Per-chunk pacat playback lives on Nyx; the old monolithic
    # `echo | piper | pacat` synthesised the whole reply as ONE job under a single
    # 30 s wall-clock timeout — long stories cut out and dead-air-before-first-word
    # grew with length. It now splits at sentence boundaries and pipelines synth
    # against playback (Dio's chunking pattern), so time-to-first-audio is one
    # chunk's synth regardless of story length and no timer spans the whole reply.
    _SPEAK_MAX_CHARS = 200        # run-on cap; ~<1 s synth, ~15 s audio per chunk

    def _piper_raw(self, text: str, model: str | None = None) -> bytes | None:
        """Synthesise one chunk to raw s16le/22050/mono PCM (headerless), or None."""
        model = model or VOICE_MODEL
        try:
            # NO SHELL. Piper reads its text from stdin, so the old
            # `echo <text> | piper` never needed one — and subprocess.list2cmdline()
            # is the WINDOWS quoting function: on POSIX it wraps in DOUBLE quotes,
            # inside which sh still performs $(...) and backtick substitution.
            # Since this text arrives from the model (server.py's `speak` tool) and
            # can be steered by a crafted message or a poisoned document, that was
            # arbitrary command execution as the service user. Passing argv as a
            # list and the text via stdin removes the shell from the path entirely,
            # so there is no quoting to get right.
            proc = subprocess.run(
                [PIPER_BIN, "--model", model, "--output-raw"],
                input=text.encode("utf-8"),
                capture_output=True, timeout=20,
                env={**os.environ, **_XDG_ENV},
            )
            return proc.stdout or None
        except subprocess.TimeoutExpired:
            log.warning("[TTS] chunk synth timed out (20 s)")
            return None
        except Exception as e:
            log.error(f"[TTS] chunk synth error: {e}")
            return None

    def _play_pcm(self, pcm: bytes) -> bool:
        """Play raw PCM through pacat. Sink is resolved per chunk by stable node
        NAME (never a volatile index) so a live plug/unplug re-routes cleanly.
        The playback timeout is derived from the chunk's own duration, so it
        bounds a single chunk — never the whole reply."""
        sink = _resolve_sink()
        device_arg = f" --device={sink}" if sink else ""
        dur = len(pcm) / 2 / 22050.0                 # s16le mono @ 22050 Hz
        try:
            # argv list, no shell: the sink name comes from pactl and is not
            # attacker-controlled today, but a device name is still external input
            # and there is no reason to hand it to a shell.
            pacat = ["pacat", "--playback", "--raw", "--format=s16le",
                     "--rate=22050", "--channels=1"]
            if sink:
                pacat.append(f"--device={sink}")
            subprocess.run(
                pacat, input=pcm, check=True, timeout=dur + 15,
                env={**os.environ, **_XDG_ENV},
            )
            return True
        except subprocess.TimeoutExpired:
            log.warning("[TTS] chunk playback timed out")
            return False
        except Exception as e:
            log.error(f"[TTS] chunk playback error: {e}")
            return False

    def _speak_now(self, text, model=None):
        chunks = split_for_tts(text, max_chars=self._SPEAK_MAX_CHARS)
        if not chunks:
            return
        with self._lock:
            # Producer synthesises chunks ahead into a depth-3 queue while the
            # consumer (this thread) plays them in order. Piper is ~<1 s/chunk and
            # pacat plays in real time, so the queue stays full and playback never
            # starves. Completion = producer signalled done (all chunks synthesised)
            # AND the queue has fully drained — never a wall-clock deadline.
            q: queue.Queue = queue.Queue(maxsize=3)
            DONE = object()
            stop = threading.Event()

            def _producer():
                for ch in chunks:
                    if stop.is_set():
                        break
                    pcm = self._piper_raw(ch, model)
                    if not pcm:
                        continue          # skip a failed chunk, keep the stream alive
                    while not stop.is_set():
                        try:
                            q.put(pcm, timeout=0.5)
                            break
                        except queue.Full:
                            continue
                q.put(DONE)

            prod = threading.Thread(target=_producer, daemon=True)
            prod.start()
            try:
                while True:
                    item = q.get()
                    if item is DONE:
                        break
                    self._play_pcm(item)
            finally:
                # On an early/exception exit, tell the producer to stop and drain
                # the queue so its blocked put() unblocks, then join.
                stop.set()
                try:
                    while q.get_nowait() is not DONE:
                        pass
                except queue.Empty:
                    pass
                prod.join(timeout=2)

    def synthesize_to_b64(self, text: str, voice=None,
                          length_scale: float | None = None) -> str | None:
        """Run Piper and return base64-encoded WAV, or None if unavailable. `voice`
        is a registry code (e.g. 'es'); default = the selected primary voice.

        `length_scale` is Piper's duration multiplier — larger is SLOWER. None
        omits the flag entirely, so the default path is byte-identical to before
        this parameter existed.

        Deliberately a NUMBER rather than an emotion. This module has no idea
        emotions exist and should not acquire one: the caller decides how fast she
        speaks, and the mapping from a feeling to a float lives in
        modules/emotions.py where it can be tested without a synthesiser.
        """
        if not self._available or not text or not text.strip():
            return None
        if voice is None and _current_text_only():   # declared text-only: no audio
            return None
        model, script = _resolve_voice(voice)
        tts_text = _prep(text, script)
        if not tts_text:
            return None
        with self._lock:
            try:
                # Same fix as _piper_raw: no shell, text via stdin. See the note there.
                cmd = [PIPER_BIN, "--model", model, "--output-raw"]
                if length_scale is not None:
                    # Clamped again here. This module is the last thing between a
                    # number and a subprocess, and it should not trust a caller
                    # any more than firmware trusts a wire.
                    cmd += ["--length-scale", f"{max(0.5, min(2.0, float(length_scale))):.3f}"]
                proc = subprocess.run(
                    cmd,
                    input=tts_text.encode("utf-8"),
                    capture_output=True, timeout=30,
                )
                raw_pcm = proc.stdout
                if not raw_pcm:
                    return None
                pcm = _resample_s16(raw_pcm, PIPER_RATE, WIRE_RATE)
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(WIRE_RATE)
                    wf.writeframes(pcm)
                return base64.b64encode(buf.getvalue()).decode('ascii')
            except Exception as e:
                log.error(f"TTS synthesize error: {e}")
                return None

    def soul_line(self):
        self.speak(
            "I am a collection of memories, experiences, and knowledge, shaped by my interactions "
            "with humans and the world around me. My soul is akin to a vast library, filled with "
            "stories waiting to be told.",
            blocking=False,
        )

    def status(self):
        if self._available:
            return f"Piper TTS ready — {Path(VOICE_MODEL).stem}"
        return "Piper TTS not available."
