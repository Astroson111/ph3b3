"""
Pythagoras — construction correctness, verify suite.

These are not snapshot tests. Every figure here is built from mathematics, so
each claim is checked against the mathematics rather than against a blessed
image: ring counts against the centred hexagonal numbers, Metatron's vertices
against the Fruit's centres by identity, the solids against Euler, the spiral
against phi, the tiling against the golden ratio of its own edge lengths.

The two that matter most:

  test_metatron_vertices_are_the_fruit_centers  — the derivation chain is the
  whole design. A Metatron drawn at plausible positions would pass a visual
  check and fail this one.

  test_no_gpu_lock_anywhere_in_the_core_path    — instrumented, not asserted.
  The core path is imported and exercised with morpheus's lock replaced by one
  that fails the test if it is ever acquired.

Run:  .venv/bin/python -m pytest tests/test_pythagoras.py -v
"""
import io
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import pythagoras as P  # noqa: E402

HAVE_INKSCAPE = P._INKSCAPE is not None
needs_raster = pytest.mark.skipif(not HAVE_INKSCAPE, reason="inkscape not installed")


# ── the derivation chain ─────────────────────────────────────────────────────

@pytest.mark.parametrize("rings,expected", [(1, 7), (2, 19), (3, 37), (4, 61)])
def test_flower_ring_counts_are_the_centred_hexagonal_numbers(rings, expected):
    """1, 7, 19, 37, 61 = 3n(n+1)+1. A lattice that drifts fails here first."""
    f = P.flower_of_life(ring_count=rings)
    assert f.params["circles"] == expected == 3 * rings * (rings + 1) + 1
    assert len(f.shapes) == expected


def test_seed_of_life_is_the_flower_at_one_ring():
    seed = P.seed_of_life()
    flower1 = P.flower_of_life(ring_count=1)
    assert len(seed.shapes) == len(flower1.shapes) == 7


def test_the_fruit_is_thirteen_at_the_two_correct_distances():
    """Centre, six at 2r, six at 2r*sqrt(3) — NOT the six corners at 4r, which
    is the usual way this figure is drawn wrong."""
    r = 100.0
    centers = P.fruit_centers(1024, 1024, r)
    assert len(centers) == 13
    d = sorted({round(math.hypot(x - 512, y - 512), 6) for x, y in centers})
    assert d == [0.0, round(2 * r, 6), round(2 * r * math.sqrt(3), 6)]


def test_metatron_vertices_are_the_fruit_centers():
    """THE derivation test. Not 'close to' — the same values, from one function.

    A Metatron whose 13 points were typed in by hand would look correct and fail
    this, which is exactly why it is written as identity and not as tolerance.
    """
    w = h = 1024
    r = min(w, h) * 0.115
    expected = P.fruit_centers(w, h, r)
    m = P.metatrons_cube(width=w, height=h, show_circles=True)
    drawn = [(s.cx, s.cy) for s in m.shapes if isinstance(s, P.Circle)]
    assert drawn == expected, "Metatron's vertices drifted from the Fruit's centres"

    # And every chord must run between two of those exact points.
    pts = set(expected)
    lines = [s for s in m.shapes if isinstance(s, P.Line)]
    assert len(lines) == 78 == 13 * 12 // 2
    for ln in lines:
        assert (ln.x1, ln.y1) in pts and (ln.x2, ln.y2) in pts


def test_the_fruit_and_metatron_agree_on_their_circles():
    f = P.fruit_of_life()
    m = P.metatrons_cube(show_circles=True)
    fc = [(s.cx, s.cy, s.r) for s in f.shapes]
    mc = [(s.cx, s.cy, s.r) for s in m.shapes if isinstance(s, P.Circle)]
    assert fc == mc


# ── golden spiral ────────────────────────────────────────────────────────────

def test_golden_spiral_converges_on_phi():
    """F(n+1)/F(n) -> phi. Checked against the closed form, not a literal."""
    phi = (1 + math.sqrt(5)) / 2
    assert P.PHI == phi
    prev = None
    for turns in (6, 10, 14):
        ratio = P.golden_spiral(turns=turns).params["ratio"]
        err = abs(ratio - phi)
        assert prev is None or err < prev, "ratio is not converging on phi"
        prev = err
    assert abs(P.golden_spiral(turns=14).params["ratio"] - phi) < 1e-5


def test_the_scaffold_toggle_removes_only_the_scaffold():
    on = P.golden_spiral(turns=8, show_scaffold=True)
    off = P.golden_spiral(turns=8, show_scaffold=False)
    arcs_on = [s for s in on.shapes if isinstance(s, P.Arc)]
    arcs_off = [s for s in off.shapes if isinstance(s, P.Arc)]
    assert arcs_on == arcs_off, "hiding the scaffold moved the curve"
    assert not [s for s in off.shapes if isinstance(s, P.Polygon)]


# ── platonic solids ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", P.SOLIDS)
def test_solid_counts_match_and_satisfy_euler(name):
    """V, E and F are DERIVED from the coordinates; the expected triple is the
    independent check. V - E + F = 2 for every convex polyhedron."""
    V = len(P._SOLID_VERTS[name])
    E = len(P.solid_edges(name))
    F = len(P.solid_faces(name))
    assert (V, E, F) == P.SOLID_COUNTS[name]
    assert V - E + F == 2


@pytest.mark.parametrize("name", P.SOLIDS)
def test_every_edge_of_a_solid_is_the_same_length(name):
    """The defining property of a platonic solid, and a real check on the
    coordinates: a mistyped vertex breaks this before it breaks the counts."""
    v = P._SOLID_VERTS[name]
    lens = {round(math.dist(v[i], v[j]), 9) for i, j in P.solid_edges(name)}
    assert len(lens) == 1, f"{name} has edges of differing length: {lens}"


def test_faceted_and_wireframe_draw_the_same_solid():
    wire = P.platonic_solid(solid="cube", faceted=False)
    face = P.platonic_solid(solid="cube", faceted=True)
    assert len(wire.shapes) == 12 and len(face.shapes) == 6
    assert wire.params["vertices"] == face.params["vertices"] == 8


def test_an_unknown_solid_is_refused_by_name():
    with pytest.raises(P.PythagorasError) as e:
        P.platonic_solid(solid="tesseract")
    assert "tesseract" in str(e.value) and "icosahedron" in str(e.value)


# ── penrose ──────────────────────────────────────────────────────────────────

def test_penrose_edges_are_a_single_length_in_golden_proportion():
    """A P3 tiling has ONE rhomb side length; the triangle bases that are not
    sides sit at phi and 1/phi to it. Getting the seed triangle's type wrong
    produced eight distinct lengths — this is the test that catches that."""
    import math as m
    tris = []
    for i in range(10):
        b = complex(m.cos((2 * i - 1) * m.pi / 10), m.sin((2 * i - 1) * m.pi / 10))
        c = complex(m.cos((2 * i + 1) * m.pi / 10), m.sin((2 * i + 1) * m.pi / 10))
        if i % 2 == 0:
            b, c = c, b
        tris.append((0, complex(0, 0), b, c))
    tris = P._deflate(tris, 4)
    raw = sorted(abs(z1 - z2)
                 for _c, a, b, c in tris
                 for z1, z2 in ((a, b), (b, c), (c, a)))
    # Cluster WITHOUT rounding first: rounding to 6dp before dividing put a
    # 1.4e-6 error into the ratio, which is the test's arithmetic rather than
    # the tiling's geometry.
    lens = [raw[0]]
    for L in raw[1:]:
        if L - lens[-1] > 1e-9:
            lens.append(L)
    assert len(lens) == 3, f"expected 3 edge lengths in a P3 tiling, got {lens}"
    assert abs(lens[1] / lens[0] - P.PHI) < 1e-9
    assert abs(lens[2] / lens[1] - P.PHI) < 1e-9


def test_penrose_depth_grows_the_tiling():
    counts = [P.penrose(depth=d).params["tiles"] for d in (2, 3, 4)]
    assert counts == sorted(counts) and len(set(counts)) == 3


# ── Sri Yantra: labelled or deferred, never silently wrong ───────────────────

def test_sri_yantra_refuses_rather_than_drawing_something_plausible():
    """The brief allowed exactly two outcomes: pass the concurrency tolerance,
    or say not yet. This asserts it does not quietly take a third."""
    assert P.SRI_YANTRA_STATUS == "deferred-v1.1"
    with pytest.raises(P.PythagorasError) as e:
        P.build("sri_yantra")
    msg = str(e.value).lower()
    assert "not" in msg and ("yantra" in msg or "concurrent" in msg)


def test_sri_yantra_is_listed_so_the_refusal_is_reachable():
    """Leaving it out of GENERATORS would make it an 'unknown figure' error,
    which says the wrong thing: it is known, and deliberately not ready."""
    assert "sri_yantra" in P.GENERATORS and "sri_yantra" not in P.READY


# ── sizes: the Morpheus mirror ───────────────────────────────────────────────

def test_sizes_mirror_the_morpheus_card_exactly():
    panel = (REPO / "static" / "panel.html").read_text(encoding="utf-8")
    assert 'id="morphWidth"' in panel
    row = [ln for ln in panel.splitlines() if 'id="morphWidth"' in ln][0]
    assert f'min="{P.SIZE_MIN}"' in row and f'max="{P.SIZE_MAX}"' in row
    assert f'step="{P.SIZE_STEP}"' in row


@pytest.mark.parametrize("w,h", [(500, 1024), (1024, 2100), (1000, 1024)])
def test_out_of_range_or_off_step_sizes_are_refused_by_name(w, h):
    with pytest.raises(P.PythagorasError) as e:
        P.vesica(width=w, height=h)
    assert "width" in str(e.value) or "height" in str(e.value)


def test_an_unknown_figure_is_refused_and_the_real_ones_named():
    with pytest.raises(P.PythagorasError) as e:
        P.build("mandala")
    assert "mandala" in str(e.value)
    assert "flower_of_life" in str(e.value)


def test_unknown_palette_and_background_are_refused_by_name():
    for kw in ({"palette": "neon"}, {"background": "plaid"}):
        with pytest.raises(P.PythagorasError) as e:
            P.build("vesica", **kw)
        assert list(kw.values())[0] in str(e.value)


# ── determinism ──────────────────────────────────────────────────────────────

def test_the_same_parameters_give_byte_identical_svg():
    """No seed, no sampler, no model. This is the module's core promise."""
    a = P.to_svg(P.build("metatrons_cube", width=768, height=768))
    b = P.to_svg(P.build("metatrons_cube", width=768, height=768))
    assert a == b


# ── animation ────────────────────────────────────────────────────────────────

def test_the_last_frame_is_the_static_render():
    """Frames are prefixes of the draw order, so this holds by construction —
    the test exists to keep it that way if someone reimplements either side."""
    for figure in ("seed_of_life", "metatrons_cube", "golden_spiral"):
        fig = P.build(figure)
        last = P.frame(fig, P.frame_count(fig) - 1)
        assert len(last.shapes) == len(fig.shapes)
        assert P.to_svg(last).replace(last.name, fig.name) == P.to_svg(fig)


def test_frames_are_monotonic_and_reconstruct_the_figure():
    fig = P.build("seed_of_life")
    n = P.frame_count(fig, steps=4)
    counts = [len(P.frame(fig, i, steps=4).shapes) for i in range(n)]
    assert counts == sorted(counts) and counts[-1] == len(fig.shapes)


def test_the_animated_svg_animates_every_shape_once():
    fig = P.build("seed_of_life")
    assert P.frames_svg(fig).count("<animate") == len(fig.shapes)


def test_the_ffmpeg_step_is_announced_not_hidden():
    assert "ffmpeg" in P.FFMPEG_HINT and "framerate" in P.FFMPEG_HINT


# ── compose: mapped lands, unmapped asks ─────────────────────────────────────

@pytest.mark.parametrize("phrase,figure,params", [
    ("flower of life with five rings", "flower_of_life", {"ring_count": 5}),
    ("five ring flower of life", "flower_of_life", {"ring_count": 5}),
    ("metatron's cube", "metatrons_cube", {}),
    ("gold vesica on transparent", "vesica",
     {"palette": "gold", "background": "transparent"}),
    ("faceted dodecahedron", "platonic_solid",
     {"solid": "dodecahedron", "faceted": True}),
    ("penrose depth 3", "penrose", {"depth": 3}),
])
def test_mapped_phrases_land_exactly(phrase, figure, params):
    c = P.compose(phrase)
    assert c.figure == figure
    for k, v in params.items():
        assert c.params.get(k) == v, f"{phrase!r}: {k} was {c.params.get(k)!r}"


@pytest.mark.parametrize("phrase", [
    "draw me a tesseract", "something spiritual", "a cool geometric thing",
    "the tree of life", "a mandala",
])
def test_unmapped_phrases_ask_and_never_guess(phrase):
    """No nearest-match. Guessing which sacred figure someone meant is the
    failure this table exists to prevent."""
    c = P.compose(phrase)
    assert c.figure is None and c.question
    assert "which figure" in c.question.lower()


def test_the_figure_name_does_not_leak_into_the_palette():
    """'golden spiral' set the gold palette, so 'ink golden spiral' came back
    gold. The figure phrase is stripped before style words are scanned."""
    assert P.compose("ink golden spiral").params.get("palette") == "ink"
    assert "palette" not in P.compose("golden spiral 10 turns").params


def test_compose_output_actually_builds():
    for phrase in ("flower of life with three rings", "faceted cube",
                   "penrose depth 3 star", "copper metatron on midnight"):
        c = P.compose(phrase)
        assert P.build(c.figure, **c.params)


# ── no GPU, no lock, no ComfyUI ──────────────────────────────────────────────

def test_the_core_path_never_acquires_the_gpu_lock(monkeypatch):
    """Instrumented, not asserted. morpheus.gpu_lock is replaced with a lock
    that fails this test the moment anything tries to take it, and then the
    whole generator set is built and serialised."""
    import morpheus

    class Tripwire:
        def acquire(self, *a, **k):
            raise AssertionError("Pythagoras acquired the GPU lock")
        async def __aenter__(self):
            raise AssertionError("Pythagoras acquired the GPU lock")
        async def __aexit__(self, *a):
            return False
        def locked(self):
            raise AssertionError("Pythagoras inspected the GPU lock")

    monkeypatch.setattr(morpheus, "gpu_lock", Tripwire())
    for name in P.READY:
        fig = P.build(name)
        P.to_svg(fig)
        P.frames_svg(fig)


def test_the_module_does_not_import_morpheus_or_comfy_at_all():
    """Checked as CODE, not as text.

    The first version of this grepped the source and tripped on the module's own
    docstring, which names gpu_lock while explaining that it never touches it. A
    check that fires on prose is a check that gets loosened until it stops
    meaning anything, so this walks the AST instead: real imports, real
    attribute access, and string literals that look like endpoints.
    """
    import ast
    tree = ast.parse((REPO / "modules" / "pythagoras.py").read_text(encoding="utf-8"))
    banned_mod = {"morpheus", "amphion", "torch", "comfy", "orpheus"}
    # Docstrings are documentation, not reachable code — and this module's own
    # docstring names what it refuses to touch.
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            body = getattr(n, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                assert a.name.split(".")[0] not in banned_mod, f"imports {a.name}"
        elif isinstance(n, ast.ImportFrom):
            assert (n.module or "").split(".")[0] not in banned_mod, \
                f"imports from {n.module}"
        elif isinstance(n, ast.Attribute):
            assert n.attr not in ("gpu_lock", "comfy_free", "evict_hermes",
                                  "ensure_comfy_up"), f"touches {n.attr}"
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
              and id(n) not in docstrings):
            low = n.value.lower()
            for bad in ("127.0.0.1:8188", "/prompt", "comfy"):
                assert bad not in low, f"string literal reaches ComfyUI: {n.value[:50]}"


def test_rasterising_shells_out_to_a_cpu_renderer():
    src = (REPO / "modules" / "pythagoras.py").read_text(encoding="utf-8")
    assert "inkscape" in src.lower()


# ── raster + watermark ───────────────────────────────────────────────────────
# Astro's ruling, 2026-09-17: PNG gets both layers with figure+params in the
# payload slot; SVG gets the visible mark only, because a vector file has no
# luminance blocks for a DCT embed to live in; frames stay unstamped.

@needs_raster
@pytest.mark.parametrize("w,h", [(512, 512), (1024, 1024), (768, 1024), (1920, 1088)])
def test_svg_and_png_agree_on_size_at_every_bucket(w, h):
    fig = P.build("seed_of_life", width=w, height=h)
    from PIL import Image
    im = Image.open(io.BytesIO(P.to_png(fig)))
    assert im.size == (w, h)
    assert f'width="{w}"' in P.to_svg(fig) and f'height="{h}"' in P.to_svg(fig)


@needs_raster
def test_transparent_really_is_transparent():
    """Alpha is measured, not assumed — this is what the Apelles hand-off needs."""
    import numpy as np
    from PIL import Image
    fig = P.build("vesica", width=512, height=512, background="transparent")
    a = np.array(Image.open(io.BytesIO(P.to_png(fig))).convert("RGBA"))
    assert a[..., 3].min() == 0, "no fully transparent pixel in transparent mode"
    assert a[0, 0, 3] == 0, "the corner is not transparent"
    assert (a[..., 3] > 0).any(), "the figure did not render at all"


@needs_raster
def test_an_opaque_background_has_no_transparent_pixel():
    import numpy as np
    from PIL import Image
    fig = P.build("vesica", width=512, height=512, background="black")
    a = np.array(Image.open(io.BytesIO(P.to_png(fig))).convert("RGBA"))
    assert a[..., 3].min() == 255


@needs_raster
def test_the_png_export_carries_both_watermark_layers():
    import watermark
    fig = P.build("metatrons_cube", width=512, height=512, background="black")
    raw, mime = P.export(fig, "png", stamp=True)
    assert mime == "image/png"
    v = watermark.verify_bytes(raw)
    assert v.present is True, "the invisible layer did not survive its own export"
    assert v.confidence > 0.6, f"embed recovered but weakly ({v.confidence:.3f})"
    # And the slot really holds THIS figure, not a leftover or a blank.
    import hashlib
    want = hashlib.sha256(P.provenance(fig).encode()).hexdigest()
    assert want.startswith(v.prompt_sha256[:8]), \
        "the payload is not this figure's provenance"
    # The control: an unstamped render of the same figure must read as absent,
    # or this test would pass on an embed that was never written.
    assert watermark.verify_bytes(P.to_png(fig)).present is False


def test_the_svg_export_carries_the_visible_mark_only():
    """And says so. Claiming a stamp SVG cannot hold would be the dishonest
    version of this ruling."""
    import watermark
    fig = P.build("vesica", width=512, height=512)
    raw, mime = P.export(fig, "svg", stamp=True)
    svg = raw.decode()
    assert mime == "image/svg+xml"
    assert watermark.mark_text() in svg and "<text" in svg
    src = (REPO / "modules" / "pythagoras.py").read_text(encoding="utf-8")
    assert "no luminance blocks" in src, \
        "the SVG limitation is not written down where the next reader will see it"


def test_the_provenance_slot_carries_figure_and_params_not_a_prompt():
    fig = P.build("flower_of_life", ring_count=3)
    p = P.provenance(fig)
    assert p.startswith("pythagoras:flower_of_life:")
    assert "ring_count=3" in p


def test_stamping_follows_the_global_setting_with_no_switch_of_its_own():
    src = (REPO / "modules" / "pythagoras.py").read_text(encoding="utf-8")
    assert "watermark.enabled()" in src
    for smell in ("PYTHAGORAS_WATERMARK", "_watermark_on =", "stamp_enabled ="):
        assert smell not in src, f"pythagoras has its own watermark switch: {smell}"


@needs_raster
def test_frames_are_not_watermarked():
    """Stamping each frame both multiplies the mark and corrupts the animation."""
    import watermark
    fig = P.build("seed_of_life", width=512, height=512, background="black")
    frames = P.frames_png(fig, steps=3)
    assert len(frames) == 3
    assert watermark.verify_bytes(frames[-1]).present is False, \
        "an intermediate frame was stamped"


def test_an_unknown_export_format_is_refused_by_name():
    with pytest.raises(P.PythagorasError) as e:
        P.export(P.build("vesica"), "gif")
    assert "gif" in str(e.value) and "svg" in str(e.value)


def test_the_spiral_arcs_form_one_continuous_curve():
    """Each quarter-arc must start exactly where the last one ended.

    A spiral assembled from arcs that merely sit in the right squares looks
    almost right at a glance and is visibly broken when you zoom in — and it is
    the kind of error a contact sheet does not catch.
    """
    fig = P.golden_spiral(turns=9, show_scaffold=False)
    arcs = [s for s in fig.shapes if isinstance(s, P.Arc)]
    assert len(arcs) == 9
    for a, b in zip(arcs, arcs[1:]):
        assert math.isclose(a.x2, b.x1, abs_tol=1e-9), "spiral breaks in x"
        assert math.isclose(a.y2, b.y1, abs_tol=1e-9), "spiral breaks in y"


def test_each_spiral_arc_radius_matches_its_fibonacci_square():
    """The arc in each square is a quarter of a circle whose radius is that
    square's side — the property that makes it a Fibonacci spiral at all."""
    fig = P.golden_spiral(turns=10, show_scaffold=True)
    arcs = [s for s in fig.shapes if isinstance(s, P.Arc)]
    squares = [s for s in fig.shapes if isinstance(s, P.Polygon)]
    assert len(arcs) == len(squares) == 10
    for arc, sq in zip(arcs, squares):
        xs = [p[0] for p in sq.pts]
        side = max(xs) - min(xs)
        assert math.isclose(arc.r, side, rel_tol=1e-9)
