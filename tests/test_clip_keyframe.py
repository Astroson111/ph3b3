"""Keyframe → motion: the approval binds, the aspect is one, the card is checked.

WHY THE GATE EXISTS, in numbers measured on this box (2026-09-26):

    the motion stage is 12m17s, of which 11m12s (91%) is sampling with BOTH
    Wan 2.2 A14B experts reporting "0.00 MB loaded, 10423.12 MB offloaded"

So an unapproved keyframe is twelve minutes of GPU spent on a picture nobody
chose. Every rule below follows from that:

  * no auto-proceed — Animate is a separate press, and the server refuses a frame
    that is not the approved one
  * approval binds to ONE job id; a re-roll invalidates it at the moment the new
    render is registered, not when it finishes
  * one aspect for both stages — a keyframe at 1024x1024 animated by a graph
    hardcoded to 816x1088 is a crop or a stretch of the single frame the whole
    clip is built from, and text does not survive that
  * the card is confirmed free by the DRIVER after the ComfyUI free, because two
    stages (Qwen peaks 14,467 MiB, Wan peaks 15,684 MiB) do not fit in 16,380 MiB
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "modules"))

import keyframe as kf     # noqa: E402
import morpheus           # noqa: E402

PANEL = (ROOT / "static" / "panel.html").read_text(encoding="utf-8")
SERVER = (ROOT / "agent" / "server.py").read_text(encoding="utf-8")

A = "a" * 36
B = "b" * 36


@pytest.fixture(autouse=True)
def _clean():
    kf._current.clear()
    kf._origin.clear()
    yield
    kf._current.clear()
    kf._origin.clear()


# ── approval binds to one exact id ───────────────────────────────────────────
def test_a_fresh_keyframe_is_not_approved():
    kf.register("s", A)
    assert kf.is_approved(A) is False
    assert kf.refuse_reason(A) == "that keyframe has not been approved yet"


def test_approving_the_wrong_id_is_refused():
    kf.register("s", A)
    assert kf.approve("s", B) is False
    assert kf.is_approved(B) is False


def test_approval_without_an_image_check_does_not_count():
    """The verdict travels with the approval. An image the floor never looked at
    cannot be animated even if approve() is called directly."""
    kf.register("s", A)
    assert kf.approve("s", A) is True          # returns True, but…
    assert kf.is_approved(A) is False          # …it does not satisfy the gate
    assert "without the image being checked" in kf.refuse_reason(A)


def test_a_checked_approval_counts():
    kf.register("s", A)
    kf.approve("s", A, image_checked=True)
    assert kf.is_approved(A) is True
    assert kf.refuse_reason(A) is None


# THE RULED VERIFY: re-roll, then approve the old id → rejected.
def test_a_reroll_invalidates_the_previous_approval():
    kf.register("s", A)
    kf.approve("s", A, image_checked=True)
    assert kf.is_approved(A) is True

    kf.register("s", B)                        # the re-roll
    assert kf.is_approved(A) is False, "the old frame is still animatable"
    assert "replaced by a newer one" in kf.refuse_reason(A)


def test_approving_the_old_id_after_a_reroll_is_refused():
    kf.register("s", A)
    kf.approve("s", A, image_checked=True)
    kf.register("s", B)
    assert kf.approve("s", A, image_checked=True) is False, \
        "consent to the first picture was accepted for the second"
    assert kf.is_approved(A) is False


def test_the_new_frame_can_be_approved_normally():
    kf.register("s", A)
    kf.register("s", B)
    assert kf.approve("s", B, image_checked=True) is True
    assert kf.is_approved(B) is True


def test_an_ordinary_gallery_render_is_not_governed_here():
    """Animating an old gallery image must keep working — it was floor-passed at
    creation and has its own provenance rule."""
    assert kf.is_keyframe("f" * 36) is False
    assert kf.refuse_reason("f" * 36) is None


def test_one_session_cannot_approve_another_sessions_frame():
    kf.register("s1", A)
    assert kf.approve("s2", A, image_checked=True) is False
    assert kf.is_approved(A) is False


def test_the_counters_separate_the_three_outcomes():
    a, b, c = (kf.APPROVED_COUNT[0], kf.REROLL_INVALIDATED_COUNT[0],
               kf.REJECTED_COUNT[0])
    kf.register("s", A)
    kf.approve("s", B, image_checked=True)     # rejected
    kf.approve("s", A, image_checked=True)     # approved
    kf.register("s", B)                        # invalidates
    assert kf.APPROVED_COUNT[0] == a + 1
    assert kf.REROLL_INVALIDATED_COUNT[0] == b + 1
    assert kf.REJECTED_COUNT[0] == c + 1


def test_approval_does_not_survive_a_restart():
    """State is in memory on purpose: an approval that outlived a restart would
    be a consent token with nobody behind it."""
    src = (ROOT / "modules" / "keyframe.py").read_text(encoding="utf-8")
    for persist in ("open(", "json.dump", "sqlite3", "pickle", "Path("):
        assert persist not in src, f"keyframe state is persisted via {persist!r}"


# ── one aspect, both stages ──────────────────────────────────────────────────
def test_the_default_aspect_is_vertical_as_ruled():
    assert morpheus.DEFAULT_CLIP_ASPECT == "9:16"
    assert morpheus.clip_dims(None) == (720, 1280)


@pytest.mark.parametrize("name,dims", list(morpheus.CLIP_ASPECTS.items()))
def test_every_aspect_fits_the_wan_latent(name, dims):
    w, h = dims
    assert w % 16 == 0 and h % 16 == 0, f"{name} is {w}x{h}, not a multiple of 16"


def test_the_i2v_graph_takes_its_size_from_the_aspect():
    """wan_i2v.json hardcodes 816x1088 (3:4). A 9:16 keyframe animated by that
    graph is a crop, on the one frame the clip is built from."""
    wf = morpheus.build_video_workflow({"preset": "wan-fast", "positive": "x",
                                        "seed": 1, "aspect": "9:16",
                                        "_comfy_image": "k.png"})
    sized = [(n["class_type"], n["inputs"]["width"], n["inputs"]["height"])
             for n in wf.values() if "width" in n.get("inputs", {})]
    assert sized, "no size node found in the i2v graph"
    for _ct, w, h in sized:
        assert (w, h) == (720, 1280), f"graph still at {w}x{h}"


def test_the_t2v_graph_follows_the_same_setting():
    wf = morpheus.build_video_workflow({"preset": "wan-fast", "positive": "x",
                                        "seed": 1, "aspect": "16:9"})
    for n in wf.values():
        ins = n.get("inputs", {})
        if "width" in ins:
            assert (ins["width"], ins["height"]) == (1280, 720)


def test_ltx_keeps_its_own_resolution():
    """LTX's graph has its own constraint (32) and is not part of this flow."""
    wf = morpheus.build_video_workflow({"preset": "ltx-fast", "positive": "x",
                                        "seed": 1, "aspect": "9:16"})
    sizes = [(n["inputs"]["width"], n["inputs"]["height"])
             for n in wf.values() if "width" in n.get("inputs", {})]
    assert (720, 1280) not in sizes, "the LTX graph was rewritten to a Wan aspect"


def test_a_frame_that_matches_no_aspect_is_recognised():
    assert morpheus.aspect_of(720, 1280) == "9:16"
    assert morpheus.aspect_of(1024, 1024) is None, \
        "a square render must not pass as a clip aspect"


# ── the card ─────────────────────────────────────────────────────────────────
# The check-and-refuse gate (assert_vram_for_wan / WAN_NEED_MB) was retired on
# 2026-10-07: clips now take the card through the same Herakles lease as images.
# Its guarantees — fail loud, never start blind, no job queued onto a card that
# can't hold it, the check after the free — live in tests/test_clip_lease.py.


# ── the server wires the three surfaces ──────────────────────────────────────
def _code_only(text):
    """Strip comment lines. Checked four times in this suite now: a test that
    greps raw source fails on the comment explaining the thing it checks."""
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_the_keyframe_prompt_is_passed_verbatim():
    i = SERVER.index("async def morpheus_keyframe(")
    body = _code_only(SERVER[i:SERVER.index("async def morpheus_keyframe_approve")])
    assert '"positive": positive,' in body, "the keyframe prompt is rewritten"
    for rewriter in ("enhance", "rewrite", "expand_prompt", "_improve"):
        assert rewriter not in body, f"the prompt passes through {rewriter!r}"


def test_the_floor_runs_on_the_keyframe_prompt():
    i = SERVER.index("async def morpheus_keyframe(")
    body = SERVER[i:SERVER.index("async def morpheus_keyframe_approve")]
    assert "_morpheus_floor_gate" in body
    assert body.index("_morpheus_floor_gate") < body.index("create_job()"), \
        "the job is created before the prompt is judged"


def test_the_floor_runs_on_the_keyframe_image_at_approval():
    i = SERVER.index("async def morpheus_keyframe_approve")
    body = SERVER[i:SERVER.index("async def morpheus_keyframe_current")]
    assert "source_minor_check" in body, "the image itself is never checked"
    assert "SafetyCheckUnavailable" in body, \
        "a check that could not run would read as a refusal"
    assert body.index("source_minor_check") < body.index("keyframe.approve"), \
        "approval binds before the image is judged"


def test_registration_happens_before_the_render_is_queued():
    """A re-roll must invalidate the old approval immediately, not when the new
    render lands — otherwise the old frame stays animatable in between."""
    i = SERVER.index("async def morpheus_keyframe(")
    body = SERVER[i:SERVER.index("async def morpheus_keyframe_approve")]
    assert body.index("keyframe.register") < body.index("add_task(morpheus.run_generation")


def test_the_video_route_consults_the_binding_before_using_the_path():
    """The binding is checked before the frame is resolved for ComfyUI — and,
    since 2026-09-27, before a job even exists to be wedged by the refusal."""
    body = _video_route_code()
    assert "keyframe.refuse_reason" in body
    assert body.index("keyframe.refuse_reason") < body.index("_resolved_src = src_path"), \
        "the frame is resolved for ComfyUI before the approval is checked"
    assert body.index("keyframe.refuse_reason") < body.index("prepare_video_source"), \
        "the frame is prepared for ComfyUI before the approval is checked"


def test_the_clip_records_its_keyframe():
    assert "keyframe_job_id=_kf_link" in SERVER
    assert '"keyframe_job_id": _kf_link' in SERVER, \
        "the response does not tell the gallery which frame this clip came from"


# ── the panel cannot auto-proceed ────────────────────────────────────────────
def test_rendering_a_keyframe_does_not_animate_anything():
    i = PANEL.index("async function kfRender()")
    body = PANEL[i:PANEL.index("async function kfCheck()")]
    assert "generateClip" not in body, \
        "rendering a keyframe starts the 12-minute stage by itself"


def test_animating_goes_through_approval_first():
    i = PANEL.index("async function kfApproveAndAnimate()")
    body = PANEL[i:PANEL.index("async function kfUpload(")]
    assert body.index("keyframe/approve") < body.index("generateClip"), \
        "the clip starts before the approval is confirmed"
    assert "if (!r.ok)" in body, "a refused approval still animates"


def test_the_panel_has_both_buttons_and_an_upload():
    for el in ("morphKfRender", "morphKfReroll", "morphKfApprove", "morphKfUpload",
               "morphKfAspect", "morphKfPrompt"):
        assert f'id="{el}"' in PANEL, f"{el} is missing from the panel"


def test_the_aspect_is_sent_with_both_stages():
    i = PANEL.index("async function kfRender()")
    render = PANEL[i:PANEL.index("async function kfCheck()")]
    assert "aspect: kfEl('morphKfAspect').value" in render
    i2 = PANEL.index("async function kfApproveAndAnimate()")
    animate = PANEL[i2:PANEL.index("async function kfUpload(")]
    assert "aspect: kfEl('morphKfAspect').value" in animate


# ── a refusal must not leave a ghost job holding the card ────────────────────
# Found 2026-09-27 by the end-to-end run. The refusal worked; what followed did
# not. create_job() ran above every source check, so a refused animate left
# {"state": "queued"} forever and Herakles then declined the NEXT render:
#
#   Not while Morpheus render cf682c8a (queued) is using the card — evicting
#   under it would break it.
#
# i.e. exercising the safety refusal wedged the machine until the ghost was
# cancelled by hand. The id is only needed for prepare_video_source's filename,
# so nothing is minted until the request is known good.
def _video_route_code():
    """The route's CODE, comments stripped — they mention the very calls these
    tests order, and a raw index() finds the comment first."""
    i = SERVER.index("async def morpheus_video(")
    j = SERVER.index("async def morpheus_job_status", i)
    return _code_only(SERVER[i:j])


def test_the_job_is_created_after_every_refusal_path():
    body = _video_route_code()
    create = body.index("job_id = morpheus.create_job()")
    for guard in ("keyframe.refuse_reason",
                  '"invalid source_job_id"',
                  '"source render not found"',
                  '"invalid source_upload_id"',
                  "source_minor_check"):
        assert body.index(guard) < create, \
            f"{guard} can refuse AFTER the job exists, leaving it queued forever"


def test_the_source_is_prepared_only_once_a_job_exists():
    body = _video_route_code()
    assert body.index("job_id = morpheus.create_job()") < body.index("prepare_video_source"), \
        "the source is prepared with an id that does not exist yet"


def test_only_one_job_is_created_in_the_video_route():
    assert _video_route_code().count("morpheus.create_job()") == 1
