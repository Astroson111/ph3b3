"""
thoth.ingest — fetch the corpus, parse it, store it.

Run:  .venv/bin/python -m thoth.ingest --list
      .venv/bin/python -m thoth.ingest --work web
      .venv/bin/python -m thoth.ingest --all

── WHAT THIS RUNG INGESTS ───────────────────────────────────────────────────
The structured sources only: USFM, the WLC XML, Tanzil's pipe-delimited Quran
files, and Sefaria's JSON. Those four adapters cover seven works and the large
majority of the corpus by volume.

The remaining works in the manifest are prose scans — Gutenberg and archive.org
OCR of century-old books — and turning those into tablet/line addresses is a
per-book job, not a format adapter. They carry `ingested: false` and an
ingest_note saying so, which is why `adapter: prose` resolves to a refusal here
rather than a silent skip: a work that cannot be ingested should say why when
you ask it to, not look like it worked.

── DOWNLOADS ARE CACHED AND HASHED ──────────────────────────────────────────
Fetched bytes land in THOTH_DATA/cache and are reused. Each ingest records the
sha256 of what it actually parsed, so "which revision of Pickthall is in the
store" has an answer. During Rung 1 two plausible-looking source URLs returned
HTTP 200 for completely different books — one Gutenberg id resolved to a Spanish
short-story collection — so a 200 is not evidence that the right text arrived.
The hash is what makes a re-download comparable to what was stored before it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import time
import urllib.parse
import urllib.request
import zipfile

from .corpus import CACHE_DIR, Corpus, load_manifest
from .schema import Passage, Work
from .sources import sefaria as sefaria_src
from .sources import tanzil as tanzil_src
from .sources import usfm as usfm_src
from .sources import wlc as wlc_src

log = logging.getLogger("ph3b3.thoth.ingest")

_UA = "Ph3b3-Thoth/1.0 (local sacred-text library; contact via repo owner)"

# Deuterocanonical USFM book codes, split out of the WEB archive into their own
# work because their canonicity differs book by book.
_DEUTERO = frozenset({"TOB", "JDT", "ESG", "WIS", "SIR", "BAR", "1MA", "2MA",
                      "1ES", "MAN", "PS2", "3MA", "2ES", "4MA", "DAG",
                      "LJE", "S3Y", "SUS", "BEL"})


class IngestError(RuntimeError):
    pass


# ── fetching ─────────────────────────────────────────────────────────────────

def fetch(url: str, cache_name: str, refresh: bool = False) -> bytes:
    """Download to the cache and return the bytes, reusing an existing copy."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / cache_name
    if dest.exists() and not refresh:
        return dest.read_bytes()
    log.info("thoth: fetching %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    dest.write_bytes(data)
    return data


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _numbered(rows: list[tuple], work_id: str) -> list[Passage]:
    """Attach a global ordinal so a work can be read start-to-finish in order —
    which Rung 4's reader lane needs and a (section, unit) sort cannot give,
    because book order is not alphabetical."""
    return [Passage(work_id=work_id, book=b, section=s, unit=u, text=t, ordinal=i)
            for i, (b, s, u, t) in enumerate(rows, start=1)]


# ── per-adapter ingest ───────────────────────────────────────────────────────

def _ingest_usfm(work: Work, refresh: bool) -> tuple[list[Passage], str]:
    data = fetch(work.source.url, "eng-web_usfm.zip", refresh)
    subset = work.source.subset or "protocanon"
    if subset not in ("protocanon", "deuterocanon"):
        raise IngestError(
            f"{work.id}: source.subset must be 'protocanon' or 'deuterocanon', "
            f"got {subset!r}")
    want_deutero = subset == "deuterocanon"
    rows: list[tuple] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            if not name.lower().endswith(".usfm"):
                continue
            raw = z.read(name).decode("utf-8-sig")
            if not raw.startswith("\\id"):
                continue
            code = raw.split(None, 2)[1].strip().upper()
            if (code in _DEUTERO) != want_deutero:
                continue
            book = usfm_src.book_name(raw, code)
            rows.extend(usfm_src.parse(raw, book))
    if not rows:
        raise IngestError(f"{work.id}: no verses parsed from the USFM archive")
    return _numbered(rows, work.id), _sha(data)


def _ingest_wlc(work: Work, refresh: bool) -> tuple[list[Passage], str]:
    data = fetch(work.source.url, "wlc-tanach.xml.zip", refresh)
    rows: list[tuple] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in sorted(z.namelist())
                 if n.endswith(".xml") and not wlc_src.is_variant_file(n)]
        for name in names:
            xml = z.read(name).decode("utf-8")
            if "<c " not in xml and '<c n=' not in xml:
                continue                      # header/index file, no chapters
            _book, book_rows = wlc_src.parse(xml, name)
            rows.extend(book_rows)
    if not rows:
        raise IngestError(f"{work.id}: no verses parsed from the WLC archive")
    return _numbered(rows, work.id), _sha(data)


def _ingest_tanzil(work: Work, refresh: bool) -> tuple[list[Passage], str]:
    data = fetch(work.source.url, f"{work.id}.txt", refresh)
    text = data.decode("utf-8-sig")
    rows = tanzil_src.parse(text)
    if len(rows) != 6236:
        # The Kufan count is 6236 ayat. A different number means the file was
        # truncated or the wrong edition arrived — refuse rather than store a
        # Quran with holes in it that Rung 2 would cite as complete.
        raise IngestError(
            f"{work.id}: parsed {len(rows)} ayat, expected 6236 (Kufan count). "
            f"Source may be truncated or a different edition.")
    return _numbered(rows, work.id), _sha(data)


# The Tanakh as Sefaria divides it: 39 books, each fetched chapter by chapter.
_SEFARIA_BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "I Samuel", "II Samuel", "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel", "Hosea", "Joel", "Amos", "Obadiah",
    "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
    "Malachi", "Psalms", "Proverbs", "Job", "Song of Songs", "Ruth",
    "Lamentations", "Ecclesiastes", "Esther", "Daniel", "Ezra", "Nehemiah",
    "I Chronicles", "II Chronicles",
]


def _sefaria_chapter_count(book: str) -> int:
    raw = fetch(f"https://www.sefaria.org/api/v2/raw/index/{urllib.parse.quote(book)}",
                f"sefaria-index-{book.replace(' ', '_')}.json", refresh=False)
    lengths = (json.loads(raw).get("schema") or {}).get("lengths") or []
    if not lengths:
        raise IngestError(f"sefaria: no chapter count for {book}")
    return int(lengths[0])


def _ingest_sefaria(work: Work, refresh: bool) -> tuple[list[Passage], str]:
    version = sefaria_src.JPS_1917
    rows: list[tuple] = []
    digest = hashlib.sha256()
    for book in _SEFARIA_BOOKS:
        n = _sefaria_chapter_count(book)
        for ch in range(1, n + 1):
            ref = urllib.parse.quote(f"{book} {ch}")
            url = (f"https://www.sefaria.org/api/v3/texts/{ref}"
                   f"?version=english|{urllib.parse.quote(version)}")
            cache = f"sefaria-jps1917-{book.replace(' ', '_')}-{ch}.json"
            cached = (CACHE_DIR / cache).exists() and not refresh
            raw = fetch(url, cache, refresh)
            digest.update(raw)
            payload = json.loads(raw)
            # parse_chapter raises if Sefaria served a different edition.
            rows.extend(sefaria_src.parse_chapter(payload, book, ch, version))
            if not cached:
                time.sleep(0.15)      # be a polite client of a free API
        log.info("thoth: JPS 1917 %s (%d chapters)", book, n)
    if not rows:
        raise IngestError("jps1917: no verses parsed")
    return _numbered(rows, work.id), digest.hexdigest()


_ADAPTERS = {
    "usfm": _ingest_usfm,
    "wlc": _ingest_wlc,
    "tanzil": _ingest_tanzil,
    "sefaria": _ingest_sefaria,
}


def ingest_work(corpus: Corpus, work: Work, refresh: bool = False) -> int:
    """Fetch, parse and store one work. Returns the passage count."""
    fn = _ADAPTERS.get(work.source.adapter)
    if fn is None:
        raise IngestError(
            f"{work.id}: adapter {work.source.adapter!r} is not implemented. "
            f"{work.ingest_note or 'This work is not ingestable yet.'}")
    if not work.provenance.vendorable:
        raise IngestError(
            f"{work.id}: provenance.vendorable is false — {work.provenance.license_note}")
    passages, sha = fn(work, refresh)
    n = corpus.replace_passages(work.id, passages)
    corpus.set_source_hash(work.id, sha)
    log.info("thoth: %s — %d passages (sha256 %s…)", work.id, n, sha[:12])
    return n


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Thoth corpus ingest")
    ap.add_argument("--work", action="append", default=[],
                    help="work id to ingest (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="ingest every work with an implemented adapter")
    ap.add_argument("--list", action="store_true", help="show corpus state and exit")
    ap.add_argument("--refresh", action="store_true", help="re-download, ignore cache")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    works, failures = load_manifest()
    for ident, why in failures:
        print(f"  MANIFEST REJECTED  {ident}: {why}", file=sys.stderr)

    corpus = Corpus()
    corpus.sync_metadata(works)

    if args.list or not (args.work or args.all):
        print(f"{'id':20s} {'lic':22s} {'retr':5s} {'ing':4s} {'passages':>9s}  title")
        for r in corpus.summary():
            print(f"{r['id']:20s} {r['license']:22s} "
                  f"{'yes' if r['retrievable'] else 'NO':5s} "
                  f"{'yes' if r['ingested'] else '-':4s} "
                  f"{r['passage_count']:9,d}  {r['title'][:44]}")
        total = sum(r["passage_count"] for r in corpus.summary())
        print(f"\n{total:,} passages across "
              f"{sum(1 for r in corpus.summary() if r['ingested'])} ingested works")
        if failures:
            return 1
        return 0

    targets = ([w for w in works if w.id in set(args.work)] if args.work
               else [w for w in works if w.source.adapter in _ADAPTERS])
    if args.work:
        missing = set(args.work) - {w.id for w in targets}
        for m in missing:
            print(f"  no such work: {m}", file=sys.stderr)

    if not targets:
        # Exiting 0 having stored nothing is the failure mode that reads as
        # success. An ingest run that matched no work is a mistake, not a no-op.
        print("  nothing to ingest: no work matched", file=sys.stderr)
        corpus.close()
        return 1

    rc = 0
    for w in targets:
        try:
            ingest_work(corpus, w, refresh=args.refresh)
        except Exception as e:
            print(f"  FAILED  {w.id}: {e}", file=sys.stderr)
            rc = 1
    corpus.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
