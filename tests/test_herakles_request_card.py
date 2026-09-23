"""Herakles as the single eviction authority.

request_card() makes room by evicting OUR tenants only, cheapest to restore
first, and hands back a lease so release_card() can put things as they were.

The standing weld: foreign memory is never touched, at any level. And nothing
is evicted out from under a render already in flight.
"""
import ast
import asyncio

import pytest

import modules.herakles as hk

SRC = ast.parse(open(hk.__file__).read())


def _fn(name):
    return next((n for n in SRC.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


class FakeSTT:
    """Stands in for the in-process Whisper. It has no pid, which is the point."""
    def __init__(self):
        self.held, self.holds, self.resumes = False, [], 0

    def hold(self, reason, eta_s=30):
        self.held = True
        self.holds.append((reason, eta_s))
        return {"released": True, "freed_mb": 4500}

    def resume(self, reload=True):
        self.held = False
        self.resumes += 1
        return True


@pytest.fixture
def card(monkeypatch):
    """Drive gpu_status() from a script of successive readings."""
    state = {"free": 400, "foreign": 0}

    def fake_status():
        return {"free_mib": state["free"], "used_mib": 16380 - state["free"],
                "total_mib": 16380, "foreign_mib": state["foreign"],
                "used_fraction": 1 - state["free"] / 16380, "gpu": "fake"}

    monkeypatch.setattr(hk, "gpu_status", fake_status)
    monkeypatch.setattr(hk, "busy_with", lambda **_kw: None)

    class FakeMorpheus:
        COMFY_HOST = "http://x"
        @staticmethod
        async def evict_hermes(c): state["free"] += 6000
        @staticmethod
        async def comfy_free(c): state["free"] += 3000

    import sys
    monkeypatch.setitem(sys.modules, "morpheus", FakeMorpheus)

    # Patch the module's OWN reference, not the global asyncio: setattr on
    # hk.asyncio.sleep mutates the real module, and a lambda delegating to
    # asyncio.sleep then calls itself forever.
    class _FastAsyncio:
        def __getattr__(self, n):
            return getattr(asyncio, n)

        @staticmethod
        async def sleep(*_a, **_k):
            return None

    monkeypatch.setattr(hk, "asyncio", _FastAsyncio())
    return state


# ---------- the weld ------------------------------------------------------
def test_foreign_memory_is_never_evicted():
    """_EVICT_ORDER must only name things we own."""
    owners = {name for name, _pat in hk._OWN} | {"stt"}
    assert set(hk._EVICT_ORDER) <= owners, \
        f"_EVICT_ORDER names something we do not own: {set(hk._EVICT_ORDER) - owners}"


def test_hearing_is_evicted_last():
    """Reloading Whisper costs ~15s of deafness; it is the expensive one."""
    assert hk._EVICT_ORDER[-1] == "stt", \
        "her hearing must be the last thing taken, not the first"


def test_refuses_under_a_live_render(monkeypatch, card):
    monkeypatch.setattr(hk, "busy_with", lambda **_kw: "a Morpheus render")
    with pytest.raises(hk.HeraklesError, match="Not while"):
        asyncio.run(hk.request_card(12000, "palamedes", http=object()))


def test_rejects_nonsense_need(card):
    with pytest.raises(hk.HeraklesError):
        asyncio.run(hk.request_card(0, "palamedes", http=object()))


# ---------- behaviour -----------------------------------------------------
def test_takes_nothing_when_there_is_already_room(card):
    card["free"] = 13000
    r = asyncio.run(hk.request_card(12000, "palamedes", http=object()))
    assert r["granted"] and r["evicted"] == []
    assert "already free" in r["line"]


def test_stops_as_soon_as_there_is_enough(card):
    """6000 from ollama alone clears a 6000 need — hearing must survive."""
    stt = FakeSTT()
    r = asyncio.run(hk.request_card(6000, "palamedes", http=object(), stt=stt))
    assert r["granted"] and r["evicted"] == ["ollama"]
    assert stt.held is False, "took her hearing when it was not needed"


def test_escalates_to_hearing_only_when_needed(card):
    stt = FakeSTT()
    r = asyncio.run(hk.request_card(13000, "palamedes", http=object(), stt=stt))
    assert r["evicted"] == ["ollama", "comfyui", "stt"]
    assert stt.held is True and stt.holds[0][0] == "palamedes"


def test_names_foreign_memory_when_it_is_the_shortfall(card):
    card["foreign"] = 5000
    stt = FakeSTT()
    r = asyncio.run(hk.request_card(16000, "palamedes", http=object(), stt=stt))
    assert r["granted"] is False
    assert "not mine" in r["line"] and r["short_mib"] > 0


def test_release_card_reloads_hearing_eagerly(card):
    stt = FakeSTT()
    lease = asyncio.run(hk.request_card(13000, "palamedes", http=object(), stt=stt))
    assert stt.held is True
    asyncio.run(hk.release_card(lease, http=object(), stt=stt))
    assert stt.held is False and stt.resumes == 1, \
        "her ears were left on a lazy fuse"


def test_release_card_drops_the_resident_tail(card):
    """ComfyUI must not squat on the card once the job is done."""
    r = asyncio.run(hk.release_card({"requester": "palamedes", "evicted": []},
                                    http=object()))
    assert any("resident tail" in d for d in r["did"])


def test_release_card_leaves_hearing_alone_if_it_was_never_taken(card):
    stt = FakeSTT()
    asyncio.run(hk.release_card({"requester": "x", "evicted": ["ollama"]},
                                http=object(), stt=stt))
    assert stt.resumes == 0, "resumed hearing that was never held"


# ---------- the 50% mark stays advisory -----------------------------------
def test_pressure_warn_is_never_a_trigger():
    """PRESSURE_WARN is display-only (ruling 2026-09-17, reaffirmed 09-22)."""
    for fname in ("request_card", "release_card"):
        body = ast.unparse(_fn(fname))
        assert "PRESSURE_WARN" not in body, \
            f"{fname} acts on the 50% mark — it is a display value, not a trigger"


# ---------- a job making room for ITSELF ----------------------------------
def test_a_job_can_clear_room_for_its_own_render(monkeypatch, card):
    """Herakles' first real caller is run_generation, which asks for the card
    WHILE holding gpu_lock with its own row already non-terminal. Without
    ignore_job the authority refused the only customer it was built for."""
    seen = {}

    def fake_busy(ignore_job=None):
        seen["ignore_job"] = ignore_job
        return None if ignore_job == "job-1" else "Morpheus render job-1 (loading)"

    monkeypatch.setattr(hk, "busy_with", fake_busy)
    r = asyncio.run(hk.request_card(6000, "palamedes", http=object(), holder="job-1"))
    assert r["granted"] is True
    assert seen["ignore_job"] == "job-1", "holder was not passed through to busy_with"


def test_another_live_job_still_refuses(monkeypatch, card):
    """Excluding yourself is the ONLY exception. Someone else's render still wins."""
    monkeypatch.setattr(hk, "busy_with",
                        lambda ignore_job=None: "Amphion song abc (sampling)")
    with pytest.raises(hk.HeraklesError, match="Not while"):
        asyncio.run(hk.request_card(6000, "palamedes", http=object(), holder="job-1"))


def test_busy_with_ignores_only_the_named_job(monkeypatch):
    """Exercise the real function, not a fake."""
    import sys, types
    fake = types.SimpleNamespace(
        jobs={"mine": {"state": "loading"}, "theirs": {"state": "sampling"}},
        gpu_lock=None)
    monkeypatch.setitem(sys.modules, "morpheus", fake)
    assert hk.busy_with(ignore_job="mine") is not None      # theirs still live
    fake.jobs.pop("theirs")
    assert hk.busy_with(ignore_job="mine") is None          # only mine left
    assert hk.busy_with() is not None                       # unnamed: mine counts


def test_a_held_lock_does_not_refuse_the_holder(monkeypatch):
    """run_generation holds gpu_lock when it asks. The lock check must not fire
    for a caller that named itself, or nothing could ever make room."""
    import sys, types

    class _Lock:
        @staticmethod
        def locked(): return True

    monkeypatch.setitem(sys.modules, "morpheus",
                        types.SimpleNamespace(jobs={}, gpu_lock=_Lock()))
    assert hk.busy_with() == "a GPU job already running"
    assert hk.busy_with(ignore_job="mine") is None
