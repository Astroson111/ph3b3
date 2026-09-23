"""Palamedes 1a — engine plumbing.

The Qwen lane exists because of measurement, and these tests exist so the
measurement cannot be quietly un-decided: a step knob reaching the sampler, a
disabled engine rendering anyway, or the SDXL default drifting while nobody was
watching.
"""
import ast
import hashlib
import json
import pathlib
import re

import pytest

import modules.morpheus as morpheus

REPO = pathlib.Path(__file__).resolve().parents[1]
HTML = (REPO / "static" / "panel.html").read_text(encoding="utf-8")

# The SDXL graph for a fixed seed, hashed. Phase 1a must not move the default
# path by a single byte; if this changes, something did.
SDXL_GOLDEN = "188b80086089d782ea5fc427e8f79c92eb3f83d5080feb145169f9d783b7bfc4"
FIXED = {"positive": "a red barn at dusk", "negative": "", "width": 1024,
         "height": 1024, "seed": 12345, "steps": 30, "cfg": 7.5,
         "sampler_name": "dpmpp_2m", "scheduler": "karras"}


@pytest.fixture
def qwen_on(monkeypatch):
    monkeypatch.setattr(morpheus, "qwen_open", lambda: True)


# ---------- the default did not move --------------------------------------
def test_sdxl_fixed_seed_graph_is_byte_identical():
    wf = morpheus.build_workflow(dict(FIXED))
    got = hashlib.sha256(json.dumps(wf, sort_keys=True).encode()).hexdigest()
    assert got == SDXL_GOLDEN, (
        "the SDXL graph changed. Phase 1a adds an engine; it must not touch "
        "the default path.")


def test_no_engine_means_sdxl():
    """An old client that never heard of engines must behave exactly as before."""
    a = morpheus.build_workflow(dict(FIXED))
    b = morpheus.build_workflow(dict(FIXED, engine="sdxl"))
    assert a == b


def test_sdxl_graph_carries_nothing_qwen():
    wf = morpheus.build_workflow(dict(FIXED))
    blob = json.dumps(wf).lower()
    for token in ("qwen", "gguf", "lightning", "lora"):
        assert token not in blob, f"the SDXL graph mentions {token!r}"


# ---------- the switch, both halves ---------------------------------------
def test_qwen_is_off_by_default():
    assert morpheus.engine_enabled("qwen") is False, \
        "the Qwen lane is enabled without PH3B3_QWEN being set"
    assert morpheus.engine_enabled("sdxl") is True


def test_disabled_engine_is_refused_by_name_with_a_reason():
    """Never a 404 — the feature exists, it is switched off — and never a
    silent fall back to SDXL, which would render the wrong thing quietly."""
    with pytest.raises(ValueError) as e:
        morpheus.resolve_engine("qwen")
    msg = str(e.value).lower()
    assert "qwen" in msg and ("switched off" in msg or "off" in msg)
    assert "nothing was rendered" in msg


def test_unknown_engine_is_refused_and_lists_the_real_ones():
    with pytest.raises(ValueError) as e:
        morpheus.resolve_engine("midjourney")
    assert "midjourney" in str(e.value) and "sdxl" in str(e.value)


def test_enabled_qwen_resolves(qwen_on):
    assert morpheus.resolve_engine("qwen") == "qwen"


def test_resolve_engine_is_the_guard_not_the_dropdown():
    """The disabled attribute in the markup is a courtesy. Anything can POST."""
    src = ast.parse((REPO / "agent" / "server.py").read_text())
    fn = next(n for n in ast.walk(src)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "image_generate")
    body = ast.unparse(fn)
    assert "resolve_engine" in body, "the endpoint does not validate the engine"
    # ordering: refused before anything is queued
    assert body.index("resolve_engine") < body.index("create_job"), \
        "the engine is validated AFTER the job is created — a refusal would " \
        "already have cost something"


# ---------- the measurement cannot be un-decided --------------------------
def test_qwen_steps_come_from_the_constants_not_the_caller(qwen_on):
    """A 4-step Lightning LoRA driven at 30 steps is simply the wrong model."""
    p = dict(FIXED, engine="qwen", steps=30, cfg=7.5)
    wf = morpheus.build_workflow(p)
    ks = wf["7"]["inputs"]
    assert ks["steps"] == morpheus.QWEN_STEPS == 4
    assert ks["cfg"] == morpheus.QWEN_CFG == 1.0
    assert p["steps"] == 4, "params did not record what actually ran"


def test_qwen_graph_uses_the_measured_pick(qwen_on):
    wf = morpheus.build_workflow(dict(FIXED, engine="qwen"))
    assert wf["1"]["inputs"]["unet_name"] == "Qwen-Image-Edit-2509-Q4_K_M.gguf"
    assert "Lightning-4steps" in wf["10"]["inputs"]["lora_name"]
    assert wf["7"]["inputs"]["model"] == ["10", 0], \
        "KSampler is not taking the LoRA-patched model"


def test_qwen_output_goes_through_the_same_save_path(qwen_on):
    """SaveImage, like SDXL, so fetch_and_save -> output check -> watermark is
    the identical path. The 2026-09-15 stamping ruling applies for free."""
    wf = morpheus.build_workflow(dict(FIXED, engine="qwen"))
    savers = [n for n in wf.values() if n["class_type"] == "SaveImage"]
    assert len(savers) == 1 and savers[0]["inputs"]["images"] == ["8", 0]


def test_unroutable_engine_raises_rather_than_defaulting():
    """Quietly rendering the wrong engine is worse than failing."""
    with pytest.raises(ValueError, match="unroutable"):
        morpheus.build_workflow(dict(FIXED, engine="flux"))


# ---------- the panel is a view of the server, not a second list ----------
def test_panel_fetches_the_enabled_set():
    assert "/image/engines" in HTML, "the panel still carries its own engine list"
    assert "engInit()" in HTML, "engInit is defined but never called"


def test_engine_travels_in_the_generate_body():
    m = re.search(r"body: JSON\.stringify\(\{positive, negative_prompt.*?\}\)",
                  HTML, re.S)
    assert m and "engine:" in m.group(0), \
        "the generate payload does not carry the engine"


def test_quality_collapses_under_a_single_speed_engine():
    """Offering Draft/Standard/Premium for a lane with one measured setting
    would be fiction."""
    assert "fixed_quality" in HTML


# ---------- the refusal costs NOTHING -------------------------------------
# Driven through the real route, because the requirement is about ordering at
# the endpoint: an engine that will not run must be turned away before the job
# exists, before the lock, before anything is evicted.
import base64                                    # noqa: E402
import sys                                       # noqa: E402

sys.path.insert(0, str(REPO))
from agent import server                         # noqa: E402
from fastapi.testclient import TestClient        # noqa: E402

_client = TestClient(server.app)
_AUTH = {"Authorization": "Basic " + base64.b64encode(
    f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()}


@pytest.fixture
def no_side_effects(monkeypatch):
    """Record anything a refused request must NOT have caused."""
    spent = {"jobs": 0, "evicted": 0, "queued": 0, "cards": 0}

    real_create = server.morpheus.create_job

    def create_job(*a, **k):
        spent["jobs"] += 1
        return real_create(*a, **k)

    async def evict(*a, **k):
        spent["evicted"] += 1

    async def run_gen(*a, **k):
        spent["queued"] += 1

    async def req_card(*a, **k):
        spent["cards"] += 1
        return {"granted": True, "evicted": [], "line": ""}

    monkeypatch.setattr(server.morpheus, "create_job", create_job)
    monkeypatch.setattr(server.morpheus, "evict_hermes", evict)
    monkeypatch.setattr(server.morpheus, "run_generation", run_gen)
    import modules.herakles as hk
    monkeypatch.setattr(hk, "request_card", req_card)
    monkeypatch.setattr(server, "_morpheus_floor_gate", lambda *a, **k: None)
    return spent


def test_switched_off_engine_is_refused_at_the_endpoint(no_side_effects):
    r = _client.post("/image/generate", headers=_AUTH,
                     json={"positive": "a shop sign", "engine": "qwen"})
    assert r.status_code == 400, f"expected a stated refusal, got {r.status_code}"
    detail = r.json().get("detail", "").lower()
    assert "qwen" in detail, "the refusal does not name the engine"
    assert "switched off" in detail or "off" in detail


def test_the_refusal_is_never_a_404(no_side_effects):
    """404 says the feature does not exist. It does — it is switched off."""
    r = _client.post("/image/generate", headers=_AUTH,
                     json={"positive": "a shop sign", "engine": "qwen"})
    assert r.status_code != 404


def test_a_refused_request_acquires_nothing_and_evicts_nothing(no_side_effects):
    _client.post("/image/generate", headers=_AUTH,
                 json={"positive": "a shop sign", "engine": "qwen"})
    assert no_side_effects == {"jobs": 0, "evicted": 0, "queued": 0, "cards": 0}, \
        f"a refused request still spent something: {no_side_effects}"


def test_an_unknown_engine_also_costs_nothing(no_side_effects):
    r = _client.post("/image/generate", headers=_AUTH,
                     json={"positive": "a shop sign", "engine": "nope"})
    assert r.status_code == 400
    assert no_side_effects["jobs"] == 0 and no_side_effects["evicted"] == 0


def test_sdxl_still_queues_normally(no_side_effects):
    """The guard must refuse the off-spec case WITHOUT breaking the default."""
    r = _client.post("/image/generate", headers=_AUTH,
                     json={"positive": "a red barn", "engine": "sdxl"})
    assert r.status_code == 200, r.text
    assert r.json()["engine"] == "sdxl"
    assert no_side_effects["jobs"] == 1


def test_engines_endpoint_reports_the_switch(no_side_effects):
    d = _client.get("/image/engines", headers=_AUTH).json()
    by = {e["id"]: e for e in d["engines"]}
    assert by["qwen"]["enabled"] is False
    assert by["qwen"]["model"] == "not installed"
    assert by["sdxl"]["enabled"] is True
    assert by["qwen"]["fixed_quality"]["label"] == "Lightning"
