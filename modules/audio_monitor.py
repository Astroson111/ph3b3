"""Backend audio monitor — Silero VAD (ONNX) + level metering.

ONE tool, two consumers:
  - Chat endpointing: knows when the speaker STOPS (speech → sustained non-speech),
    so a capture can end before the hard cap — WITHOUT an energy floor. A fan/hum
    keeps RMS high, so "loud vs quiet" never sees silence; Silero judges SPEECH vs
    NOISE instead. (This is why the old device-side energy VAD was scrapped.)
  - Ghost-hunting readout: per-frame level (dBFS) + speech probability + a
    non-speech energy-spike flag for a live activity meter.

Torch-free: runs the Silero v5 ONNX model on onnxruntime (CPU). Feed 16 kHz mono
int16 PCM in 512-sample frames (32 ms). Stateful — ONE instance per stream.
"""
from __future__ import annotations
import math
import os
import numpy as np
import onnxruntime as ort

# Model is gitignored (2.3 MB binary). Fetch (see requirements.txt):
#   curl -sSL -o models/silero_vad.onnx \
#     https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "silero_vad.onnx")
FRAME = 512            # samples per inference @16 kHz (Silero v5 requirement)
SR = 16000
_FRAME_MS = 1000.0 * FRAME / SR   # 32 ms


class AudioMonitor:
    """Stateful per-stream VAD + level meter. Feed 512-sample int16 frames via push()."""

    def __init__(self, speech_on: float = 0.5, speech_off: float = 0.35,
                 min_speech_ms: int = 250, min_silence_ms: int = 700,
                 spike_db_over_floor: float = 12.0):
        self._sess = ort.InferenceSession(_MODEL, providers=["CPUExecutionProvider"])
        self.speech_on = speech_on            # prob to enter speech (hysteresis high)
        self.speech_off = speech_off          # prob to stay in silence (hysteresis low)
        self._min_speech = max(1, int(min_speech_ms / _FRAME_MS))
        self._min_silence = max(1, int(min_silence_ms / _FRAME_MS))
        self._spike_over = spike_db_over_floor
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(64, dtype=np.float32)   # Silero v5: 64 prev samples prepended per frame
        self._byte_buf = bytearray()   # partial-frame carry for feed_bytes(); overwritten, never persisted
        self._active = False          # currently inside speech
        self._speech_run = 0          # consecutive speech frames (onset debounce)
        self._silence_run = 0         # consecutive silence frames since speech
        self.had_speech = False       # any speech this stream
        self.endpoint = False         # sticky: speaker stopped after speaking
        self._noise_db = -60.0        # rolling non-speech floor (for the ghost spike flag)
        self._n = 0

    def push(self, frame_int16: np.ndarray) -> dict:
        """Feed one 512-sample int16 frame; returns per-frame telemetry."""
        f = np.asarray(frame_int16, dtype=np.int16)
        if len(f) < FRAME:
            f = np.pad(f, (0, FRAME - len(f)))
        ff = f[:FRAME].astype(np.float32) / 32768.0
        # Silero v5 wants [64-sample context | 512-sample frame] = 576 samples.
        inp = np.concatenate([self._context, ff]).reshape(1, -1).astype(np.float32)
        prob, self._state = self._sess.run(
            None, {"input": inp, "state": self._state, "sr": np.array(SR, dtype=np.int64)})
        self._context = ff[-64:].copy()
        p = float(prob[0][0])
        rms = float(np.sqrt(np.mean(ff * ff)) + 1e-9)
        rms_db = 20.0 * math.log10(rms)
        self._n += 1

        speech = p >= (self.speech_off if self._active else self.speech_on)
        if speech:
            self._speech_run += 1
            self._silence_run = 0
            if self._speech_run >= self._min_speech:
                self._active = True
                self.had_speech = True
        else:
            self._silence_run += 1
            self._speech_run = 0
            # track a slow non-speech floor for the ghost activity meter
            self._noise_db += 0.05 * (rms_db - self._noise_db)
            if self._active and self._silence_run >= self._min_silence:
                self._active = False
                self.endpoint = True      # sticky — the speaker stopped

        # ghost: a loud NON-speech frame well above the noise floor = activity/EVP
        spike = (not self._active) and (rms_db > self._noise_db + self._spike_over) and p < 0.3

        return {"t": round(self._n * _FRAME_MS / 1000.0, 3), "speech_prob": p,
                "rms_db": rms_db, "is_speech": self._active,
                "endpoint": self.endpoint, "spike": spike}


    def feed_bytes(self, raw: bytes) -> list:
        """Accept arbitrary 16 kHz mono int16-LE bytes (e.g. a WS frame), buffer into
        512-sample frames, and return the per-frame telemetry for whatever COMPLETE
        frames arrived. The partial tail is carried in-memory only and never stored."""
        self._byte_buf.extend(raw)
        out = []
        fb = FRAME * 2
        while len(self._byte_buf) >= fb:
            frame = np.frombuffer(bytes(self._byte_buf[:fb]), dtype=np.int16)
            del self._byte_buf[:fb]
            out.append(self.push(frame))
        return out


def analyze(pcm_int16: np.ndarray, **kw):
    """Offline: run a whole clip through a fresh monitor. Returns (frames, monitor)."""
    mon = AudioMonitor(**kw)
    frames = [mon.push(pcm_int16[i:i + FRAME])
              for i in range(0, max(0, len(pcm_int16) - FRAME + 1), FRAME)]
    return frames, mon
