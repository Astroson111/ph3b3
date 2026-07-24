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


def _png_bytes():
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (80, 40), "white").save(buf, "PNG"); return buf.getvalue()


# ── upload: valid → 200 ─────────────────────────────────────────────────────────
raw = _pdf_bytes(pages=3)
r = client.post("/kadmos/upload?session_id=itest",
                files={"file": ("report.pdf", raw, "application/pdf")}, headers=HEADERS)
check("valid PDF upload → 200 with doc_id + kind",
      r.status_code == 200 and r.json().get("kind") == "pdf" and r.json().get("doc_id"))

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

# The staged doc is behind the confirmation gate; confirm it so the read tests run.
server.kadmos.confirm("itest")

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

# ── reading mode: a BARE question (no "pdf") routes to the doc, instruction folds in
server.kadmos.set_reading("itest", True, "focus on dates and dollar amounts")
calls.clear()
ans_r = asyncio.run(server._answer_pdf("what is the risk", "itest"))
check("reading-mode: bare question answered from the loaded doc",
      ans_r is not None and len(calls) == 1)
check("reading-mode: standing instruction folded into the sealed query",
      calls and "focus on dates" in calls[0][0])

# ── cancel endpoint sets the flag ───────────────────────────────────────────────
r = client.delete("/kadmos/read/itest", headers=HEADERS)
check("cancel endpoint → 200 + cancelling flag",
      r.status_code == 200 and r.json().get("cancelling") is True and server._kadmos_cancel.get("itest"))

# ── v1.1 confirmation gate: nothing reads until an explicit go ──────────────────
r = client.post("/kadmos/upload?session_id=gate1",
                files={"file": ("g.pdf", _pdf_bytes(2), "application/pdf")}, headers=HEADERS)
gp = r.json().get("gate_prompt", "")
check("upload returns a gate prompt naming the file", "g.pdf" in gp and "read it?" in gp)
check("unconfirmed doc is NOT read by _answer_pdf (nothing extracted before go)",
      asyncio.run(server._answer_pdf("summarize this document", "gate1")) is None)
resp_no = asyncio.run(server._kadmos_gate("no, wrong one", "gate1"))
check("gate 'no' → discarded plainly, pending cleared",
      "unread" in resp_no.lower() and server.kadmos.get_pending("gate1") is None)

server._summarize_pdf_untrusted = _fake_summarize
client.post("/kadmos/upload?session_id=gate2",
            files={"file": ("g2.pdf", _pdf_bytes(2), "application/pdf")}, headers=HEADERS)
calls.clear()
asyncio.run(server._kadmos_gate("yes go ahead", "gate2"))
check("gate 'yes' → reads (summarizer engaged) and marks confirmed",
      len(calls) >= 1 and server.kadmos.get_pending("gate2")["confirmed"] is True)

client.post("/kadmos/upload?session_id=gate3",
            files={"file": ("g3.pdf", _pdf_bytes(2), "application/pdf")}, headers=HEADERS)
calls.clear()
resp_amb = asyncio.run(server._kadmos_gate("hmm maybe", "gate3"))
check("gate ambiguous → re-asks, does not read",
      "?" in resp_amb and calls == [] and server.kadmos.get_pending("gate3")["confirmed"] is False)

# ── v1.1 vision lane: image 'look at it' → LLaVA describe (mocked), floor-checked ─
r = client.post("/kadmos/upload?session_id=vis1",
                files={"file": ("photo.png", _png_bytes(), "image/png")}, headers=HEADERS)
gpi = r.json().get("gate_prompt", "")
check("image gate offers the read-or-look fork",
      "read the text" in gpi and "describe" in gpi)
_orig_describe = server.vision.describe_bytes
server.vision.describe_bytes = lambda raw, prompt: "A photo of a cat sitting on a mat."
try:
    resp_v = asyncio.run(server._kadmos_gate("look at it and describe it", "vis1"))
    check("vision lane returns the LLaVA description", "cat sitting on a mat" in resp_v)
    check("vision lane recorded on the pending slot",
          server.kadmos.get_pending("vis1")["lane"] == "vision")
finally:
    server.vision.describe_bytes = _orig_describe

print(f"\n{sum(_results)}/{len(_results)} passed")
sys.exit(0 if all(_results) else 1)
