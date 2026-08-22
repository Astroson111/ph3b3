#!/usr/bin/env python3
"""Prometheus ingest — corpus → FTS5 index.

Reuses Kadmos for extraction (PyMuPDF, tesseract fallback); Prometheus only
chunks, filters, and indexes. No network, no GPU, no model.

    ./ingest.py              rebuild the whole index
    ./ingest.py --source ID  re-ingest one source
    ./ingest.py --dry-run    report what would be indexed, write nothing

THE BLACKLIST IS ENFORCED HERE, NOT AT QUERY TIME. A blacklisted section never
enters index.db at all, so no retrieval — however phrased, however clever — can
surface it. Filtering at answer time would leave the text sitting in the index
waiting for a query that slips past. The floor still runs on every output; this
is the layer underneath it.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "modules"))

import prometheus                                    # noqa: E402
from prometheus import blacklist_headings, is_blacklisted, load_manifest  # noqa: E402

CHUNK_TARGET_CHARS = 3200          # ~800 tokens
CHUNK_OVERLAP_CHARS = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    source_id   TEXT NOT NULL,
    source_name TEXT NOT NULL,
    category    TEXT,
    priority    INTEGER DEFAULT 9,
    page        INTEGER,
    heading     TEXT,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, heading, content='chunks', content_rowid='id', tokenize='porter'
);
"""

# A line that looks like a section heading: short, not sentence-punctuated, and
# either titlecase/uppercase or numbered. Deliberately conservative — a missed
# heading costs chunking quality, a false one could mislabel a blacklist match.
_HEADING = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*)[.)]?\s+)?([A-Z][^.!?]{2,70})\s*$"
)


def detect_heading(line: str) -> str | None:
    m = _HEADING.match(line or "")
    if not m:
        return None
    text = m.group(1).strip()
    if len(text.split()) > 12:
        return None
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return None
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    return text if upper_ratio > 0.25 else None


def chunk_pages(pages, patterns):
    """pages: iterable of (page_number, text). Yields dicts ready for insert.

    Splits on headings where a document has them, falling back to fixed windows
    with overlap where it does not. Carries the current heading forward across
    pages, so a section spanning a page break is still attributed — and still
    blacklisted — correctly.
    """
    out, skipped = [], []
    heading = ""
    buf, buf_page = [], None

    def flush():
        """Close the current section: blacklist it, or window it into `out`."""
        nonlocal buf
        body = "\n".join(buf).strip()
        buf = []
        if not body:
            return
        if is_blacklisted(heading, patterns):
            skipped.append((heading, buf_page))
            return
        for piece in window(body):
            out.append({"page": buf_page, "heading": heading, "text": piece})

    for pageno, text in pages:
        for line in (text or "").splitlines():
            h = detect_heading(line)
            if h:
                flush()                 # the previous section ends here
                heading = h
                buf_page = pageno
                continue
            if buf_page is None:
                buf_page = pageno
            buf.append(line)
        # Page break is NOT a section break: the heading and buffer carry over,
        # so a section spanning pages stays one section and stays attributed —
        # and stays blacklisted — correctly.
    flush()
    return out, skipped


def window(body: str):
    """Fixed windows with overlap, for prose with no usable headings."""
    if len(body) <= CHUNK_TARGET_CHARS:
        return [body]
    out, start = [], 0
    while start < len(body):
        end = start + CHUNK_TARGET_CHARS
        out.append(body[start:end])
        if end >= len(body):
            break
        start = end - CHUNK_OVERLAP_CHARS
    return out


def extract_pages(path: Path):
    """(page_number, text) per page, via Kadmos' extractor.

    CSV is handled directly — a repeater list is rows, not prose, and running it
    through a PDF text extractor would produce nothing useful.
    """
    if path.suffix.lower() == ".csv":
        return [(None, path.read_text(encoding="utf-8", errors="replace"))]
    try:
        import fitz
    except ImportError:
        raise SystemExit("PyMuPDF (fitz) is required for ingest — pip install -r requirements.txt")
    out = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            out.append((i, page.get_text() or ""))
    return out


def build(db_path: Path, manifest: dict, only: str | None, dry_run: bool):
    patterns = blacklist_headings(manifest)
    corpus = ROOT / str(manifest.get("corpus_dir") or "corpus")
    sources = [s for s in (manifest.get("sources") or [])
               if not only or s.get("id") == only]
    if not sources:
        print(f"no matching sources{' for ' + only if only else ''}", file=sys.stderr)
        return 1

    db = None
    if not dry_run:
        db = sqlite3.connect(db_path)
        db.executescript(SCHEMA)

    total, total_skipped, missing = 0, 0, []
    for s in sources:
        sid = s.get("id")
        path = corpus / str(s.get("path") or "")
        if not path.exists():
            missing.append(sid)
            print(f"  {sid:22} MISSING  {path}")
            continue
        try:
            pages = extract_pages(path)
        except Exception as e:
            print(f"  {sid:22} EXTRACT FAILED  {e}")
            continue

        chunks, skipped = chunk_pages(pages, patterns)
        total += len(chunks)
        total_skipped += len(skipped)
        print(f"  {sid:22} {len(chunks):5} chunks"
              + (f"   ({len(skipped)} blacklisted sections dropped)" if skipped else ""))
        for h, p in skipped:
            print(f"      dropped: {h!r} (p. {p})")

        if dry_run:
            continue
        db.execute("DELETE FROM chunks WHERE source_id = ?", (sid,))
        db.executemany(
            "INSERT INTO chunks(source_id, source_name, category, priority, page, heading, text)"
            " VALUES (?,?,?,?,?,?,?)",
            [(sid, s.get("name") or sid, s.get("category") or "", int(s.get("priority") or 9),
              c["page"], c["heading"], c["text"]) for c in chunks],
        )

    if not dry_run:
        # Rebuild the FTS mirror from the content table in one shot — cheaper and
        # less error-prone than keeping triggers in sync across a full rebuild.
        db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        db.commit()
        db.close()

    print(f"\n{total} chunks indexed, {total_skipped} blacklisted sections dropped")
    if missing:
        print(f"{len(missing)} source(s) missing — run ./fetch.sh first: {', '.join(missing)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Prometheus FTS index.")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    manifest = load_manifest()
    if not manifest:
        print("no readable manifest at prometheus/manifest.yaml", file=sys.stderr)
        return 2
    db_path = prometheus.index_path(manifest)
    print(f"index: {db_path}{'  (dry run — nothing written)' if args.dry_run else ''}")
    return build(db_path, manifest, args.source, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
