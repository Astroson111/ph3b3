"""Images and clips take the card through ONE Herakles lease (rulings, 2026-10-07).

Replaces the clip path's evict_hermes + assert_vram_for_wan, which evicted only
the chat model and then checked-and-refused: on 2026-10-07 six clips in 3½
minutes were refused 233-442 MiB short while Whisper held 4.5 GB it never asked
for. These run the REAL run_video / run_generation and the REAL Herakles ladder
against a scripted card, so they check behaviour, not wiring.

The brief's verify list, in order:
  - the 10267/10500 case starts after evicting, and restores after
  - a failure mid-render still restores, no deafness
  - a cancel mid-render still restores
  - an unknown GPU process is refused, NAMED with pid + MiB, never touched
  - the image path goes through the same lease
plus the C1 restore order and "restore failure is never silent".
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import herakles  # noqa: E402
import morpheus  # noqa: E402

TOTAL = 16380


class FakeSTT:
    """In-process Whisper. hold() frees its MiB on the card; resume() takes it back."""

    def __init__(self, card, mb=4500, selftest_ok=True):
        self.card, self.mb, self.selftest_ok = card, mb, selftest_ok
        self.held, self.holds, self.resumes, self.loads = False, [], 0, 0
        self._model = object()

    def hold(self, reason, eta_s=30):
        self.held = True
        self.holds.append(reason)
        if self._model is not None:
            self._model = None
            self.card["free"] += self.mb
        return {"released": True, "freed_mb": self.mb}

    def resume(self, reload=True):
        self.held = False
        self.resumes += 1
        if reload:
            if self.card["free"] < self.mb:          # a real load would OOM here
                self.card["oom"] = True
                return False
            self.card["free"] -= self.mb
            self._model = object()
            self.loads += 1
            return True
        return True

    def self_test(self):
        return {"ok": self.selftest_ok, "text": "The quick brown fox jumps over the lazy dog."}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """Scripted card + every ComfyUI/Ollama call morpheus would make."""
    card = {"free": 10267, "ollama": 0, "comfy_tail": 0, "foreign": [],
            "calls": [], "oom": False, "said": []}

    def status():
        tenants = [{"pid": pid, "used_mib": mib, "mine": False, "proc": name,
                    "owner": None} for pid, name, mib in card["foreign"]]
        if card["ollama"]:
            tenants.append({"pid": 7, "used_mib": card["ollama"], "mine": True,
                            "owner": "ollama", "proc": "ollama"})
        if card["comfy_tail"]:
            tenants.append({"pid": 8, "used_mib": card["comfy_tail"] + 250, "mine": True,
                            "owner": "comfyui", "proc": "python"})
        return {"free_mib": card["free"], "used_mib": TOTAL - card["free"],
                "total_mib": TOTAL, "gpu": "fake", "used_fraction": 0.5,
                "foreign_mib": sum(m for _p, _n, m in card["foreign"]),
                "tenants": tenants}

    monkeypatch.setattr(herakles, "gpu_status", status)
    monkeypatch.setattr(herakles, "free_mib", lambda: card["free"])
    monkeypatch.setattr(herakles, "busy_with", lambda **_k: None)
    monkeypatch.setattr(herakles, "CONFIRM_TIMEOUT_S", 0.05)

    async def comfy_free(_h):
        card["calls"].append("comfy_free")
        card["free"] += card["comfy_tail"]; card["comfy_tail"] = 0

    async def evict_ollama_all(_h):
        card["calls"].append("ollama_evict")
        if not card["ollama"]:
            return []
        card["free"] += card["ollama"]; card["ollama"] = 0
        return ["ph3b3-chat:latest"]

    async def noop(*_a, **_k):
        return None

    async def queue(_h, _wf):
        card["calls"].append("comfy_queue")
        return "pid-1"

    async def wait(_h, _pid, timeout_s=0):
        card["calls"].append("comfy_wait")
        hook = card.get("during_render")
        if hook:
            hook()
        return {}

    async def save(_h, _o, job_id):
        p = tmp_path / f"{job_id}.mp4"; p.write_bytes(b"x"); return p

    for name, fn in {"comfy_free": comfy_free, "evict_ollama_all": evict_ollama_all,
                     "ensure_comfy_up": noop, "comfy_queue": queue, "comfy_wait": wait,
                     "fetch_and_save_video": save}.items():
        monkeypatch.setattr(morpheus, name, fn)
    monkeypatch.setattr(morpheus, "maybe_stamp_clip", lambda p, j: p)
    monkeypatch.setattr(morpheus, "_make_video_thumb", lambda *a: None)
    monkeypatch.setattr(morpheus, "_db_insert_video", lambda *a: None)
    monkeypatch.setattr(morpheus, "video_lane_open", lambda: True)
    monkeypatch.setattr(morpheus, "build_video_workflow", lambda p: {})
    monkeypatch.setattr(morpheus, "announce", lambda t: card["said"].append(t))

    real_sleep = asyncio.sleep

    async def fast_sleep(*_a, **_k):
        await real_sleep(0)
    monkeypatch.setattr(herakles.asyncio, "sleep", fast_sleep)

    stt = FakeSTT(card)
    card["stt"] = stt
    monkeypatch.setattr(morpheus, "stt_provider", lambda: stt)
    return card


def _clip(preset="wan-fast", job="lease-test"):
    morpheus.jobs[job] = {"state": "queued"}
    asyncio.run(morpheus.run_video(job, {"preset": preset, "positive": "x",
                                         "seed": 1, "aspect": "9:16"}))
    return morpheus.jobs.pop(job)


# ── the 10267 case ───────────────────────────────────────────────────────────
def test_the_10267_case_starts_after_evicting_and_restores_after(rig):
    rig["ollama"] = 0                     # as measured at 16:25:35: Ollama already empty
    rec = _clip()
    assert rec["state"] == "done", rec
    assert "comfy_queue" in rig["calls"], "the clip never started"
    assert rig["stt"].holds, "Whisper was not evicted, so the clip could not fit"
    assert rig["stt"].loads == 1 and not rig["stt"].held, "her hearing was not restored"
    assert "deaf" in rec["plan"].lower(), "deafness was not announced in the plan"
    assert any("deaf" in s.lower() for s in rig["said"]), "deafness was not SPOKEN"
    assert "restore_error" not in rec
    assert "Hearing restored and checked" in rec["restore"]


def test_the_ladder_is_cheapest_first(rig):
    rig.update(free=4500, ollama=5800, comfy_tail=400)     # needs BOTH rungs
    _clip()
    i_c, i_o = rig["calls"].index("comfy_free"), rig["calls"].index("ollama_evict")
    assert i_c < i_o, "Ollama was evicted before ComfyUI's cache was dropped"


# ── failure and cancel still restore ─────────────────────────────────────────
def test_a_failure_mid_render_still_restores(rig):
    def boom():
        raise RuntimeError("ComfyUI died mid-render")
    rig["during_render"] = boom
    rec = _clip()
    assert rec["state"] == "error"
    assert rig["stt"].loads == 1 and not rig["stt"].held, "a failed render left her deaf"


def test_a_cancel_mid_render_still_restores(rig):
    job = "lease-cancel"

    def cancel():
        morpheus.jobs[job]["state"] = "cancelled"
    rig["during_render"] = cancel
    rec = _clip(job=job)
    assert rec["state"] == "cancelled"
    assert rig["stt"].loads == 1 and not rig["stt"].held, "a cancel left her deaf"


# ── unknown holders ──────────────────────────────────────────────────────────
def test_an_unknown_gpu_process_is_refused_named_and_untouched(rig):
    rig["free"] = 2000
    rig["foreign"] = [(4242, "someone-elses-trainer", 9000)]
    rec = _clip()
    assert rec["state"] == "error"
    assert "pid 4242" in rec["error"] and "9000 MiB" in rec["error"], rec["error"]
    assert "not mine" in rec["error"].lower()
    assert rig["foreign"] == [(4242, "someone-elses-trainer", 9000)], "foreign memory touched"
    assert "comfy_queue" not in rig["calls"], "a clip was queued onto a card it can't fit"
    # The refusal happened after the ladder held her hearing — it must come back.
    assert not rig["stt"].held and rig["stt"].loads == 1, "a REFUSAL left her deaf"


def test_herakles_has_no_way_to_kill_anything():
    src = (ROOT / "modules" / "herakles.py").read_text()
    for banned in ("os.kill", "signal.SIG", "pkill", "kill -", ".terminate()"):
        assert banned not in src


# ── every preset, every path ─────────────────────────────────────────────────
@pytest.mark.parametrize("preset", sorted(morpheus.VIDEO_PRESETS))
def test_no_preset_skips_the_lease(rig, monkeypatch, preset):
    asked = []
    real = herakles.request_card

    async def spy(need, requester, **kw):
        asked.append((need, requester))
        return await real(need, requester, **kw)
    monkeypatch.setattr(herakles, "request_card", spy)
    _clip(preset=preset)
    assert asked and asked[0][1].startswith(preset), f"{preset} skipped the lease"


@pytest.mark.parametrize("engine,mode", [("sdxl", "sdxl"), ("qwen", "qwen")])
def test_the_image_path_takes_the_same_lease(rig, monkeypatch, engine, mode):
    asked = []

    async def spy(need, requester, **kw):
        asked.append(requester)
        return {"granted": False, "line": "stop here", "evicted": [], "stt_held": False}
    monkeypatch.setattr(herakles, "request_card", spy)
    job = f"img-{engine}"
    morpheus.jobs[job] = {"state": "queued"}
    asyncio.run(morpheus.run_generation(job, {"engine": engine, "positive": "x"}))
    rec = morpheus.jobs.pop(job)
    assert asked and asked[0].startswith(mode), f"never reached the lease: {rec}"


def test_the_retired_helpers_are_gone_from_the_render_paths():
    src = (ROOT / "modules" / "morpheus.py").read_text()
    for fn in ("async def run_generation(", "async def run_edit(", "async def run_video("):
        i = src.index(fn)
        body = src[i:src.index("\nasync def ", i + 10) if "\nasync def " in src[i + 10:] else None]
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        assert "evict_hermes(" not in code, f"{fn} still uses evict_hermes"
    assert "def assert_vram_for_wan" not in src and "WAN_NEED_MB =" not in src


# ── the C1 restore order ─────────────────────────────────────────────────────
def test_judges_reloaded_inside_the_lease_are_evicted_before_whisper_returns(rig):
    """The 15:04 case: the output floor check pulled llava + chat back onto the
    card inside the lease, and Whisper was then reloaded into ~3.7 GB and OOM'd."""
    def judges_come_back():
        rig["ollama"] = 10800                 # llava ~5 GB + chat ~5.8 GB
        rig["free"] -= 10800
    rig["during_render"] = judges_come_back
    rec = _clip()
    assert rec["state"] == "done"
    assert not rig["oom"], "Whisper was reloaded into a card that could not hold it"
    assert rig["stt"].loads == 1
    calls = rig["calls"]
    assert calls.index("ollama_evict", calls.index("comfy_wait")) < len(calls)


def test_a_restore_that_cannot_fit_does_not_try_and_says_so_out_loud(rig):
    def strangers_arrive():
        rig["foreign"] = [(5555, "game.exe", 13000)]
        rig["free"] -= 13000
    rig["during_render"] = strangers_arrive
    rec = _clip()
    assert not rig["oom"], "attempted a load that could only OOM — that is how memory orphans"
    assert rig["stt"].loads == 0 and not rig["stt"].held, "hold not cleared"
    assert "restore_error" in rec, "a failed restore was silent on the job"
    assert any("hearing" in s.lower() for s in rig["said"]), "a failed restore was not SPOKEN"
    assert "pid 5555" in rec["restore_error"]


def test_a_failed_self_test_is_a_failed_restore(rig):
    rig["stt"].selftest_ok = False
    rec = _clip()
    assert "restore_error" in rec and "self-test" in rec["restore_error"]


# ── the need figures ─────────────────────────────────────────────────────────
def test_need_is_the_config_figure_plus_the_500_margin():
    cfg = json.loads((ROOT / "config" / "vram_needs.json").read_text())
    assert cfg["margin_mib"] == 500
    for mode in ("sdxl", "edit", "qwen"):
        need, e = morpheus.need_for(mode)
        assert need == e["need_mib"] + 500, mode


def test_wan_defaults_to_streamed_so_whisper_stays_loaded():
    """Ruled 2026-10-07 after B measured no speed gain for 13 min of deafness."""
    for mode in ("wan-fast", "wan-quality"):
        need, e = morpheus.need_for(mode)
        assert e["policy"] == "streamed", mode
        assert need == 10354, f"{mode}: {need} — the peak, no margin (ruled)"
        assert need <= 10724, "won't fit beside Whisper — she'd be evicted for every clip"
        assert e.get("resident_mib"), "resident must stay available for measurement"
    assert morpheus.need_for("wan-fast")[1]["resident_mib"] == 13946, "the measured B figure"


def test_a_broken_config_fails_closed(monkeypatch, tmp_path):
    bad = tmp_path / "v.json"; bad.write_text("{nope")
    monkeypatch.setattr(morpheus, "VRAM_NEEDS_FILE", bad)
    need, _ = morpheus.need_for("wan-fast")
    assert need >= 16000, "a broken config let a render start on a guess"


def test_every_preset_and_engine_has_a_figure():
    for mode in list(morpheus.VIDEO_PRESETS) + ["sdxl", "edit", "qwen"]:
        need, e = morpheus.need_for(mode)
        assert e.get("policy") != "fallback" and need < 16000, mode
