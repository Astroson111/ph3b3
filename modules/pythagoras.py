"""
Pythagoras — sacred geometry drawn from mathematics, never from a model.

WHAT MAKES THIS DIFFERENT FROM MORPHEUS. Every figure here is *constructed*.
There is no prompt, no sampler, no seed that changes the picture, and no GPU:
give the same parameters twice and you get byte-identical SVG. That is the whole
point of the module, and it is why the derivation chain below is written as
derivation rather than as coordinates someone typed in once and eyeballed.

THE CHAIN IS LOAD-BEARING. Vesica -> Seed -> Flower -> Fruit -> Metatron. Each
figure is built from the one before it, so Metatron's thirteen vertices are not
drawn freehand at plausible positions — they ARE the Fruit's thirteen centers,
the same float objects. A Metatron that merely looks right is the failure this
structure exists to prevent, and `test_metatron_vertices_are_the_fruit_centers`
compares them exactly rather than within a tolerance.

NO LOCK, NO CARD. Nothing in the core path imports morpheus, touches gpu_lock or
calls ComfyUI. Rasterisation shells out to Inkscape on the CPU. The only
GPU-adjacent surface is the optional hand-off, where a finished PNG is offered to
Morpheus img2img through the existing generate gate like any other image — this
module never reaches past that gate itself.

SIZES mirror the Morpheus card exactly (512-2048, step 64, free width/height)
because that is what the Morpheus card actually does. The brief called for eight
closed buckets matching a resolution selector; neither exists in this codebase,
and Astro's ruling was to mirror the real behaviour rather than invent a
vocabulary. There is therefore no refuse-by-name path here, deliberately.
"""
from __future__ import annotations

import math
import subprocess
import shutil
from dataclasses import dataclass, field

# ── canvas ───────────────────────────────────────────────────────────────────
# Identical to static/panel.html's morphWidth/morphHeight controls.
SIZE_MIN, SIZE_MAX, SIZE_STEP = 512, 2048, 64
SIZE_DEFAULT = 1024

PHI = (1.0 + math.sqrt(5.0)) / 2.0


class PythagorasError(ValueError):
    """A parameter this module will not draw."""


def check_size(width: int, height: int) -> tuple[int, int]:
    """Mirror of the Morpheus card's constraints, enforced server-side.

    The card clamps with min/max/step attributes, which a hand-rolled POST does
    not have to honour — so the same rule is re-stated here rather than trusted.
    """
    for label, v in (("width", width), ("height", height)):
        if not isinstance(v, int) or isinstance(v, bool):
            raise PythagorasError(f"{label} must be a whole number of pixels")
        if not (SIZE_MIN <= v <= SIZE_MAX):
            raise PythagorasError(
                f"{label} {v} is outside {SIZE_MIN}-{SIZE_MAX} — same range as the "
                f"Morpheus card")
        if v % SIZE_STEP:
            raise PythagorasError(f"{label} {v} is not a multiple of {SIZE_STEP}")
    return width, height


# ── palette ──────────────────────────────────────────────────────────────────
PALETTES: dict[str, dict[str, str]] = {
    "gold":      {"stroke": "#d4af37", "fill": "none"},
    "ink":       {"stroke": "#1a1a1a", "fill": "none"},
    "bone":      {"stroke": "#f2ece1", "fill": "none"},
    "copper":    {"stroke": "#b87333", "fill": "none"},
    "verdigris": {"stroke": "#43b3a0", "fill": "none"},
}
BACKGROUNDS: dict[str, str | None] = {
    "transparent": None,
    "black":       "#000000",
    "white":       "#ffffff",
    "parchment":   "#f4ecd8",
    "midnight":    "#0b1026",
}


@dataclass
class Style:
    palette: str = "gold"
    background: str = "transparent"
    line_weight: float = 2.0

    def __post_init__(self):
        if self.palette not in PALETTES:
            raise PythagorasError(
                f"'{self.palette}' isn't a palette I have — try: "
                f"{', '.join(sorted(PALETTES))}")
        if self.background not in BACKGROUNDS:
            raise PythagorasError(
                f"'{self.background}' isn't a background I have — try: "
                f"{', '.join(sorted(BACKGROUNDS))}")
        if not (0.1 <= float(self.line_weight) <= 40.0):
            raise PythagorasError("line_weight must be between 0.1 and 40")

    @property
    def stroke(self) -> str:
        return PALETTES[self.palette]["stroke"]

    @property
    def bg(self) -> str | None:
        return BACKGROUNDS[self.background]


# ── primitives ───────────────────────────────────────────────────────────────
# Deliberately tiny and immutable. Every generator below emits a list of these
# in DRAW ORDER, which is what makes the animation lane a re-slice of the static
# render rather than a second implementation of it.

@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float

    def svg(self, st: Style) -> str:
        return (f'<circle cx="{self.cx:.4f}" cy="{self.cy:.4f}" r="{self.r:.4f}" '
                f'fill="none" stroke="{st.stroke}" stroke-width="{st.line_weight}"/>')


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float

    def svg(self, st: Style) -> str:
        return (f'<line x1="{self.x1:.4f}" y1="{self.y1:.4f}" '
                f'x2="{self.x2:.4f}" y2="{self.y2:.4f}" '
                f'stroke="{st.stroke}" stroke-width="{st.line_weight}" '
                f'stroke-linecap="round"/>')


@dataclass(frozen=True)
class Polygon:
    pts: tuple[tuple[float, float], ...]
    filled: bool = False

    def svg(self, st: Style) -> str:
        d = " ".join(f"{x:.4f},{y:.4f}" for x, y in self.pts)
        fill = st.stroke + '" fill-opacity="0.18' if self.filled else "none"
        return (f'<polygon points="{d}" fill="{fill}" stroke="{st.stroke}" '
                f'stroke-width="{st.line_weight}" stroke-linejoin="round"/>')


@dataclass(frozen=True)
class Arc:
    """A quarter-turn arc, used by the golden spiral."""
    x1: float
    y1: float
    x2: float
    y2: float
    r: float
    sweep: int = 1

    def svg(self, st: Style) -> str:
        return (f'<path d="M {self.x1:.4f} {self.y1:.4f} '
                f'A {self.r:.4f} {self.r:.4f} 0 0 {self.sweep} '
                f'{self.x2:.4f} {self.y2:.4f}" fill="none" stroke="{st.stroke}" '
                f'stroke-width="{st.line_weight}"/>')


Shape = Circle | Line | Polygon | Arc


@dataclass
class Figure:
    """A constructed figure: shapes in draw order, plus how it was made.

    `notes` carries anything the viewer deserves to know — chiefly whether a
    figure is exact or approximate. It is rendered into the SVG as a comment and
    surfaced by the API, so an approximation can never travel silently.
    """
    name: str
    shapes: list[Shape]
    width: int
    height: int
    style: Style
    params: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    exact: bool = True


# ── the derivation chain ─────────────────────────────────────────────────────
# vesica -> seed -> flower -> fruit -> metatron.
#
# Every one of these is expressed in terms of the hex (triangular) lattice that
# the Flower of Life lives on, because that is what the construction actually
# IS: overlapping circles of equal radius whose centres are one radius apart.
# Working in lattice coordinates rather than in pixels is what lets Metatron's
# vertices be the Fruit's centres exactly, instead of approximately.

def _hex_centers(rings: int, r: float) -> list[tuple[float, float]]:
    """Triangular-lattice points within `rings` rings of the origin, spacing r.

    Returned in rings outward, and within a ring counter-clockwise from angle 0,
    because that ordering IS the construction order the animation lane replays.
    """
    if rings < 0:
        raise PythagorasError("ring_count cannot be negative")
    out = [(0.0, 0.0)]
    for ring in range(1, rings + 1):
        # Walk the ring: start at (ring, 0) in axial coords, then follow the six
        # edge directions. Standard hex-ring traversal.
        q, s = ring, 0
        ring_pts = []
        for direction in range(6):
            dq, ds = _HEX_DIRS[(direction + 2) % 6]
            for _ in range(ring):
                ring_pts.append((q, s))
                q, s = q + dq, s + ds
        for q_, s_ in ring_pts:
            out.append(_axial_to_xy(q_, s_, r))
    return out


# Axial hex directions, counter-clockwise from east.
_HEX_DIRS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))


def _axial_to_xy(q: int, s: int, r: float) -> tuple[float, float]:
    """Axial hex coords -> cartesian, for a lattice of spacing r."""
    return (r * (q + s / 2.0), r * (s * math.sqrt(3.0) / 2.0))


def vesica(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None, **_kw) -> Figure:
    """Two equal circles, each passing through the other's centre.

    The primitive. Everything below is this relation repeated on a lattice.
    """
    width, height = check_size(width, height)
    st = style or Style()
    r = min(width, height) * 0.24
    cx, cy = width / 2.0, height / 2.0
    return Figure(
        name="vesica",
        shapes=[Circle(cx - r / 2.0, cy, r), Circle(cx + r / 2.0, cy, r)],
        width=width, height=height, style=st,
        params={"radius": r},
        notes=["Two circles of equal radius, centres one radius apart."],
    )


def _circles_from_centers(centers, cx, cy, r) -> list[Circle]:
    return [Circle(cx + x, cy + y, r) for x, y in centers]


def seed_of_life(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None, **_kw) -> Figure:
    """Seven circles: the centre plus its six lattice neighbours. Ring 1."""
    width, height = check_size(width, height)
    st = style or Style()
    r = min(width, height) * 0.155
    cx, cy = width / 2.0, height / 2.0
    centers = _hex_centers(1, r)
    return Figure(
        name="seed_of_life",
        shapes=_circles_from_centers(centers, cx, cy, r),
        width=width, height=height, style=st,
        params={"radius": r, "circles": len(centers)},
        notes=["Ring 1 of the hex lattice: 7 circles."],
    )


def flower_of_life(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None,
                   ring_count: int = 2, **_kw) -> Figure:
    """The lattice carried out to `ring_count` rings.

    Circle counts are the centred hexagonal numbers: 1, 7, 19, 37, 61 ...
    """
    width, height = check_size(width, height)
    if not isinstance(ring_count, int) or isinstance(ring_count, bool):
        raise PythagorasError("ring_count must be a whole number")
    if not (1 <= ring_count <= 8):
        raise PythagorasError("ring_count must be between 1 and 8")
    st = style or Style()
    # Keep the whole figure on canvas whatever the ring count.
    r = min(width, height) * 0.44 / (ring_count + 1)
    cx, cy = width / 2.0, height / 2.0
    centers = _hex_centers(ring_count, r)
    return Figure(
        name="flower_of_life",
        shapes=_circles_from_centers(centers, cx, cy, r),
        width=width, height=height, style=st,
        params={"ring_count": ring_count, "radius": r, "circles": len(centers)},
        notes=[f"{ring_count} ring(s): {len(centers)} circles "
               f"(centred hexagonal number)."],
    )


# The Fruit's thirteen. In lattice terms: the centre, the six neighbours at
# distance 2r, and the six at distance 2r*sqrt(3) — NOT the six corner points at
# 4r, which is the usual mistake. Expressed in axial coords so the selection is
# a statement about the lattice rather than a list of pixel positions.
_FRUIT_AXIAL: tuple[tuple[int, int], ...] = (
    (0, 0),
    (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1),          # 6 at 2r
    (1, 1), (-1, 2), (-2, 1), (-1, -1), (1, -2), (2, -1),        # 6 at 2r*sqrt(3)
)


def fruit_of_life(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None, **_kw) -> Figure:
    """Thirteen circles drawn from the Flower — the Fruit."""
    width, height = check_size(width, height)
    st = style or Style()
    r = min(width, height) * 0.115
    cx, cy = width / 2.0, height / 2.0
    centers = fruit_centers(width, height, r)
    return Figure(
        name="fruit_of_life",
        shapes=[Circle(x, y, r) for x, y in centers],
        width=width, height=height, style=st,
        params={"radius": r, "circles": len(centers)},
        notes=["13 circles: centre, 6 at 2r, 6 at 2r*sqrt(3)."],
    )


def fruit_centers(width: int, height: int, r: float) -> list[tuple[float, float]]:
    """The thirteen centres, in absolute canvas coordinates.

    THIS IS THE SHARED SOURCE OF TRUTH. fruit_of_life() draws circles here and
    metatrons_cube() draws lines between these same points — one function, so the
    two figures cannot drift apart. Spacing is 2r because the Fruit's circles are
    tangent, not overlapping.
    """
    cx, cy = width / 2.0, height / 2.0
    out = []
    for q, s in _FRUIT_AXIAL:
        x, y = _axial_to_xy(q, s, 2.0 * r)
        out.append((cx + x, cy + y))
    return out


def metatrons_cube(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None,
                   show_circles: bool = True, **_kw) -> Figure:
    """Every one of the Fruit's thirteen centres joined to every other.

    13 choose 2 = 78 lines. The vertices are not re-derived here: they come from
    fruit_centers(), the same call the Fruit itself makes.
    """
    width, height = check_size(width, height)
    st = style or Style()
    r = min(width, height) * 0.115
    centers = fruit_centers(width, height, r)
    shapes: list[Shape] = []
    if show_circles:
        shapes += [Circle(x, y, r) for x, y in centers]
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            shapes.append(Line(*centers[i], *centers[j]))
    return Figure(
        name="metatrons_cube",
        shapes=shapes,
        width=width, height=height, style=st,
        params={"radius": r, "vertices": len(centers), "show_circles": show_circles,
                "edges": len(centers) * (len(centers) - 1) // 2},
        notes=["Vertices are the Fruit of Life's 13 centres, not redrawn.",
               "78 chords = 13 choose 2."],
    )


# ── golden spiral ────────────────────────────────────────────────────────────

def _fib(n: int) -> list[int]:
    seq = [1, 1]
    while len(seq) < max(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:max(2, n)]


def golden_spiral(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None,
                  turns: int = 8, show_scaffold: bool = True, **_kw) -> Figure:
    """Fibonacci squares laid out in a spiral, with a quarter-arc in each.

    The scaffold is the construction and the arc chain is the curve; both are
    emitted so the toggle hides the scaffold rather than regenerating anything.
    The ratio of successive squares converges on phi, which is what
    `test_golden_spiral_converges_on_phi` measures against math.sqrt(5).
    """
    width, height = check_size(width, height)
    if not isinstance(turns, int) or isinstance(turns, bool):
        raise PythagorasError("turns must be a whole number")
    if not (2 <= turns <= 14):
        raise PythagorasError("turns must be between 2 and 14")
    st = style or Style()
    fib = _fib(turns)

    # Lay the squares out in the classic anticlockwise spiral. Track the bounding
    # box as we go so the whole thing can be fitted to the canvas afterwards
    # rather than guessed at.
    x = y = 0.0
    boxes: list[tuple[float, float, float, int]] = []   # x, y, size, direction
    for i, f in enumerate(fib):
        d = i % 4
        s = float(f)
        if i == 0:
            bx, by = 0.0, 0.0
        elif d == 1:                      # right
            bx, by = x + prev, y
        elif d == 2:                      # down
            bx, by = x + prev - s, y + prev
        elif d == 3:                      # left
            bx, by = x - s, y + prev - s
        else:                             # up
            bx, by = x, y - s
        boxes.append((bx, by, s, d))
        x, y, prev = bx, by, s

    xs = [b[0] for b in boxes] + [b[0] + b[2] for b in boxes]
    ys = [b[1] for b in boxes] + [b[1] + b[2] for b in boxes]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    scale = (min(width, height) * 0.82) / span
    ox = (width - (max(xs) - min(xs)) * scale) / 2.0 - min(xs) * scale
    oy = (height - (max(ys) - min(ys)) * scale) / 2.0 - min(ys) * scale

    def T(px, py):
        return (ox + px * scale, oy + py * scale)

    shapes: list[Shape] = []
    if show_scaffold:
        for bx, by, s, _d in boxes:
            p0, p1 = T(bx, by), T(bx + s, by + s)
            shapes.append(Polygon(((p0[0], p0[1]), (p1[0], p0[1]),
                                   (p1[0], p1[1]), (p0[0], p1[1]))))
    # The arc in each square runs corner to corner, centred on the corner the
    # spiral turns about. Which corner depends on the direction of travel.
    for bx, by, s, d in boxes:
        if d == 0:    a, b = (bx, by + s), (bx + s, by)
        elif d == 1:  a, b = (bx, by), (bx + s, by + s)
        elif d == 2:  a, b = (bx + s, by), (bx, by + s)
        else:         a, b = (bx + s, by + s), (bx, by)
        (ax, ay), (bx2, by2) = T(*a), T(*b)
        shapes.append(Arc(ax, ay, bx2, by2, s * scale, sweep=1))

    return Figure(
        name="golden_spiral", shapes=shapes, width=width, height=height, style=st,
        params={"turns": turns, "show_scaffold": show_scaffold,
                "fibonacci": fib, "ratio": fib[-1] / fib[-2]},
        notes=[f"Fibonacci {fib[0]}..{fib[-1]}; "
               f"last ratio {fib[-1]/fib[-2]:.9f} vs phi {PHI:.9f}."],
    )


# ── platonic solids ──────────────────────────────────────────────────────────
# Vertices are stated; edges and faces are DERIVED. Stating all three invites the
# three to disagree — deriving edges from the minimum vertex distance and faces
# from the convex hull means the Euler check (V - E + F = 2) is a real test of
# the coordinates rather than a test of my arithmetic in a comment.

_IPHI = 1.0 / PHI

_SOLID_VERTS: dict[str, list[tuple[float, float, float]]] = {
    "tetrahedron": [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)],
    "cube": [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
    "octahedron": [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
    "dodecahedron": (
        [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        + [(0, y * _IPHI, z * PHI) for y in (-1, 1) for z in (-1, 1)]
        + [(x * _IPHI, y * PHI, 0) for x in (-1, 1) for y in (-1, 1)]
        + [(x * PHI, 0, z * _IPHI) for x in (-1, 1) for z in (-1, 1)]
    ),
    "icosahedron": (
        [(0, y * 1.0, z * PHI) for y in (-1, 1) for z in (-1, 1)]
        + [(x * 1.0, y * PHI, 0) for x in (-1, 1) for y in (-1, 1)]
        + [(x * PHI, 0, z * 1.0) for x in (-1, 1) for z in (-1, 1)]
    ),
}
SOLIDS = tuple(_SOLID_VERTS)

# Euler's formula for each, as the independent expectation the derivation is
# checked against. Not used to build anything.
SOLID_COUNTS = {
    "tetrahedron":  (4, 6, 4),
    "cube":         (8, 12, 6),
    "octahedron":   (6, 12, 8),
    "dodecahedron": (20, 30, 12),
    "icosahedron":  (12, 30, 20),
}


def solid_edges(name: str) -> list[tuple[int, int]]:
    """Pairs at the minimum vertex separation — the edges, derived not listed."""
    v = _SOLID_VERTS[name]
    d2 = [[sum((a - b) ** 2 for a, b in zip(p, q)) for q in v] for p in v]
    best = min(d2[i][j] for i in range(len(v)) for j in range(len(v)) if i != j)
    tol = best * 1e-6
    return [(i, j) for i in range(len(v)) for j in range(i + 1, len(v))
            if abs(d2[i][j] - best) <= tol]


def solid_faces(name: str) -> list[list[int]]:
    """Faces from the convex hull, with coplanar triangles merged.

    The hull returns triangles, so a dodecahedron would come back as 36 of them
    and draw false diagonals across every pentagon. Grouping by plane and walking
    each group's boundary recovers the real polygon.
    """
    import numpy as np
    from scipy.spatial import ConvexHull
    pts = np.array(_SOLID_VERTS[name], dtype=float)
    hull = ConvexHull(pts)
    groups: dict[tuple, set[int]] = {}
    for simplex, eq in zip(hull.simplices, hull.equations):
        key = tuple(np.round(eq, 6))
        groups.setdefault(key, set()).update(int(i) for i in simplex)
    faces = []
    for key, idx in groups.items():
        ring = list(idx)
        normal = np.array(key[:3])
        centroid = pts[ring].mean(axis=0)
        # Order the face's vertices around its own centroid, in its own plane.
        u = pts[ring[0]] - centroid
        u /= np.linalg.norm(u)
        w = np.cross(normal, u)
        ring.sort(key=lambda i: math.atan2(float(np.dot(pts[i] - centroid, w)),
                                           float(np.dot(pts[i] - centroid, u))))
        faces.append(ring)
    return faces


def _rot(p, ax: float, ay: float):
    x, y, z = p
    ca, sa = math.cos(ax), math.sin(ax)
    y, z = y * ca - z * sa, y * sa + z * ca
    cb, sb = math.cos(ay), math.sin(ay)
    x, z = x * cb + z * sb, -x * sb + z * cb
    return (x, y, z)


def platonic_solid(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None,
                   solid: str = "icosahedron", projection: str = "orthographic",
                   faceted: bool = False, **_kw) -> Figure:
    """One of the five, wireframe or faceted, orthographic or perspective."""
    width, height = check_size(width, height)
    if solid not in _SOLID_VERTS:
        raise PythagorasError(
            f"'{solid}' isn't one of the five — try: {', '.join(SOLIDS)}")
    if projection not in ("orthographic", "perspective"):
        raise PythagorasError("projection must be 'orthographic' or 'perspective'")
    st = style or Style()

    # A fixed, pleasant three-quarter view. Deterministic: no random orientation,
    # because two renders of the same figure must be byte-identical.
    verts = [_rot(p, math.radians(26.0), math.radians(37.0))
             for p in _SOLID_VERTS[solid]]
    span = max(max(abs(c) for c in p) for p in verts) or 1.0
    scale = (min(width, height) * 0.36) / span
    cx, cy = width / 2.0, height / 2.0

    def proj(p):
        x, y, z = p
        if projection == "perspective":
            d = 4.0 * span
            k = d / (d - z)
            x, y = x * k, y * k
        return (cx + x * scale, cy - y * scale)

    pts2 = [proj(p) for p in verts]
    shapes: list[Shape] = []
    if faceted:
        # Painter's algorithm: furthest face first. Back faces are drawn too —
        # this is a diagram, not a solid render, and hiding them would lose the
        # structure the figure exists to show.
        faces = solid_faces(solid)
        faces.sort(key=lambda f: sum(verts[i][2] for i in f) / len(f))
        for f in faces:
            shapes.append(Polygon(tuple(pts2[i] for i in f), filled=True))
    else:
        for i, j in solid_edges(solid):
            shapes.append(Line(*pts2[i], *pts2[j]))

    V, E, F = SOLID_COUNTS[solid]
    return Figure(
        name="platonic_solid", shapes=shapes, width=width, height=height, style=st,
        params={"solid": solid, "projection": projection, "faceted": faceted,
                "vertices": V, "edges": E, "faces": F},
        notes=[f"{solid}: {V} vertices, {E} edges, {F} faces (Euler {V - E + F})."],
    )


# ── SVG + raster ─────────────────────────────────────────────────────────────

def to_svg(fig: Figure) -> str:
    """The canonical output. Deterministic — same params, same bytes."""
    bg = fig.style.bg
    body = [s.svg(fig.style) for s in fig.shapes]
    rect = (f'<rect width="100%" height="100%" fill="{bg}"/>' if bg else "")
    notes = "".join(f"\n  <!-- {n} -->" for n in fig.notes)
    approx = "" if fig.exact else '\n  <!-- APPROXIMATE: see notes -->'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fig.width}" '
        f'height="{fig.height}" viewBox="0 0 {fig.width} {fig.height}">'
        f'{notes}{approx}\n  <title>{fig.name}</title>\n  {rect}\n  '
        + "\n  ".join(body) + "\n</svg>\n"
    )


_INKSCAPE = shutil.which("inkscape")


def to_png(fig: Figure, svg: str | None = None) -> bytes:
    """Rasterise on the CPU via Inkscape. No GPU, no lock, no ComfyUI.

    Inkscape rather than a Python library because no Python rasteriser is
    installed here and Inkscape 1.2.2 already is — it renders alpha correctly,
    which a transparent-PNG hand-off to Apelles depends on.
    """
    if not _INKSCAPE:
        raise PythagorasError(
            "Inkscape is not installed, so I can only give you the SVG. "
            "Install inkscape to export PNG.")
    import tempfile, os
    svg = svg if svg is not None else to_svg(fig)
    with tempfile.TemporaryDirectory() as td:
        sp, pp = os.path.join(td, "f.svg"), os.path.join(td, "f.png")
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(svg)
        try:
            subprocess.run(
                [_INKSCAPE, "--export-type=png", f"--export-filename={pp}",
                 f"--export-width={fig.width}", f"--export-height={fig.height}", sp],
                capture_output=True, timeout=60, check=True)
        except subprocess.TimeoutExpired:
            raise PythagorasError("Inkscape did not finish rasterising within 60s")
        except subprocess.CalledProcessError as e:
            raise PythagorasError(
                f"Inkscape failed: {(e.stderr or b'').decode('utf-8', 'replace')[:160]}")
        with open(pp, "rb") as fh:
            return fh.read()


# ── Sri Yantra — deferred to v1.1, deliberately ──────────────────────────────
# The brief allowed three outcomes: solve it, ship it labelled approximate, or
# defer. Taking the second would mean shipping a figure whose STRUCTURE I cannot
# verify, not merely one whose precision is loose.
#
# The problem: the nine interlocking triangles are not free. Their intersections
# must be concurrent — specific triples of edges have to meet at a single point,
# and there are dozens of such conditions. That makes it a constraint-solving
# problem, not a drawing problem. Solving it needs a reference set of those
# concurrency conditions to solve AGAINST, and I have no trustworthy one here.
#
# I could write a solver, feed it constraints I half-remember, watch the residual
# go to zero, and ship a figure that is beautifully self-consistent and wrong.
# It would look right. That is exactly the failure the brief names: a module that
# draws a sloppy Sri Yantra is worse than one that says "not yet".
#
# For v1.1 this needs: the classical concurrency condition set from a source that
# can be cited, then scipy.optimize.least_squares over the nine triangles' base
# heights and half-widths, with the residual reported in the figure's notes so
# the precision is visible rather than claimed.

SRI_YANTRA_STATUS = "deferred-v1.1"


def sri_yantra(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None, **_kw) -> Figure:
    """Not yet. Refuses by name rather than drawing something plausible."""
    raise PythagorasError(
        "I'm not drawing the Sri Yantra yet. Its nine triangles have to meet at "
        "exact concurrent points — that's a constraint-solving problem, and I "
        "won't ship a version that looks right but isn't. It's deferred to v1.1. "
        f"The other {len(GENERATORS) - 1} figures are ready.")


# ── Penrose tiling (P3 rhombs) ───────────────────────────────────────────────
# Deflation from a starting wheel: the standard, provably correct subdivision.
# Every rhomb is split into smaller rhombs by rules that preserve the matching
# constraint, so the result is a genuine aperiodic tiling rather than a pattern
# that resembles one.

def _deflate(tris, depth):
    """One deflation step on half-rhombs, per the standard P3 rules."""
    for _ in range(depth):
        out = []
        for colour, a, b, c in tris:
            if colour == 0:                      # thin (36-degree) half-rhomb
                p = a + (b - a) / PHI
                out += [(0, c, p, b), (1, p, c, a)]
            else:                                # thick (72-degree) half-rhomb
                q = b + (a - b) / PHI
                r = b + (c - b) / PHI
                out += [(1, r, c, a), (1, q, r, b), (0, r, q, a)]
        tris = out
    return tris


def penrose(width=SIZE_DEFAULT, height=SIZE_DEFAULT, style=None,
            depth: int = 5, seed: str = "sun", **_kw) -> Figure:
    """Aperiodic P3 rhomb tiling, grown by deflation from a ten-fold wheel."""
    width, height = check_size(width, height)
    if not isinstance(depth, int) or isinstance(depth, bool):
        raise PythagorasError("depth must be a whole number")
    if not (1 <= depth <= 7):
        raise PythagorasError("depth must be between 1 and 7 (8+ is millions of tiles)")
    if seed not in ("sun", "star"):
        raise PythagorasError("seed must be 'sun' or 'star'")
    st = style or Style()

    scale = min(width, height) * 0.46
    cx, cy = width / 2.0, height / 2.0
    tris = []
    for i in range(10):
        b = complex(math.cos((2 * i - 1) * math.pi / 10),
                    math.sin((2 * i - 1) * math.pi / 10))
        c = complex(math.cos((2 * i + 1) * math.pi / 10),
                    math.sin((2 * i + 1) * math.pi / 10))
        # Mirror every second triangle, or the wheel is not a valid tiling.
        if (i % 2 == 0) == (seed == "sun"):
            b, c = c, b
        # The wheel's triangles have sides 1, 1, 1/phi: angles 36-72-72, the
        # golden triangle, which is a THIN half-rhomb. Seeding it as thick ran
        # the wrong subdivision rule from the first step and produced eight
        # distinct edge lengths instead of the two a P3 tiling has.
        tris.append((0, complex(0, 0), b, c))
    tris = _deflate(tris, depth)

    # Deflation yields HALF-rhombs. Drawing each as a triangle draws every
    # rhomb's internal diagonal too, which is what makes a naive render look
    # like a mess of thin triangles instead of a rhomb tiling.
    #
    # Which edge is the cut differs by triangle, so rather than guess, use the
    # property that defines P3: every rhomb SIDE has the same length, and the
    # diagonals do not. Keep the modal edge length, drop the rest.
    def key(z1, z2):
        a = (round(z1.real, 6), round(z1.imag, 6))
        b = (round(z2.real, 6), round(z2.imag, 6))
        return (a, b) if a <= b else (b, a)

    edges: dict = {}
    for _colour, a, b, c in tris:
        for z1, z2 in ((a, b), (b, c), (c, a)):
            edges[key(z1, z2)] = abs(z1 - z2)
    from collections import Counter
    modal = Counter(round(L, 6) for L in edges.values()).most_common(1)[0][0]
    shapes = [Line(cx + k[0][0] * scale, cy + k[0][1] * scale,
                   cx + k[1][0] * scale, cy + k[1][1] * scale)
              for k, L in edges.items() if abs(L - modal) < 1e-6]
    rhombs = len(tris) // 2
    return Figure(
        name="penrose", shapes=shapes, width=width, height=height, style=st,
        params={"depth": depth, "seed": seed, "tiles": rhombs,
                "edges": len(shapes)},
        notes=[f"P3 rhombs, {depth} deflations from a {seed} wheel: "
               f"{rhombs} tiles.", "Aperiodic: no translational symmetry."],
    )


GENERATORS: dict[str, callable] = {
    "vesica": vesica,
    "seed_of_life": seed_of_life,
    "flower_of_life": flower_of_life,
    "fruit_of_life": fruit_of_life,
    "metatrons_cube": metatrons_cube,
    "golden_spiral": golden_spiral,
    "platonic_solid": platonic_solid,
    "penrose": penrose,
    "sri_yantra": sri_yantra,          # refuses; listed so it is never silent
}
READY = tuple(k for k in GENERATORS if k != "sri_yantra")


def build(figure: str, **params) -> Figure:
    """The one way in. Unknown figure names are refused by name."""
    if figure not in GENERATORS:
        raise PythagorasError(
            f"'{figure}' isn't a figure I can construct — try: {', '.join(READY)}")
    style = Style(palette=params.pop("palette", "gold"),
                  background=params.pop("background", "transparent"),
                  line_weight=float(params.pop("line_weight", 2.0)))
    return GENERATORS[figure](style=style, **params)


# ── animation: construction order ────────────────────────────────────────────
# The draw order IS the shapes list. A frame is a prefix of it, which is what
# makes "the last frame equals the static render" true by construction rather
# than by two implementations happening to agree.

def frame_count(fig: Figure, steps: int | None = None) -> int:
    return len(fig.shapes) if steps is None else max(1, min(steps, len(fig.shapes)))


def frame(fig: Figure, i: int, steps: int | None = None) -> Figure:
    """Figure as it stood at frame `i` (0-based). The last frame is the whole."""
    n = frame_count(fig, steps)
    if not (0 <= i < n):
        raise PythagorasError(f"frame {i} is outside 0..{n - 1}")
    cut = len(fig.shapes) if i == n - 1 else round(len(fig.shapes) * (i + 1) / n)
    return Figure(name=f"{fig.name}_frame{i:04d}", shapes=fig.shapes[:cut],
                  width=fig.width, height=fig.height, style=fig.style,
                  params={**fig.params, "frame": i, "frames": n},
                  notes=fig.notes, exact=fig.exact)


def frames_svg(fig: Figure, steps: int | None = None, seconds: float = 6.0) -> str:
    """One self-contained animated SVG: each shape appears on its turn.

    SMIL rather than CSS because it survives being opened as a bare file, which
    is how these actually get looked at. Each shape is wrapped in a <g> that
    starts invisible and freezes visible — wrapping avoids editing the shape's
    own markup, so the animated and static renders stay the same geometry.
    """
    per = max(0.01, seconds / max(1, len(fig.shapes)))
    bg = fig.style.bg
    rect = f'<rect width="100%" height="100%" fill="{bg}"/>' if bg else ""
    groups = []
    for k, sh in enumerate(fig.shapes):
        groups.append(
            f'<g opacity="0">{sh.svg(fig.style)}'
            f'<animate attributeName="opacity" from="0" to="1" '
            f'dur="{per:.3f}s" begin="{k * per:.3f}s" fill="freeze"/></g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{fig.width}" '
            f'height="{fig.height}" viewBox="0 0 {fig.width} {fig.height}">\n  '
            f'<title>{fig.name} — construction</title>\n  {rect}\n  '
            + "\n  ".join(groups) + "\n</svg>\n")


def frames_png(fig: Figure, steps: int | None = None) -> list[bytes]:
    """Numbered PNG frames. Frames are intermediates and are NOT watermarked —
    see the stamping note in export()."""
    return [to_png(frame(fig, i, steps)) for i in range(frame_count(fig, steps))]


FFMPEG_HINT = ("ffmpeg -framerate 24 -i frame_%04d.png -c:v libx264 "
               "-pix_fmt yuv420p out.mp4")


# ── watermark ────────────────────────────────────────────────────────────────
# Astro's ruling, 2026-09-17, extending the 2026-09-15 Morpheus ruling:
#
#   PNG exports   visible mark + DCT embed, figure+params in the payload slot
#   SVG exports   visible mark only — SVG is vector, it has no luminance blocks
#                 for a DCT embed to live in. Stated, never implied.
#   frames        unstamped. They are intermediates for assembly, and stamping
#                 each one both corrupts the animation and multiplies the mark.

def provenance(fig: Figure) -> str:
    """What goes in the invisible layer's payload slot, in place of a prompt."""
    bits = [f"{k}={fig.params[k]}" for k in sorted(fig.params)
            if isinstance(fig.params[k], (int, float, str, bool))]
    return f"pythagoras:{fig.name}:" + ",".join(bits)


def _svg_visible_mark(svg: str, text: str, fig: Figure) -> str:
    """The visible mark as a real SVG text element, bottom-right."""
    from xml.sax.saxutils import escape
    px = max(10.0, min(fig.width, fig.height) * 0.022)
    t = (f'<text x="{fig.width - px * 0.6:.1f}" y="{fig.height - px * 0.6:.1f}" '
         f'text-anchor="end" font-family="DejaVu Sans, sans-serif" '
         f'font-size="{px:.1f}" fill="{fig.style.stroke}" fill-opacity="0.55">'
         f'{escape(text)}</text>')
    return svg.replace("</svg>", f"  {t}\n</svg>")


def export(fig: Figure, fmt: str = "svg", stamp: bool | None = None) -> tuple[bytes, str]:
    """Render and stamp. Returns (bytes, mime).

    `stamp=None` follows the global watermark setting, exactly as Morpheus does,
    so the module has no switch of its own to drift out of step with it.
    """
    import watermark
    on = watermark.enabled() if stamp is None else bool(stamp)
    if fmt == "svg":
        svg = to_svg(fig)
        if on:
            svg = _svg_visible_mark(svg, watermark.mark_text(), fig)
        return svg.encode("utf-8"), "image/svg+xml"
    if fmt == "png":
        raw = to_png(fig)
        if on:
            # Both layers. The payload slot carries figure+params where a
            # Morpheus render carries its prompt.
            raw = watermark.stamp_png(raw, provenance(fig))
        return raw, "image/png"
    raise PythagorasError(f"'{fmt}' isn't an export format — try: svg, png")


# ── compose: the closed vocabulary ───────────────────────────────────────────
# Phoebe maps language to figures through THIS TABLE and nothing else. There is
# no fuzzy match and no nearest-figure fallback: an unmapped request comes back
# as a question, because guessing which sacred figure someone meant is exactly
# the kind of confident wrongness this module exists to avoid.

_FIGURE_WORDS: dict[str, str] = {
    "vesica": "vesica", "vesica piscis": "vesica", "mandorla": "vesica",
    "seed of life": "seed_of_life", "seed": "seed_of_life",
    "flower of life": "flower_of_life", "flower": "flower_of_life",
    "fruit of life": "fruit_of_life", "fruit": "fruit_of_life",
    "metatron": "metatrons_cube", "metatron's cube": "metatrons_cube",
    "metatrons cube": "metatrons_cube", "cube of metatron": "metatrons_cube",
    "golden spiral": "golden_spiral", "fibonacci": "golden_spiral",
    "fibonacci spiral": "golden_spiral", "golden ratio": "golden_spiral",
    "penrose": "penrose", "penrose tiling": "penrose", "girih": "penrose",
    "aperiodic tiling": "penrose",
    "sri yantra": "sri_yantra", "shri yantra": "sri_yantra",
    "tetrahedron": "platonic_solid", "cube": "platonic_solid",
    "hexahedron": "platonic_solid", "octahedron": "platonic_solid",
    "dodecahedron": "platonic_solid", "icosahedron": "platonic_solid",
    "platonic solid": "platonic_solid",
}
_SOLID_WORDS = {"tetrahedron": "tetrahedron", "cube": "cube",
                "hexahedron": "cube", "octahedron": "octahedron",
                "dodecahedron": "dodecahedron", "icosahedron": "icosahedron"}
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8}
_PALETTE_WORDS = {"gold": "gold", "golden": "gold", "ink": "ink", "black": "ink",
                  "bone": "bone", "white": "bone", "copper": "copper",
                  "verdigris": "verdigris", "green": "verdigris"}
_BG_WORDS = {"transparent": "transparent", "no background": "transparent",
             "on black": "black", "on white": "white",
             "parchment": "parchment", "midnight": "midnight"}


@dataclass
class Compose:
    figure: str | None
    params: dict
    question: str | None = None


def compose(text: str) -> Compose:
    """Language -> figure + params, or a question. Never a guess."""
    import re as _re
    t = " " + (text or "").lower().strip() + " "
    figure, matched = None, ""
    for phrase in sorted(_FIGURE_WORDS, key=len, reverse=True):
        if _re.search(rf"(?<![a-z]){_re.escape(phrase)}(?![a-z])", t):
            figure, matched = _FIGURE_WORDS[phrase], phrase
            break
    if figure is None:
        return Compose(None, {}, question=(
            "Which figure would you like? I can construct: "
            + ", ".join(READY.__iter__()) + ". I don't guess at geometry."))

    params: dict = {}
    if figure == "platonic_solid":
        for w, s in _SOLID_WORDS.items():
            if _re.search(rf"(?<![a-z]){w}(?![a-z])", t):
                params["solid"] = s
                break
        if "perspective" in t:
            params["projection"] = "perspective"
        if "faceted" in t or "solid" in t and "platonic solid" not in t:
            params["faceted"] = True
    if figure == "flower_of_life":
        m = _re.search(r"(\d+)\s*rings?", t) or _re.search(
            rf"({'|'.join(_NUMBER_WORDS)})\s*rings?", t)
        if m:
            g = m.group(1)
            params["ring_count"] = int(g) if g.isdigit() else _NUMBER_WORDS[g]
    if figure == "golden_spiral":
        m = _re.search(r"(\d+)\s*turns?", t)
        if m:
            params["turns"] = int(m.group(1))
        if "no scaffold" in t or "without scaffold" in t or "hide scaffold" in t:
            params["show_scaffold"] = False
    if figure == "penrose":
        m = _re.search(r"depth\s*(\d+)", t)
        if m:
            params["depth"] = int(m.group(1))
        if "star" in t:
            params["seed"] = "star"
    # Scan for style words with the FIGURE NAME removed, or "golden spiral"
    # silently sets the gold palette and "ink golden spiral" comes back gold.
    style_t = t.replace(matched, " ") if matched else t
    for w, p in _PALETTE_WORDS.items():
        if _re.search(rf"(?<![a-z]){w}(?![a-z])", style_t):
            params["palette"] = p
            break
    for w, b in _BG_WORDS.items():
        if w in style_t:
            params["background"] = b
            break
    return Compose(figure, params)
