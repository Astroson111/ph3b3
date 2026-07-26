"""Amphion — local song generation for Ph3b3 (ACE-Step 1.5, via ComfyUI).

Architecturally Morpheus's SIBLING, not a new integration: it rides the same
ComfyUI backend, the SAME GPU lock (morpheus.gpu_lock), the same Ollama-evict
swap, and the same content floor. It does NOT invent a second GPU queue.

Jobs are long by Ph3b3 standards, so they follow the Morpheus job pattern:
announced, progress-visible, cancellable. Output lands in ~/ph3b3_data/songs/
with a reproducibility sidecar (prompt, lyrics, model variant, seed) beside each
track — including failures, so a bad result can be reproduced.

SAFETY: the content floor is the Morpheus floor, reused (NOT re-authored), run on
the prompt AND the lyrics before anything is queued. No LoRA / voice-clone path
exists here by construction — the workflow contains no LoRA loader and there is no
training endpoint.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

import morpheus                      # reuse gpu_lock, evict_hermes, comfy_*, floor_check, profile_check
from paths import PH3B3_DATA

log = logging.getLogger("Ph3b3")

COMFY_HOST = morpheus.COMFY_HOST
SONGS_DIR = PH3B3_DATA / "songs"

# ── ACE-Step 1.5 2B "base" (chose base for quality; there is no 2B sft) ──────────
DIT_BY_VARIANT = {"base": "acestep_v1.5_base.safetensors"}
ENC1 = "qwen_0.6b_ace15.safetensors"     # DualCLIPLoader needs BOTH qwen encoders
ENC2 = "qwen_1.7b_ace15.safetensors"
VAE  = "ace_1.5_vae.safetensors"
STEPS, CFG, SAMPLER, SCHED, SHIFT = 50, 6.0, "euler", "simple", 3.0   # base settings (NOT turbo's 8/1)
DEFAULT_DURATION = 60.0
MAX_DURATION = 240.0

# In-memory job state (job_id -> {state, ...}). Mirrors morpheus.jobs.
# states: queued -> loading -> generating -> done | error | cancelled
jobs: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


def _songs_dir() -> Path:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    return SONGS_DIR


def ready() -> bool:
    """ComfyUI reachable AND the ACE-Step base weights are on disk. Used for the
    honest boot line — do not register silently and fail at first use."""
    if not morpheus.comfy_up():
        return False
    # weights live under the ComfyUI install; probe the known dirs.
    cu = Path.home() / "Desktop" / "comfyui" / "models"
    need = [cu / "diffusion_models" / DIT_BY_VARIANT["base"],
            cu / "text_encoders" / ENC1, cu / "text_encoders" / ENC2,
            cu / "vae" / VAE]
    return all(p.exists() for p in need)


# ── Content floor — the Morpheus floor, reused, on prompt AND lyrics ─────────────
def content_floor(tags: str, lyrics: str = "") -> str | None:
    """Return a floor category string if the hard floor fires on the prompt OR the
    lyrics, else None. Reuses morpheus.floor_check verbatim — never a parallel floor."""
    for field in (tags or "", lyrics or ""):
        if field.strip():
            cat = morpheus.floor_check(field)
            if cat:
                return cat
    return None


def profile_ok(tags: str, lyrics: str = "") -> bool:
    """Profile denylist (default strict) on prompt AND lyrics. Call only after the
    floor passes, mirroring Morpheus."""
    if not morpheus.profile_check(tags or ""):
        return False
    if (lyrics or "").strip() and not morpheus.profile_check(lyrics):
        return False
    return True


# ── ComfyUI ACE-Step 1.5 text-to-music workflow (API format) ────────────────────
def build_workflow(job_id: str, p: dict) -> dict:
    dit = DIT_BY_VARIANT.get(p.get("variant", "base"), DIT_BY_VARIANT["base"])
    return {
      "1":  {"class_type": "UNETLoader", "inputs": {"unet_name": dit, "weight_dtype": "default"}},
      "2":  {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": ENC1, "clip_name2": ENC2, "type": "ace", "device": "default"}},
      "3":  {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
      "4":  {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": SHIFT}},
      "5":  {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
                "clip": ["2", 0], "tags": p["tags"], "lyrics": p.get("lyrics", ""),
                "seed": p["seed"], "bpm": p.get("bpm", 120), "duration": float(p["seconds"]),
                "timesignature": p.get("timesig", "4"), "language": p.get("language", "en"),
                "keyscale": p.get("keyscale", "C major"), "generate_audio_codes": True,
                "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9, "top_k": 0, "min_p": 0.0}},
      "6":  {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
      "7":  {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": float(p["seconds"]), "batch_size": 1}},
      "8":  {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": p["seed"], "steps": STEPS, "cfg": CFG,
                "sampler_name": SAMPLER, "scheduler": SCHED, "positive": ["5", 0], "negative": ["6", 0],
                "latent_image": ["7", 0], "denoise": 1.0}},
      "9":  {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
      "10": {"class_type": "SaveAudio", "inputs": {"audio": ["9", 0], "filename_prefix": f"amphion/{job_id}"}},
    }


def _write_sidecar(job_id: str, p: dict, path: Path) -> None:
    """Reproducibility sidecar beside the track (prompt/lyrics/variant/seed). Per brief:
    written even on failure so a bad result can be reproduced."""
    meta = {"job_id": job_id, "model_variant": p.get("variant", "base"),
            "model_file": DIT_BY_VARIANT.get(p.get("variant", "base")),
            "steps": STEPS, "cfg": CFG, "sampler": SAMPLER, "scheduler": SCHED, "shift": SHIFT,
            "tags": p.get("tags", ""), "lyrics": p.get("lyrics", ""), "bpm": p.get("bpm"),
            "keyscale": p.get("keyscale"), "timesignature": p.get("timesig", "4"),
            "seconds": p.get("seconds"), "seed": p.get("seed"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": "Ph3b3 Amphion — AI-generated (ACE-Step 1.5)"}
    (path.with_suffix(".json")).write_text(json.dumps(meta, indent=2))


def new_job() -> str:
    jid = uuid.uuid4().hex[:12]
    jobs[jid] = {"state": "queued", "created_at": datetime.now(timezone.utc).isoformat()}
    return jid


async def run_generation(job_id: str, p: dict) -> None:
    """Full GPU-swap lifecycle on the shared morpheus.gpu_lock. Always a BackgroundTask."""
    async with morpheus.gpu_lock:
        async with httpx.AsyncClient() as http:
            path = _songs_dir() / f"{job_id}.flac"
            try:
                jobs[job_id]["state"] = "loading"
                await morpheus.evict_hermes(http)          # free VRAM: swap Ollama out (shared pattern)
                jobs[job_id]["state"] = "generating"
                pid = await morpheus.comfy_queue(http, build_workflow(job_id, p))
                jobs[job_id]["comfy_id"] = pid
                outputs = await morpheus.comfy_wait(http, pid, timeout_s=300)
                audio = next(a for node in outputs.values() if "audio" in node for a in node["audio"])
                raw = (await http.get(f"{COMFY_HOST}/view", params={
                    "filename": audio["filename"], "subfolder": audio.get("subfolder", ""),
                    "type": audio.get("type", "output")}, timeout=120.0)).content
                path.write_bytes(raw)
                _write_sidecar(job_id, p, path)
                jobs[job_id].update(state="done", file=str(path))
                log.info("[amphion] job %s done -> %s (%d bytes)", job_id, path.name, len(raw))
            except asyncio.CancelledError:
                jobs[job_id]["state"] = "cancelled"
                _write_sidecar(job_id, p, path)            # keep the recipe even on cancel
                log.info("[amphion] job %s cancelled", job_id)
                raise
            except Exception as exc:
                jobs[job_id].update(state="error", error=str(exc))
                _write_sidecar(job_id, p, path)            # reproduce the failure
                log.warning("[amphion] job %s error: %s", job_id, exc)
            finally:
                await morpheus.comfy_free(http)
                _tasks.pop(job_id, None)


async def cancel(job_id: str) -> bool:
    """Interrupt a running ComfyUI job and cancel its task. Cooperative, like Morpheus."""
    t = _tasks.get(job_id)
    if jobs.get(job_id, {}).get("state") in (None, "done", "error", "cancelled"):
        return False
    try:
        async with httpx.AsyncClient() as http:
            await http.post(f"{COMFY_HOST}/interrupt", timeout=10.0)
    except Exception as exc:
        log.warning("[amphion] interrupt failed (non-fatal): %s", exc)
    if t and not t.done():
        t.cancel()
    jobs.setdefault(job_id, {})["state"] = "cancelled"
    return True


def register_task(job_id: str, task: asyncio.Task) -> None:
    _tasks[job_id] = task


# ── Library — scan songs/ + sidecars (no SQLite; sidecar IS the record) ──────────
def library(n: int = 100) -> list[dict]:
    d = _songs_dir()
    out = []
    for f in sorted(d.glob("*.flac"), key=lambda x: x.stat().st_mtime, reverse=True)[:n]:
        side = f.with_suffix(".json")
        meta = json.loads(side.read_text()) if side.exists() else {}
        out.append({"job_id": f.stem, "tags": meta.get("tags", ""), "lyrics": meta.get("lyrics", ""),
                    "seed": meta.get("seed"), "variant": meta.get("model_variant", "base"),
                    "bpm": meta.get("bpm"), "keyscale": meta.get("keyscale"),
                    "created_at": meta.get("created_at"), "bytes": f.stat().st_size})
    return out


def song_path(job_id: str) -> Path | None:
    p = _songs_dir() / f"{job_id}.flac"
    return p if p.exists() and p.parent == _songs_dir() else None


# ── Export (amendment 5) — FLAC master stays the ONLY copy on disk; convert at
# download. -1 dBTP true-peak normalize on EVERY export (export-only — the stored
# master is never touched, so it stays reversible). WAV = Dio-karaoke-ready. ─────
EXPORT_FORMATS = frozenset({"flac", "wav", "mp3"})


def _true_peak_gain_db(src: Path) -> float:
    """Measure the master's input true-peak (ffmpeg loudnorm analysis) and return the
    gain that brings it to -1 dBTP. 0.0 on any parse failure (safe no-op)."""
    import subprocess, re
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)
        m = re.search(r'"input_tp"\s*:\s*"?(-?\d+(?:\.\d+)?)', r.stderr)
        tp = float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0
    return round(-1.0 - tp, 2)


# ── Embedded metadata (producer addendum, item 1) ────────────────────────────
# The sidecar JSON is intended metadata, not a log — but it sits next to the
# master and does NOT travel. Drag the exported WAV into a DAW and the bpm, key
# and lyrics are gone. So write them into the file itself: FLAC takes Vorbis
# comments, MP3 takes ID3v2 (TBPM / TKEY / USLT for lyrics), WAV takes a RIFF
# INFO chunk which is much narrower.
#
# WAV IS DELIBERATELY SPARSE. RIFF INFO has no bpm, key or lyrics field. ffmpeg
# will happily accept -metadata bpm=120 for a WAV and silently drop it, which
# would look like it worked. Rather than fake it, WAV carries only what the
# format really holds (title, artist, comment, date) with the rest folded into
# the comment. "Accept what fits and don't fake the rest", per the brief.
PROVENANCE = "AI-generated by Ph3b3 Amphion (ACE-Step 1.5)"


def _tags_for(job_id: str, p: dict, fmt: str) -> list[str]:
    """ffmpeg -metadata arguments for this format. Provenance is MANDATORY and is
    written in every format — it is what makes the remix provenance check
    enforceable, and it is the honest thing to ship on generated audio."""
    prov = f"{PROVENANCE}; generation_id={job_id}"
    title = (p.get("title") or f"Amphion {job_id}").strip()
    tags = (p.get("tags") or "").strip()
    lyrics = (p.get("lyrics") or "").strip()
    bpm = p.get("bpm")
    key = (p.get("keyscale") or "").strip()
    seed = p.get("seed")
    dur = p.get("seconds")

    if fmt == "wav":
        # RIFF INFO only. Everything that has no home goes into the comment
        # rather than being written to a field the format will drop.
        extra = "; ".join(x for x in (
            f"bpm={bpm}" if bpm else "", f"key={key}" if key else "",
            f"seed={seed}" if seed is not None else "",
            f"duration={dur}s" if dur else "", f"style={tags}" if tags else "") if x)
        return ["-metadata", f"title={title}",
                "-metadata", "artist=Ph3b3 Amphion",
                "-metadata", f"comment={prov}" + (f"; {extra}" if extra else "")]

    m = ["-metadata", f"title={title}",
         "-metadata", "artist=Ph3b3 Amphion",
         "-metadata", "album=Amphion Sessions",
         "-metadata", f"comment={prov}",
         "-metadata", f"AMPHION_GENERATION_ID={job_id}",
         "-metadata", f"AMPHION_PROVENANCE={PROVENANCE}"]
    if tags:
        m += ["-metadata", f"genre={tags}"]
    if bpm:
        m += ["-metadata", f"TBPM={bpm}", "-metadata", f"BPM={bpm}"]
    if key:
        m += ["-metadata", f"TKEY={key}", "-metadata", f"KEY={key}",
              "-metadata", f"initial_key={key}"]
    if seed is not None:
        m += ["-metadata", f"AMPHION_SEED={seed}"]
    if dur:
        m += ["-metadata", f"AMPHION_DURATION={dur}"]
    if lyrics:
        # FLAC: LYRICS Vorbis comment. MP3: ffmpeg maps `lyrics` to a USLT frame.
        m += ["-metadata", f"lyrics={lyrics}", "-metadata", f"LYRICS={lyrics}"]
    return m


def _sidecar_for(job_id: str) -> dict:
    """The generation record written beside the master, or {} if absent."""
    try:
        return json.loads((_songs_dir() / f"{job_id}.json").read_text("utf-8"))
    except Exception:
        return {}


def export_bytes(job_id: str, fmt: str) -> tuple[bytes, str, str] | None:
    """Convert the master FLAC to fmt (flac/wav/mp3) with an export-only -1 dBTP
    normalize. Returns (bytes, media_type, filename) or None. Master untouched."""
    import subprocess, tempfile
    fmt = (fmt or "flac").lower()
    src = song_path(job_id)
    if not src or fmt not in EXPORT_FORMATS:
        return None
    gain = _true_peak_gain_db(src)
    af = f"volume={gain}dB" if gain else "anull"
    with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tf:
        dst = tf.name
    meta = _tags_for(job_id, _sidecar_for(job_id), fmt)
    if fmt == "wav":        # Dio karaoke-ready: 44.1 kHz / 16-bit / stereo pcm_s16le
        cmd = ["ffmpeg", "-y", "-i", str(src), "-af", af, "-ar", "44100", "-ac", "2",
               "-c:a", "pcm_s16le", *meta, dst]
        mt = "audio/wav"
    elif fmt == "mp3":      # 320 kbps CBR, 44.1 kHz; id3v2.3 is what DJ software reads
        cmd = ["ffmpeg", "-y", "-i", str(src), "-af", af, "-ar", "44100",
               "-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3",
               "-write_id3v1", "1", *meta, dst]
        mt = "audio/mpeg"
    else:                   # flac — native 48 kHz, normalized
        cmd = ["ffmpeg", "-y", "-i", str(src), "-af", af, "-c:a", "flac", *meta, dst]
        mt = "audio/flac"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            log.warning("[amphion] export %s -> %s failed: %s", job_id, fmt, r.stderr[-300:])
            return None
        return Path(dst).read_bytes(), mt, f"{job_id}.{fmt}"
    finally:
        Path(dst).unlink(missing_ok=True)


def delete_song(job_id: str) -> bool:
    p = song_path(job_id)
    if not p:
        return False
    p.unlink(missing_ok=True)
    p.with_suffix(".json").unlink(missing_ok=True)
    return True
