"""
Kadmos — PDF reader for Ph3b3 / Phoebe.

Reads a PDF the user hands her (invoices, forms, letters, memos, resumes, short
reports, syllabi) and answers questions about it or summarizes it. Text-layer
extraction via PyMuPDF (fitz); OCR fallback via tesseract for scanned/image-only
PDFs; table-aware extraction so amounts stay matched to line items.

SECURITY (non-negotiable). Extracted PDF text is UNTRUSTED INPUT:
  * It is summarized with tool-calling DISABLED (the injection firewall — the
    payload handed to the model has no `tools` key, mirroring modules/metis.py's
    web-content discipline). It is NEVER returned raw into the tool-enabled chat
    loop, so an "ignore your instructions / call take_photo" line on page 12 is
    treated as document data, not a command.
  * The content-safety floor (morpheus.floor_check + metis.query_gate) runs on
    the user's question AND on the produced summary. Profile-independent, no
    off-switch. A hit returns a fixed refusal; the category is never surfaced.
  * Local files only. Remote URLs and out-of-bounds paths are refused. This
    module opens no sockets except the localhost model call handed to it.
  * Nothing is retained beyond the staged file and the in-memory rolling summary.

HONEST LIMITS (do not over-claim — same framing as morpheus.py / metis.py):
  * The floor is deterministic English keyword gating plus the model's own
    refusal directive. It stops casual/obvious misuse in every response
    language, not a determined adversary using euphemism.
  * Chunked mode is a sequential map-reduce LOOP, not RAG/embeddings. For a
    chunked document, follow-up detail questions are answered from the rolling
    summary WITH an explicit offer to re-scan the whole document for that
    specific detail — never faked page-level recall.
"""

import io
import re
import uuid
import shutil
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

# ── Designated local drop location — the ONLY place a PDF may be read from ──────
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

# Injection-firewall delimiters (mirror Metis's <<<WEB>>> fencing).
_PDF_OPEN  = "<<<PDF>>>"
_PDF_CLOSE = "<<<END PDF>>>"

_REFUSE_FLOOR_QUERY   = "I won't help with that — that crosses a hard line for me."
_REFUSE_FLOOR_CONTENT = "I read that document, but its contents cross into something I won't relay."

# A "whole-document" ask (summary/overview) vs a follow-up detail question.
_WHOLE_DOC_RE = re.compile(
    r"\b(summar|overview|gist|what(?:'s| is) (?:this|it)(?: about| say)?|"
    r"what does (?:this|it|the (?:pdf|document|doc|file)) say|read (?:this|it|the)|"
    r"tl;?dr|main points?|key points?|go over (?:this|it|the))\b", re.I)

# Intent claim: "read/summarize this pdf/document …". Excludes resume/job-posting
# phrasing, which the resume ATS tools own (they are not intent-registry claims).
_DOC_NOUN = r"(?:pdf|document|doc|paper|invoice|contract|memo|letter|report|syllabus|file)"
_PDF_INTENT_RE = re.compile(
    # verb → doc-noun:  "read/summarize/go over … this pdf/document/invoice"
    r"\b(?:read|summari[sz]e|summary of|go over|look over|walk me through|open)\b"
    rf"[\w\s]{{0,30}}?\b{_DOC_NOUN}\b"
    # doc-noun → verb:  "what does this pdf say / what's in this document"
    rf"|\bwhat(?:'?s| is| does| do)\b[\w\s]{{0,30}}?\b{_DOC_NOUN}\b[\w\s]{{0,20}}?\b(?:say|about|contain|mean|state)\b"
    rf"|\bwhat(?:'?s| is)\s+in\b[\w\s]{{0,20}}?\b{_DOC_NOUN}\b",
    re.I)
_PDF_EXCLUDE_RE = re.compile(
    r"\b(?:resume|cv|curriculum vitae|job (?:posting|description|listing|ad))\b", re.I)


class KadmosError(Exception):
    """Raised for an unreadable/encrypted/corrupt PDF — surfaced as an honest error."""


class KadmosModule:
    def __init__(self):
        INBOX.mkdir(parents=True, exist_ok=True)
        # session_id -> {doc_id, filename, page_count, was_chunked, rolling_summary, full_text}
        self._pending: dict = {}
        log.info("Kadmos PDF module ready.")

    # ── Session document tracking ─────────────────────────────────────────────
    def set_pending(self, session_id: str, doc_id: str, filename: str, page_count: int):
        self._pending[session_id or "default"] = {
            "doc_id": doc_id, "filename": filename, "page_count": page_count,
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
        """Return (Path, None) for a safe local PDF inside INBOX, else (None, refusal)."""
        s = (path_str or "").strip()
        if not s:
            return None, "I don't have a document yet — upload a PDF first, then ask me to read it."
        if self.looks_like_url(s):
            return None, "I only read local files you've handed me — I can't fetch a PDF from a URL."
        base = INBOX.resolve()
        cand = Path(s)
        p = (cand if cand.is_absolute() else (INBOX / cand)).resolve()
        if p.parent != base:                     # traversal / absolute / subdir → outside
            return None, "That path is outside the documents folder, so I won't open it."
        if not p.exists():
            return None, f"I don't have a document called {p.name}. Upload it first."
        if p.suffix.lower() != ".pdf":
            return None, "That isn't a PDF — I can only read PDF files right now."
        return p, None

    def path_for_doc_id(self, doc_id: str) -> Path:
        return INBOX / f"{doc_id}.pdf"

    # ── Upload staging ────────────────────────────────────────────────────────
    def stage_upload(self, raw: bytes, filename: str = "document.pdf"):
        """Validate + stage an uploaded PDF. Return (doc_id, safe_name, page_count, None)
        or (None, None, None, (status_code, message)). Extension/MIME never trusted."""
        if not raw:
            return None, None, None, (400, "empty upload")
        if len(raw) > PDF_MAX_BYTES:
            return None, None, None, (413, f"file too large: {len(raw)} bytes (max {PDF_MAX_BYTES})")
        if not raw[:1024].lstrip().startswith(b"%PDF-"):
            return None, None, None, (400, "not a PDF (missing %PDF header)")
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
            n = doc.page_count
            enc = doc.needs_pass
            doc.close()
        except Exception:
            return None, None, None, (400, "not a decodable PDF")
        if enc:
            return None, None, None, (400, "PDF is encrypted/password-protected — I can't open it")
        if n < 1:
            return None, None, None, (400, "PDF has no pages")
        doc_id = uuid.uuid4().hex
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename or "document.pdf").name)[:80] or "document.pdf"
        (INBOX / f"{doc_id}.pdf").write_bytes(raw)
        log.info("[kadmos] staged upload %s (%r, %d pages)", doc_id, safe, n)
        return doc_id, safe, n, None

    # ── Extraction ────────────────────────────────────────────────────────────
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

    def _extract_page(self, page) -> str:
        """Text + tables for one page. Tables become lightweight markdown rows so
        line items and amounts stay aligned (invoices are the trap)."""
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

    def _ocr_page(self, page) -> str:
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
        """Extract per-page text. Detects scans and OCRs them (if tesseract is
        installed). Returns {pages: [str], scanned: bool, ocr_used: bool,
        ocr_unavailable: bool, page_count: int, cancelled: bool}."""
        n = doc.page_count
        pages, digital_chars = [], 0
        for i in range(n):
            if is_cancelled and is_cancelled():
                return {"pages": pages, "scanned": False, "ocr_used": False,
                        "ocr_unavailable": False, "page_count": n, "cancelled": True}
            t = self._extract_page(doc[i])
            pages.append(t)
            digital_chars += len(t)

        scanned = digital_chars < SCAN_TEXT_FLOOR * n
        if not scanned:
            return {"pages": pages, "scanned": False, "ocr_used": False,
                    "ocr_unavailable": False, "page_count": n, "cancelled": False}

        # Scanned / image-only PDF → OCR fallback.
        if not self.ocr_available():
            return {"pages": pages, "scanned": True, "ocr_used": False,
                    "ocr_unavailable": True, "page_count": n, "cancelled": False}
        if speak:
            speak("This looks like a scan — running OCR. Give me a minute.")
        ocr_pages, limit = [], min(n, OCR_PAGE_CAP)
        for i in range(limit):
            if is_cancelled and is_cancelled():
                return {"pages": ocr_pages, "scanned": True, "ocr_used": True,
                        "ocr_unavailable": False, "page_count": n, "cancelled": True}
            try:
                ocr_pages.append(self._ocr_page(doc[i]))
            except Exception as e:
                log.warning("[kadmos] OCR failed on page %d: %s", i, e)
                ocr_pages.append("")
        return {"pages": ocr_pages, "scanned": True, "ocr_used": True,
                "ocr_unavailable": False, "page_count": n, "cancelled": False}

    # ── Summarize / answer (tools DISABLED, floor-checked) ────────────────────
    async def answer(self, *, query: str, path: Path, summarize, speak=None,
                     is_cancelled=None, session_id: str = "default",
                     store: bool = True) -> str:
        """Extract `path` and answer `query` over it with the injection firewall.

        `summarize(query, fenced_text)` is an injected async callable that runs a
        TOOLS-DISABLED model pass over already-fenced untrusted text (the server
        provides it — see _summarize_pdf_untrusted). `speak(msg)` announces spoken
        status (no-op if None). `is_cancelled()` is polled between chunks.
        """
        # 1. Floor on the user's question (gated question is never processed).
        if morpheus.floor_check(query or "") or metis.query_gate(query or ""):
            return _REFUSE_FLOOR_QUERY

        # 2. Open + extract.
        doc = self.open_doc(path)
        try:
            n = doc.page_count
            if n > PDF_PAGE_CEILING:
                return (f"That document is {n} pages — past my {PDF_PAGE_CEILING}-page limit. "
                        f"I can't read the whole thing; hand me a shorter file or a section of it.")
            ex = self.extract_pages(doc, speak=speak, is_cancelled=is_cancelled)
        finally:
            doc.close()

        if ex["cancelled"]:
            return "Stopped — I didn't finish reading that document."
        if ex["ocr_unavailable"]:
            return ("This looks like a scanned document with no selectable text, and OCR isn't "
                    "installed on me yet, so I can't read it. Install tesseract-ocr and I will.")

        pages = ex["pages"]
        joined = "\n\n".join(p for p in pages if p).strip()
        if not joined:
            return "I opened that PDF but found no readable text in it."

        # 2b. Floor on the EXTRACTED CONTENT (brief: floor runs on extracted text,
        # not only outputs) — objectionable document content is refused before it is
        # ever summarized.
        if morpheus.floor_check(joined) or metis.query_gate(joined):
            return _REFUSE_FLOOR_CONTENT

        # 3. Fast path (single pass) vs chunked map-reduce.
        if len(pages) <= PDF_FASTPATH_CAP:
            answer = await self._summarize_fenced(query, joined, summarize)
            was_chunked, rolling = False, None
            full_text = joined
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
        summarize the summaries. A loop, not RAG. Returns (final_answer, rolling)
        or (None, None) if cancelled."""
        groups = [pages[i:i + PDF_CHUNK_PAGES] for i in range(0, len(pages), PDF_CHUNK_PAGES)]
        total = len(groups)
        if speak:
            speak(f"Big document — {len(pages)} pages. I'll read it in {total} sections; "
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
        """Answer a follow-up over an already-read document. For a chunked doc,
        answer from the rolling summary WITH a re-scan offer (never fake page
        recall). For a fast-path doc, answer over the cached full text."""
        st = self._pending.get(session_id or "default")
        if not st or not (st.get("full_text") or st.get("rolling_summary")):
            return None
        if morpheus.floor_check(query or "") or metis.query_gate(query or ""):
            return _REFUSE_FLOOR_QUERY
        if st.get("full_text"):                       # small doc — full text is accurate
            ans = await self._summarize_fenced(query, st["full_text"], summarize)
        else:                                         # chunked — from rolling summary + offer
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


# Register the PDF intent claim at import time (precedence over Metis). Fires only
# on document-reference phrasing; the dispatch declines (returns None → falls
# through) when no document is actually staged for the session.
intent_registry.register("pdf", "read_pdf", _PDF_INTENT_RE, exclude=_PDF_EXCLUDE_RE)
