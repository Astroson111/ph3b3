"""Herakles v1.1 — the eviction authority stops lying about what it evicted.

Measured 2026-09-23. Herakles logged evicted=['ollama','comfyui','stt'] and
refused with "everything of mine evicted" while two Ollama runners held 5.16 GiB
and 4.98 GiB. Both classify as OURS, so they were not even counted as foreign.
The message was not unhelpful — it was false, and a false success claim is the
tesseract failure in prose.
"""
import ast
import asyncio
import pathlib
import types

import pytest

import herakles as hk

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = (REPO / "modules" / "herakles.py").read_text()
MO = (REPO / "modules" / "morpheus.py").read_text()


class FakeSTT:
    def __init__(self, mb=4516):
        self.held, self.mb, self.resumes = False, mb, 0
    def hold(self, reason, eta_s=30):
        self.held = True
        return {"released": True, "freed_mb": self.mb}
    def resume(self, reload=True):
        self.held = False; self.resumes += 1; return True


@pytest.fixture
def card(monkeypatch):
    """Scripted card. free_mib() is what the tiers are judged against."""
    state = {"free": 500, "tenants": [], "ollama": ["hermes3:latest", "llava:latest"]}
    monkeypatch.setattr(hk, "free_mib", lambda: state["free"])
    monkeypatch.setattr(hk, "busy_with", lambda **_k: None)
    monkeypatch.setattr(hk, "gpu_status", lambda: {
        "free_mib": state["free"], "used_mib": 16380 - state["free"],
        "total_mib": 16380, "gpu": "fake",
        "foreign_mib": sum(t["used_mib"] for t in state["tenants"] if not t["mine"]),
        "tenants": state["tenants"], "used_fraction": 0.5})

    class FakeMorpheus:
        COMFY_HOST = "http://x"
        @staticmethod
        async def evict_ollama_all(c):
            names = list(state["ollama"]); state["ollama"] = []
            state["free"] += 6000 if names else 0
            return names
        @staticmethod
        async def comfy_free(c):
            state["free"] += 3000
    import sys
    monkeypatch.setitem(sys.modules, "morpheus", FakeMorpheus)

    class _Fast:
        def __getattr__(self, n): return getattr(asyncio, n)
        @staticmethod
        async def sleep(*_a, **_k): return None
    monkeypatch.setattr(hk, "asyncio", _Fast())
    # The unhappy path waits for the driver. With sleep stubbed out that would
    # busy-spin the real 8s deadline per tier; the behaviour under test is the
    # verdict, not the duration.
    monkeypatch.setattr(hk, "CONFIRM_TIMEOUT_S", 0.05)
    return state


# ---------- LEAD: every model, not one species ---------------------------
def test_the_ollama_tier_unloads_every_model():
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "request_card")
    body = ast.unparse(fn)
    assert "evict_ollama_all" in body, \
        "the ollama tier still unloads one model by name"
    assert "evict_hermes" not in body, \
        "the ollama tier still calls the single-species evictor"


def test_evict_ollama_all_waits_for_an_empty_runner_list():
    fn = next(n for n in ast.walk(ast.parse(MO))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "evict_ollama_all")
    body = ast.unparse(fn)
    assert "/api/ps" in body, "it does not confirm with ollama at all"
    assert "raise RuntimeError" in body, \
        "it can return claiming success while models are still loaded"


def test_every_loaded_model_is_asked_to_unload(card):
    card["ollama"] = ["hermes3:latest", "llava:latest", "ph3b3-chat:latest"]
    asyncio.run(hk.request_card(6000, "palamedes", http=object()))
    assert card["ollama"] == [], "a loaded model survived the ollama tier"


# ---------- Fix 2: confirmed, or it is not counted -----------------------
def test_a_tier_that_frees_nothing_is_not_reported_as_evicted(card, monkeypatch):
    """The exact failure: claiming an eviction the driver never reflected."""
    class Stuck:
        COMFY_HOST = "http://x"
        @staticmethod
        async def evict_ollama_all(c): return ["llava:latest"]   # frees nothing
        @staticmethod
        async def comfy_free(c): pass
    import sys
    monkeypatch.setitem(sys.modules, "morpheus", Stuck)
    r = asyncio.run(hk.request_card(14000, "palamedes", http=object(),
                                    stt=FakeSTT(0)))
    assert "ollama" not in r["evicted"], \
        "a tier that released nothing was counted as an eviction"
    assert "ollama" in r["unconfirmed"]
    assert "asked" in r["line"].lower()


def test_a_tier_that_does_free_is_counted(card):
    r = asyncio.run(hk.request_card(6000, "palamedes", http=object()))
    assert "ollama" in r["evicted"] and r["granted"] is True


# ---------- Fix 3: names and sizes, and never a false success ------------
def test_refusal_names_who_holds_the_remainder(card):
    card["tenants"] = [
        {"pid": 4242, "used_mib": 2100, "mine": False, "proc": "firefox"},
        {"pid": 4243, "used_mib": 1300, "mine": False, "proc": "obs"},
    ]
    r = asyncio.run(hk.request_card(15000, "palamedes", http=object(), stt=FakeSTT()))
    assert r["granted"] is False
    assert "firefox" in r["line"] and "2100" in r["line"], r["line"]
    assert "obs" in r["line"] and "1300" in r["line"], r["line"]
    assert "not mine" in r["line"].lower()


def test_a_reaped_pid_is_named_as_releasing_not_as_a_stranger():
    """A pid nvidia-smi still reports whose /proc has gone is almost always
    something of ours mid-release, not an alien."""
    assert "already exited" in hk._proc_name(999999)


def test_refusal_never_claims_everything_was_evicted_when_it_was_not(card, monkeypatch):
    class Stuck:
        COMFY_HOST = "http://x"
        @staticmethod
        async def evict_ollama_all(c): return ["llava:latest"]
        @staticmethod
        async def comfy_free(c): pass
    import sys
    monkeypatch.setitem(sys.modules, "morpheus", Stuck)
    r = asyncio.run(hk.request_card(15000, "palamedes", http=object(), stt=FakeSTT(0)))
    assert "everything of mine" not in r["line"].lower(), \
        f"the false success claim is back: {r['line']}"


# ---------- the weld: reporting is not a licence -------------------------
def test_the_refusal_path_kills_nothing():
    """Naming a foreign process is reporting. The weld does not move."""
    tree = ast.parse(SRC)
    banned = {"kill", "killpg", "terminate", "send_signal", "Popen", "run",
              "check_call", "check_output", "system"}
    offenders = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in banned:
                base = ast.unparse(n.func.value)
                # _smi() shells out to nvidia-smi to READ. That is the only one.
                if not (n.func.attr == "run" and "subprocess" in base):
                    offenders.append(f"{base}.{n.func.attr} line {n.lineno}")
    assert not offenders, f"herakles can signal a process: {offenders}"


def test_herakles_imports_no_signalling_machinery():
    assert "import signal" not in SRC
    assert "import psutil" not in SRC


# ---------- Fix 1 (cosmetic): the host process is reclaimable ------------
def test_reclaimable_counts_the_host_process(monkeypatch):
    """Whisper lives inside the host pid and stt.release() is the handle on it.
    Reporting it as neither reclaimable nor foreign is a lie waiting for a
    believer.

    Behavioural, not a string match: an earlier version compared source text and
    ast.unparse normalises quoting, so it failed on correct code.
    """
    monkeypatch.setattr(hk, "_smi", lambda *_a: [[
        "fake", "16380", "5000", "11380", "40", "10"]])
    monkeypatch.setattr(hk, "tenants", lambda: [
        {"pid": 1, "used_mib": 4516, "owner": "ph3b3", "mine": True,
         "is_self": True,  "cmd": "server.py"},
        {"pid": 2, "used_mib": 200,  "owner": "comfyui", "mine": True,
         "is_self": False, "cmd": "main.py"},
    ])
    st = hk.gpu_status()
    assert st["reclaimable_mib"] == 4716, \
        f"the host process is missing from reclaimable: {st['reclaimable_mib']}"
    assert st["reclaimable_excluding_self_mib"] == 200
    assert st["foreign_mib"] == 0


def test_host_sized_memory_routes_to_the_stt_tier_not_the_foreign_bucket(card):
    """A fake host-pid holding stt-sized VRAM must be reachable via the stt
    tier, never reported as somebody else's."""
    card["tenants"] = [{"pid": 2084539, "used_mib": 4516, "mine": True,
                        "is_self": True, "proc": "python"}]
    stt = FakeSTT(4516)
    r = asyncio.run(hk.request_card(15000, "palamedes", http=object(), stt=stt))
    assert stt.held is True, "the stt tier was never reached for host memory"
    assert "not mine" not in r["line"].lower(), \
        f"her own Whisper was reported as foreign: {r['line']}"
