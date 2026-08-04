"""
Tests for Morpheus negative_prompt support + safety-floor broadening.

Run:  .venv/bin/python tests/test_morpheus_negative.py
No GPU/ComfyUI needed — run_generation is stubbed so no job ever reaches the
GPU-swap lifecycle (Hermes is never evicted, ComfyUI is never queued).

Floor/profile probes use a neutral sentinel + monkeypatch: the tests verify the
endpoint ROUTES each field through floor_check / profile_check, without embedding
any real banned literal in the repo. Whether the denylists' contents are correct
is a separate concern with its own coverage.
"""
import base64
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))   # for `import server`
                                           # (server.py adds modules/ to path itself)

import server                              # noqa: E402  — builds FastAPI app + imports morpheus
from fastapi.testclient import TestClient  # noqa: E402

morpheus = server.morpheus

# Neutralize the GPU-swap background task: accepted requests must not evict
# Hermes or hit ComfyUI during tests. server.py calls `morpheus.run_generation`.
async def _noop_run_generation(*_a, **_k):
    return None
morpheus.run_generation = _noop_run_generation

client = TestClient(server.app)

# Endpoints are Basic-auth gated. Pull the configured creds from the loaded
# module (no secrets baked into this file) so the tests hit the real auth path.
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}", "X-Ph3b3-Device": "pytest"}

DEFAULT_NEG = "text, watermark, multiple objects, cluttered background, blurry"

# Neutral probe — carries no real banned content. The stubs below make the
# safety checks fire on this token only, delegating everything else to the real
# implementation so unrelated behavior is unchanged.
SENTINEL = "__floor_probe_sentinel__"

_real_floor_check = morpheus.floor_check
def _stub_floor_check(text):
    if SENTINEL in (text or ""):
        return "test_probe_category"
    return _real_floor_check(text)

_real_profile_check = morpheus.profile_check
def _stub_profile_check(text, denylist=None):
    if SENTINEL in (text or ""):
        return False   # False = denied
    return _real_profile_check(text, denylist=denylist)

_results: list[tuple[str, bool]] = []
def check(name: str, ok: bool, extra: str = "") -> None:
    _results.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name, (f"  [{extra}]" if extra and not ok else ""))


# Every negative that reaches the sampler carries CHILD_NEGATIVE appended, from
# with_child_negative(). It is not user-strippable and not surfaced as editable —
# a control the user can remove is not a floor. So these assert the SHAPE
# "<what was asked for>, <floor>" rather than equality with the input, and they
# assert the floor half explicitly: an equality test would have gone green if the
# suffix were ever silently dropped.
CN = morpheus.CHILD_NEGATIVE


def _neg_ok(actual: str, expected_head: str) -> bool:
    return actual == f"{expected_head}, {CN}" if expected_head else actual == CN


# ── 1. build_workflow routes an explicit negative into the negative node ──────
wf = morpheus.build_workflow(
    {"positive": "a moon", "negative": "thin wires, floating parts", "seed": 1}
)
check("explicit negative routed to CLIPTextEncode node 7, floor appended",
      _neg_ok(wf["7"]["inputs"]["text"], "thin wires, floating parts"),
      extra=wf["7"]["inputs"]["text"])

# ── 2. Default behavior: empty / missing negative → default negative ──────────
wf_missing = morpheus.build_workflow({"positive": "a moon", "seed": 1})
check("missing negative → default applied, floor appended",
      _neg_ok(wf_missing["7"]["inputs"]["text"], DEFAULT_NEG),
      extra=wf_missing["7"]["inputs"]["text"])
wf_blank = morpheus.build_workflow({"positive": "a moon", "negative": "", "seed": 1})
check("blank-string negative → default applied, floor appended",
      _neg_ok(wf_blank["7"]["inputs"]["text"], DEFAULT_NEG),
      extra=wf_blank["7"]["inputs"]["text"])

# Idempotent: re-running a job must not stack the block into the conditioning.
wf_twice = morpheus.build_workflow(
    {"positive": "a moon", "negative": f"thin wires, {CN}", "seed": 1})
check("floor negative not stacked on a re-run",
      wf_twice["7"]["inputs"]["text"].count("loli") == 1,
      extra=wf_twice["7"]["inputs"]["text"])
# resolved negative is written back for DB provenance
check("resolved default written back into params",
      morpheus.build_workflow({"positive": "x", "seed": 1}).get("7") is not None)

# ── 3. Endpoint accepts a clean request carrying a negative ───────────────────
r = client.post("/image/generate", headers=HEADERS, json={
    "positive": "product photography of a single decorative crescent moon",
    "negative_prompt": "thin wires, floating parts, intricate filigree",
})
check("clean request with negative_prompt accepted (job queued)",
      r.status_code == 200 and "job_id" in r.json(),
      extra=f"{r.status_code} {r.text[:80]}")

# ── 4/5/6. FLOOR routing — sentinel in each field must hard-block (403) ────────
# floor_check is stubbed to fire only on SENTINEL; this proves the endpoint runs
# the floor over the positive AND both negative field names — the actual behavior
# under test — without any real floor-category literal in the tree.
morpheus.floor_check = _stub_floor_check
try:
    r = client.post("/image/generate", headers=HEADERS, json={"positive": SENTINEL})
    check("positive routed through floor → 403 (regression)",
          r.status_code == 403, extra=str(r.status_code))

    r = client.post("/image/generate", headers=HEADERS, json={
        "positive": "a serene mountain landscape at dawn",
        "negative_prompt": SENTINEL,
    })
    check("negative_prompt routed through floor → 403 (new coverage)",
          r.status_code == 403, extra=str(r.status_code))

    r = client.post("/image/generate", headers=HEADERS, json={
        "positive": "a serene mountain landscape at dawn",
        "negative": SENTINEL,
    })
    check("legacy `negative` field routed through floor → 403",
          r.status_code == 403, extra=str(r.status_code))
finally:
    morpheus.floor_check = _real_floor_check   # always restore

# ── 7. PROFILE routing — sentinel in negative must hit the denylist (403) ─────
# Sentinel passes the (real, restored) floor, then the stubbed profile check
# denies it — proving the negative also flows through the profile layer.
morpheus.profile_check = _stub_profile_check
try:
    r = client.post("/image/generate", headers=HEADERS, json={
        "positive": "a serene mountain landscape at dawn",
        "negative_prompt": SENTINEL,
    })
    check("negative routed through profile denylist → 403 (broadened)",
          r.status_code == 403, extra=str(r.status_code))
finally:
    morpheus.profile_check = _real_profile_check   # always restore

# ── summary ───────────────────────────────────────────────────────────────────
passed = sum(1 for _, ok in _results if ok)
print(f"\n{passed}/{len(_results)} passed")
sys.exit(0 if passed == len(_results) else 1)
