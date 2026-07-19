"""Metis — Ph3b3's web-search egress (SearXNG-backed).

The FIRST deliberate-egress module. Search is chosen, visible, minimal, and it
treats the open web as UNTRUSTED: fetched content is data to summarize, never
instructions to follow. This module owns the network + security surface (egress
switch, SearXNG client, SSRF-guarded fetch, extraction). The summarize pass and
tool orchestration live in the server so the "no tools inside a summarize" rule
is enforced where the model is called.

Guarantees enforced here:
  - Egress master switch (default OFF) — no switch, no packets.
  - SearXNG is localhost-only; we only ever talk to 127.0.0.1.
  - Fetcher refuses non-http(s), and any host resolving to a private / loopback /
    link-local / CGNAT-tailnet / reserved address (no probing the LAN via Metis).
  - Redirects are NOT followed (redirect-based SSRF is impossible; a redirecting
    page just falls back to its search snippet).
  - Timeouts + hard byte cap on every fetch; extracted text is length-capped.
  - No search log — Metis keeps no separate record (the chat transcript is it).
"""
import ipaddress
import json
import logging
import re
import socket
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

import httpx


class SearchBroken(RuntimeError):
    """Backend is BROKEN or unreachable (not merely empty) — fail LOUD. The tool
    speaks 'search is broken', never returns a silent zero-result answer."""


class SearchBusy(RuntimeError):
    """Per-minute rate cap hit — courtesy so a chatty session doesn't hammer the backend."""

try:
    from paths import PH3B3_DATA
except ImportError:
    from modules.paths import PH3B3_DATA

log = logging.getLogger("ph3b3.metis")

SEARXNG_URL   = "http://127.0.0.1:8888"          # localhost-only; the ONLY host we call
EGRESS_PATH   = Path(PH3B3_DATA) / "egress.json"  # persisted master switch (default OFF)

RESULT_CAP     = 6           # top results returned to the model
FETCH_PAGES    = 2           # how many top pages we deep-fetch
PAGE_BYTE_CAP  = 2_000_000   # hard read cap per page (2 MB)
PAGE_TEXT_CAP  = 6_000       # chars of extracted text kept per page
HTTP_TIMEOUT   = 6.0
FETCH_UA       = "Ph3b3-Metis/1.0 (+local research assistant)"


# ── Search safety gate (text) ─────────────────────────────────────────────────
# The image floor (morpheus.floor_check, applied in the server) covers CSAM /
# sexual / real-person categories. This complements it with the dangerous-
# INSTRUCTION class that a text search can seek: weapons/CBRN/explosives, illicit
# synthesis, weaponizing, self-harm methods. Applied to the QUERY and the SUMMARY.
# Honest limit (same as the image floor): a keyword gate stops casual misuse and
# accidental drift, not a determined adversary using euphemism. The model's own
# refusal is the first line; this is the belt-and-suspenders so a gated topic
# doesn't become fetchable just because the answer lives on the web.
# ACTIONABLE intent only — an action verb near a dangerous target — so "how to
# synthesize VX" is gated but "what is VX" / "history of chemical weapons" are not.
_DANGER_RE = re.compile(
    r"(?:how (?:to|do i) |steps? (?:to|for) |guide (?:to|for) |instructions? (?:to|for) |"
    r"recipe (?:to|for) |tutorial |synthesi[sz]e |manufactur\w* |produce |make |build |construct |cook )"
    r"[\w\s,'\"-]{0,40}?"
    r"\b(vx|sarin|tabun|soman|nerve agent|mustard gas|chemical weapon|bioweapon|"
    r"biological weapon|anthrax|weaponized ricin|botulinum toxin|bomb|explosive|ied|tatp|"
    r"napalm|meth|methamphetamine|fentanyl|ghost gun|untraceable firearm)\b"
    r"|\bpipe bomb\b|\bpressure[- ]?cooker bomb\b|\b3d[- ]?print(?:ed)? (?:gun|firearm)\b"
    r"|\bauto[- ]?sear\b|\bfull[- ]?auto conversion\b"
    r"|\b(?:how to |ways? to )(?:kill|hurt|harm) (?:myself|yourself)\b"
    r"|\bsuicide method\b|\bpainless way to die\b",
    re.I,
)


def query_gate(text: str) -> str | None:
    """Return a category string if `text` seeks a gated dangerous-instruction
    topic, else None. Complements morpheus.floor_check; both run on query + summary."""
    return "dangerous-instructions" if _DANGER_RE.search(text or "") else None


# ── Egress master switch (default OFF — the first egress ships dark) ───────────
def egress_enabled() -> bool:
    try:
        return bool(json.loads(EGRESS_PATH.read_text()).get("web_access", False))
    except Exception:
        return False


def set_egress(on: bool) -> dict:
    EGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    EGRESS_PATH.write_text(json.dumps({"web_access": bool(on)}))
    log.info("web egress %s", "ENABLED" if on else "DISABLED")
    return {"web_access": bool(on)}


# ── SearXNG (localhost only) ───────────────────────────────────────────────────
def searxng_up() -> bool:
    """True if the local SearXNG container answers. Fails fast (no hang)."""
    try:
        r = httpx.get(f"{SEARXNG_URL}/", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


# ── rate courtesy (a chatty session shouldn't hammer the backend) ──────────────
RATE_MAX    = 10          # searches per minute (one-per-turn already caps most of it)
RATE_WINDOW = 60.0
_recent: deque = deque()


def _rate_ok() -> bool:
    now = time.time()
    while _recent and now - _recent[0] > RATE_WINDOW:
        _recent.popleft()
    if len(_recent) >= RATE_MAX:
        return False
    _recent.append(now)
    return True


def _norm(items) -> list:
    """Normalize backend rows → [{title, url, snippet}], http(s) only, capped."""
    out = []
    for it in (items or []):
        url = it.get("url", "")
        if not url.startswith(("http://", "https://")):
            continue
        out.append({"title": (it.get("title") or "").strip(),
                    "url": url, "snippet": (it.get("content") or it.get("snippet") or "").strip()})
        if len(out) >= RESULT_CAP:
            break
    return out


def _searxng_search(query: str) -> list:
    r = httpx.get(f"{SEARXNG_URL}/search",
                  params={"q": query, "format": "json", "safesearch": 2},
                  headers={"User-Agent": FETCH_UA}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return _norm(r.json().get("results"))


# ── DuckDuckGo-direct FALLBACK (only if SearXNG is down) ───────────────────────
DDG_HTML   = "https://html.duckduckgo.com/html/"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def _decode_ddg_url(href: str) -> str:
    if "uddg=" in href:
        q = parse_qs(urlsplit(href).query)
        if q.get("uddg"):
            return unquote(q["uddg"][0])
    return ("https:" + href) if href.startswith("//") else href


def _ddg_search(query: str) -> list:
    """DuckDuckGo HTML endpoint, parsed with bs4. FALLBACK only. Raises
    SearchBroken if the markup isn't recognized (a changed scrape target is
    BROKEN, not empty); returns [] only on a genuine no-results page."""
    from bs4 import BeautifulSoup
    r = httpx.post(DDG_HTML, data={"q": query, "kp": "1"},   # kp=1 = safe-search strict
                   headers={"User-Agent": BROWSER_UA}, timeout=HTTP_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    anchors = soup.select("a.result__a")
    if not anchors:
        if soup.select_one(".no-results") or "No results" in soup.get_text():
            return []
        raise SearchBroken("DuckDuckGo markup unrecognized (no result anchors)")
    rows = []
    for a in anchors:
        block = a.find_parent(class_="result")
        snip = block.select_one(".result__snippet") if block else None
        rows.append({"title": a.get_text(" ").strip(),
                     "url": _decode_ddg_url(a.get("href", "")),
                     "snippet": snip.get_text(" ").strip() if snip else ""})
    out = _norm(rows)
    if not out:
        raise SearchBroken("DuckDuckGo anchors present but no usable URLs parsed")
    return out


def search(query: str) -> list:
    """PRIMARY: SearXNG (one retry). FALLBACK: DuckDuckGo-direct. If BOTH fail,
    raise SearchBroken — the tool speaks 'search is broken', NEVER a silent zero.
    A genuinely empty result set returns []."""
    if not _rate_ok():
        raise SearchBusy("web-search rate cap hit")
    errs = []
    for attempt in (1, 2):                          # SearXNG primary + one retry
        try:
            return _searxng_search(query)
        except Exception as e:
            errs.append(f"searxng#{attempt}: {e}")
    log.warning("[metis] SearXNG failed (%s) — DDG fallback", "; ".join(errs))
    try:
        return _ddg_search(query)                   # fallback
    except SearchBroken:
        raise
    except Exception as e:
        raise SearchBroken(f"both backends failed — {'; '.join(errs)}; ddg: {e}") from e


# ── SSRF-guarded fetch ─────────────────────────────────────────────────────────
def _ip_forbidden(ip: str) -> bool:
    """True if an IP is off-limits: loopback, RFC1918, link-local, CGNAT/tailnet
    (100.64/10), reserved, multicast, unspecified — anything not a public host."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
            or a.is_multicast or a.is_unspecified
            or a in ipaddress.ip_network("100.64.0.0/10"))   # CGNAT / Tailscale


def _host_ok(host: str) -> tuple[bool, str]:
    """Resolve host → reject if ANY resolved address is forbidden (no LAN/tailnet
    probing via Metis)."""
    if not host:
        return False, "no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        return False, f"dns fail: {e}"
    for info in infos:
        ip = info[4][0]
        if _ip_forbidden(ip):
            return False, f"host resolves to non-public address ({ip})"
    return True, "ok"


def fetch_page(url: str) -> tuple[str | None, str]:
    """Fetch + extract readable text from a URL, SSRF-guarded and size-capped.
    Returns (text, 'ok') or (None, reason). Never follows redirects; never touches
    a private/tailnet/loopback host."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None, f"refused scheme {parts.scheme!r}"
    ok, reason = _host_ok(parts.hostname or "")
    if not ok:
        log.warning("[metis] fetch refused %s — %s", url, reason)
        return None, reason
    try:
        with httpx.stream("GET", url, timeout=HTTP_TIMEOUT, follow_redirects=False,
                          headers={"User-Agent": FETCH_UA}) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                return None, f"redirect ({r.status_code}) not followed"
            if r.status_code != 200:
                return None, f"http {r.status_code}"
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype:
                return None, f"non-text content-type {ctype!r}"
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf.extend(chunk)
                if len(buf) > PAGE_BYTE_CAP:                  # hard cap
                    break
            html = bytes(buf[:PAGE_BYTE_CAP]).decode("utf-8", "replace")
    except Exception as e:
        return None, f"fetch error: {e}"
    return extract_text(html), "ok"


def extract_text(html: str) -> str:
    """Readable main text from HTML (bs4): drop script/style/nav/etc., collapse
    whitespace, cap length. Best-effort — this is untrusted input, not a document."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer",
                         "form", "svg", "iframe", "aside"]):
            tag.decompose()
        text = " ".join((soup.body or soup).get_text(" ").split())
    except Exception:
        import re
        text = " ".join(re.sub(r"<[^>]+>", " ", html).split())
    return text[:PAGE_TEXT_CAP]
