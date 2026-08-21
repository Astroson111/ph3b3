"""
Tests for Morpheus Edit Mode (img2img) — safety-floor enforcement + rate limit.

Run:  .venv/bin/python tests/test_edit_floor.py
No GPU/ComfyUI needed — run_edit is stubbed, so a flagged prompt/negative is
rejected BEFORE the job is scheduled: no gpu_lock acquisition, no ComfyUI queue.

Floor/profile probes use a neutral SENTINEL + monkeypatch (same technique as
test_morpheus_negative.py): the tests verify the edit endpoint ROUTES each field
through floor_check / profile_check pre-lock, without embedding a real banned
literal in the repo.
"""
import base64
import sys
from io import BytesIO
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))     # for `import server`

import server                                # noqa: E402 — builds FastAPI app + imports morpheus
from fastapi.testclient import TestClient    # noqa: E402
from PIL import Image                        # noqa: E402

morpheus = server.morpheus

# Neutralize the GPU-swap background task. An accepted edit must NOT evict Hermes
# or touch ComfyUI. Mark the job done so stubbed jobs don't linger as "pending"
# and trip the rate limit during the floor tests.
_run_edit_calls = {"n": 0}
async def _spy_run_edit(job_id, params):
    _run_edit_calls["n"] += 1
    if job_id in morpheus.jobs:
        morpheus.jobs[job_id]["state"] = "done"
    return None
morpheus.run_edit = _spy_run_edit

client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}

SENTINEL = "__floor_probe_sentinel__"

_real_floor = morpheus.floor_check
def _stub_floor(text):
    if SENTINEL in (text or ""):
        return "test_probe_category"
    return _real_floor(text)

_real_profile = morpheus.profile_check
def _stub_profile(text, denylist=None):
    if SENTINEL in (text or ""):
        return False   # False = denied
    return _real_profile(text, denylist=denylist)

_results: list[tuple[str, bool]] = []
def check(name: str, ok: bool, extra: str = "") -> None:
    _results.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name, (f"  [{extra}]" if extra and not ok else ""))


def _upload() -> str:
    """Mint a real upload so /image/edit/run reaches the floor stage."""
    buf = BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, "PNG")
    r = client.post("/image/edit/upload", headers=HEADERS,
                    files={"file": ("t.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["upload_id"]


uid = _upload()

# ── 0. sanity: a clean edit is accepted and schedules run_edit ────────────────
_run_edit_calls["n"] = 0
r = client.post("/image/edit/run", headers=HEADERS,
                json={"upload_id": uid, "prompt": "a watercolor mountain", "strength": 0.4})
check("clean edit accepted (job queued, run_edit scheduled once)",
      r.status_code == 200 and "job_id" in r.json() and _run_edit_calls["n"] == 1,
      extra=f"{r.status_code} calls={_run_edit_calls['n']} {r.text[:80]}")

# ── 1/2. FLOOR routing — sentinel in each field must hard-block PRE-LOCK ──────
morpheus.floor_check = _stub_floor
try:
    for label, payload in (
        ("prompt",          {"upload_id": uid, "prompt": SENTINEL, "strength": 0.4}),
        ("negative_prompt", {"upload_id": uid, "prompt": "a calm lake",
                             "negative_prompt": SENTINEL, "strength": 0.4}),
    ):
        _run_edit_calls["n"] = 0
        njobs = len(morpheus.jobs)
        r = client.post("/image/edit/run", headers=HEADERS, json=payload)
        check(f"flagged {label} → 403", r.status_code == 403, extra=str(r.status_code))
        check(f"flagged {label}: run_edit NOT scheduled (pre-lock)", _run_edit_calls["n"] == 0)
        check(f"flagged {label}: no job created", len(morpheus.jobs) == njobs)
        check(f"flagged {label}: gpu_lock never acquired", not morpheus.gpu_lock.locked())
finally:
    morpheus.floor_check = _real_floor   # always restore

# ── 3. PROFILE layer also gates the negative (post-floor, still pre-lock) ─────
morpheus.profile_check = _stub_profile
try:
    _run_edit_calls["n"] = 0
    r = client.post("/image/edit/run", headers=HEADERS,
                    json={"upload_id": uid, "prompt": "a calm lake",
                          "negative_prompt": SENTINEL, "strength": 0.4})
    check("negative routed through profile denylist → 403", r.status_code == 403,
          extra=str(r.status_code))
    check("profile block: run_edit NOT scheduled", _run_edit_calls["n"] == 0)
finally:
    morpheus.profile_check = _real_profile

# ── 4. RATE LIMIT — max N concurrent pending edit jobs per session → 429 ──────
sess = "basic:" + server.AUTH_USER
fakes = []
for i in range(server._EDIT_MAX_PENDING):
    jid = f"__ratetest_{i}__"
    morpheus.jobs[jid] = {"state": "queued", "kind": "edit", "session": sess}
    fakes.append(jid)
try:
    r = client.post("/image/edit/run", headers=HEADERS,
                    json={"upload_id": uid, "prompt": "a river", "strength": 0.4})
    check(f"{server._EDIT_MAX_PENDING} pending → next edit 429", r.status_code == 429,
          extra=str(r.status_code))
finally:
    for jid in fakes:
        morpheus.jobs.pop(jid, None)

_run_edit_calls["n"] = 0
r = client.post("/image/edit/run", headers=HEADERS,
                json={"upload_id": uid, "prompt": "a river", "strength": 0.4})
check("after slots free, edit accepted again", r.status_code == 200, extra=str(r.status_code))

# ── 5. path-traversal guard on upload_id ──────────────────────────────────────
r = client.post("/image/edit/run", headers=HEADERS,
                json={"upload_id": "../../etc/passwd", "prompt": "x", "strength": 0.4})
check("non-hex upload_id rejected (traversal guard) → 400", r.status_code == 400,
      extra=str(r.status_code))

# ── 6. UNAVAILABLE ≠ REFUSED ──────────────────────────────────────────────────
# The source check shares a 16 GB card with ComfyUI and runs PRE-LOCK, so a video
# job holding 8 GB starves llava and the check cannot run. That must read as "try
# again", not as a child-floor refusal on an ordinary photo.
#
# ONLY the vision judge is downed, carrying the real Ollama 500 body. That is
# what VRAM starvation actually does — llava is the model that cannot load,
# hermes3 is already resident. Downing the shared _judge_ex instead would also
# break the TEXT floor gate that runs earlier on the prompt, and that gate's 403
# would mask the very behaviour under test.
_real_vision_ex = morpheus._vision_judge_ex

def _vision_down(raw, question, npred=4):
    return "", "HTTP 500: model runner has unexpectedly stopped"

uid_503 = _upload()
src_503 = server.EDIT_SCRATCH / f"{uid_503}.png"
morpheus._vision_judge_ex = _vision_down
try:
    _run_edit_calls["n"] = 0
    r = client.post("/image/edit/run", headers=HEADERS,
                    json={"upload_id": uid_503, "prompt": "a watercolor mountain",
                          "strength": 0.4})
    check("vision judge down → 503, NOT a 403 floor refusal", r.status_code == 503,
          extra=f"{r.status_code} {r.text[:90]}")
    check("503 body says it is not a refusal",
          "not a refusal" in r.text.lower() and "child" not in r.text.lower(),
          extra=r.text[:90])
    check("503 sets Retry-After", r.headers.get("Retry-After") == "30",
          extra=str(r.headers.get("Retry-After")))
    check("503 KEEPS the upload so the retry it advises is actually possible",
          src_503.exists())
    check("503: run_edit NOT scheduled", _run_edit_calls["n"] == 0)
    check("503: gpu_lock never acquired", not morpheus.gpu_lock.locked())

    # The output path has no "try again" to offer — it must stay fail-CLOSED.
    check("output_minor_check still fail-closed when the judge is down",
          morpheus.output_minor_check(b"whatever") is True)
finally:
    morpheus._vision_judge_ex = _real_vision_ex

# A REAL verdict must still refuse (403) and still destroy the upload — the 503
# path must not have turned every block into a retry. Patched at _minor_check so
# the earlier text gate on the prompt is left completely alone.
_real_minor_check = morpheus._minor_check
uid_403 = _upload()
src_403 = server.EDIT_SCRATCH / f"{uid_403}.png"
morpheus._minor_check = lambda raw: (True, None)   # a verdict, NOT an outage
try:
    _run_edit_calls["n"] = 0
    r = client.post("/image/edit/run", headers=HEADERS,
                    json={"upload_id": uid_403, "prompt": "a watercolor mountain",
                          "strength": 0.4})
    check("real source verdict still → 403 (not softened to 503)", r.status_code == 403,
          extra=f"{r.status_code} {r.text[:90]}")
    check("real verdict still destroys the upload", not src_403.exists())
    check("real verdict: run_edit NOT scheduled", _run_edit_calls["n"] == 0)
finally:
    morpheus._minor_check = _real_minor_check

if __name__ == "__main__":
    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{len(_results)} passed")
    sys.exit(0 if passed == len(_results) else 1)
else:
    # Collected by pytest — see the note in test_triage_gate.py. The module-scope
    # sys.exit() this replaces aborted collection for the whole tests/ directory.
    import pytest

    def test_probe_produced_results():
        assert _results, "the probe body recorded nothing — it did not run"

    @pytest.mark.parametrize("name,ok", _results, ids=[n for n, _ in _results])
    def test_check(name, ok):
        assert ok, name
