"""
morpheus.py — GPU-swap image generation for Ph3b3.

GPU swap lifecycle (one asyncio.Lock, single-user):
  POST /image/generate
    └─ acquire gpu_lock
         1. evict Hermes from VRAM  (keep_alive:0)  ─ state: evicting
         2. VERIFY eviction (/api/ps poll)           ← OOM TRAP #1
         3. queue workflow to ComfyUI                ─ state: loading
         4. wait for completion (/history poll)      ─ state: sampling
         5. fetch PNG, save to disk, index SQLite    ─ state: saving
         6. free ComfyUI VRAM (/free)                ← LEAK TRAP #2
       └─ release gpu_lock
  (Hermes lazily reloads on the next /chat turn, ~2-5s)

Verified on this Ollama build: keep_alive:0 with empty prompt blocks until
the model is actually unloaded and returns done_reason:"unload". The /api/ps
poll below is defense-in-depth, not the primary eviction signal.
"""
import asyncio
import copy
import logging
import os
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("ph3b3.morpheus")

# ── Config (all overridable via env) ─────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST",  "http://127.0.0.1:11434")
# Match against server.py's HEAVY_MODEL so eviction targets the right model.
HERMES_MODEL = os.getenv("PH3B3_HEAVY_MODEL",
               os.getenv("PH3B3_MODEL", "hermes3"))
_HERMES_STEM = HERMES_MODEL.split(":")[0]  # "hermes3" — safe startswith match

COMFY_HOST   = os.getenv("COMFY_HOST",  "http://127.0.0.1:8188")
IMAGE_DIR    = Path(os.getenv("MORPHEUS_IMAGE_DIR",
                              "$HOME/Desktop/ph3b3_v2_data/images"))
DB_PATH      = Path(os.getenv("MORPHEUS_DB_PATH",
                              "$HOME/Desktop/ph3b3_v2_data/generations.db"))
SDXL_CKPT    = os.getenv("MORPHEUS_CKPT",  "sd_xl_base_1.0.safetensors")
SDXL_STEPS   = int(os.getenv("MORPHEUS_STEPS", "20"))
SDXL_NEG     = os.getenv(
    "MORPHEUS_NEG",
    "blurry, low quality, deformed, ugly, bad anatomy, watermark, text, signature",
)

# ── SDXL workflow template (ComfyUI API format) ───────────────────────
# Node keys are intentionally strings — ComfyUI requires that.
# Only the marked fields are filled at request time; sampler/scheduler/cfg
# are fixed here. Swap models by changing MORPHEUS_CKPT or passing ckpt_name.
_SDXL_TEMPLATE: dict = {
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": None}},
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": None, "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode",
          "inputs": {"text": None, "clip": ["4", 1]}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": None, "height": None, "batch_size": 1}},
    "3": {"class_type": "KSampler",
          "inputs": {"seed": None, "steps": None, "cfg": 7.0,
                     "sampler_name": "dpmpp_2m", "scheduler": "karras",
                     "denoise": 1.0,
                     "model":        ["4", 0],
                     "positive":     ["6", 0],
                     "negative":     ["7", 0],
                     "latent_image": ["5", 0]}},
    "8": {"class_type": "VAEDecode",
          "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "ph3b3", "images": ["8", 0]}},
}

# ── GPU lock + in-memory job state ────────────────────────────────────
gpu_lock: asyncio.Lock = asyncio.Lock()
jobs: dict[str, dict] = {}   # job_id → {state, image_url?, error?, seed?}


# ── SQLite helpers (blocking — always call via asyncio.to_thread) ─────
def _db_init() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS generations (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id      TEXT UNIQUE NOT NULL,
          prompt      TEXT NOT NULL,
          negative    TEXT,
          model       TEXT NOT NULL,
          seed        INTEGER NOT NULL,
          steps       INTEGER,
          width       INTEGER,
          height      INTEGER,
          filename    TEXT NOT NULL,
          created_at  TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def _db_insert(job_id: str, params: dict, path: Path) -> None:
    con = sqlite3.connect(str(DB_PATH))
    con.execute("""
        INSERT OR IGNORE INTO generations
          (job_id, prompt, negative, model, seed, steps,
           width, height, filename, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        job_id,
        params.get("positive", ""),
        params.get("negative", ""),
        params.get("ckpt_name", SDXL_CKPT),
        params.get("seed", 0),
        params.get("steps", SDXL_STEPS),
        params.get("width", 1024),
        params.get("height", 1024),
        str(path),
        datetime.now(timezone.utc).isoformat(),
    ))
    con.commit()
    con.close()


def _db_gallery(n: int) -> list[dict]:
    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute(
        "SELECT job_id, prompt, model, seed, width, height, created_at "
        "FROM generations ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    con.close()
    return [
        {"job_id": r[0], "prompt": r[1], "model": r[2],
         "seed": r[3], "width": r[4], "height": r[5], "created_at": r[6]}
        for r in rows
    ]


# ── Ollama eviction — OOM TRAP #1 ─────────────────────────────────────
async def evict_hermes(http: httpx.AsyncClient) -> None:
    # Empty-prompt generate with keep_alive:0 — Ollama blocks until unloaded.
    # On this install, returns {"done_reason": "unload"} synchronously.
    # If the model is already absent this call is a no-op.
    await http.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": HERMES_MODEL, "prompt": "", "keep_alive": 0},
        timeout=30.0,
    )
    # Defense-in-depth: do NOT proceed until /api/ps confirms VRAM is clear.
    for _ in range(20):
        ps = (await http.get(f"{OLLAMA_HOST}/api/ps", timeout=10.0)).json()
        loaded = [m.get("name", "") for m in ps.get("models", [])]
        if not any(n.startswith(_HERMES_STEM) for n in loaded):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"Hermes ({HERMES_MODEL}) did not evict within 10s — aborting to avoid OOM"
    )


# ── ComfyUI helpers ───────────────────────────────────────────────────
def build_workflow(params: dict) -> dict:
    """Fill the SDXL template from params. Resolves seed=-1 to a random value
    and writes it back into params so the caller can index it."""
    wf = copy.deepcopy(_SDXL_TEMPLATE)
    seed = params.get("seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
        params["seed"] = seed  # write resolved seed back for indexing
    wf["4"]["inputs"]["ckpt_name"] = params.get("ckpt_name", SDXL_CKPT)
    wf["6"]["inputs"]["text"]      = params.get("positive", "")
    wf["7"]["inputs"]["text"]      = params.get("negative", SDXL_NEG)
    wf["5"]["inputs"]["width"]     = params.get("width",  1024)
    wf["5"]["inputs"]["height"]    = params.get("height", 1024)
    wf["3"]["inputs"]["seed"]      = seed
    wf["3"]["inputs"]["steps"]     = params.get("steps",  SDXL_STEPS)
    return wf


async def comfy_queue(http: httpx.AsyncClient, workflow: dict) -> str:
    r = (await http.post(
        f"{COMFY_HOST}/prompt",
        json={"prompt": workflow},
        timeout=30.0,
    )).json()
    return r["prompt_id"]


async def comfy_wait(http: httpx.AsyncClient, prompt_id: str,
                     timeout_s: int = 180) -> dict:
    for _ in range(timeout_s * 2):
        h = (await http.get(
            f"{COMFY_HOST}/history/{prompt_id}", timeout=10.0
        )).json()
        if prompt_id in h:
            return h[prompt_id]["outputs"]
        await asyncio.sleep(0.5)
    raise RuntimeError(f"ComfyUI generation timed out after {timeout_s}s")


async def fetch_and_save(http: httpx.AsyncClient, outputs: dict,
                         job_id: str) -> Path:
    img = next(
        i for node in outputs.values()
        if "images" in node
        for i in node["images"]
    )
    raw = (await http.get(
        f"{COMFY_HOST}/view",
        params={"filename": img["filename"],
                "subfolder": img["subfolder"],
                "type":      img["type"]},
        timeout=60.0,
    )).content
    path = IMAGE_DIR / f"{job_id}.png"
    path.write_bytes(raw)
    return path


async def comfy_free(http: httpx.AsyncClient) -> None:
    try:
        await http.post(
            f"{COMFY_HOST}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=30.0,
        )
    except Exception as exc:
        log.warning("comfy_free failed (non-fatal): %s", exc)


# ── Job lifecycle helpers ─────────────────────────────────────────────
def create_job() -> str:
    """Allocate a job_id and insert the initial queued state."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"state": "queued"}
    return job_id


# ── Main generation coroutine ─────────────────────────────────────────
async def run_generation(job_id: str, params: dict) -> None:
    """Full GPU-swap lifecycle. Always call as a FastAPI BackgroundTask."""
    async with gpu_lock:
        async with httpx.AsyncClient() as http:
            try:
                jobs[job_id]["state"] = "evicting"
                await evict_hermes(http)

                jobs[job_id]["state"] = "loading"
                wf = build_workflow(params)   # resolves seed in-place
                prompt_id = await comfy_queue(http, wf)

                jobs[job_id]["state"] = "sampling"
                outputs = await comfy_wait(http, prompt_id)

                jobs[job_id]["state"] = "saving"
                path = await fetch_and_save(http, outputs, job_id)
                await asyncio.to_thread(_db_insert, job_id, params, path)
                jobs[job_id].update(
                    state="done",
                    image_url=f"/image/file/{job_id}",
                    seed=params.get("seed"),
                )
                log.info("Morpheus: job %s done — %s", job_id, path)

            except Exception as exc:
                log.error("Morpheus: job %s failed: %s", job_id, exc)
                jobs[job_id].update(state="error", error=str(exc))

            finally:
                await comfy_free(http)   # TRAP #2 — always, even on error


# ── Module-level init: create dirs + DB schema on import ─────────────
_db_init()
log.info("Morpheus initialised — IMAGE_DIR=%s  DB=%s", IMAGE_DIR, DB_PATH)
