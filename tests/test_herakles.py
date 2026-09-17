"""
Herakles — GPU eviction, verify suite.

THE RULES THIS GUARDS, in the order they matter:

  1. Nothing is freed unless asked. There is no threshold, timer or heuristic
     anywhere in this module that calls free_gpu() on its own. The one exception
     is the OOM valve, which fires only AFTER a call has already failed.
  2. Other people's processes are never touched, and a process we cannot
     attribute counts as other people's.
  3. The valve retries ONCE. A loop would turn a reproducible OOM into an
     eviction storm against a card the work will never fit on.
  4. The valve never cancels running work to make room for itself.

Run:  .venv/bin/python -m pytest tests/test_herakles.py -v
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import herakles  # noqa: E402

_REAL_SLEEP = asyncio.sleep          # bound BEFORE any monkeypatch of it


async def _no_wait(_seconds):
    """Skip free_gpu's settle pause without recursing into the patch."""
    await _REAL_SLEEP(0)


# ── fixtures: a fake card, no GPU involved ───────────────────────────────────

SERVER_CMD = "/home/astroson/Desktop/ph3b3_v2/.venv/bin/python agent/server.py"
COMFY_CMD = "/home/astroson/Desktop/comfyui/.venv/bin/python main.py --listen 127.0.0.1"
STRANGER_CMD = "/usr/bin/python3 /opt/somebody-elses/train.py"


@pytest.fixture
def card(monkeypatch):
    """A controllable GPU. `card.used` drives every reading."""

    class Card:
        def __init__(self):
            self.total, self.used = 16380, 6538
            self.procs = [("1057379", 4538, SERVER_CMD), ("1151492", 120, COMFY_CMD)]

        def smi(self, *query):
            q = query[0]
            if q.startswith("--query-gpu"):
                # name,total,used,free,temp,util — the shape gpu_status asks for
                return [["NVIDIA GeForce RTX 4060 Ti", str(self.total),
                         str(self.used), str(self.total - self.used), "52", "8"]]
            return [[p, str(m)] for p, m, _c in self.procs]

        def cmdline(self, pid):
            return next((c for p, _m, c in self.procs if p == str(pid)), "")

    c = Card()
    monkeypatch.setattr(herakles, "_SMI", "/usr/bin/nvidia-smi")
    monkeypatch.setattr(herakles, "_smi", c.smi)
    monkeypatch.setattr(herakles, "_cmdline", c.cmdline)
    return c


# ── 1. read-only means read-only ─────────────────────────────────────────────

def test_gpu_status_reports_the_card(card):
    st = herakles.gpu_status()
    assert st["total_mib"] == 16380 and st["used_mib"] == 6538
    assert st["free_mib"] == 16380 - 6538
    assert st["pressure"] == "ok"


def test_pressure_crosses_at_the_documented_marks(card):
    card.used = int(16380 * 0.49)
    assert herakles.gpu_status()["pressure"] == "ok"
    card.used = int(16380 * 0.51)
    assert herakles.gpu_status()["pressure"] == "warn"
    card.used = int(16380 * 0.86)
    assert herakles.gpu_status()["pressure"] == "tight"


def test_status_never_frees_anything(card, monkeypatch):
    """The read path must not be able to reach the write path at all."""
    async def boom(*a, **k):
        raise AssertionError("gpu_status() freed something")
    monkeypatch.setattr(herakles, "free_gpu", boom)
    herakles.gpu_status()
    herakles.status_line()


# ── 2. whose processes ───────────────────────────────────────────────────────

def test_our_tenants_are_recognised(card):
    by = {t["owner"]: t for t in herakles.tenants()}
    assert by["ph3b3"]["used_mib"] == 4538
    assert by["comfyui"]["used_mib"] == 120
    assert all(t["mine"] for t in herakles.tenants())


def test_a_stranger_on_the_card_is_never_ours(card):
    card.procs.append(("999999", 3000, STRANGER_CMD))
    st = herakles.gpu_status()
    stranger = [t for t in st["tenants"] if t["pid"] == 999999][0]
    assert stranger["mine"] is False and stranger["owner"] is None
    assert st["foreign_mib"] == 3000
    assert 3000 not in (st["reclaimable_mib"],), "foreign memory counted as reclaimable"
    assert st["reclaimable_mib"] == 4658, "reclaimable must exclude the stranger"


def test_an_unattributable_process_is_treated_as_foreign(card):
    """/proc gone, or a cmdline we cannot read. Unknown means hands off."""
    card.procs.append(("888888", 500, ""))
    t = [x for x in herakles.tenants() if x["pid"] == 888888][0]
    assert t["mine"] is False and t["owner"] is None


def test_the_stranger_is_named_in_what_a_person_hears(card):
    card.procs.append(("999999", 3000, STRANGER_CMD))
    line = herakles.status_line()
    assert "not mine" in line and "3000" in line


# ── 3. freeing is explicit, and reports measurements not claims ──────────────

@pytest.fixture
def freeable(card, monkeypatch):
    """morpheus stubbed; freeing 'works' by dropping used_mib."""
    calls = []

    class FakeMorpheus:
        COMFY_HOST = "http://127.0.0.1:8188"

        @staticmethod
        async def evict_hermes(http):
            calls.append("evict_hermes"); card.used -= 4000

        @staticmethod
        async def comfy_free(http):
            calls.append("comfy_free"); card.used -= 100

    class FakeClient:
        async def post(self, url, **kw):
            calls.append(f"POST {url.rsplit('/', 1)[-1]}")

        async def aclose(self):
            pass

    monkeypatch.setitem(sys.modules, "morpheus", FakeMorpheus)
    monkeypatch.setattr(herakles.asyncio, "sleep", _no_wait)
    return calls, FakeClient()


def test_free_gpu_rejects_an_unknown_level(card):
    with pytest.raises(herakles.HeraklesError):
        asyncio.run(herakles.free_gpu("nuke"))


def test_cached_level_does_not_cancel_running_work(freeable):
    calls, client = freeable
    asyncio.run(herakles.free_gpu("cached", http=client))
    assert "evict_hermes" in calls and "comfy_free" in calls
    assert not any("interrupt" in c for c in calls), \
        "the cached level cancelled a running job"


def test_running_level_interrupts_first(freeable):
    calls, client = freeable
    asyncio.run(herakles.free_gpu("running", http=client))
    assert any("interrupt" in c for c in calls)
    assert calls.index("POST interrupt") < calls.index("comfy_free"), \
        "freed the cache before cancelling the job that would refill it"


def test_free_reports_measured_before_and_after(freeable, card):
    _calls, client = freeable
    before_free = card.total - card.used
    r = asyncio.run(herakles.free_gpu("cached", http=client))
    assert r["freed_mib"] == 4100
    assert r["before"]["free_mib"] == before_free
    assert r["after"]["free_mib"] == before_free + 4100


def test_a_backend_that_refuses_is_reported_not_hidden(card, monkeypatch):
    class Stubborn:
        COMFY_HOST = "http://127.0.0.1:8188"

        @staticmethod
        async def evict_hermes(http):
            raise RuntimeError("Hermes did not evict within 10s")

        @staticmethod
        async def comfy_free(http):
            pass

    class C:
        async def post(self, *a, **k): pass
        async def aclose(self): pass

    monkeypatch.setitem(sys.modules, "morpheus", Stubborn)
    monkeypatch.setattr(herakles.asyncio, "sleep", _no_wait)
    r = asyncio.run(herakles.free_gpu("cached", http=C()))
    assert any("ollama evict" in f for f in r["failed"])
    assert r["freed_mib"] == 0
    assert "Nothing came back" in r["line"], "a no-op free claimed success"


# ── 4. the OOM valve ─────────────────────────────────────────────────────────

def test_oom_is_recognised_in_the_shapes_this_machine_emits():
    """The real line from this journal, 2026-08-30 and four times since."""
    real = RuntimeError("llama runner process has terminated: "
                        "cudaMalloc failed: out of memory")
    assert herakles.looks_like_oom(real)
    assert herakles.looks_like_oom(RuntimeError("CUDA error: out of memory"))
    assert not herakles.looks_like_oom(ValueError("prompt too long"))


def test_the_valve_frees_once_and_the_retry_succeeds(card, monkeypatch):
    freed = []

    async def fake_free(level="cached", http=None):
        freed.append(level); card.used = 1000
        return {"freed_mib": 5538}

    monkeypatch.setattr(herakles, "free_gpu", fake_free)
    attempts = []

    def factory():
        async def run():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("cudaMalloc failed: out of memory")
            return "rendered"
        return run()

    assert asyncio.run(herakles.with_oom_retry(factory, "the render")) == "rendered"
    assert len(attempts) == 2, "did not retry exactly once"
    assert freed == ["cached"], "the valve used a level that cancels running work"


def test_the_valve_never_retries_twice(card, monkeypatch):
    async def fake_free(level="cached", http=None):
        return {"freed_mib": 0}
    monkeypatch.setattr(herakles, "free_gpu", fake_free)
    attempts = []

    def factory():
        async def run():
            attempts.append(1)
            raise RuntimeError("CUDA out of memory")
        return run()

    with pytest.raises(herakles.HeraklesError) as e:
        asyncio.run(herakles.with_oom_retry(factory, "the render"))
    assert len(attempts) == 2, "an eviction storm — retried more than once"
    assert "too big for this GPU" in str(e.value), \
        "the second failure must say it does not fit, not blame contention"


def test_a_non_oom_failure_is_not_a_reason_to_free_the_card(card, monkeypatch):
    async def fake_free(level="cached", http=None):
        raise AssertionError("freed the card over a non-OOM error")
    monkeypatch.setattr(herakles, "free_gpu", fake_free)

    def factory():
        async def run():
            raise ValueError("bad workflow json")
        return run()

    with pytest.raises(ValueError):
        asyncio.run(herakles.with_oom_retry(factory))


# ── 5. nothing fires on its own ──────────────────────────────────────────────

def test_no_automatic_trigger_exists_in_the_module():
    """The invariant stated as source: nothing schedules or thresholds a free."""
    src = (REPO / "modules" / "herakles.py").read_text(encoding="utf-8")
    for smell in ("create_task", "call_later", "Timer(", "while True",
                  "schedule", "auto_free", "atexit"):
        assert smell not in src, f"herakles can act without being asked: {smell}"


def test_herakles_never_kills_a_process():
    src = (REPO / "modules" / "herakles.py").read_text(encoding="utf-8")
    for smell in ("os.kill", "SIGKILL", "SIGTERM", "terminate()", "pkill", ".kill("):
        assert smell not in src, f"herakles signals processes: {smell}"


def test_the_readout_keeps_what_the_old_tool_reported(card):
    """gpu_status REPLACED system.gpu_status(), which reported temperature and
    utilisation and is read aloud by Dio and Iris. Dropping either would be a
    silent regression in what a person hears, not just in a dict."""
    st = herakles.gpu_status()
    assert st["temp_c"] == 52 and st["util_pct"] == 8
    line = herakles.status_line(st)
    assert "52C" in line and "8% busy" in line


# ── 6. Morpheus / ComfyUI must never be interrupted by accident ──────────────
# Morpheus, Amphion and the upscale path share ONE lock and hold it for the whole
# render — up to 40 minutes for video. comfy_free() passes unload_models=True, so
# the "harmless" level is the dangerous one: run it mid-render and the model is
# pulled out from under a job that is already executing.

@pytest.fixture
def rendering(monkeypatch):
    """A Morpheus render in flight, registered the way the real one is."""
    class FakeLock:
        def __init__(self, held): self._h = held
        def locked(self): return self._h

    class FakeMorpheus:
        COMFY_HOST = "http://127.0.0.1:8188"
        jobs = {"job-abc": {"state": "rendering"}}
        gpu_lock = FakeLock(True)

        @staticmethod
        async def evict_hermes(http): raise AssertionError("evicted mid-render")

        @staticmethod
        async def comfy_free(http): raise AssertionError("unloaded models mid-render")

    monkeypatch.setitem(sys.modules, "morpheus", FakeMorpheus)
    monkeypatch.setitem(sys.modules, "amphion", type("A", (), {"jobs": {}}))
    return FakeMorpheus


def test_a_running_render_is_named(rendering, card):
    assert herakles.busy_with() == "Morpheus render job-abc (rendering)"


def test_cached_free_refuses_while_morpheus_is_rendering(rendering, card):
    """The whole point: the gentle level must not touch a live render."""
    with pytest.raises(herakles.HeraklesError) as e:
        asyncio.run(herakles.free_gpu("cached"))
    assert "job-abc" in str(e.value)
    assert "running" in str(e.value), "the refusal does not say how to override it"


def test_the_oom_valve_will_not_break_someone_elses_render(rendering, card):
    """The valve uses 'cached', so the guard above stops it — and the caller
    gets its ORIGINAL out-of-memory error, not a confusing eviction failure."""
    def factory():
        async def run():
            raise RuntimeError("cudaMalloc failed: out of memory")
        return run()

    with pytest.raises(RuntimeError) as e:
        asyncio.run(herakles.with_oom_retry(factory, "an upscale"))
    assert "out of memory" in str(e.value)


def test_the_lock_alone_is_enough_to_refuse(rendering, card, monkeypatch):
    """A job holding the lock without registering a row still counts."""
    rendering.jobs = {}
    assert herakles.busy_with() == "a GPU job already running"
    with pytest.raises(herakles.HeraklesError):
        asyncio.run(herakles.free_gpu("cached"))


def test_a_finished_render_does_not_block_freeing(card, monkeypatch):
    class Done:
        COMFY_HOST = "http://127.0.0.1:8188"
        jobs = {"job-old": {"state": "done"}}
        gpu_lock = type("L", (), {"locked": staticmethod(lambda: False)})()
        @staticmethod
        async def evict_hermes(http): card.used -= 4000
        @staticmethod
        async def comfy_free(http): card.used -= 100

    class C:
        async def post(self, *a, **k): pass
        async def aclose(self): pass

    monkeypatch.setitem(sys.modules, "morpheus", Done)
    monkeypatch.setitem(sys.modules, "amphion", type("A", (), {"jobs": {}}))
    monkeypatch.setattr(herakles.asyncio, "sleep", _no_wait)
    assert herakles.busy_with() is None
    r = asyncio.run(herakles.free_gpu("cached", http=C()))
    assert r["freed_mib"] == 4100


def test_running_level_is_allowed_through_because_cancelling_is_its_job(card, monkeypatch):
    """'running' must still work mid-render — that is what the caller asked for."""
    acted = []

    class Busy:
        COMFY_HOST = "http://127.0.0.1:8188"
        jobs = {"job-abc": {"state": "rendering"}}
        gpu_lock = type("L", (), {"locked": staticmethod(lambda: True)})()
        @staticmethod
        async def evict_hermes(http): acted.append("evict")
        @staticmethod
        async def comfy_free(http): acted.append("free")

    class C:
        async def post(self, url, **k): acted.append("interrupt")
        async def aclose(self): pass

    monkeypatch.setitem(sys.modules, "morpheus", Busy)
    monkeypatch.setitem(sys.modules, "amphion", type("A", (), {"jobs": {}}))
    monkeypatch.setattr(herakles.asyncio, "sleep", _no_wait)
    asyncio.run(herakles.free_gpu("running", http=C()))
    assert acted[0] == "interrupt", "cancelled after freeing, not before"


def test_the_status_readout_warns_a_render_is_up(rendering, card):
    line = herakles.status_line()
    assert "job-abc" in line and "won't clear the card" in line
