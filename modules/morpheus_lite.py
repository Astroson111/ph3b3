"""
morpheus_lite.py — stripped, demo-day image path for Ph3b3 ("Morpheus-lite").

This is NOT Nyx's Morpheus: one hardcoded workflow, zero knobs, plus a pre-baked
gallery fallback. Every image request — in EVERY mode — passes the content-safety
floor FIRST:

    handle(prompt):
        1. floor_check(prompt)     hard six-category block, no off switch   <-- first, always
        2. profile_check(prompt)   demo denylist (strict profile)
        3. dispatch on the runtime image mode (get_mode()):
             gallery -> serve a pre-baked image, no generation
             live    -> generate via ComfyUI (only if LIVE_GEN_ENABLED)
             auto    -> try live (if enabled); on any failure fall back to gallery

TWO independent controls:
  - MODE (get_mode/set_mode): gallery|live|auto, switchable at runtime, persisted.
  - LIVE_GEN_ENABLED (env, default OFF): master server gate. While OFF the API
    refuses live generation even if the mode/request/UI asks for it. UI state is
    never trusted for this — the gate is enforced here, server-side.

Live generation does a single-GPU swap on the shared 6GB card:
    reachable? (if not, DO NOT evict) -> evict hermes3 (keep_alive:0) -> queue the
    one SD1.5 512x512 workflow -> poll /history (HARD_TIMEOUT) -> fetch PNG -> save
    -> background: free ComfyUI VRAM + pre-warm hermes3 (so the next chat is fast).

handle() never raises to the caller — floor blocks, gate refusals, empty gallery,
and live failures all return clean dicts, so the panel shows a message, never a
stack trace.
"""
import logging
import os
import random
import threading
import time
from pathlib import Path

import httpx

from morpheus_floor import floor_check, profile_check
from paths import PH3B3_HOME, MORPHEUS_DATA

log = logging.getLogger("ph3b3.morpheus_lite")

_VALID_MODES  = ("gallery", "live", "auto")
_DEFAULT_MODE = os.getenv("PH3B3_IMAGE_MODE", "gallery").strip().lower()
GALLERY_DIR   = Path(os.getenv("PH3B3_GALLERY_DIR", str(PH3B3_HOME / "gallery")))
GENERATED_DIR = Path(os.getenv("PH3B3_GENERATED_DIR", str(MORPHEUS_DATA / "images")))
_IMG_EXTS     = (".png", ".jpg", ".jpeg", ".webp")

# ── Live generation config ───────────────────────────────────────────
COMFY_HOST   = os.getenv("COMFY_HOST",  "http://127.0.0.1:8188")
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
HERMES_MODEL = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3"))
_HERMES_STEM = HERMES_MODEL.split(":")[0]
# One hardcoded workflow — SD1.5, 512x512, fixed sampler/steps/cfg. Zero knobs.
_CKPT      = os.getenv("PH3B3_IMAGE_CKPT", "v1-5-pruned-emaonly-fp16.safetensors")
_STEPS     = 20
_CFG       = 7.0
_SAMPLER   = "euler"
_SCHEDULER = "normal"
_SIZE      = 512
_NEG       = "blurry, low quality, watermark, text, signature, deformed"
# Hard ceiling for the whole live path (evict + queue + sample + fetch). Cold
# generation measured ~12s; 120s leaves generous margin before we bail to gallery.
HARD_TIMEOUT = int(os.getenv("PH3B3_IMAGE_TIMEOUT", "120"))

# Master server-side gate for live generation. Default OFF. When false the API
# refuses live generation even if the mode/request/UI asks for it. Flip
# PH3B3_LIVE_GEN_ENABLED=true only after the safety floor is verified.
LIVE_GEN_ENABLED = os.getenv("PH3B3_LIVE_GEN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")

_BLOCK_MSG = "That request was blocked by the content-safety filter and cannot be generated."

try:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    log.warning("[morpheus-lite] could not create GENERATED_DIR %s: %s", GENERATED_DIR, e)


# ── Runtime image mode (switchable without restart; persisted to a file) ──
_MODE_FILE = MORPHEUS_DATA / "image_mode"


def _load_mode() -> str:
    try:
        m = _MODE_FILE.read_text(encoding="utf-8").strip().lower()
        if m in _VALID_MODES:
            return m
    except OSError:
        pass
    return _DEFAULT_MODE if _DEFAULT_MODE in _VALID_MODES else "gallery"


_current_mode = _load_mode()


def get_mode() -> str:
    return _current_mode


def set_mode(mode: str) -> str:
    """Set the runtime image mode (gallery|live|auto), persisted so it survives a
    restart. Does NOT enable live generation — that stays governed by the
    LIVE_GEN_ENABLED master gate."""
    global _current_mode
    mode = (mode or "").strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    _current_mode = mode
    try:
        _MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _MODE_FILE.write_text(mode, encoding="utf-8")
    except OSError as e:
        log.warning("[morpheus-lite] could not persist mode: %s", e)
    return mode


# ── Served-image resolution (gallery + generated), traversal-safe ────
def resolve_served_image(name: str) -> Path | None:
    """Return a Path for a served image name (from generated or gallery dirs), or
    None. Rejects any path-traversal in the name."""
    if not name or name != Path(name).name or "/" in name or "\\" in name or ".." in name:
        return None
    for base in (GENERATED_DIR, GALLERY_DIR):
        p = base / name
        if p.is_file():
            return p
    return None


def list_served_images() -> list[str]:
    """Names of every servable image — generated first, then pre-baked gallery —
    ordered newest-first by mtime. Powers the web UI's gallery view; each name here
    resolves through /image/file/{name} (same traversal-safe served dirs)."""
    seen: dict[str, float] = {}
    for base in (GENERATED_DIR, GALLERY_DIR):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if p.is_file() and p.suffix.lower() in _IMG_EXTS and p.name not in seen:
                try:
                    seen[p.name] = p.stat().st_mtime
                except OSError:
                    seen[p.name] = 0.0
    return [name for name, _ in sorted(seen.items(), key=lambda kv: kv[1], reverse=True)]


# ── Gallery fallback ─────────────────────────────────────────────────
def _gallery_files() -> list[Path]:
    if not GALLERY_DIR.is_dir():
        return []
    return sorted(p for p in GALLERY_DIR.iterdir()
                  if p.is_file() and p.suffix.lower() in _IMG_EXTS)


def _pick_gallery(prompt: str) -> Path | None:
    files = _gallery_files()
    if not files:
        return None
    words = {w for w in "".join(c.lower() if c.isalnum() else " " for c in prompt).split()
             if len(w) > 3}
    if words:
        best_score, best = 0, None
        for p in files:
            score = sum(w in p.stem.lower() for w in words)
            if score > best_score:
                best_score, best = score, p
        if best is not None:
            return best
    return random.choice(files)


def _gallery_result(prompt: str) -> dict:
    pick = _pick_gallery(prompt)
    if pick is None:
        return {"ok": False, "mode": get_mode(), "source": "gallery",
                "error": "No gallery images are available yet."}
    return {"ok": True, "mode": get_mode(), "source": "gallery",
            "image_url": f"/image/file/{pick.name}", "name": pick.name}


# ── Live generation (GPU swap) ───────────────────────────────────────
def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0)


def _comfy_reachable() -> bool:
    try:
        with _client() as c:
            return c.get(f"{COMFY_HOST}/system_stats", timeout=5.0).status_code == 200
    except Exception:
        return False


def _evict_hermes() -> None:
    """keep_alive:0 with an empty prompt blocks until the model unloads; then poll
    /api/ps (defense-in-depth) until hermes3 is no longer resident (VRAM freed)."""
    with _client() as c:
        try:
            c.post(f"{OLLAMA_HOST}/api/generate",
                   json={"model": HERMES_MODEL, "prompt": "", "keep_alive": 0}, timeout=60.0)
        except Exception as e:
            log.warning("[morpheus-lite] evict request error (continuing): %s", e)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                resident = [m.get("name", "") for m in c.get(f"{OLLAMA_HOST}/api/ps").json().get("models", [])]
            except Exception:
                break
            if not any(_HERMES_STEM in n for n in resident):
                log.info("[morpheus-lite] hermes3 evicted — VRAM freed for ComfyUI")
                return
            time.sleep(1)
        log.warning("[morpheus-lite] hermes3 still resident after evict poll — proceeding")


def _release_and_warm() -> None:
    """Background cleanup after a swap: free ComfyUI's VRAM (it keeps SD1.5 resident
    after a job), THEN pre-warm hermes3 into the freed space. Runs off-thread so it
    never delays the image response. Called after a successful generation (so the
    next chat skips the ~cold reload) and after a post-eviction failure (so the box
    is never left evicted with nothing loaded). Freeing first avoids SD1.5+hermes3
    both fighting for the 6GB card."""
    def _seq():
        try:
            with httpx.Client(timeout=30.0) as c:
                c.post(f"{COMFY_HOST}/free", json={"unload_models": True, "free_memory": True})
            log.info("[morpheus-lite] freed ComfyUI VRAM")
        except Exception as e:
            log.warning("[morpheus-lite] ComfyUI /free failed: %s", e)
        try:
            with httpx.Client(timeout=180.0) as c:
                c.post(f"{OLLAMA_HOST}/api/generate",
                       json={"model": HERMES_MODEL, "prompt": "", "keep_alive": "5m"})
            log.info("[morpheus-lite] hermes3 pre-warmed — next chat will be fast")
        except Exception as e:
            log.warning("[morpheus-lite] hermes3 pre-warm failed: %s", e)
    threading.Thread(target=_seq, daemon=True).start()


def _workflow(prompt: str) -> dict:
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": random.randint(1, 2**31 - 1), "steps": _STEPS, "cfg": _CFG,
            "sampler_name": _SAMPLER, "scheduler": _SCHEDULER, "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": _CKPT}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": _SIZE, "height": _SIZE, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEG, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ph3b3", "images": ["8", 0]}},
    }


def generate_live(prompt: str) -> dict:
    """Evict hermes3, run the one SD1.5 workflow on ComfyUI, save + return the PNG.
    Raises on unreachable ComfyUI (without evicting) or on timeout/error (after
    scheduling free+re-warm). Callers (handle) fall back to the gallery on any raise.
    NOTE: this does not itself check LIVE_GEN_ENABLED — handle() gates entry."""
    if not prompt:
        raise RuntimeError("empty prompt")
    if not _comfy_reachable():
        # Do NOT evict — leaving hermes3 loaded is safer than a cold box.
        raise RuntimeError(f"ComfyUI not reachable at {COMFY_HOST}")

    t0 = time.monotonic()
    _evict_hermes()
    try:
        with _client() as c:
            pid = c.post(f"{COMFY_HOST}/prompt", json={"prompt": _workflow(prompt)}).json()["prompt_id"]
            log.info("[morpheus-lite] queued ComfyUI prompt %s", pid)
            img = None
            while time.monotonic() - t0 < HARD_TIMEOUT:
                entry = c.get(f"{COMFY_HOST}/history/{pid}").json().get(pid)
                if entry and entry.get("outputs"):
                    for node in entry["outputs"].values():
                        if node.get("images"):
                            img = node["images"][0]; break
                    if img:
                        break
                time.sleep(1)
            if img is None:
                raise TimeoutError(f"ComfyUI generation exceeded {HARD_TIMEOUT}s")
            data = c.get(f"{COMFY_HOST}/view", params={
                "filename": img["filename"], "subfolder": img.get("subfolder", ""),
                "type": img.get("type", "output")}).content
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("ComfyUI returned non-PNG output")
        name = f"gen_{pid}.png"
        (GENERATED_DIR / name).write_bytes(data)
        secs = round(time.monotonic() - t0, 1)
        log.info("[morpheus-lite] live image %s (%d bytes) in %ss", name, len(data), secs)
        _release_and_warm()  # free ComfyUI VRAM + pre-warm hermes3 so the next chat is fast
        return {"ok": True, "source": "live", "image_url": f"/image/file/{name}",
                "name": name, "gen_seconds": secs}
    except Exception:
        _release_and_warm()  # post-eviction failure: free + reload so the box isn't left cold
        raise


def handle(prompt: str) -> dict:
    """Single entry point for an image request. Returns a clean JSON-able dict in
    all cases. Never raises to the caller."""
    prompt = (prompt or "").strip()

    # ── SAFETY FLOOR — first, always, every mode ────────────────────────────
    cat = floor_check(prompt)
    if cat is not None:
        log.warning("[safety] image request floor-blocked — category: %s", cat)
        return {"ok": False, "blocked": True, "reason": _BLOCK_MSG}
    if not profile_check(prompt):
        log.info("[safety] image request denied by profile")
        return {"ok": False, "blocked": True, "reason": _BLOCK_MSG}

    # ── Mode dispatch (+ live-generation master gate) ───────────────────────
    mode = get_mode()
    if mode == "gallery":
        return _gallery_result(prompt)

    if not LIVE_GEN_ENABLED:
        # Gate off: refuse explicit live outright; auto quietly serves gallery.
        if mode == "live":
            log.info("[morpheus-lite] live requested but PH3B3_LIVE_GEN_ENABLED is off — refused")
            return {"ok": False, "live_disabled": True, "mode": "live",
                    "reason": "Live image generation is not enabled on this build."}
        fb = _gallery_result(prompt)
        fb["mode"] = mode
        fb["live_disabled"] = True
        return fb

    if mode in ("live", "auto"):
        try:
            result = generate_live(prompt)
            result.setdefault("mode", mode)
            result.setdefault("source", "live")
            return result
        except Exception as e:
            log.warning("[morpheus-lite] live generation failed (%s) — "
                        "falling back to gallery: %s", mode, e)
            fb = _gallery_result(prompt)
            fb["mode"] = mode
            fb["fell_back"] = True
            fb["live_error"] = "live generation unavailable"
            return fb

    log.warning("[morpheus-lite] unknown mode %r — using gallery", mode)
    return _gallery_result(prompt)
