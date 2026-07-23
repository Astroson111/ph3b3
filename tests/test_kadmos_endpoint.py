"""
Kadmos HTTP-layer integration test (standalone, like test_edit_floor.py).

Imports the real server + FastAPI TestClient and exercises the /kadmos/upload
endpoint (200 / 413 / 400) and the forced-routing read path in-process, with the
Ollama summarize call stubbed. Proves the wiring — auth, file parsing,
HTTPException→status, session doc-tracking, and that _answer_pdf drives Kadmos's
sealed summarizer — without a live server or GPU.

Run:  .venv/bin/python tests/test_kadmos_endpoint.py
"""

import io
import sys
import base64
import asyncio
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))
sys.path.insert(0, str(REPO / "agent"))

import fitz
import kadmos_module
import server
from fastapi.testclient import TestClient

client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}

_results = []


def check(desc, ok):
    ok = bool(ok)
    _results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} - {desc}")


def _pdf_bytes(pages=2, text="Quarterly revenue rose. Apples and oranges discussed."):
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"Page {i+1}. {text}")
    buf = doc.tobytes()
    doc.close()
    return buf


# ── upload: valid → 200 ─────────────────────────────────────────────────────────
raw = _pdf_bytes(pages=3)
r = client.post("/kadmos/upload?session_id=itest",
                files={"file": ("report.pdf", raw, "application/pdf")}, headers=HEADERS)
check("valid PDF upload → 200 with doc_id + page count",
      r.status_code == 200 and r.json().get("pages") == 3 and r.json().get("doc_id"))

# ── upload: not a PDF → 400 ─────────────────────────────────────────────────────
r = client.post("/kadmos/upload",
                files={"file": ("x.pdf", b"totally not a pdf", "application/pdf")}, headers=HEADERS)
check("non-PDF upload → 400", r.status_code == 400)

# ── upload: oversized → 413 (shrink the cap instead of sending 25 MB) ───────────
_old = kadmos_module.PDF_MAX_BYTES
try:
    kadmos_module.PDF_MAX_BYTES = 200
    r = client.post("/kadmos/upload",
                    files={"file": ("big.pdf", b"%PDF-" + b"0" * 900, "application/pdf")}, headers=HEADERS)
    check("oversized upload → 413", r.status_code == 413)
finally:
    kadmos_module.PDF_MAX_BYTES = _old

# ── upload requires auth → 401 without header ───────────────────────────────────
r = client.post("/kadmos/upload", files={"file": ("a.pdf", raw, "application/pdf")})
check("upload without auth → 401", r.status_code == 401)

# ── forced-routing read: _answer_pdf drives the sealed summarizer ────────────────
calls = []
async def _fake_summarize(query, fenced):
    calls.append((query, fenced))
    return "Revenue rose this quarter; the document covers apples and oranges."

server._summarize_pdf_untrusted = _fake_summarize   # stub the Ollama pass
ans = asyncio.run(server._answer_pdf("summarize this document", "itest"))
check("read of uploaded doc returns the sealed summary",
      ans == "Revenue rose this quarter; the document covers apples and oranges.")
check("summarizer received fenced untrusted text",
      len(calls) == 1 and calls[0][1].startswith("<<<PDF>>>") and "Apples" in calls[0][1])

# ── no staged doc for a session → _answer_pdf falls through (returns None) ───────
ans_none = asyncio.run(server._answer_pdf("summarize this document", "nobody"))
check("no staged doc → falls through (None), never hijacks", ans_none is None)

# ── cancel endpoint sets the flag ───────────────────────────────────────────────
r = client.delete("/kadmos/read/itest", headers=HEADERS)
check("cancel endpoint → 200 + cancelling flag",
      r.status_code == 200 and r.json().get("cancelling") is True and server._kadmos_cancel.get("itest"))

print(f"\n{sum(_results)}/{len(_results)} passed")
sys.exit(0 if all(_results) else 1)
