"""
Kadmos — document reader for Ph3b3 / Phoebe.

Reads a document the user hands her (invoices, forms, letters, memos, resumes,
short reports, syllabi, photos of forms) and answers questions about it or
summarizes it. ONE tool (`read_document`) with an internal router that dispatches
by MAGIC BYTES first, then extension — never trusting the extension alone.

Supported (v1), all feeding the SAME downstream pipeline (untrusted delimiters →
fast path / chunked map-reduce → floor). No per-format exception to any rule:
  * PDF (.pdf)          — PyMuPDF text layer; scan → tesseract OCR; tables kept aligned.
  * Word (.docx)        — python-docx paragraphs + tables. Legacy .doc refused by name.
  * Text (.txt, .md)    — decoded (UTF-8 + fallbacks); markdown passed through as-is.
  * Images (.jpg/.png)  — straight to tesseract OCR (TEXT extraction only; NOT image
                          description — that is the vision path's lane).
Refused by name (do not improvise unlisted formats):
  * Spreadsheets (.csv/.xlsx) — arithmetic needs a compute path, not the LLM eyeballing
                          rows; coming as its own future module.
  * Legacy .doc/.xls (OLE)    — re-save as .docx.

SECURITY (non-negotiable). Extracted document text is UNTRUSTED INPUT:
  * Summarized with tool-calling DISABLED (the injection firewall — the payload
    handed to the model has no `tools` key, mirroring modules/metis.py). NEVER
    returned raw into the tool-enabled chat loop, so an "ignore your instructions
    / call take_photo" line on page 12 is treated as document data, not a command.
  * The content-safety floor (morpheus.floor_check + metis.query_gate) runs on the
    user's question, the extracted content, AND the produced summary.
    Profile-independent, no off-switch. A hit returns a fixed refusal.
  * Local files only. Remote URLs and out-of-bounds paths refused. Opens no sockets
    except the localhost model call handed in. Nothing retained beyond the staged
    file and the in-memory rolling summary.

HONEST LIMITS (do not over-claim — same framing as morpheus.py / metis.py):
  * The floor is deterministic English keyword gating plus the model's own refusal
    directive. It stops casual/obvious misuse in every response language, not a
    determined adversary using euphemism.
  * Chunked mode is a sequential map-reduce LOOP, not RAG/embeddings. For a chunked
    document, follow-up detail questions are answered from the rolling summary WITH
    an explicit offer to re-scan — never faked page-level recall.
"""

import io
import re
import uuid
import shutil
import zipfile
import logging
from pathlib import Path

import fitz  # PyMuPDF

# Import shim: bare names when modules/ is on sys.path (server), package path in tests.
try:
    from paths import PH3B3_DATA
    import morpheus
    import metis
    import intent_registry
except ImportError:  # pragma: no cover - exercised only by import context
    from modules.paths import PH3B3_DATA
    from modules import morpheus, metis, intent_registry

log = logging.getLogger("ph3b3.kadmos")

# ── Designated local drop location — the ONLY place a document may be read from ─
INBOX = Path(PH3B3_DATA) / "documents"

# ── Tunables (module-level UPPERCASE, Metis convention) ────────────────────────
PDF_MAX_BYTES     = 25 * 1024 * 1024   # oversized upload → refused (413 at endpoint)
PDF_PAGE_CEILING  = 500                # hard ceiling — beyond this, honest refusal
PDF_FASTPATH_CAP  = 30                 # ≤ this many pages → single-pass fast path
PDF_CHUNK_PAGES   = 25                 # chunked map-reduce group size
OCR_PAGE_CAP      = 50                 # max pages we will OCR (OCR is slow, CPU-side)
SCAN_TEXT_FLOOR   = 20                 # chars/page below which a page has no text layer
TEXT_CHAR_CAP     = 14000              # chars fed to one summarize pass (mirror Metis)
PROGRESS_EVERY    = 3                  # speak chunked progress every N chunks
PSEUDO_PAGE_CHARS = 3000               # chars per pseudo-page for non-paginated formats

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md", ".jpg", ".jpeg", ".png"}

# Injection-firewall delimiters (generic untrusted-document fence; mirror Metis's
# <<<WEB>>>). Kept as <<<PDF>>> for continuity with _summarize_pdf_untrusted.
_PDF_OPEN  = "<<<PDF>>>"
_PDF_CLOSE = "<<<END PDF>>>"

_REFUSE_FLOOR_QUERY   = "I won't help with that — that crosses a hard line for me."
_REFUSE_FLOOR_CONTENT = "I read that document, but its contents cross into something I won't relay."

# A "whole-document" ask (summary/overview) vs a follow-up detail question.
_WHOLE_DOC_RE = re.compile(
    r"\b(summar|overview|gist|what(?:'s| is) (?:this|it)(?: about| say)?|"
    r"what does (?:this|it|the (?:pdf|document|doc|file)) say|read (?:this|it|the)|"
    r"tl;?dr|main points?|key points?|go over (?:this|it|the))\b", re.I)

# Intent claim: "read/summarize this document …". Excludes resume/job-posting
# phrasing, which the resume ATS tools own (they are not intent-registry claims).
_DOC_NOUN = r"(?:pdf|document|doc|paper|invoice|contract|memo|letter|report|syllabus|file)"
_PDF_INTENT_RE = re.compile(
    r"\b(?:read|summari[sz]e|summary of|go over|look over|walk me through|open)\b"
    rf"[\w\s]{{0,30}}?\b{_DOC_NOUN}\b"
    rf"|\bwhat(?:'?s| is| does| do)\b[\w\s]{{0,30}}?\b{_DOC_NOUN}\b[\w\s]{{0,20}}?\b(?:say|about|contain|mean|state)\b"
    rf"|\bwhat(?:'?s| is)\s+in\b[\w\s]{{0,20}}?\b{_DOC_NOUN}\b",
    re.I)
_PDF_EXCLUDE_RE = re.compile(
    r"\b(?:resume|cv|curriculum vitae|job (?:posting|description|listing|ad))\b", re.I)

# Friendly labels per routed kind (for the upload confirmation).
_KIND_LABEL = {"pdf": "PDF", "docx": "Word document", "text": "text file", "image": "image"}
_KIND_EXT = {"pdf": ".pdf", "docx": ".docx", "text": ".txt", "image": ".png"}


class KadmosError(Exception):
    """Raised for an unreadable/encrypted/corrupt document — surfaced honestly."""


class KadmosModule:
    def __init__(self):
        INBOX.mkdir(parents=True, exist_ok=True)
        # session_id -> {doc_id, filename, label, was_chunked, rolling_summary, full_text}
        self._pending: dict = {}
        # session_id -> {"mode": bool, "instruction": str} — the reading-mode UI state
        self._reading: dict = {}
        log.info("Kadmos document reader ready.")

    # ── Reading-mode state (explicit, user-controlled via the portal switch) ───
    def set_reading(self, session_id: str, mode: bool, instruction: str = ""):
        self._reading[session_id or "default"] = {
            "mode": bool(mode), "instruction": (instruction or "").strip()[:500]}

    def get_reading(self, session_id: str) -> dict:
        return self._reading.get(session_id or "default", {"mode": False, "instruction": ""})

    # ── Session document tracking ─────────────────────────────────────────────
    def set_pending(self, session_id: str, doc_id: str, filename: str, label: str = "document"):
        self._pending[session_id or "default"] = {
            "doc_id": doc_id, "filename": filename, "label": label,
            "was_chunked": None, "rolling_summary": None, "full_text": None,
        }

    def get_pending(self, session_id: str):
        return self._pending.get(session_id or "default")

    def clear_pending(self, session_id: str):
        self._pending.pop(session_id or "default", None)

    # ── Input / path safety ───────────────────────────────────────────────────
    @staticmethod
    def looks_like_url(s: str) -> bool:
        s = (s or "").strip()
        return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", s)) or s.lower().startswith("www.")

    def resolve_in_inbox(self, path_str: str):
        """Return (Path, None) for a safe local file inside INBOX, else (None, refusal)."""
        s = (path_str or "").strip()
        if not s:
            return None, "I don't have a document yet — upload one first, then ask me to read it."
        if self.looks_like_url(s):
            return None, "I only read local files you've handed me — I can't fetch a document from a URL."
        base = INBOX.resolve()
        cand = Path(s)
        p = (cand if cand.is_absolute() else (INBOX / cand)).resolve()
        if p.parent != base:                     # traversal / absolute / subdir → outside
            return None, "That path is outside the documents folder, so I won't open it."
        if not p.exists():
            return None, f"I don't have a document called {p.name}. Upload it first."
        if p.suffix.lower() not in SUPPORTED_EXTS:
            return None, ("I can only read PDF, Word (.docx), text (.txt/.md), and document photos "
                          "(.jpg/.png).")
        return p, None

    def path_for_doc_id(self, doc_id: str) -> Path:
        matches = sorted(INBOX.glob(f"{doc_id}.*"))
        return matches[0] if matches else (INBOX / f"{doc_id}.pdf")

    # ── Format router — magic bytes first, extension second ───────────────────
    @staticmethod
    def _zip_kind(raw: bytes):
        try:
            names = zipfile.ZipFile(io.BytesIO(raw)).namelist()
        except Exception:
            return None
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        return None

    def detect_format(self, raw: bytes, filename: str):
        """Route to a supported kind ('pdf'|'docx'|'text'|'image') or return an
        honest refusal. Magic bytes are authoritative (catches mislabeled files);
        text formats fall back to extension since they carry no magic."""
        ext = Path(filename or "").suffix.lower()
        if raw[:5] == b"%PDF-":
            return "pdf", None
        if raw[:4] == b"\x89PNG" or raw[:3] == b"\xff\xd8\xff":
            return "image", None
        if raw[:4] == b"PK\x03\x04":                     # OOXML / zip — peek inside
            inner = self._zip_kind(raw)
            if inner == "docx":
                return "docx", None
            if inner in ("xlsx", "pptx"):
                return None, ("That's a spreadsheet — I can't read those yet. Honest math needs a "
                              "compute path, so spreadsheet support is coming as its own feature."
                              if inner == "xlsx" else
                              "That's a PowerPoint file — I don't read slide decks yet. Export it to "
                              "PDF and I'll read it.")
            return None, "That's a zipped Office file I don't handle — export it as PDF, .docx, or text."
        if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE compound — legacy .doc/.xls/.ppt
            return None, ("That's a legacy Microsoft Office file. I can't read the old .doc/.xls "
                          "format — re-save it as .docx (or export to PDF) and I'll read it.")
        # No binary magic → text-ish; decide by extension.
        if ext in (".txt", ".md"):
            return "text", None
        if ext in (".csv", ".xlsx", ".xls"):
            return None, ("That's a spreadsheet — I can't read those yet. Spreadsheet support is "
                          "coming as its own feature.")
        if ext == ".doc":
            return None, "That's a legacy .doc file. Re-save it as .docx and I'll read it."
        if ext == ".pdf":
            return None, "That file says .pdf but isn't a readable PDF — it may be corrupt."
        if ext in (".docx", ".jpg", ".jpeg", ".png"):
            return None, f"That file says {ext} but isn't a readable {ext[1:]} — it may be corrupt."
        return None, (f"I can't read {ext or 'that'} files. I handle PDF, Word (.docx), text "
                      f"(.txt/.md), and photos of documents (.jpg/.png).")

    # ── Upload staging ────────────────────────────────────────────────────────
    def stage_upload(self, raw: bytes, filename: str = "document"):
        """Validate + stage an uploaded document. Return
        (doc_id, safe_name, kind, label, None) or (None,None,None,None,(code,msg))."""
        if not raw:
            return None, None, None, None, (400, "empty upload")
        if len(raw) > PDF_MAX_BYTES:
            return None, None, None, None, (413, f"file too large: {len(raw)} bytes (max {PDF_MAX_BYTES})")
        kind, refusal = self.detect_format(raw, filename)
        if refusal:
            return None, None, None, None, (400, refusal)
        # Encrypted PDFs are refused up front (never store an unreadable file).
        if kind == "pdf":
            try:
                d = fitz.open(stream=raw, filetype="pdf")
                enc, npages = d.needs_pass, d.page_count
                d.close()
            except Exception:
                return None, None, None, None, (400, "not a decodable PDF")
            if enc:
                return None, None, None, None, (400, "PDF is encrypted/password-protected — I can't open it")
            if npages < 1:
                return None, None, None, None, (400, "PDF has no pages")
        doc_id = uuid.uuid4().hex
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename or "document").name)[:80] or "document"
        ext = Path(safe).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            ext = _KIND_EXT[kind]
        (INBOX / f"{doc_id}{ext}").write_bytes(raw)
        label = _KIND_LABEL.get(kind, "document")
        log.info("[kadmos] staged %s (%r, kind=%s)", doc_id, safe, kind)
        return doc_id, safe, kind, label, None

    # ── Per-format extraction → a uniform ex dict ─────────────────────────────
    @staticmethod
    def ocr_available() -> bool:
        return shutil.which("tesseract") is not None

    @staticmethod
    def _table_to_md(rows) -> str:
        out = []
        for r in rows:
            cells = [("" if c is None else str(c)).replace("\n", " ").strip() for c in r]
            if any(cells):
                out.append("| " + " | ".join(cells) + " |")
        return "\n".join(out)

    @staticmethod
    def _paginate(text: str):
        text = (text or "").strip()
        if not text:
            return []
        return [text[i:i + PSEUDO_PAGE_CHARS] for i in range(0, len(text), PSEUDO_PAGE_CHARS)]

    @staticmethod
    def _ex(pages, *, scanned=False, ocr_used=False, ocr_unavailable=False,
            page_count=None, cancelled=False, over_ceiling=False):
        return {"pages": pages, "scanned": scanned, "ocr_used": ocr_used,
                "ocr_unavailable": ocr_unavailable,
                "page_count": len(pages) if page_count is None else page_count,
                "cancelled": cancelled, "over_ceiling": over_ceiling}

    def _extract_page(self, page) -> str:
        """PDF page: text + tables (aligned markdown rows so amounts stay matched)."""
        text = (page.get_text("text") or "").strip()
        tables = []
        try:
            found = page.find_tables()
            for t in (found.tables if found else []):
                rows = t.extract()
                if rows:
                    tables.append(self._table_to_md(rows))
        except Exception:
            pass
        if tables:
            return (text + "\n\n" + "\n\n".join(tables)).strip()
        return text

    def _ocr_pixmap(self, page) -> str:
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return (pytesseract.image_to_string(img) or "").strip()

    def open_doc(self, path: Path):
        """Open a PDF, raising KadmosError with an honest message on failure."""
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise KadmosError(f"I couldn't open that PDF — it looks corrupt or unreadable ({e}).")
        if doc.needs_pass:
            doc.close()
            raise KadmosError("That PDF is encrypted or password-protected, so I can't read it.")
        if doc.page_count < 1:
            doc.close()
            raise KadmosError("That PDF has no pages I can read.")
        return doc

    def extract_pages(self, doc, *, speak=None, is_cancelled=None) -> dict:
        """PDF: per-page text, OCR fallback for scans (if tesseract installed)."""
        n = doc.page_count
        pages, digital_chars = [], 0
        for i in range(n):
            if is_cancelled and is_cancelled():
                return self._ex(pages, page_count=n, cancelled=True)
            t = self._extract_page(doc[i])
            pages.append(t)
            digital_chars += len(t)

        if digital_chars >= SCAN_TEXT_FLOOR * n:
            return self._ex(pages, page_count=n)
        # Scanned / image-only PDF → OCR fallback.
        if not self.ocr_available():
            return self._ex(pages, scanned=True, ocr_unavailable=True, page_count=n)
        if speak:
            speak("This looks like a scan — running OCR. Give me a minute.")
        ocr_pages = []
        for i in range(min(n, OCR_PAGE_CAP)):
            if is_cancelled and is_cancelled():
                return self._ex(ocr_pages, scanned=True, ocr_used=True, page_count=n, cancelled=True)
            try:
                ocr_pages.append(self._ocr_pixmap(doc[i]))
            except Exception as e:
                log.warning("[kadmos] OCR failed on page %d: %s", i, e)
                ocr_pages.append("")
        return self._ex(ocr_pages, scanned=True, ocr_used=True, page_count=n)

    def _extract_pdf(self, path, *, speak=None, is_cancelled=None) -> dict:
        doc = self.open_doc(path)
        try:
            if doc.page_count > PDF_PAGE_CEILING:
                return self._ex([], page_count=doc.page_count, over_ceiling=True)
            return self.extract_pages(doc, speak=speak, is_cancelled=is_cancelled)
        finally:
            doc.close()

    def _extract_docx(self, raw: bytes) -> dict:
        try:
            import docx  # python-docx
        except ImportError:
            raise KadmosError("I can't read Word documents right now — python-docx isn't installed.")
        try:
            d = docx.Document(io.BytesIO(raw))
        except Exception as e:
            raise KadmosError(f"I couldn't open that Word document — it looks corrupt ({e}).")
        parts = [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]
        for tbl in d.tables:                     # tables structurally → aligned rows
            rows = [[(c.text or "").replace("\n", " ").strip() for c in r.cells] for r in tbl.rows]
            md = self._table_to_md(rows)
            if md:
                parts.append(md)
        pages = self._paginate("\n".join(parts))
        return self._ex(pages, over_ceiling=len(pages) > PDF_PAGE_CEILING)

    def _extract_text(self, raw: bytes) -> dict:
        text = None
        for enc in ("utf-8-sig", "utf-8", "utf-16"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                text = None
        if text is None:
            text = raw.decode("latin-1", errors="replace")
        sample = text[:2000]
        if sample:
            printable = sum((c.isprintable() or c in "\n\r\t ") for c in sample)
            if printable / len(sample) < 0.7:
                raise KadmosError("That text file doesn't decode into readable text — the "
                                  "character encoding isn't one I recognize.")
        pages = self._paginate(text)
        return self._ex(pages, over_ceiling=len(pages) > PDF_PAGE_CEILING)

    def _extract_image(self, raw: bytes, *, speak=None) -> dict:
        if not self.ocr_available():
            return self._ex([], scanned=True, ocr_unavailable=True, page_count=1)
        if speak:
            speak("Reading the photo with OCR — give me a second.")
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            text = (pytesseract.image_to_string(img) or "").strip()
        except Exception as e:
            raise KadmosError(f"I couldn't read that image ({e}).")
        return self._ex([text], scanned=True, ocr_used=True, page_count=1)

    def _extract(self, kind, path, raw, *, speak=None, is_cancelled=None) -> dict:
        if kind == "pdf":
            return self._extract_pdf(path, speak=speak, is_cancelled=is_cancelled)
        if kind == "docx":
            return self._extract_docx(raw)
        if kind == "text":
            return self._extract_text(raw)
        if kind == "image":
            return self._extract_image(raw, speak=speak)
        raise KadmosError("Unsupported document format.")

    # ── Summarize / answer (tools DISABLED, floor-checked) ────────────────────
    async def answer(self, *, query: str, path: Path, summarize, speak=None,
                     is_cancelled=None, session_id: str = "default",
                     store: bool = True) -> str:
        """Detect + extract `path` (any supported format) and answer `query` over
        it with the injection firewall. `summarize(query, fenced_text)` is an
        injected TOOLS-DISABLED async pass over fenced untrusted text."""
        # 1. Floor on the user's question (gated question is never processed).
        if morpheus.floor_check(query or "") or metis.query_gate(query or ""):
            return _REFUSE_FLOOR_QUERY

        # 2. Read, route, extract.
        path = Path(path)
        try:
            raw = path.read_bytes()
        except Exception:
            return "I couldn't open that file — it may have moved. Upload it again."
        kind, refusal = self.detect_format(raw, path.name)
        if refusal:
            return refusal
        ex = self._extract(kind, path, raw, speak=speak, is_cancelled=is_cancelled)

        if ex["cancelled"]:
            return "Stopped — I didn't finish reading that document."
        if ex["over_ceiling"]:
            return (f"That document is {ex['page_count']} pages — past my {PDF_PAGE_CEILING}-page "
                    f"limit. I can't read the whole thing; hand me a shorter file or a section.")
        if ex["ocr_unavailable"]:
            return ("This looks like a scan/photo with no selectable text, and OCR isn't installed "
                    "on me yet, so I can't read it. Install tesseract-ocr and I will.")

        pages = ex["pages"]
        joined = "\n\n".join(p for p in pages if p).strip()
        if not joined:
            return "I opened that, but couldn't find any readable text in it."

        # 2b. Floor on the EXTRACTED CONTENT (brief: floor runs on extracted text,
        # not only outputs) — objectionable content refused before it is summarized.
        if morpheus.floor_check(joined) or metis.query_gate(joined):
            return _REFUSE_FLOOR_CONTENT

        # 3. Fast path (single pass) vs chunked map-reduce.
        if len(pages) <= PDF_FASTPATH_CAP:
            answer = await self._summarize_fenced(query, joined, summarize)
            was_chunked, rolling, full_text = False, None, joined
        else:
            answer, rolling = await self._chunked_answer(
                query, pages, summarize, speak=speak, is_cancelled=is_cancelled)
            if answer is None:                        # cancelled mid-chunk
                return "Stopped — I read part of it but didn't finish the full document."
            was_chunked, full_text = True, None

        # 4. Floor on the produced summary (never relay gated content).
        if morpheus.floor_check(answer or "") or metis.query_gate(answer or ""):
            return _REFUSE_FLOOR_CONTENT

        # 5. Remember rolling state for honest follow-ups.
        if store:
            st = self._pending.get(session_id or "default")
            if st:
                st.update(was_chunked=was_chunked, rolling_summary=(rolling or answer),
                          full_text=full_text)
        return answer

    async def _summarize_fenced(self, query: str, text: str, summarize) -> str:
        fenced = f"{_PDF_OPEN}\n{text[:TEXT_CHAR_CAP]}\n{_PDF_CLOSE}"
        return (await summarize(query or "Summarize this document.", fenced)).strip()

    async def _chunked_answer(self, query, pages, summarize, *, speak=None, is_cancelled=None):
        """Sequential map-reduce: summarize each ~PDF_CHUNK_PAGES group, then
        summarize the summaries. A loop, not RAG. Returns (final, rolling) or
        (None, None) if cancelled."""
        groups = [pages[i:i + PDF_CHUNK_PAGES] for i in range(0, len(pages), PDF_CHUNK_PAGES)]
        total = len(groups)
        if speak:
            speak(f"Big document — {len(pages)} sections. I'll read it in {total} passes; "
                  f"this will take a few minutes.")
        partials = []
        for idx, g in enumerate(groups, 1):
            if is_cancelled and is_cancelled():
                return None, None
            chunk_text = "\n\n".join(p for p in g if p)[:TEXT_CHAR_CAP]
            fenced = f"{_PDF_OPEN}\n{chunk_text}\n{_PDF_CLOSE}"
            partials.append(await summarize(
                "Summarize the key points of this section of a document.", fenced))
            if speak and (idx % PROGRESS_EVERY == 0) and idx < total:
                speak(f"Read {idx} of {total} sections so far.")
        if is_cancelled and is_cancelled():
            return None, None
        rolling = "\n\n".join(f"[section {i}] {s}" for i, s in enumerate(partials, 1))
        fenced = f"{_PDF_OPEN}\n{rolling[:TEXT_CHAR_CAP]}\n{_PDF_CLOSE}"
        final = (await summarize(query or "Give an overall summary of this document.", fenced)).strip()
        if speak:
            speak("Done — I've read the whole document.")
        return final, rolling

    async def followup(self, *, query: str, session_id: str, summarize) -> str:
        """Answer a follow-up over an already-read document. Chunked doc → from the
        rolling summary WITH a re-scan offer (never fake page recall); fast-path doc
        → over the cached full text."""
        st = self._pending.get(session_id or "default")
        if not st or not (st.get("full_text") or st.get("rolling_summary")):
            return None
        if morpheus.floor_check(query or "") or metis.query_gate(query or ""):
            return _REFUSE_FLOOR_QUERY
        if st.get("full_text"):
            ans = await self._summarize_fenced(query, st["full_text"], summarize)
        else:
            fenced = f"{_PDF_OPEN}\n{st['rolling_summary'][:TEXT_CHAR_CAP]}\n{_PDF_CLOSE}"
            ans = (await summarize(query, fenced)).strip()
            ans += ("\n\nThat's from my section-by-section summary — want me to re-scan the whole "
                    "document for that specific detail?")
        if morpheus.floor_check(ans or "") or metis.query_gate(ans or ""):
            return _REFUSE_FLOOR_CONTENT
        return ans

    @staticmethod
    def is_whole_doc_ask(msg: str) -> bool:
        return bool(_WHOLE_DOC_RE.search(msg or ""))


# Register the document intent claim at import time (precedence over Metis). Fires
# only on document-reference phrasing; the dispatch declines (returns None → falls
# through) when no document is actually staged for the session.
intent_registry.register("document", "read_document", _PDF_INTENT_RE, exclude=_PDF_EXCLUDE_RE)
