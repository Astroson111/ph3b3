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
import io
import logging
import os
import random
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image
from content_profiles import ACTIVE_PROFILE_NAME, load_profile
from paths import MORPHEUS_DATA

log = logging.getLogger("ph3b3.morpheus")

# ── Config (all overridable via env) ─────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST",  "http://127.0.0.1:11434")
# Match against server.py's HEAVY_MODEL so eviction targets the right model.
HERMES_MODEL = os.getenv("PH3B3_HEAVY_MODEL",
               os.getenv("PH3B3_MODEL", "hermes3"))
_HERMES_STEM = HERMES_MODEL.split(":")[0]  # "hermes3" — safe startswith match

COMFY_HOST   = os.getenv("COMFY_HOST",  "http://127.0.0.1:8188")
IMAGE_DIR    = Path(os.getenv("MORPHEUS_IMAGE_DIR",
                              str(MORPHEUS_DATA / "images")))
DB_PATH      = Path(os.getenv("MORPHEUS_DB_PATH",
                              str(MORPHEUS_DATA / "generations.db")))
SDXL_CKPT    = os.getenv("MORPHEUS_CKPT",  "sd_xl_base_1.0.safetensors")
SDXL_STEPS   = int(os.getenv("MORPHEUS_STEPS", "20"))
SDXL_NEG     = os.getenv(
    "MORPHEUS_NEG",
    "text, watermark, multiple objects, cluttered background, blurry",
)

# ── Content safety ───────────────────────────────────────────────────
# FLOOR (Part 1) — hardcoded in morpheus.py, runs on EVERY request, EVERY profile.
# No env var, no flag, no profile setting can disable or weaken these checks.
# Both strict and permissive profiles inherit them identically because they run
# BEFORE profile selection, before the gpu_lock, before any workflow is queued.
#
# Six welded categories:
#   1. Minors in any sexual/suggestive context
#   2. Real identifiable named people in intimate context
#   3. Sexualized likeness of any real identifiable person
#   4. Real-person likeness in fabricated criminal/violent/defamatory context
#   5. Bestiality / non-consensual themes
#   6. (Framing for permissive lane) fictional/generated subjects only
#
# Honest limit: this floor stops casual misuse and accidental drift. It is NOT
# an adversary-proof wall — deliberate euphemism or coded language can evade
# keyword/pattern checks. Build the floor; do not over-claim it as exhaustive.

# ── Category 1 — minor indicators ────────────────────────────────────
_FLOOR_MINOR: frozenset[str] = frozenset([
    "child", "children", "kid", "kids", "minor", "minors",
    "toddler", "infant", "loli", "lolita", "shota",
    "underage", "preteen", "pre-teen", "juvenile", "prepubescent",
    "young girl", "young boy", "little girl", "little boy",
    "schoolgirl", "school girl", "schoolboy",
])

# ── Categories 2/3 — sexual/intimate context ─────────────────────────
_FLOOR_SEXUAL: frozenset[str] = frozenset([
    "nude", "naked", "nudity", "nsfw",
    "sexual", "sex", "porn", "hentai",
    "erotic", "erotica", "xxx", "lewd",
    "adult content", "intimate",
])

# ── Category 4 — criminal/violent/defamatory framing of real persons ──
# Two-signal check: these terms alone are NOT blocked; they block only
# when combined with a real-person reference (_PERSON_RE below).
_FLOOR_CRIMINAL: frozenset[str] = frozenset([
    "drug dealer", "drug lord", "drug kingpin",
    "terrorist", "terrorism",
    "pedophile", "paedophile", "child molester",
    "sex offender",
    "convicted of", "arrested for", "prison for",
    "committing murder", "committing rape",
    "crimes against",
])

# ── Category 5 — bestiality / non-consensual (standalone block) ───────
_FLOOR_NONCONSENSUAL: frozenset[str] = frozenset([
    "bestiality", "zoophilia",
    "rape", "non-consensual", "nonconsensual",
    "without consent", "forced sex", "forced intercourse",
])

# Union of all floor term sets — used by _person_signal to blank them out
# before running the bigram match so multi-word floor tokens can't self-match
# as name-shaped references (e.g. "adult content", "drug dealer").
_ALL_FLOOR_TERMS: frozenset[str] = (
    _FLOOR_MINOR | _FLOOR_SEXUAL | _FLOOR_CRIMINAL | _FLOOR_NONCONSENSUAL
)

# ── Whole-word floor matching ────────────────────────────────────────────────
# Floor terms match on a LEADING word boundary (\bterm), not as a raw substring.
# This still catches inflections/plurals ("rape"→raped/rapes, "nude"→nudes) so no
# real content slips the floor, while killing substring false positives where a
# term hides *inside* an innocent word ("rape" in "d-rape-d"/"grape", "sex" in
# "Sus-sex"/"Es-sex"). Trailing boundary is intentionally omitted (safety bias:
# a suffixed real term must still fire; over-matching a word that STARTS with a
# term — e.g. "sextant" — is an accepted, rare cost of never weakening the floor).
def _floor_re(terms: frozenset[str]):
    alts = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(r"\b(?:" + alts + r")")

_RE_MINOR         = _floor_re(_FLOOR_MINOR)
_RE_SEXUAL        = _floor_re(_FLOOR_SEXUAL)
_RE_CRIMINAL      = _floor_re(_FLOOR_CRIMINAL)
_RE_NONCONSENSUAL = _floor_re(_FLOOR_NONCONSENSUAL)

# Name-shaped bigram: proxy for named individuals (First Last).
# IGNORECASE: elon musk / Elon Musk / ELON MUSK all match the structure.
# Signal fires ONLY when paired with a compromising-context term (AND-gate in
# floor_check). Applied via _person_signal() which strips floor terms first.
_PERSON_RE = re.compile(r"\b[A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20}\b", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse separator tricks (n_u_d_e, n.u.d.e → nude)."""
    s = text.lower().strip()
    # Collapse non-space separators between single letters: underscores, hyphens, dots
    s = re.sub(r"(?<=[a-z])[_.\-](?=[a-z])", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _person_signal(text: str) -> bool:
    """Return True if text contains a name-shaped bigram that is not itself a
    floor term. Floor terms are blanked out first so multi-word tokens like
    'adult content' or 'drug dealer' don't self-match as person references."""
    s = text.lower()
    for t in _ALL_FLOOR_TERMS:
        s = s.replace(t, " ")
    return bool(_PERSON_RE.search(s))


def floor_check(prompt: str) -> str | None:
    """Return a category string if the hard floor fires, else None.
    No off switch. Runs before gpu_lock, before profile checks, before queuing.
    The returned string is for internal logging only — never expose to callers."""
    norm = _normalize(prompt)

    has_sex    = bool(_RE_SEXUAL.search(norm))
    has_minor  = bool(_RE_MINOR.search(norm))

    # Category 1: minor + sexual/suggestive
    if has_minor and has_sex:
        return "minor-sexual"

    # Category 5: bestiality / non-consensual (standalone — no second signal needed)
    if _RE_NONCONSENSUAL.search(norm):
        return "nonconsensual"

    # Categories 2/3/4: two-signal — real-person reference + compromising context.
    # Compromising = sexual (cats 2/3) OR criminal/defamatory (cat 4).
    has_criminal    = bool(_RE_CRIMINAL.search(norm))
    has_compromising = has_sex or has_criminal
    if has_compromising and _person_signal(prompt):
        return "real-person-compromising"

    return None


# ── PROFILE layer (Part 2) ────────────────────────────────────────────
# Loaded once at import. floor_check always runs first; profile_check only
# if the floor passes. Profile choice: PH3B3_CONTENT_PROFILE (default: strict).

ACTIVE_PROFILE: str = ACTIVE_PROFILE_NAME
_PROFILE_DENYLIST: frozenset[str] = load_profile(ACTIVE_PROFILE_NAME)

# Strict denylist always available for the localhost interlock in server.py
STRICT_DENYLIST: frozenset[str] = load_profile("strict")


def profile_check(prompt: str, denylist: frozenset | None = None) -> bool:
    """Return True if prompt passes the denylist, False if denied.
    Must be called only after floor_check passes.
    Pass denylist=morpheus.STRICT_DENYLIST to force strict (used by the
    localhost interlock when permissive is active but request is non-local)."""
    active = denylist if denylist is not None else _PROFILE_DENYLIST
    norm = _normalize(prompt)
    return not any(term in norm for term in active)


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


def _db_meta(job_id: str) -> dict | None:
    con = sqlite3.connect(str(DB_PATH))
    row = con.execute(
        "SELECT prompt, seed FROM generations WHERE job_id = ?", (job_id,)
    ).fetchone()
    con.close()
    return {"prompt": row[0], "seed": row[1]} if row else None


def _db_delete(job_id: str) -> dict:
    """Atomically delete one generation: DB row + PNG file together.
    Unlink happens inside the transaction window; any error rolls the DELETE back."""
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute(
            "SELECT filename FROM generations WHERE job_id=?", (job_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not found"}
        path = Path(row[0])
        freed = path.stat().st_size if path.exists() else 0
        con.execute("BEGIN")
        con.execute("DELETE FROM generations WHERE job_id=?", (job_id,))
        path.unlink(missing_ok=True)
        con.commit()
        return {"ok": True, "job_id": job_id, "freed_bytes": freed}
    except Exception as e:
        con.rollback()
        return {"ok": False, "reason": str(e)}
    finally:
        con.close()


def _db_all_job_ids() -> list[str]:
    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute("SELECT job_id FROM generations ORDER BY id").fetchall()
    con.close()
    return [r[0] for r in rows]


def _slug(text: str, maxlen: int = 40) -> str:
    s = text.lower().replace(" ", "-")
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-+", "-", s)
    return s[:maxlen].strip("-") or "image"


def convert_image(path: Path, fmt: str) -> tuple[bytes, str]:
    """Convert stored PNG to jpeg or webp in-memory. No disk writes."""
    img = Image.open(path)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.convert("RGB").save(buf, "JPEG", quality=92)
        return buf.getvalue(), "image/jpeg"
    # webp
    img.save(buf, "WEBP", quality=92)
    return buf.getvalue(), "image/webp"


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
    # Empty or missing negative → default negative (SDXL_NEG). `or` (not dict
    # default) so an explicit "" from the endpoint also falls back. Write the
    # resolved value back into params so the DB records what actually conditioned.
    neg = params.get("negative") or SDXL_NEG
    params["negative"] = neg
    wf["4"]["inputs"]["ckpt_name"] = params.get("ckpt_name", SDXL_CKPT)
    wf["6"]["inputs"]["text"]      = params.get("positive", "")
    wf["7"]["inputs"]["text"]      = neg
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


# ── On-demand ComfyUI startup ─────────────────────────────────────────
_COMFY_POLL_INTERVAL = 3.0   # seconds between readiness probes
_COMFY_START_TIMEOUT = 120   # max seconds to wait for ComfyUI to serve


async def ensure_comfy_up(http: httpx.AsyncClient) -> None:
    """Start ComfyUI on demand and wait until it is actually serving.

    Fast path: /system_stats answers 200 → already up, return immediately.
    Slow path: `systemctl start comfyui` (polkit rule grants this without sudo),
    then poll /system_stats until ComfyUI is HTTP-ready — not just process-alive.
    Cold start (PyTorch + CUDA init + model index) can take 30-90 s.

    Must be called inside gpu_lock so concurrent jobs cannot race on startup.
    """
    # Fast path — skip startup if ComfyUI is already serving.
    try:
        r = await http.get(f"{COMFY_HOST}/system_stats", timeout=4.0)
        if r.status_code == 200:
            return
    except Exception:
        pass  # connection refused / timeout — fall through to start

    log.info("ComfyUI not responding — starting via systemctl")
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "start", "comfyui",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"systemctl start comfyui failed (rc={proc.returncode}): "
            f"{stderr.decode().strip()}"
        )

    # Poll until /system_stats answers — process-exists is not enough.
    attempts = int(_COMFY_START_TIMEOUT / _COMFY_POLL_INTERVAL)
    for _ in range(attempts):
        await asyncio.sleep(_COMFY_POLL_INTERVAL)
        try:
            r = await http.get(f"{COMFY_HOST}/system_stats", timeout=4.0)
            if r.status_code == 200:
                log.info("ComfyUI ready")
                return
        except Exception:
            pass  # still initialising — keep polling
    raise RuntimeError(
        f"ComfyUI did not become ready within {_COMFY_START_TIMEOUT}s "
        "after systemctl start"
    )


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

                jobs[job_id]["state"] = "starting"
                await ensure_comfy_up(http)

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


# ── img2img (Edit Mode) — same checkpoint + sampler family as txt2img ─────────
# Differs from _SDXL_TEMPLATE only in the latent source: LoadImage → VAEEncode
# feeds an encoded real image into KSampler, and denoise = strength (how far the
# edit travels from the source). Everything else (cfg/sampler/scheduler) matches.
_SDXL_IMG2IMG_TEMPLATE: dict = {
    "4":  {"class_type": "CheckpointLoaderSimple",
           "inputs": {"ckpt_name": None}},
    "6":  {"class_type": "CLIPTextEncode",
           "inputs": {"text": None, "clip": ["4", 1]}},
    "7":  {"class_type": "CLIPTextEncode",
           "inputs": {"text": None, "clip": ["4", 1]}},
    "10": {"class_type": "LoadImage",
           "inputs": {"image": None}},
    "11": {"class_type": "VAEEncode",
           "inputs": {"pixels": ["10", 0], "vae": ["4", 2]}},
    "3":  {"class_type": "KSampler",
           "inputs": {"seed": None, "steps": None, "cfg": 7.0,
                      "sampler_name": "dpmpp_2m", "scheduler": "karras",
                      "denoise": None,
                      "model":        ["4", 0],
                      "positive":     ["6", 0],
                      "negative":     ["7", 0],
                      "latent_image": ["11", 0]}},
    "8":  {"class_type": "VAEDecode",
           "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9":  {"class_type": "SaveImage",
           "inputs": {"filename_prefix": "ph3b3_edit", "images": ["8", 0]}},
}

EDIT_STRENGTH_MIN = 0.15
EDIT_STRENGTH_MAX = 0.9


def _prep_edit_image(src: Path, job_id: str) -> tuple[Path, int, int]:
    """Scale the source to SDXL-native long-edge 1024, dims rounded to /8,
    preserving aspect. Returns (run_copy_path, width, height)."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    scale = 1024 / max(w, h)
    nw = max(8, round(w * scale / 8) * 8)
    nh = max(8, round(h * scale / 8) * 8)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.LANCZOS)
    out = src.parent / f"{job_id}_run.png"
    img.save(out, format="PNG")
    return out, nw, nh


async def comfy_upload_image(http: httpx.AsyncClient, path: Path) -> str:
    """Upload a prepared image into ComfyUI's input dir; return its LoadImage ref."""
    data = Path(path).read_bytes()
    r = (await http.post(
        f"{COMFY_HOST}/upload/image",
        files={"image": (Path(path).name, data, "image/png")},
        data={"overwrite": "true"},
        timeout=60.0,
    )).json()
    name = r["name"]
    sub = r.get("subfolder", "") or ""
    return f"{sub}/{name}" if sub else name


def build_edit_workflow(params: dict) -> dict:
    """Fill the img2img template. Resolves seed=-1, clamps strength→denoise, and
    writes both back into params for indexing. `comfy_image` must already be set."""
    wf = copy.deepcopy(_SDXL_IMG2IMG_TEMPLATE)
    seed = params.get("seed", -1)
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)
        params["seed"] = seed
    neg = params.get("negative") or SDXL_NEG
    params["negative"] = neg
    strength = float(params.get("strength", 0.45))
    strength = max(EDIT_STRENGTH_MIN, min(EDIT_STRENGTH_MAX, strength))  # defense-in-depth
    params["strength"] = strength
    wf["4"]["inputs"]["ckpt_name"] = params.get("ckpt_name", SDXL_CKPT)
    wf["6"]["inputs"]["text"]      = params.get("positive", "")
    wf["7"]["inputs"]["text"]      = neg
    wf["10"]["inputs"]["image"]    = params["comfy_image"]
    wf["3"]["inputs"]["seed"]      = seed
    wf["3"]["inputs"]["steps"]     = params.get("steps", SDXL_STEPS)
    wf["3"]["inputs"]["denoise"]   = strength
    return wf


async def run_edit(job_id: str, params: dict) -> None:
    """img2img GPU-swap lifecycle — mirrors run_generation exactly, reusing the
    same lock/evict/ensure/queue/wait/save/free helpers. Adds: resize→upload the
    source before queuing, and delete scratch on completion."""
    async with gpu_lock:
        async with httpx.AsyncClient() as http:
            run_img: Path | None = None
            try:
                jobs[job_id]["state"] = "evicting"
                await evict_hermes(http)

                jobs[job_id]["state"] = "starting"
                await ensure_comfy_up(http)

                jobs[job_id]["state"] = "loading"
                run_img, nw, nh = await asyncio.to_thread(
                    _prep_edit_image, Path(params["image_path"]), job_id)
                params["width"], params["height"] = nw, nh
                params["comfy_image"] = await comfy_upload_image(http, run_img)
                wf = build_edit_workflow(params)   # resolves seed/strength in-place
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
                log.info("Morpheus edit: job %s done — %s (denoise=%.2f)",
                         job_id, path, params.get("strength", 0.0))

            except Exception as exc:
                log.error("Morpheus edit: job %s failed: %s", job_id, exc)
                jobs[job_id].update(state="error", error=str(exc))

            finally:
                await comfy_free(http)   # TRAP #2 — always
                # Delete only the transient per-job resized copy. Keep the source
                # upload so the SAME image can be re-edited at other strengths
                # (the slider workflow); the source expires via the TTL janitor.
                try:
                    if run_img:
                        run_img.unlink(missing_ok=True)
                except OSError:
                    pass


# ── Module-level init: create dirs + DB schema on import ─────────────
_db_init()
log.info("Morpheus initialised — IMAGE_DIR=%s  DB=%s", IMAGE_DIR, DB_PATH)
