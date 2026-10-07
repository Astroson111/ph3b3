"""
Herakles — the card gets cleared when asked, and only when asked.

WHY THIS IS NOT AUTOMATIC. A module that frees VRAM on its own judgement is a
module that kills a render someone is watching, mid-stroke, because a number
crossed a line. Every entry point here is reached by an explicit ask, and the
only thing that acts without being asked is the OOM valve — which fires AFTER a
call has already failed, retries exactly once, and never fires twice for the
same call.

WHOSE PROCESSES. Ours and no one else's. A tenant is recognised by its command
line matching one of _OWN below; anything else on the card is reported as
foreign and is never signalled, never freed, never counted as reclaimable. If
Herakles cannot tell whose a process is, it does not touch it.

WHY nvidia-smi AND NOT pynvml. pynvml is not installed on this machine and the
brief's premise that it was did not hold. nvidia-smi ships with the driver, is
already how the rest of this app reads the card, and adds no dependency to keep
current. The cost is parsing CSV instead of calling an API, which is a fair
trade for one less thing to install.

WHAT "FREED" MEANS. Ollama and ComfyUI are asked to release cached weights.
Both comply promptly in the normal case, and neither is compelled — there is no
signal that forces a CUDA context to let go short of killing the process, and
Herakles does not kill processes. So free_gpu reports what the card looked like
before and after, measured, and lets the numbers say whether it worked.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import subprocess

log = logging.getLogger("ph3b3")

# ── Tenants we are allowed to act on ─────────────────────────────────────────
# Matched against the process command line. Ordered most-specific first so the
# server does not match the bare-python pattern meant for something else.
_OWN = (
    ("ph3b3",   re.compile(r"ph3b3_v2/\.venv/bin/python.*agent/server\.py")),
    ("comfyui", re.compile(r"comfyui/\.venv/bin/python.*main\.py")),
    ("ollama",  re.compile(r"\bollama\b")),
)

# The card is considered under pressure past these marks. They are advisory:
# nothing here acts on them, they are what gpu_status() reports so a person can.
PRESSURE_WARN = 0.50      # half the card gone — worth knowing before a big render
PRESSURE_TIGHT = 0.85     # a render is likely to fail from here

_SMI = shutil.which("nvidia-smi")


class HeraklesError(RuntimeError):
    """Something about the card could not be read or acted on."""


def _smi(*query: str) -> list[list[str]]:
    """Run nvidia-smi and return parsed CSV rows, or raise."""
    if not _SMI:
        raise HeraklesError("nvidia-smi is not on PATH — cannot read the GPU")
    try:
        out = subprocess.run([_SMI, *query, "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
    except subprocess.TimeoutExpired:
        raise HeraklesError("nvidia-smi did not answer within 10s")
    except subprocess.CalledProcessError as e:
        raise HeraklesError(f"nvidia-smi failed: {(e.stderr or '').strip()[:120]}")
    return [[c.strip() for c in ln.split(",")] for ln in out.splitlines() if ln.strip()]


def _cmdline(pid: str) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _whose(cmd: str) -> str | None:
    """The tenant name for a command line, or None if it is not ours."""
    for name, pat in _OWN:
        if pat.search(cmd):
            return name
    return None


def tenants() -> list[dict]:
    """Every process holding VRAM right now, ours flagged as such.

    A process we cannot attribute is reported with owner=None and mine=False.
    That is deliberate: unknown means hands off, not "probably fine".
    """
    rows = _smi("--query-compute-apps=pid,used_memory")
    out = []
    for r in rows:
        if len(r) < 2:
            continue
        pid, mem = r[0], r[1]
        cmd = _cmdline(pid)
        owner = _whose(cmd)
        out.append({
            "pid": int(pid) if pid.isdigit() else pid,
            "used_mib": int(mem) if mem.isdigit() else 0,
            "owner": owner,
            "mine": owner is not None,
            "is_self": owner == "ph3b3" and str(pid) == str(os.getpid()),
            "cmd": cmd[:120],
        })
    return sorted(out, key=lambda t: -t["used_mib"])


def free_mib() -> int:
    """Free VRAM, and nothing else. Cheap enough to poll in a loop.

    gpu_status() walks /proc for every tenant, which is the right shape for a
    report and the wrong shape for a settle-wait that runs every 250 ms.
    """
    rows = _smi("--query-gpu=memory.free")
    if not rows or not rows[0]:
        raise HeraklesError("nvidia-smi returned no GPU row")
    return int(rows[0][0])


def gpu_status() -> dict:
    """Read-only. Never frees anything, never signals anything.

    Safe to call on a timer or from a panel poll — it shells out to nvidia-smi
    and reads /proc, and touches no CUDA context of its own.
    """
    # temperature/utilisation are carried because the tool this replaces
    # reported them and devices read it aloud — dropping them would be a
    # silent regression in what a person hears.
    rows = _smi("--query-gpu=name,memory.total,memory.used,memory.free,"
                "temperature.gpu,utilization.gpu")
    if not rows or len(rows[0]) < 6:
        raise HeraklesError("nvidia-smi returned no GPU row")
    name, total, used, free = rows[0][0], int(rows[0][1]), int(rows[0][2]), int(rows[0][3])
    temp_c = int(rows[0][4]) if rows[0][4].isdigit() else None
    util_pct = int(rows[0][5]) if rows[0][5].isdigit() else None
    frac = (used / total) if total else 0.0
    # One pass. This is called by voice from Dio and Iris, and each tenants()
    # call is an nvidia-smi subprocess plus a /proc walk per pid.
    _all = tenants()
    ours = [t for t in _all if t["mine"]]
    foreign = [t for t in _all if not t["mine"]]
    return {
        "gpu": name,
        "total_mib": total, "used_mib": used, "free_mib": free,
        "temp_c": temp_c, "util_pct": util_pct,
        "used_fraction": round(frac, 3),
        "pressure": ("tight" if frac >= PRESSURE_TIGHT
                     else "warn" if frac >= PRESSURE_WARN else "ok"),
        # What Herakles could actually reclaim if asked. Foreign memory is
        # excluded because it is not ours to reclaim, at any level.
        #
        # The host process IS included. Whisper lives inside it and stt.release()
        # is the handle on that memory, so dropping is_self into a void reported
        # her hearing as neither reclaimable nor foreign — a field that is a lie
        # waiting for its first believer. request_card never consulted it, which
        # is the only reason this was cosmetic rather than the cause of a bad
        # refusal.
        "reclaimable_mib": sum(t["used_mib"] for t in ours),
        "reclaimable_excluding_self_mib": sum(
            t["used_mib"] for t in ours if not t["is_self"]),
        "tenants": ours + foreign,
        "foreign_mib": sum(t["used_mib"] for t in foreign),
    }


def status_line(st: dict | None = None) -> str:
    """One sentence a person or a voice can use."""
    st = st or gpu_status()
    pct = int(round(st["used_fraction"] * 100))
    line = (f"{st['gpu']}: {st['used_mib']} of {st['total_mib']} MiB used ({pct}%), "
            f"{st['free_mib']} MiB free")
    if st.get("util_pct") is not None:
        line += f", {st['util_pct']}% busy"
    if st.get("temp_c") is not None:
        line += f", {st['temp_c']}C"
    line += "."
    if st["pressure"] == "tight":
        line += " That is tight — a large render will probably fail."
    elif st["pressure"] == "warn":
        line += " That is over half the card."
    busy = busy_with()
    if busy:
        line += f" {busy[0].upper()}{busy[1:]} — I won't clear the card under it."
    if st["foreign_mib"]:
        line += (f" {st['foreign_mib']} MiB belongs to something that is not mine; "
                 "I will not touch it.")
    return line


# ── What must not be interrupted ─────────────────────────────────────────────
# Morpheus, Amphion and the upscale path share ONE asyncio.Lock and hold it for
# the whole render — up to 40 minutes for video. Herakles does not take that
# lock, because a "free the card now" that blocks for forty minutes is not a
# thing anyone asked for. It READS it instead, and refuses.
#
# This matters more than it looks. comfy_free() passes unload_models=True: run
# it mid-render and the model is pulled out from under a job that is already
# executing. evict_hermes() is safe by comparison but pointless mid-render,
# because the render evicted Ollama itself on the way in.
#
# The job tables are read directly rather than through orpheus.gpu_busy_with(),
# which does the same thing — that module is being rewritten, and this guard
# should not be waiting on it.
_TERMINAL_STATES = {"done", "error", "cancelled", "failed", "complete", "completed"}


def busy_with(ignore_job: str | None = None) -> str | None:
    """The render currently promised the GPU, named — or None if the card is ours.

    A busy GPU is not the question; nvidia-smi answers that. The question is
    whether this machine has PROMISED the card to something, and that promise
    lives in the job tables and the shared lock, not in the memory figures.

    `ignore_job` is for the job that IS the promise. A render holding gpu_lock
    and clearing room for its own work is not contending with anything — it is
    the thing everyone else is being kept away from. Without this the guard
    refused Herakles' first real caller, because run_generation asks for the
    card while holding the lock with its own row already non-terminal.
    Excluding itself is the only exception; any OTHER live job still refuses.
    """
    try:
        import morpheus
    except Exception:
        return None
    tables = [("Morpheus render", getattr(morpheus, "jobs", {}))]
    try:
        import amphion
        tables.append(("Amphion song", getattr(amphion, "jobs", {})))
    except Exception:
        pass
    for label, table in tables:
        for jid, j in list((table or {}).items()):
            if ignore_job is not None and str(jid) == str(ignore_job):
                continue
            st = (j or {}).get("state")
            if st and st not in _TERMINAL_STATES:
                return f"{label} {jid} ({st})"
    lock = getattr(morpheus, "gpu_lock", None)
    # A caller that named itself is the lock holder, so the lock says nothing
    # new. Checking it anyway would refuse every in-job request.
    if ignore_job is None and lock is not None and lock.locked():
        # Held by something that registered no job row. "Something has the GPU"
        # is still the honest answer, and still a reason not to touch it.
        return "a GPU job already running"
    return None


# ── Freeing ──────────────────────────────────────────────────────────────────
# Two levels, and the difference between them is whether running work is
# allowed to survive.
#
#   1 "cached"  — release what is merely being HELD: idle Ollama weights and
#                 ComfyUI's model cache. Nothing in flight is disturbed. This is
#                 the level the OOM valve uses, because a valve that cancels the
#                 user's other render to make room for this one is not a valve.
#
#   2 "running" — level 1, plus interrupt whatever ComfyUI is currently
#                 executing. This CANCELS WORK. It is never automatic and never
#                 reached by the valve; a person has to ask for it by name.

LEVELS = ("cached", "running")


async def free_gpu(level: str = "cached", http=None) -> dict:
    """Ask our own tenants to give the card back. Explicit-ask only.

    Returns before/after measurements rather than a claim of success — neither
    Ollama nor ComfyUI is compelled to comply, so the numbers are the evidence.
    """
    if level not in LEVELS:
        raise HeraklesError(f"level must be one of {LEVELS}, got {level!r}")

    import httpx
    import morpheus

    # The interference guard. `cached` is the level that looks harmless and is
    # not: comfy_free() unloads models, and a render in flight is using them.
    # `running` is allowed through because cancelling is precisely what it means
    # — the caller had to name it, and the tool description says what it does.
    busy = busy_with()
    if busy and level == "cached":
        raise HeraklesError(
            f"Not while {busy} is using the card — freeing the model cache would "
            f"break it. Ask for level 'running' if you want that render cancelled."
        )

    before = gpu_status()
    acted, failed = [], []

    own = httpx.AsyncClient() if http is None else None
    client = http or own
    try:
        if level == "running":
            # Cancel first: freeing a cache the running job is about to refill
            # accomplishes nothing.
            try:
                await client.post(f"{morpheus.COMFY_HOST}/interrupt", timeout=10.0)
                acted.append("interrupted the running ComfyUI job")
            except Exception as e:
                failed.append(f"comfy interrupt: {e}")

        try:
            await morpheus.evict_hermes(client)
            acted.append("evicted the Ollama chat model")
        except Exception as e:
            failed.append(f"ollama evict: {e}")

        try:
            await morpheus.comfy_free(client)     # already swallows its own errors
            acted.append("released the ComfyUI model cache")
        except Exception as e:
            failed.append(f"comfy free: {e}")

        # Both backends free asynchronously; measure after they have settled
        # rather than immediately, or the "after" is just the "before".
        await asyncio.sleep(1.5)
    finally:
        if own is not None:
            await own.aclose()

    after = gpu_status()
    freed = after["free_mib"] - before["free_mib"]
    log.info("[herakles] free_gpu(%s): %+d MiB (%d -> %d free); did=%s failed=%s",
             level, freed, before["free_mib"], after["free_mib"], acted, failed)
    return {
        "level": level,
        "freed_mib": freed,
        "before": {k: before[k] for k in ("used_mib", "free_mib", "used_fraction")},
        "after": {k: after[k] for k in ("used_mib", "free_mib", "used_fraction")},
        "did": acted,
        "failed": failed,
        "line": (f"Freed {freed} MiB — {after['free_mib']} MiB free now."
                 if freed > 0 else
                 f"Nothing came back. Still {after['free_mib']} MiB free."),
    }


# How long to wait for the DRIVER to reflect a release before calling it
# unconfirmed. Named rather than inline so it is tunable and so tests can make
# the unhappy path fast instead of burning the real deadline.
CONFIRM_TIMEOUT_S = 8.0


async def _confirmed_free(baseline: int,
                          timeout: float | None = None) -> tuple[int, bool]:
    """Wait until the driver reflects a release. Returns (free_mib, confirmed).

    A tier that POSTs an unload has not freed anything yet — Ollama and ComfyUI
    both reclaim asynchronously, and a pid can vanish from /proc while nvidia-smi
    still reports its memory. Counting that window either way is wrong: as still
    held it produces a false refusal, as available it produces the OOM this guard
    exists to prevent.

    Measured 2026-09-23: the same race one level up restarted Ph3b3 into a card
    that had not been reclaimed, and her Whisper load died with CUDA OOM.
    """
    deadline = time.monotonic() + (CONFIRM_TIMEOUT_S if timeout is None else timeout)
    free = baseline
    while time.monotonic() < deadline:
        free = free_mib()
        if free > baseline:
            return free, True
        await asyncio.sleep(0.25)
    return free, False


def _foreign_breakdown(st: dict) -> str:
    """Name what is holding the remainder, with sizes. Reporting only."""
    rows = []
    for t in st["tenants"]:
        if t["mine"]:
            continue
        who = t.get("proc") or _proc_name(t["pid"]) or "unattributable"
        # PID and size, so the Captain can decide about it — never us.
        rows.append(f"{who} (pid {t['pid']}) {t['used_mib']} MiB")
    return ", ".join(rows)


def _proc_name(pid) -> str:
    """Short name for a pid, or "" once it is gone.

    A pid whose /proc entry has already vanished is not an alien — it is almost
    always something of ours that was just told to release and has not been
    reaped. It gets named as such rather than counted as a stranger.
    """
    try:
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return "a process that has already exited (releasing)"


# ── The single eviction authority ────────────────────────────────────────────
#
# Cheapest rung first (Captain's ruling, 2026-10-07). ComfyUI's cache is dropped
# by every render's finally anyway, so freeing it first costs nothing; Ollama
# reloads lazily on the next chat turn; her hearing costs ~5-15s during which
# she is deaf, so it goes last and only if the first two were not enough.
# Images AND clips use this one ladder — evict_hermes/assert_vram_for_wan retired.
_EVICT_ORDER = ("comfyui", "ollama", "stt")

# What reloading Whisper needs, driver-confirmed, before release_card tries.
# Measured 2026-10-07: Whisper medium holds 4,516-4,546 MiB in-process. A
# reload attempted into less than this OOMs and — before the stt fix — left
# ~3.8 GB orphaned (C1). The extra is the same margin the renders use.
WHISPER_RESTORE_MB = int(os.getenv("PH3B3_WHISPER_RESTORE_MB", "5050"))


async def request_card(need_mb: int, requester: str, *, http=None, stt=None,
                       eta_s: int = 60, holder: str | None = None) -> dict:
    """Make room for `need_mb`, evicting OUR tenants only, cheapest first.

    Returns a LEASE describing what was given up, so release_card() can put it
    back. Foreign memory is never touched at any level — if the shortfall is
    somebody else's, this says so and leaves the decision to the caller.

    Measured 2026-09-22: a Qwen render peaks at 14,467 MiB of a 16,380 MiB card.
    Whisper medium holds ~4.5 GB from boot inside the ph3b3 process, so it is
    not a tenant with a pid of its own — it can only be released in-process,
    which is why `stt` is injected rather than discovered.
    """
    if need_mb <= 0:
        raise HeraklesError(f"need_mb must be positive, got {need_mb}")

    # `holder` is the job id making room for ITSELF — it already holds the lock.
    busy = busy_with(ignore_job=holder)
    if busy:
        raise HeraklesError(
            f"Not while {busy} is using the card — evicting under it would "
            f"break it. Wait for it, or cancel it deliberately with "
            f"free_gpu(level='running').")

    import httpx
    import morpheus

    before = gpu_status()
    evicted, failed = [], []

    if before["free_mib"] >= need_mb:
        return {"requester": requester, "need_mb": need_mb, "granted": True,
                "evicted": [], "failed": [],
                "free_mib": before["free_mib"],
                "before": before["free_mib"], "after": before["free_mib"],
                "foreign_mib": before["foreign_mib"],
                "line": f"{before['free_mib']} MiB was already free — took nothing."}

    own = httpx.AsyncClient() if http is None else None
    client = http or own
    # Per-tier record. "asked" is not "evicted": a tier that POSTs an unload and
    # frees nothing must not be reported as having worked. Saying so falsely is
    # how "everything of mine evicted" appeared beside two live Ollama runners.
    detail: dict[str, str] = {}
    unconfirmed: list[str] = []
    stt_held = False
    try:
        for who in _EVICT_ORDER:
            before_tier = free_mib()
            if before_tier >= need_mb:
                break
            try:
                if who == "ollama":
                    # EVERY loaded model, not hermes3 by name. llava and
                    # ph3b3-chat are Ollama models too, and they are the
                    # floor's judges — leaving them resident is what made
                    # "everything of mine evicted" a false claim.
                    names = await morpheus.evict_ollama_all(client)
                    detail[who] = ", ".join(names) if names else "nothing loaded"
                    if not names:
                        continue          # nothing to evict is not an eviction
                elif who == "comfyui":
                    await morpheus.comfy_free(client)
                    detail[who] = "model cache"
                elif who == "stt":
                    if stt is None or getattr(stt, "held", False):
                        continue   # no STT injected, or already on hold
                    r = stt.hold(requester, eta_s=eta_s)
                    # The hold is a fact whether or not the driver shows memory
                    # coming back. C1: a hold that freed nothing was never
                    # resumed, because only CONFIRMED tiers reached `evicted`.
                    stt_held = True
                    detail[who] = f"her hearing ({r.get('freed_mb', 0)} MiB)"
            except Exception as e:                     # noqa: BLE001
                failed.append(f"{who}: {e}")
                continue
            # Confirm with the DRIVER before counting it.
            after_tier, confirmed = await _confirmed_free(before_tier)
            if confirmed:
                evicted.append(who)
                detail[who] = f"{detail.get(who, who)} — {after_tier - before_tier} MiB back"
            else:
                unconfirmed.append(who)
                detail[who] = f"{detail.get(who, who)} — asked, nothing came back"
                log.warning("[herakles] %s was asked to release and the driver "
                            "reflected nothing within the wait", who)
    finally:
        if own is not None:
            await own.aclose()

    after = gpu_status()
    granted = after["free_mib"] >= need_mb
    short = max(0, need_mb - after["free_mib"])

    # Accounting, not arithmetic. What was actually released, what merely got
    # asked, and who holds the rest — by name and size.
    did = "; ".join(f"{k}: {v}" for k, v in detail.items() if k in evicted)
    if granted:
        line = f"{after['free_mib']} MiB free for {requester}." + (f" Freed {did}." if did else "")
    else:
        parts = [f"Still {short} MiB short."]
        if did:
            parts.append(f"Freed {did}.")
        if unconfirmed:
            # Named separately on purpose. "I asked and nothing came back" is a
            # different fact from "I freed it", and reporting the second when
            # the first is true is the failure this patch exists to end.
            parts.append("Asked but saw nothing back from: "
                         + ", ".join(unconfirmed) + ".")
        if failed:
            parts.append("Failed: " + "; ".join(failed) + ".")
        rest = _foreign_breakdown(after)
        if rest:
            parts.append(f"Holding the remainder: {rest}.")
            parts.append("Not mine, and I will not touch it.")
        elif not unconfirmed and not failed:
            parts.append("Everything of mine is already released.")
        line = " ".join(parts)

    log.info("[herakles] request_card(%d, %s): granted=%s free %d -> %d, "
             "evicted=%s failed=%s", need_mb, requester, granted,
             before["free_mib"], after["free_mib"], evicted, failed)

    return {"requester": requester, "need_mb": need_mb, "granted": granted,
            "evicted": evicted, "unconfirmed": unconfirmed, "detail": detail,
            "failed": failed, "stt_held": stt_held,
            "free_mib": after["free_mib"], "short_mib": short,
            "before": before["free_mib"], "after": after["free_mib"],
            "foreign_mib": after["foreign_mib"], "line": line}


async def release_card(lease: dict, *, http=None, stt=None) -> dict:
    """Give back what the lease took, and clear the job's resident tail.

    Runs in the caller's `finally` — on success, failure AND cancel.

    THE C1 ORDER (2026-10-07). Whisper was reloaded straight after comfy_free,
    but by then the job's OUTPUT FLOOR CHECK had pulled llava (~5 GB) and the
    chat judge (~5.8 GB) back onto the card inside the lease. Every Qwen render
    then reloaded Whisper into ~3.7 GB, OOM'd, and left ~3.8 GB orphaned. Now:
      1. drop ComfyUI's tail;
      2. if Whisper was held, confirm WITH THE DRIVER there is room for it;
      3. if not, evict Ollama again — ours, and it reloads lazily on the next
         turn — and confirm again;
      4. still no room: do NOT attempt a load (that is what orphans memory).
         Clear the hold and say so, loudly;
      5. reload, then prove it with a self-test transcript.
    `restored` is True/False when hearing was involved, None when it was not.
    Never silent: a failed restore is in `line` and in the log at ERROR.
    """
    import httpx
    import morpheus

    before = gpu_status()
    did, failed = [], []
    restored = None
    took_stt = bool((lease or {}).get("stt_held")) or "stt" in (lease or {}).get("evicted", [])

    own = httpx.AsyncClient() if http is None else None
    client = http or own
    try:
        try:
            await morpheus.comfy_free(client)
            did.append("dropped the ComfyUI resident tail")
        except Exception as e:                         # noqa: BLE001
            failed.append(f"comfy free: {e}")

        if stt is not None and took_stt:
            restored = False
            free = free_mib()
            if free < WHISPER_RESTORE_MB:
                try:
                    names = await morpheus.evict_ollama_all(client)
                    if names:
                        did.append("unloaded " + ", ".join(names) +
                                   " to make room for her hearing (reloads on the next turn)")
                except Exception as e:                 # noqa: BLE001
                    failed.append(f"ollama evict before restore: {e}")
                free = await _settle_until(WHISPER_RESTORE_MB)
            if free < WHISPER_RESTORE_MB:
                stt.resume(reload=False)               # clear the hold; do not load
                rest = _foreign_breakdown(gpu_status())
                failed.append(f"Whisper NOT restored: {free} MiB free, "
                              f"{WHISPER_RESTORE_MB} needed"
                              + (f" — holding the rest: {rest}" if rest else ""))
            else:
                try:
                    ok = stt.resume(reload=True)
                    st = (stt.self_test() if ok and hasattr(stt, "self_test")
                          else {"ok": ok, "text": ""})
                    if ok and st.get("ok"):
                        restored = True
                        did.append(f"reloaded Whisper and a self-test transcript "
                                   f"came back ({st.get('text', '')[:40]!r})")
                    elif ok:
                        failed.append("Whisper reloaded but its self-test transcript "
                                      f"failed: {st.get('error') or st.get('text')!r}")
                    else:
                        failed.append("Whisper did not reload")
                except Exception as e:                 # noqa: BLE001
                    failed.append(f"stt resume: {e}")
        await asyncio.sleep(1.0)
    finally:
        if own is not None:
            await own.aclose()

    after = gpu_status()
    if restored is False:
        line = ("I couldn't get my hearing back after the render — "
                + "; ".join(f for f in failed if "Whisper" in f or "stt" in f)
                + ". I'm not hearing you right now.")
        log.error("[herakles] release_card(%s): HEARING NOT RESTORED — %s",
                  (lease or {}).get("requester", "?"), failed)
    else:
        line = f"Card back: {after['free_mib']} MiB free."
        if restored:
            line += " Hearing restored and checked."
    log.info("[herakles] release_card(%s): free %d -> %d; did=%s failed=%s",
             (lease or {}).get("requester", "?"), before["free_mib"],
             after["free_mib"], did, failed)
    return {"did": did, "failed": failed, "restored": restored,
            "before": before["free_mib"], "after": after["free_mib"],
            "line": line}


async def _settle_until(need: int, timeout: float | None = None) -> int:
    """Poll the driver until `need` MiB is free or the timeout passes."""
    deadline = time.monotonic() + (CONFIRM_TIMEOUT_S if timeout is None else timeout)
    free = free_mib()
    while free < need and time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        free = free_mib()
    return free


# ── The plan, before anything is touched ─────────────────────────────────────
# Spec (2026-10-07): "show the plan before starting" and "announce deafness at
# render start". An ESTIMATE from the current tenants — request_card still
# re-measures after every rung and is the authority on what actually happens.
_RUNG_TEXT = {"comfyui": "ComfyUI's cache", "ollama": "the chat model",
              "stt": "Whisper"}


def plan_card(need_mb: int, eta_s: int = 60, *, stt=None) -> dict:
    st = gpu_status()
    free = st["free_mib"]
    freeable = {"comfyui": 0, "ollama": 0, "stt": 0}
    for t in st["tenants"]:
        if not t.get("mine"):
            continue
        owner = t.get("owner")
        if owner == "comfyui":
            freeable["comfyui"] += max(0, t["used_mib"] - 250)   # CUDA context stays
        elif owner == "ollama":
            freeable["ollama"] += t["used_mib"]
    if stt is not None and getattr(stt, "_model", None) is not None \
            and not getattr(stt, "held", False):
        freeable["stt"] = WHISPER_RESTORE_MB - 500
    rungs, est = [], free
    for who in _EVICT_ORDER:
        if est >= need_mb:
            break
        if freeable[who] > 0:
            rungs.append(who)
            est += freeable[who]
    fits = est >= need_mb
    deaf = "stt" in rungs
    mins = max(1, round(eta_s / 60))
    if not rungs and fits:
        line = f"Room already free — starting now, ~{mins} min."
    elif fits:
        what = " + ".join(_RUNG_TEXT[r] for r in rungs)
        line = f"Freeing {what}, ~{mins} min."
        if deaf:
            line += f" I'll be deaf during this render, ~{mins} min."
        if "ollama" in rungs:
            line += " Chat pauses until it's done."
    else:
        rest = _foreign_breakdown(st)
        line = (f"Even freeing everything of mine leaves ~{need_mb - est} MiB short"
                + (f" — also on the card: {rest}" if rest else "") + ".")
    return {"rungs": rungs, "fits": fits, "deaf": deaf, "need_mb": need_mb,
            "free_mib": free, "estimate_mib": est, "line": line}


# ── The OOM valve ────────────────────────────────────────────────────────────
_OOM = re.compile(r"out of memory|cudaMalloc failed|CUDA error: out of memory|"
                  r"OutOfMemoryError|insufficient .{0,20}memory", re.I)


def looks_like_oom(exc: BaseException) -> bool:
    return bool(_OOM.search(f"{type(exc).__name__}: {exc}"))


async def with_oom_retry(coro_factory, what: str = "the render"):
    """Run an awaitable; on a VRAM failure, free CACHED memory and retry ONCE.

    `coro_factory` is a zero-arg callable returning a fresh awaitable, because a
    coroutine cannot be awaited twice — the retry needs a new one.

    Exactly one retry. A loop here would turn a reproducible OOM into an
    eviction storm that keeps clearing a card the work will never fit on, and
    the second failure is the honest answer: it does not fit.

    Only level "cached" is ever used. The valve does not cancel anyone's work to
    make room for this call.
    """
    try:
        return await coro_factory()
    except Exception as first:
        if not looks_like_oom(first):
            raise
        log.warning("[herakles] %s hit VRAM pressure — freeing cached weights and "
                    "retrying once: %s", what, first)
        try:
            await free_gpu("cached")
        except Exception as e:
            log.error("[herakles] valve could not free the card: %s", e)
            raise first
        try:
            return await coro_factory()
        except Exception as second:
            if looks_like_oom(second):
                raise HeraklesError(
                    f"{what} ran out of VRAM, and still did not fit after the card "
                    f"was cleared — {gpu_status()['free_mib']} MiB free. It is too "
                    f"big for this GPU, not blocked by something else."
                ) from second
            raise
