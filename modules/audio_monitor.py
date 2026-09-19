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
import json
import math
import os
from pathlib import Path
import numpy as np
import onnxruntime as ort

# Model is gitignored (2.3 MB binary). Fetch (see requirements.txt):
#   curl -sSL -o models/silero_vad.onnx \
#     https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
_MODEL = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "silero_vad.onnx")
FRAME = 512            # samples per inference @16 kHz (Silero v5 requirement)
SR = 16000
_FRAME_MS = 1000.0 * FRAME / SR   # 32 ms


# ── Tuning, editable without a deploy ────────────────────────────────────────
# Same pattern as config/argus_contracts.json: a plain file, read fresh each
# time a stream opens, so a change takes effect on the NEXT turn without a
# restart. Dio lives in a room with a fan and a HEPA unit, and the right numbers
# for that room are not knowable from here — they have to be tried.
#
# Every value has a safe default and a bad file is ignored rather than fatal: a
# typo in a tuning file must not take her hearing offline.
TUNING_PATH = Path(__file__).resolve().parents[1] / "config" / "vad_tuning.json"

_DEFAULTS = {
    "speech_on": 0.5,          # prob to ENTER speech (hysteresis high)
    "speech_off": 0.35,        # prob to stay in silence (hysteresis low)
    "min_speech_ms": 250,      # debounce before a turn counts as started
    "min_silence_ms": 700,     # trailing quiet before the turn is declared over
    # "consecutive" — the shipped rule: min_silence_ms of UNBROKEN quiet, reset
    #                 to zero by any single frame above speech_off.
    # "windowed"     — the proposal: at least `window_frac` of the last
    #                 min_silence_ms below speech_off. One stray frame no longer
    #                 restarts everything.
    "endpoint_rule": "consecutive",
    "window_frac": 0.8,
}


def load_tuning(path: Path | None = None) -> dict:
    """Merged over the defaults. A missing or broken file yields the defaults."""
    out = dict(_DEFAULTS)
    try:
        raw = json.loads((path or TUNING_PATH).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in _DEFAULTS:
                if k in raw:
                    out[k] = raw[k]
    except Exception:
        pass
    if out["endpoint_rule"] not in ("consecutive", "windowed"):
        out["endpoint_rule"] = _DEFAULTS["endpoint_rule"]
    return out


class AudioMonitor:
    """Stateful per-stream VAD + level meter. Feed 512-sample int16 frames via push()."""

    def __init__(self, speech_on: float = 0.5, speech_off: float = 0.35,
                 min_speech_ms: int = 250, min_silence_ms: int = 700,
                 spike_db_over_floor: float = 12.0,
                 endpoint_rule: str = "consecutive", window_frac: float = 0.8):
        self._sess = ort.InferenceSession(_MODEL, providers=["CPUExecutionProvider"])
        self.speech_on = speech_on            # prob to enter speech (hysteresis high)
        self.speech_off = speech_off          # prob to stay in silence (hysteresis low)
        self._min_speech = max(1, int(min_speech_ms / _FRAME_MS))
        self._min_silence = max(1, int(min_silence_ms / _FRAME_MS))
        self._spike_over = spike_db_over_floor
        self.endpoint_rule = (endpoint_rule if endpoint_rule in ("consecutive", "windowed")
                              else "consecutive")
        self.window_frac = float(window_frac)
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
        # ── endpoint diagnostics (Phase 3c) ──────────────────────────────────
        # NUMBERS ABOUT a turn, never any audio. The privacy invariant on this
        # path is absolute: frames are judged and discarded, and nothing here
        # may hold, log or derive a sample value that could reconstruct speech.
        #
        # Why these particular numbers. The endpoint needs _min_silence
        # CONSECUTIVE sub-threshold frames and resets to zero on any single
        # frame above speech_off. If the room puts one stray frame into an
        # otherwise-quiet pause, the count restarts and the turn rides to the
        # cap. Max run vs required is the one comparison that distinguishes
        # "she never stopped talking" from "she stopped and the counter kept
        # being reset" — and those need opposite fixes.
        self._sub_runs = []           # lengths of consecutive sub-threshold runs
        self._cur_sub = 0
        self._sub_frames = 0          # total frames below speech_off while active
        self._active_frames = 0       # frames seen since speech started
        # SHADOW rule, evaluated but never acted on: would a windowed majority
        # have ended the turn, and when? Lets the proposed fix be measured on
        # real traffic before it changes any behaviour.
        self._live_win = []           # rolling window the LIVE windowed rule reads
        self._shadow_win = []         # the same window, for the rule that is NOT live
        self._shadow_at = None        # frame index the shadow rule would have fired

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

        # ── diagnostics: sub-threshold run tracking + the shadow rule ────────
        if self._active:
            self._active_frames += 1
            sub = p < self.speech_off
            self._sub_frames += int(sub)
            if sub:
                self._cur_sub += 1
            elif self._cur_sub:
                self._sub_runs.append(self._cur_sub)
                self._cur_sub = 0
            # One rolling window, read by whichever rule needs it.
            self._live_win.append(sub)
            if len(self._live_win) > self._min_silence:
                self._live_win.pop(0)
            self._shadow_win = self._live_win

            # The shadow always evaluates the rule that is NOT live, so flipping
            # the config gives a before/after in both directions rather than
            # only one. Whichever way it is set, the journal keeps answering
            # "and what would the other one have done?"
            if self._shadow_at is None:
                if self.endpoint_rule == "consecutive":
                    # shadow = windowed
                    if (len(self._live_win) >= self._min_silence
                            and sum(self._live_win) >= self.window_frac * self._min_silence):
                        self._shadow_at = self._n
                else:
                    # shadow = consecutive
                    if self._cur_sub >= self._min_silence:
                        self._shadow_at = self._n

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
            # ── the endpoint decision ────────────────────────────────────
            # "consecutive" is the shipped rule and the default: min_silence
            # frames of UNBROKEN quiet. It is brittle by construction — the run
            # resets to zero on any single frame above speech_off, so one breath
            # or fan transient in an otherwise-quiet pause restarts the count and
            # the turn rides to the device's 8s backstop. 13 of 59 speech turns
            # ended that way, with Silero reporting 0.999 confidence throughout.
            #
            # "windowed" needs window_frac of the last min_silence frames quiet
            # rather than all of them. Same latency on a clean pause; survives a
            # spike. Off by default — flip it in config/vad_tuning.json.
            if self._active and self._endpoint_now():
                self._active = False
                self.endpoint = True      # sticky — the speaker stopped

        # ghost: a loud NON-speech frame well above the noise floor = activity/EVP
        spike = (not self._active) and (rms_db > self._noise_db + self._spike_over) and p < 0.3

        return {"t": round(self._n * _FRAME_MS / 1000.0, 3), "speech_prob": p,
                "rms_db": rms_db, "is_speech": self._active,
                "endpoint": self.endpoint, "spike": spike}


    def _endpoint_now(self) -> bool:
        """Has the speaker stopped, by whichever rule is configured?"""
        if self.endpoint_rule == "windowed":
            w = self._live_win
            return (len(w) >= self._min_silence
                    and sum(w) >= self.window_frac * self._min_silence)
        return self._silence_run >= self._min_silence

    def endpoint_diag(self) -> dict:
        """Why the endpoint did or did not fire — numbers only, never audio.

        `max_sub_run` against `need` is the discriminator:
          max_sub_run ~= 0        she genuinely never stopped; the threshold is
                                  the lever, or she really did talk for 8s
          0 < max_sub_run < need  she DID pause and the consecutive-run counter
                                  kept being reset — a windowed rule fixes it,
                                  lowering the threshold would not
        `shadow_at_s` is when the proposed windowed-majority rule WOULD have
        ended the turn. It is evaluated and discarded; nothing acts on it.
        """
        runs = self._sub_runs + ([self._cur_sub] if self._cur_sub else [])
        return {
            "need": self._min_silence,
            "max_sub_run": max(runs) if runs else 0,
            "sub_runs": len(runs),
            "sub_pct": (round(100.0 * self._sub_frames / self._active_frames, 1)
                        if self._active_frames else 0.0),
            "active_frames": self._active_frames,
            "shadow_at_s": (round(self._shadow_at * _FRAME_MS / 1000.0, 2)
                            if self._shadow_at is not None else None),
        }

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
