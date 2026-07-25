"""
render_verify.py — Ariadne's render-verify loop (skeleton + honest-unverified path).

Ariadne builds a .docx and, until now, nobody looked at it. Source-level
correctness is not page correctness: a role heading can orphan across a page
break, a section can spill onto a third page, a list font can silently fall back
to something else. The document reads fine as a block of text and lands wrong on
the page.

So: render the .docx to PDF via LibreOffice headless, then inspect the render.

┌─ THREE STATES, NOT TWO — the anti-fake-pass rule ────────────────────────────┐
│ PASS       the render was produced AND every check ran AND all of them agree  │
│ FAIL       the render was produced, checks ran, and something is wrong        │
│ UNVERIFIED no render was produced, or a check could not run                   │
│                                                                              │
│ UNVERIFIED is NOT a pass. If LibreOffice is missing, the conversion fails, or │
│ a detector cannot answer, Ariadne says so and hands back the document flagged │
│ unverified. It never reports a clean render it did not actually look at. Any  │
│ future check added here MUST register itself in Report.checks_run, so a check │
│ that silently did not execute can never be mistaken for a check that passed.  │
└──────────────────────────────────────────────────────────────────────────────┘

Artifacts are transient by construction: every render happens inside a
TemporaryDirectory that is removed when the call returns, pass or fail. No
intermediate PDF or raster outlives the request, and nothing about a resume is
written outside the caller's own output path.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("ph3b3.ariadne.render")

# LibreOffice conversion is bounded. Headless soffice can wedge — on a bad font
# cache, a stale lockfile, or a malformed document — and a wedged converter must
# not become a hung resume build. On timeout we report UNVERIFIED, never a pass.
SOFFICE_TIMEOUT_S = 90

# Default page target for a built resume. Overridable per build.
DEFAULT_TARGET_PAGES = 2

STATUS_PASS       = "pass"
STATUS_FAIL       = "fail"
STATUS_UNVERIFIED = "unverified"

# Places to look beyond PATH. A snap/flatpak install does not always land a
# `soffice` on PATH for a service user even when the desktop app works fine.
_SOFFICE_CANDIDATES = (
    "soffice",
    "libreoffice",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
    "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice",
)


@dataclass
class Report:
    """What the render actually showed.

    `checks_run` is load-bearing, not bookkeeping: a caller must be able to tell
    "the orphan detector ran and found nothing" from "the orphan detector never
    ran". Without it, adding a check that quietly no-ops would read as a pass.
    """
    status: str = STATUS_UNVERIFIED
    target_pages: int = DEFAULT_TARGET_PAGES
    pages: int | None = None
    defects: list[str] = field(default_factory=list)   # human-readable, names the problem
    checks_run: list[str] = field(default_factory=list)
    checks_skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # benign observations, NOT defects
    reason: str = ""                                   # why UNVERIFIED, when it is

    @property
    def verified(self) -> bool:
        return self.status in (STATUS_PASS, STATUS_FAIL)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_PASS

    def summary(self) -> str:
        """One line for the report surface and for TTS. Must never imply a clean
        render we did not perform."""
        if self.status == STATUS_UNVERIFIED:
            return f"UNVERIFIED — {self.reason or 'the rendered page was not checked'}"
        pg = f"{self.pages} page{'s' if self.pages != 1 else ''}"
        if self.status == STATUS_PASS:
            return f"render OK — {pg}, {len(self.checks_run)} checks passed"
        return f"render FAILED — {pg}; " + "; ".join(self.defects)


def find_soffice() -> str | None:
    """Absolute path to a usable LibreOffice binary, or None."""
    for cand in _SOFFICE_CANDIDATES:
        p = shutil.which(cand) if os.sep not in cand else (cand if os.path.exists(cand) else None)
        if p:
            return p
    return None


def availability() -> tuple[bool, str]:
    """(available, human reason). The reason is spoken to the user verbatim when
    unavailable, so it says what to do rather than just what failed."""
    exe = find_soffice()
    if not exe:
        return False, ("LibreOffice isn't installed, so I can't render the document to "
                       "check its layout. Install it with: sudo apt install libreoffice")
    return True, exe


@contextmanager
def _workspace():
    """Temp dir for the render, removed on the way out no matter what happens.
    This is the mechanism behind 'no intermediate PDFs beyond the request' — it
    is structural, not a cleanup call someone has to remember."""
    d = tempfile.mkdtemp(prefix="ariadne-render-")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def docx_to_pdf(docx_path: Path, workdir: Path) -> tuple[Path | None, str]:
    """Convert with LibreOffice headless. Returns (pdf_path, error_reason).

    Runs against a THROWAWAY LibreOffice profile inside workdir. Without this,
    soffice uses the desktop user's real profile at ~/.config/libreoffice — which
    means a resume build can fail or hang simply because LibreOffice is already
    open on screen (a single profile does not tolerate two instances). Ariadne
    must not be affected by, or interfere with, someone using LibreOffice for
    their own work at the same time.
    """
    exe = find_soffice()
    if not exe:
        return None, "LibreOffice not installed"
    if not docx_path.exists():
        return None, f"document not found: {docx_path.name}"

    profile = workdir / "loprofile"
    cmd = [
        exe,
        f"-env:UserInstallation=file://{profile}",
        "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nologo",
        "--convert-to", "pdf",
        "--outdir", str(workdir),
        str(docx_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SOFFICE_TIMEOUT_S,
            # Keep LibreOffice out of the service user's real HOME entirely.
            env={**os.environ, "HOME": str(workdir)},
        )
    except subprocess.TimeoutExpired:
        log.warning("[ariadne] soffice timed out after %ss converting %s",
                    SOFFICE_TIMEOUT_S, docx_path.name)
        return None, f"LibreOffice timed out after {SOFFICE_TIMEOUT_S}s"
    except OSError as e:
        return None, f"could not run LibreOffice: {e}"

    pdf = workdir / (docx_path.stem + ".pdf")
    if not pdf.exists():
        # soffice exits 0 on some failures, so trust the artifact, not the code.
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}, no output file"
        log.warning("[ariadne] soffice produced no PDF for %s — %s", docx_path.name, tail)
        return None, f"LibreOffice produced no PDF ({tail})"
    return pdf, ""


# ── Font substitution: which swaps are real defects ──────────────────────────
# A resume built here declares Calibri. Calibri is a Microsoft font and is not on
# a Linux box, so LibreOffice substitutes Carlito — which is METRIC-COMPATIBLE:
# same advance widths, same line breaks, same page count. The page is identical.
#
# So "resolved font != declared font" is the WRONG test. It is true of every
# single build here, and a check that fires on every document would send the
# repair loop through three futile iterations and then warn about a defect that
# does not exist. What matters is whether the substitution MOVED anything.
#
# These are the standard metric-compatible pairs (the reason these clones exist
# at all is drop-in substitution). Anything outside this map genuinely reflows
# the page and IS a defect worth reporting.
_METRIC_COMPATIBLE = {
    "calibri":          {"carlito"},
    "cambria":          {"caladea"},
    "arial":            {"liberation sans", "arimo", "helvetica"},
    "helvetica":        {"liberation sans", "arimo", "arial"},
    "times new roman":  {"liberation serif", "tinos", "times"},
    "courier new":      {"liberation mono", "cousine", "courier"},
}


def _norm_font(name: str) -> str:
    """'Carlito-Bold' / 'ABCDEF+Carlito,Bold' -> 'carlito'. PDF font names carry
    subset prefixes and weight suffixes that say nothing about the family."""
    n = (name or "").split("+")[-1]
    n = re.split(r"[-,]", n)[0]
    return re.sub(r"(MT|PS|Std)$", "", n).strip().lower()


def _is_benign_substitution(declared: str, resolved: str) -> bool:
    d, r = _norm_font(declared), _norm_font(resolved)
    return d == r or r in _METRIC_COMPATIBLE.get(d, set())


def _extract_lines(doc) -> list[dict]:
    """Flatten the render to text lines with the geometry the checks need."""
    out: list[dict] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                top = spans[0]
                out.append({
                    "page":   pno,
                    "text":   "".join(s["text"] for s in spans).strip(),
                    "font":   top["font"],
                    "size":   round(top["size"], 1),
                    "bold":   bool(top["flags"] & 16),        # fitz flag bit 4 = bold
                    "y0":     line["bbox"][1],
                    "y1":     line["bbox"][3],
                    "fonts":  {s["font"] for s in spans},
                })
    return out


def _check_fonts(lines: list[dict], declared: set[str]) -> tuple[list[str], list[str]]:
    """(defects, notes). A benign metric-compatible swap is a NOTE, not a defect —
    reporting it as a defect would make the check fire on every build."""
    resolved = sorted({f for ln in lines for f in ln["fonts"]})
    defects, notes = [], []
    for r in resolved:
        if any(_is_benign_substitution(d, r) for d in declared):
            if not any(_norm_font(d) == _norm_font(r) for d in declared):
                notes.append(f"{r} substituted for {'/'.join(sorted(declared))} "
                             f"(metric-compatible — layout unaffected)")
            continue
        defects.append(f"font fell back to {r}, which is not metric-compatible with "
                       f"{'/'.join(sorted(declared))} — the page will have reflowed")
    return defects, notes


def _check_orphans(lines: list[dict]) -> list[str]:
    """A heading stranded at the foot of a page with its content on the next.

    Two kinds are detectable from the render alone:
      section header — bold and >= 12pt (SUMMARY, EXPERIENCE, ...)
      entry heading  — any line immediately followed by a bullet (a role/project
                       line: 'Senior Engineer - Acme (2019-2024)' above its bullets)
    The second is why this works without needing the source blocks: bullets are
    self-identifying in the render by their leading marker.
    """
    defects = []
    for i, ln in enumerate(lines[:-1]):
        nxt = lines[i + 1]
        is_section = ln["bold"] and ln["size"] >= 12
        is_entry = (not ln["text"].startswith(("•", "-", "*"))
                    and nxt["text"].startswith(("•", "-", "*")))
        if not (is_section or is_entry):
            continue
        if nxt["page"] != ln["page"]:
            kind = "section heading" if is_section else "entry heading"
            defects.append(f"{kind} \"{ln['text'][:40]}\" is orphaned at the foot of "
                           f"page {ln['page'] + 1} — its content starts on page {nxt['page'] + 1}")
    return defects


def _check_overflow(doc, lines: list[dict], bottom_margin_pt: float) -> list[str]:
    """Content extending past the bottom margin. Tolerance of 2pt absorbs
    rounding between the .docx margin and the rendered baseline."""
    defects = []
    for pno in range(doc.page_count):
        limit = doc[pno].rect.height - bottom_margin_pt + 2.0
        for ln in lines:
            if ln["page"] == pno and ln["y1"] > limit:
                defects.append(f"content runs past the bottom margin on page {pno + 1} "
                               f"(\"{ln['text'][:34]}\")")
                break            # one report per page is enough to act on
    return defects


def _declared(docx_path: Path) -> tuple[set[str], float]:
    """Fonts the .docx asks for, and its bottom margin in points. Read from the
    source document, so the check compares the render against what was actually
    requested rather than against a hardcoded assumption."""
    fonts: set[str] = set()
    bottom = 43.2                                     # 0.6in fallback, matches the builder
    try:
        import docx as _docx
        d = _docx.Document(str(docx_path))
        n = d.styles["Normal"].font.name
        if n:
            fonts.add(n)
        for p in d.paragraphs:
            for r in p.runs:
                if r.font.name:
                    fonts.add(r.font.name)
        if d.sections and d.sections[0].bottom_margin is not None:
            bottom = d.sections[0].bottom_margin.pt
    except Exception as e:
        log.warning("[ariadne] could not read declared fonts/margins: %s", e)
    return (fonts or {"Calibri"}), bottom


def _page_count(pdf: Path) -> tuple[int | None, str]:
    """Page count via PyMuPDF. Returns (pages, error)."""
    try:
        import fitz
    except ImportError:
        return None, "PyMuPDF (fitz) not installed — cannot read the render"
    try:
        with fitz.open(str(pdf)) as doc:
            return doc.page_count, ""
    except Exception as e:
        return None, f"could not open the render: {e}"


def verify(docx_path: Path, target_pages: int = DEFAULT_TARGET_PAGES) -> Report:
    """Render the .docx and check it. Never raises — a verifier that throws would
    take the user's document with it, and the document is still worth returning.

    SKELETON: page-count is the only check wired so far. Orphaned-heading, font
    fallback and bottom-margin overflow detection land next; until they do they
    appear in `checks_skipped`, so a report cannot read as fully clean while
    three of its four checks are absent.
    """
    rep = Report(target_pages=target_pages)
    ok, why = availability()
    if not ok:
        rep.status = STATUS_UNVERIFIED
        rep.reason = why
        log.warning("[ariadne] render-verify UNAVAILABLE: %s", why)
        return rep

    try:
        with _workspace() as work:
            pdf, err = docx_to_pdf(Path(docx_path), work)
            if not pdf:
                rep.status = STATUS_UNVERIFIED
                rep.reason = err
                return rep

            pages, perr = _page_count(pdf)
            if pages is None:
                rep.status = STATUS_UNVERIFIED
                rep.reason = perr
                return rep

            rep.pages = pages
            rep.checks_run.append("page_count")
            if pages > target_pages:
                rep.defects.append(
                    f"spills to {pages} pages (target {target_pages})")

            import fitz
            declared, bottom_margin = _declared(Path(docx_path))
            with fitz.open(str(pdf)) as doc:
                lines = _extract_lines(doc)
                if not lines:
                    # A render with no extractable text is not a clean render.
                    rep.status = STATUS_UNVERIFIED
                    rep.reason = "the render contained no readable text"
                    return rep

                fdef, fnotes = _check_fonts(lines, declared)
                rep.defects += fdef
                rep.notes += fnotes
                rep.checks_run.append("font_fallback")

                rep.defects += _check_orphans(lines)
                rep.checks_run.append("orphaned_headings")

                rep.defects += _check_overflow(doc, lines, bottom_margin)
                rep.checks_run.append("margin_overflow")

            rep.status = STATUS_FAIL if rep.defects else STATUS_PASS
            return rep
    except Exception as e:                       # never let a verifier eat the document
        log.exception("[ariadne] render-verify crashed")
        rep.status = STATUS_UNVERIFIED
        rep.reason = f"the layout check itself failed: {e}"
        return rep
