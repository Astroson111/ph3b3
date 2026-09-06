"""Orpheus — karaoke for Ph3b3: stems, word-timed lyrics, and a stage to sing on.

Named by Astro, Sept 5 2026. Two letters from Morpheus and nothing like it: this
module makes no images, no video and no audio. It TAKES APART songs Amphion
already made, so they can be sung over live.

Three pieces, in the order a song moves through them:

  1. SEPARATION (Demucs htdemucs, GPU). A finished render is split into stems.
     The full mix minus the vocal becomes <slug>-instrumental.flac, written
     beside the master. The isolated vocal is kept as a WORKING FILE only — it
     exists to give step 2 a clean signal, and it is not a deliverable.
  2. TIMING (Whisper, word_timestamps). Run on the isolated vocal rather than
     the full mix, because alignment on a mix full of drums and guitar is where
     word timing goes to die. Whisper supplies TIMING ONLY; the sidecar lyrics
     are the words, always.
  3. THE STAGE (static/orpheus.html, served at /orpheus). Not this module's
     business beyond handing it JSON.

WHAT THIS MODULE WILL NOT DO, and why each one is load-bearing:

  * NO FLOOR CALL, and no floor import. Separation, alignment and playback act on
    renders that already passed the floor at generation. The floor gates what
    gets MADE; nothing here makes anything.
  * NO NETWORK at runtime. Demucs weights are fetched once, at install, by
    `python -m orpheus_fetch` or the first separation run — after that this
    module is offline. Whisper is already local.
  * NO ARBITRARY AUDIO IN. Every entry point takes an Amphion job_id and nothing
    else. There is no path parameter, no URL parameter and no upload. That is
    what keeps Astro's stream strike-proof: a catalog of his own songs cannot
    accidentally acquire somebody else's master. A file picker here would not be
    a convenience, it would be the end of the property.
  * NO MICROPHONE, and no recording. OBS owns the mic on its own track. Orpheus
    plays and displays. Nothing captured means nothing retained.
  * NO GPU QUEUE-JUMPING. Separation and alignment REFUSE while an Amphion or
    Morpheus render is in flight, by name. They do not wait politely in the
    background — a job that silently queues behind a 10-minute video render is
    indistinguishable from one that hung.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import amphion
from paths import PH3B3_DATA

log = logging.getLogger("Ph3b3")

# Instrumentals live BESIDE the master, because they are a deliverable and are
# meant to be found. Vocal stems and Demucs scratch live in a cache dir that can
# be deleted at any time without losing anything a person asked for.
SONGS_DIR = amphion.SONGS_DIR
CACHE_DIR = PH3B3_DATA / "orpheus" / "cache"
SETLIST_FILE = PH3B3_DATA / "orpheus" / "setlist.json"

DEMUCS_MODEL = "htdemucs"
# Alignment model. Overridden by PH3B3_WHISPER_MODEL, the same knob stt_module
# reads, and defaulted to the same value so a machine with no .env still aligns
# properly. NOT a free choice: measured on "A Light in Every Home", base ran out
# of transcript at 80s of a 180s track and only one line landed on a real vocal
# onset; medium covered the sung range to 130s and put five lines on onsets.
# base is faster and it is wrong.
WHISPER_MODEL = "medium"

# Terminal job states. A job in any OTHER state is in flight and owns the GPU or
# is about to. Matched as "not terminal" rather than against a list of busy
# states, because Amphion's chunked path invents states as it goes
# ("generating 2/4") and an allow-list would quietly stop seeing them.
_TERMINAL = frozenset({"done", "error", "cancelled"})


class Busy(Exception):
    """The GPU is taken. Carries the name of the job holding it so the refusal
    can say which one rather than 'try again later'."""


class OrpheusError(Exception):
    """Anything that went wrong loudly enough to show a person mid-stream."""


def _cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


# ── GPU etiquette ────────────────────────────────────────────────────────────
def gpu_busy_with() -> str | None:
    """The job currently holding, or about to hold, the GPU — or None.

    Reads the SAME job tables the renderers write, rather than looking at
    nvidia-smi: a busy GPU is not the question. The question is whether this
    machine has promised the GPU to something, and that promise lives in
    morpheus.jobs / amphion.jobs and in morpheus.gpu_lock.
    """
    import morpheus
    for label, table in (("Morpheus render", morpheus.jobs), ("Amphion song", amphion.jobs)):
        for jid, j in list(table.items()):
            st = (j or {}).get("state")
            if st and st not in _TERMINAL:
                return f"{label} {jid} ({st})"
    if morpheus.gpu_lock.locked():
        # Held by something that did not register a job row. Reported anyway:
        # "something has the GPU" is still the honest answer.
        return "a GPU job already running"
    return None


def require_free_gpu() -> None:
    """Raise Busy, naming the job. Called at the TOP of every GPU entry point."""
    who = gpu_busy_with()
    if who:
        raise Busy(f"GPU busy: {who}")


# ── Songs Orpheus is allowed to touch ────────────────────────────────────────
def _sidecar_path(job_id: str) -> Path:
    return SONGS_DIR / f"{job_id}.json"


def _require_amphion_song(job_id: str) -> tuple[Path, dict]:
    """The master and sidecar for an Amphion render, or a loud failure.

    THIS IS THE WHOLE IMPORT POLICY. Orpheus reaches audio exactly one way: by
    the id of a track this machine generated, verified by the sidecar sitting
    next to it. There is no second way in, which is why no argument anywhere in
    this module is a path.
    """
    if not re.fullmatch(r"[0-9a-f]{6,32}", job_id or ""):
        raise OrpheusError("not an Amphion track id")
    src = amphion.song_path(job_id)
    if not src:
        raise OrpheusError(f"no Amphion master for {job_id}")
    side = amphion._sidecar_for(job_id)
    if not side:
        raise OrpheusError(f"no sidecar for {job_id} — Orpheus only plays Amphion renders")
    return src, side


def has_vocals(side: dict) -> bool:
    """Whether the render was asked to sing. An instrumental has no vocal stem to
    separate and no words to align, and that is a normal song, not an error."""
    return bool((side.get("lyrics") or "").strip())


# ── 1. Separation (Demucs htdemucs, GPU) ─────────────────────────────────────
# Demucs returns four stems (drums/bass/other/vocals). The instrumental is the
# mix MINUS vocals, and it is built by summing the other three rather than by
# subtracting the vocal stem from the master: subtraction leaves the vocal's
# separation error behind as a ghost, summing leaves silence where the vocal was.
_STEMS = ("drums", "bass", "other", "vocals")


def instrumental_path(job_id: str, side: dict | None = None) -> Path:
    """Where the instrumental for this track lives — named by the SLUG, so it
    lands beside the master under the name the song actually has."""
    side = amphion._sidecar_for(job_id) if side is None else side
    return SONGS_DIR / f"{amphion.slug_for(job_id, side)}-instrumental.flac"


def vocal_stem_path(job_id: str) -> Path:
    """The isolated vocal. A WORKING FILE: it exists so Whisper has a clean
    signal to align against, it lives in the cache, and deleting it costs
    nothing but a re-separation."""
    return _cache_dir() / f"{job_id}-vocals.flac"


def _demucs_device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def separate(job_id: str, force: bool = False) -> dict:
    """Split one Amphion render into stems; write the instrumental beside the
    master and the vocal into the cache. Returns the sidecar `stems` block.

    THE MASTER IS NEVER TOUCHED. Demucs reads it and writes elsewhere; nothing in
    this function opens the master for writing. That is what makes acceptance 1's
    "originals bit-identical" a property of the code rather than a hope.
    """
    require_free_gpu()
    src, side = _require_amphion_song(job_id)
    if not has_vocals(side):
        raise OrpheusError(
            "this render is an instrumental already — there is no vocal to separate")

    out = instrumental_path(job_id, side)
    voc = vocal_stem_path(job_id)
    if out.exists() and voc.exists() and not force:
        return side.get("stems") or _stems_block(job_id, out, voc, side, reused=True)

    import torch
    import numpy as np
    import soundfile as sf
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    t0 = time.monotonic()
    device = _demucs_device()
    log.info("[orpheus] separating %s on %s (%s)", job_id, device, DEMUCS_MODEL)

    wav, sr = sf.read(str(src), dtype="float32", always_2d=True)   # (frames, ch)
    model = get_model(DEMUCS_MODEL)
    model.to(device).eval()
    if sr != model.samplerate:
        wav, sr = _resample(wav, sr, model.samplerate)
    # Demucs wants (batch, channels, frames) and exactly model.audio_channels.
    x = torch.from_numpy(wav.T).unsqueeze(0)
    if x.shape[1] == 1 and model.audio_channels == 2:
        x = x.repeat(1, 2, 1)
    elif x.shape[1] > model.audio_channels:
        x = x[:, :model.audio_channels]
    ref = x.mean(dim=1, keepdim=True)
    x = (x - ref.mean()) / (ref.std() + 1e-8)                      # demucs' own normalisation
    try:
        with torch.no_grad():
            est = apply_model(model, x.to(device), device=device, split=True, overlap=0.25)[0]
        est = est * (ref.std() + 1e-8) + ref.mean()
    finally:
        model.cpu()
        if device == "cuda":
            torch.cuda.empty_cache()          # hand the VRAM back; renders need it

    names = list(model.sources)
    est = est.cpu().numpy()                                        # (stem, ch, frames)
    vocals = est[names.index("vocals")]
    instrumental = sum(est[names.index(n)] for n in names if n != "vocals")

    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), instrumental.T, sr)
    sf.write(str(voc), vocals.T, sr)
    _tag_instrumental(out, job_id, side)
    log.info("[orpheus] separated %s in %.1fs -> %s", job_id, time.monotonic() - t0, out.name)
    return _stems_block(job_id, out, voc, side, elapsed_s=round(time.monotonic() - t0, 1))


def _resample(wav, sr: int, target: int):
    """Only reached if a master is ever written at something other than the
    engine's rate. Kept simple and honest rather than clever."""
    import numpy as np
    n = int(round(wav.shape[0] * target / sr))
    idx = np.linspace(0, wav.shape[0] - 1, n)
    out = np.stack([np.interp(idx, np.arange(wav.shape[0]), wav[:, c])
                    for c in range(wav.shape[1])], axis=1).astype("float32")
    return out, target


def _tag_instrumental(path: Path, job_id: str, side: dict) -> None:
    """The instrumental inherits the original's metadata with " (Instrumental)"
    on the title. It carries the SAME provenance line: it is still AI-generated
    audio from this machine, and a file that loses that on the way out of the
    separator is a file that can be passed off as something else."""
    title = (side.get("title") or amphion.slug_for(job_id, side)) + " (Instrumental)"
    meta = amphion._tags_for(job_id, {**side, "title": title, "lyrics": ""}, "flac")
    tmp = path.with_suffix(".tagging.flac")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(path), "-c:a", "copy", *meta,
           "-metadata", f"AMPHION_INSTRUMENTAL_OF={job_id}",
           "-metadata", f"ORPHEUS_SEPARATION={DEMUCS_MODEL}", str(tmp)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and tmp.exists():
            tmp.replace(path)
        else:
            log.warning("[orpheus] instrumental tagging failed (audio kept): %s", r.stderr[-200:])
    except Exception as exc:
        log.warning("[orpheus] instrumental tagging failed (audio kept): %s", exc)
    finally:
        tmp.unlink(missing_ok=True)


def _demucs_version() -> str:
    try:
        import importlib.metadata as m
        return m.version("demucs")
    except Exception:
        return "unknown"


def _stems_block(job_id: str, out: Path, voc: Path, side: dict,
                 elapsed_s: float | None = None, reused: bool = False) -> dict:
    """What goes into the sidecar. Records the LINEAGE — which render, which seed,
    which slug, which model — so an instrumental found on its own can be traced
    back to the track it came from and the exact separator that made it."""
    return {"instrumental": out.name,
            "vocal_stem_cached": voc.name,
            "model": DEMUCS_MODEL,
            "demucs_version": _demucs_version(),
            "source_job_id": job_id,
            "source_seed": side.get("seed"),
            "source_slug": amphion.slug_for(job_id, side),
            "elapsed_s": elapsed_s,
            "separated_at": datetime.now(timezone.utc).isoformat(),
            "reused": reused}


def find_instrumental(job_id: str, side: dict | None = None) -> Path | None:
    """The instrumental on disk, or None.

    Prefers the filename RECORDED in the sidecar over the one computed from the
    current slug. Those two disagree the moment a track is renamed: the slug
    moves, the file on disk does not, and a computed-only lookup would declare a
    perfectly good instrumental missing and offer to spend GPU time remaking it.
    """
    side = amphion._sidecar_for(job_id) if side is None else side
    recorded = ((side.get("stems") or {}).get("instrumental") or "").strip()
    if recorded:
        p = SONGS_DIR / recorded
        if p.exists():
            return p
    p = instrumental_path(job_id, side)
    return p if p.exists() else None


# ── 2. Timing (Whisper word timestamps, aligned to the real lyrics) ──────────
# THE DIVISION OF LABOUR: the sidecar lyrics are the WORDS, Whisper supplies only
# WHEN. Whisper mishears sung vowels constantly — it is a speech model listening
# to melody — and a karaoke screen that displays what Whisper heard would put
# wrong words in front of the person who wrote the right ones.
#
# So the transcript is never displayed. It is aligned against the true lyrics and
# then thrown away, and every word on screen comes from the sidecar.

_SECTION_RE = re.compile(r"^\s*[\[(]\s*[^\]\)]{0,40}\s*[\])]\s*$")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")


def _norm(w: str) -> str:
    return "".join(ch for ch in (w or "").lower() if ch.isalnum())


def lyric_lines(lyrics: str) -> list[dict]:
    """The sidecar lyrics as display lines.

    Section markers ([Verse], [Chorus]) are kept as lines with no words: they are
    part of how Astro writes and reading them on screen tells him where he is,
    but they are never sung and must never take timing from a word.
    """
    out = []
    for raw in (lyrics or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        if _SECTION_RE.match(text):
            out.append({"text": text, "section": True, "words": []})
        else:
            out.append({"text": text, "section": False,
                        "words": _WORD_RE.findall(text)})
    return out


def transcribe_vocal(path: Path) -> list[dict]:
    """Whisper word timestamps for the ISOLATED VOCAL.

    Loaded on demand and released, rather than borrowing stt_module's instance:
    that model belongs to the microphone path, it may be mid-utterance, and
    Orpheus must never be the reason the wake word missed a turn.
    """
    import os
    import torch
    import whisper

    name = os.getenv("PH3B3_WHISPER_MODEL", WHISPER_MODEL)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("[orpheus] aligning with whisper %s on %s", name, device)
    model = whisper.load_model(name, device=device)
    try:
        res = model.transcribe(str(path), word_timestamps=True, language="en",
                               condition_on_previous_text=False, fp16=(device == "cuda"))
    finally:
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    words = []
    for seg in res.get("segments") or []:
        for w in seg.get("words") or []:
            t = (w.get("word") or "").strip()
            if t:
                words.append({"word": t, "start": float(w["start"]), "end": float(w["end"])})
    return words


def vocal_onsets(path: Path, hop: float = 0.05, quiet_before: float = 0.35) -> list[float]:
    """Times where singing STARTS, measured from the isolated stem.

    Whisper's word timestamps come from attention weights, they are noisy by
    ±0.2-0.5s, and they are not even the same twice — transcribing this track
    three times put the first word at 22.78s, 22.98s and 23.56s. The vocal stem
    does not have opinions: it is loud when he is singing and quiet when he is
    not. Used to correct Whisper rather than replace it, because energy says
    WHEN a phrase begins and nothing about which words are in it.

    The floor is the stem's own median level, not zero. Separation leaves a
    breath of bleed everywhere, and this track has a burst of it at 18s — five
    seconds before the first word — which an absolute threshold reads as singing.
    """
    import numpy as np
    import soundfile as sf
    try:
        wav, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        return []
    mono = wav.mean(axis=1)
    win = max(1, int(sr * hop))
    n = len(mono) // win
    if n < 3:
        return []
    rms = np.sqrt((mono[:n * win].reshape(-1, win) ** 2).mean(axis=1))
    # Twenty times the stem's own median, or 8% of its peak, whichever is higher.
    # Tuned against the real bleed burst on "A Light in Every Home", which sits at
    # eight times the floor five seconds before the first word — and deliberately
    # left with headroom above that, because bleed loud enough to pass 10x is
    # ordinary. The asymmetry is the point: a MISSED onset costs nothing (the line
    # keeps Whisper's own timing), while a FALSE one drags a line onto a breath.
    loud = rms > max(float(np.median(rms)) * 20.0, float(rms.max()) * 0.08)
    gap = max(1, int(quiet_before / hop))
    out = []
    for i in range(len(loud)):
        if loud[i] and not loud[max(0, i - gap):i].any():
            out.append(round(i * hop, 3))
    return out


_SNAP_WINDOW = 0.8          # how far a line start may be nudged onto an onset


def snap_to_onsets(lines: list[dict], onsets: list[float]) -> int:
    """Nudge each line onto the onset it is clearly meant to sit on. In place.

    Only LINE STARTS are snapped, and the whole line shifts with its start. A
    karaoke line reads as in time when it lights up at the moment the phrase
    begins; the words inside it are being swept relative to that, so moving them
    independently would buy accuracy nobody can see and cost the sweep its shape.

    A shift that would cross a neighbouring line is dropped rather than clamped.
    Clamping produces a line that starts exactly when the previous one ends,
    which looks deliberate and is not — dropping leaves Whisper's own answer,
    which is at least self-consistent.
    """
    timed = [ln for ln in lines if ln.get("start") is not None]
    moved = 0
    for idx, ln in enumerate(timed):
        near = [o for o in onsets if abs(o - ln["start"]) <= _SNAP_WINDOW]
        if not near:
            continue
        delta = min(near, key=lambda o: abs(o - ln["start"])) - ln["start"]
        if abs(delta) < 0.02:
            continue
        prev_end = timed[idx - 1]["end"] if idx else None
        next_start = timed[idx + 1]["start"] if idx + 1 < len(timed) else None
        if prev_end is not None and ln["start"] + delta < prev_end:
            continue
        if next_start is not None and ln["end"] + delta > next_start:
            continue
        ln["start"] += delta
        ln["end"] += delta
        for w in ln["words"]:
            if w["start"] is not None:
                w["start"] += delta
                w["end"] += delta
        moved += 1
    return moved


def align(lines: list[dict], heard: list[dict]) -> list[dict]:
    """Give every lyric word a start and an end.

    Monotonic by construction: difflib's matching blocks over the two normalised
    word streams are already in order, so a word can never be handed a time
    earlier than the word before it — which is the one property a karaoke
    highlight cannot survive losing.

    Anchors come from matched words. Everything between two anchors is spread
    evenly across the gap. That is the "interpolate rather than trust garbage"
    rule from the brief, and it is not a fallback for rare cases: a sung line
    routinely matches on three words out of eight, and the five in between are
    better off evenly spaced inside a known span than pinned to whatever Whisper
    thought it heard.
    """
    import difflib

    flat: list[tuple[int, int]] = []          # (line index, word index)
    toks: list[str] = []
    for li, ln in enumerate(lines):
        for wi, w in enumerate(ln["words"]):
            flat.append((li, wi))
            toks.append(_norm(w))

    times: list[list[float] | None] = [None] * len(flat)
    if flat and heard:
        htoks = [_norm(h["word"]) for h in heard]
        sm = difflib.SequenceMatcher(a=toks, b=htoks, autojunk=False)
        for i, j, n in sm.get_matching_blocks():
            for k in range(n):
                times[i + k] = [heard[j + k]["start"], heard[j + k]["end"]]

    _fill_gaps(times, heard)

    out = []
    cursor = 0                                # walks `times` in the same order as `flat`
    for ln in lines:
        words = []
        for w in ln["words"]:
            t = times[cursor]
            cursor += 1
            words.append({"word": w, "start": t[0] if t else None, "end": t[1] if t else None})
        starts = [w["start"] for w in words if w["start"] is not None]
        ends = [w["end"] for w in words if w["end"] is not None]
        out.append({"text": ln["text"], "section": ln["section"], "words": words,
                    "start": min(starts) if starts else None,
                    "end": max(ends) if ends else None})
    return out


def _fill_gaps(times: list[list[float] | None], heard: list[dict]) -> None:
    """Spread unanchored words evenly between the anchors either side, in place.

    Leading and trailing runs are the awkward ones: there is only one anchor, so
    the span is borrowed from the audio's own edges. A word with no timing at all
    stays None and the display simply does not sweep it — better than inventing a
    time and sweeping the wrong word.
    """
    n = len(times)
    anchors = [i for i, t in enumerate(times) if t is not None]
    if not anchors:
        return
    audio_start = heard[0]["start"] if heard else 0.0
    audio_end = heard[-1]["end"] if heard else 0.0

    def spread(lo: int, hi: int, t0: float, t1: float) -> None:
        """Words lo..hi-1 get equal slices of [t0, t1]."""
        count = hi - lo
        if count <= 0 or t1 <= t0:
            return
        step = (t1 - t0) / count
        for k in range(count):
            times[lo + k] = [t0 + k * step, t0 + (k + 1) * step]

    spread(0, anchors[0], audio_start, times[anchors[0]][0])
    for a, b in zip(anchors, anchors[1:]):
        if b > a + 1:
            spread(a + 1, b, times[a][1], times[b][0])
    spread(anchors[-1] + 1, n, times[anchors[-1]][1], audio_end)


def timing_path(job_id: str, side: dict | None = None) -> Path:
    side = amphion._sidecar_for(job_id) if side is None else side
    return SONGS_DIR / f"{amphion.slug_for(job_id, side)}-timing.json"


def find_timing(job_id: str, side: dict | None = None) -> Path | None:
    """Same rename-proof lookup as find_instrumental: the recorded name wins."""
    side = amphion._sidecar_for(job_id) if side is None else side
    recorded = ((side.get("stems") or {}).get("timing") or "").strip()
    if recorded:
        p = SONGS_DIR / recorded
        if p.exists():
            return p
    p = timing_path(job_id, side)
    return p if p.exists() else None


def build_timing(job_id: str, force: bool = False) -> dict:
    """Word-timed lyrics for one track. Requires the vocal stem, so separation
    runs first if it has not. Returns the written document."""
    require_free_gpu()
    src, side = _require_amphion_song(job_id)
    if not has_vocals(side):
        # Not an error. An instrumental has nothing to time, and the stage falls
        # back to no lyrics — which is a valid way to play a song.
        raise OrpheusError("this render has no lyrics — nothing to time")

    voc = vocal_stem_path(job_id)
    if not voc.exists():
        separate(job_id)

    out = timing_path(job_id, side)
    if out.exists() and not force:
        try:
            return json.loads(out.read_text("utf-8"))
        except Exception:
            pass                              # unreadable: fall through and rebuild

    import os
    t0 = time.monotonic()
    lines = align(lyric_lines(side.get("lyrics", "")), transcribe_vocal(voc))
    snapped = snap_to_onsets(lines, vocal_onsets(voc))

    # How much of the track the lyric sheet actually covers. ACE-Step vamps and
    # repeats sections the sheet only states once, so a three-minute render can
    # run out of written words at eighty seconds and keep singing. That is not a
    # failure and it is not fixable from the sheet — but the stage needs to know,
    # or it shows a frozen last line for a minute and looks broken.
    sung = [w["end"] for ln in lines for w in ln["words"] if w["end"] is not None]
    duration = float(side.get("measured_seconds") or side.get("seconds") or 0.0)
    doc = {"job_id": job_id,
           "slug": amphion.slug_for(job_id, side),
           "whisper_model": os.getenv("PH3B3_WHISPER_MODEL", WHISPER_MODEL),
           "source": "vocal stem (htdemucs) — timing only; words are the sidecar's",
           "built_at": datetime.now(timezone.utc).isoformat(),
           "elapsed_s": round(time.monotonic() - t0, 1),
           "lines_snapped_to_onset": snapped,
           "lyrics_end_s": round(max(sung), 2) if sung else None,
           "duration_s": duration or None,
           "lines": lines}
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info("[orpheus] timed %s: %d lines in %.1fs", job_id, len(lines), doc["elapsed_s"])
    return doc


def prepare(job_id: str, force: bool = False) -> dict:
    """Everything a song needs to be sung: stems then timing, one GPU check.

    The two steps are deliberately callable on their own as well — a batch run
    that dies halfway through alignment should not have to separate forty tracks
    again to resume.
    """
    require_free_gpu()
    _, side = _require_amphion_song(job_id)
    stems = separate(job_id, force=force)
    if has_vocals(side):
        build_timing(job_id, force=force)
        stems = {**stems, "timing": timing_path(job_id, side).name}
    _record_stems(job_id, stems)
    return stems


def _record_stems(job_id: str, stems: dict) -> None:
    """Write the `stems` block into the sidecar, preserving everything else.

    Read-modify-write of the whole document rather than a rebuild through
    amphion._write_sidecar: that function is a whitelist over GENERATION params
    and does not know about stems, so rebuilding through it would silently drop
    this block — and, worse, drop the title and slug the naming feature put there.
    """
    p = _sidecar_path(job_id)
    try:
        side = json.loads(p.read_text("utf-8"))
    except Exception as exc:
        raise OrpheusError(f"sidecar for {job_id} is unreadable: {exc}")
    side["stems"] = stems
    p.write_text(json.dumps(side, indent=2), encoding="utf-8")


# ── 2.5 Setlist ──────────────────────────────────────────────────────────────
# The night's running order, on disk. It survives a page reload, a browser crash
# and a restart of this service, because it has to: losing the lineup at 40
# minutes into a stream is not a bug someone forgives.
#
# Server-side rather than localStorage. The setlist is a property of the SHOW,
# not of a browser tab — Astro may well have the stage window on one screen and
# the panel on another, and two views of one queue that disagree is worse than
# no persistence at all.
MAX_SETLIST = 100


def _empty_setlist() -> dict:
    return {"items": [], "position": 0, "mode": "hold", "updated_at": None}


def load_setlist() -> dict:
    """The setlist, or an empty one. A corrupt file reads as empty rather than
    raising: the stage must open."""
    try:
        d = json.loads(SETLIST_FILE.read_text("utf-8"))
    except Exception:
        return _empty_setlist()
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        return _empty_setlist()
    base = _empty_setlist()
    base.update({k: d[k] for k in ("items", "position", "mode") if k in d})
    base["mode"] = "auto" if base.get("mode") == "auto" else "hold"
    base["position"] = max(0, min(int(base.get("position") or 0), max(0, len(base["items"]) - 1)))
    return base


def save_setlist(items: list[dict], position: int = 0, mode: str = "hold") -> dict:
    SETLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    d = {"items": items[:MAX_SETLIST],
         "position": max(0, min(int(position or 0), max(0, len(items) - 1))),
         "mode": "auto" if mode == "auto" else "hold",
         "updated_at": datetime.now(timezone.utc).isoformat()}
    SETLIST_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return d


def setlist_entry(job_id: str) -> dict:
    """One row of the queue. Denormalised on purpose — the stage must be able to
    draw the whole running order without a round trip per song, and a title that
    changes mid-show is a smaller problem than a queue that will not render."""
    _, side = _require_amphion_song(job_id)
    inst = find_instrumental(job_id, side)
    tim = find_timing(job_id, side)
    return {"job_id": job_id,
            "title": (side.get("title") or "").strip() or amphion.slug_for(job_id, side),
            "slug": amphion.slug_for(job_id, side),
            "seconds": side.get("measured_seconds") or side.get("seconds"),
            "has_instrumental": inst is not None,
            "has_timing": tim is not None,
            "instrumental_only": not has_vocals(side)}


def add_to_setlist(job_id: str) -> dict:
    """Append a song. Refuses one with no instrumental: a queue entry that cannot
    play is a trapdoor in the running order, and the caller is expected to have
    prepared it first."""
    entry = setlist_entry(job_id)
    if not entry["has_instrumental"]:
        raise OrpheusError(
            f"{entry['title']!r} has no instrumental yet — separate it before queueing")
    d = load_setlist()
    d["items"].append(entry)
    return save_setlist(d["items"], d["position"], d["mode"])


def library() -> list[dict]:
    """Every Amphion render, with what Orpheus can do with it.

    ONLY Amphion renders. There is no branch here that reads any other directory,
    and that is the strike-proof property in one line of code: Astro's stage can
    physically only play songs this machine wrote.
    """
    out = []
    for s in amphion.library(500):
        try:
            out.append(setlist_entry(s["job_id"]))
        except OrpheusError:
            continue
    return out
