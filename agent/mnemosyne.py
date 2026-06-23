"""
mnemosyne.py — Jamendo music provider for the Karaoke library.

Mnemosyne: Titaness of Memory, mother of the nine Muses.
She is the source before the performance.

Clean-by-construction:
  - Only Jamendo tracks where audiodownload_allowed is True are returned or pulled.
  - Attribution JSON is written atomically with every downloaded track.
  - No generic URL path exists in this module.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

log = logging.getLogger("ph3b3.mnemosyne")

JAMENDO_BASE = "https://api.jamendo.com/v3.0"
_CLIENT_ID: str = ""


def init(client_id: str) -> None:
    global _CLIENT_ID
    _CLIENT_ID = client_id
    if client_id:
        log.info("Mnemosyne ready — Jamendo client_id: %s…", client_id[:4])
    else:
        log.warning("Mnemosyne: JAMENDO_CLIENT_ID not set — discover/pull will return 503")


def _client_id() -> str:
    if not _CLIENT_ID:
        raise RuntimeError("JAMENDO_CLIENT_ID not configured")
    return _CLIENT_ID


# ── Sanitise a track name into a safe filesystem stem ─────────────────────────

_SAFE_RE = re.compile(r"[^a-z0-9\-]")

def _stem(raw: str, max_len: int = 24) -> str:
    s = raw.lower().replace(" ", "-").replace("_", "-")
    s = _SAFE_RE.sub("", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return (s or "track")[:max_len]


# ── Track shape returned to callers ───────────────────────────────────────────

def _shape(t: dict) -> dict:
    return {
        "id":                   t["id"],
        "name":                 t["name"],
        "artist_name":          t.get("artist_name", ""),
        "artist_id":            t.get("artist_id", ""),
        "album_name":           t.get("album_name", ""),
        "duration":             t.get("duration", 0),
        "license_ccurl":        t.get("license_ccurl", ""),
        "shareurl":             t.get("shareurl", ""),
        "audiodownload":        t.get("audiodownload", ""),
        "audiodownload_allowed": t.get("audiodownload_allowed", False),
        "image":                t.get("image", ""),
        "stem":                 _stem(t.get("name", "track")),
    }


# ── Discover ──────────────────────────────────────────────────────────────────

async def _head_ok(client: httpx.AsyncClient, url: str) -> bool:
    """Return True if a HEAD request to url gives a 2xx response."""
    try:
        r = await client.head(url, follow_redirects=True, timeout=8)
        return r.status_code < 300
    except Exception:
        return False


async def discover(
    query: str | None = None,
    tags: str | None = None,
    limit: int = 6,
) -> list[dict]:
    """Return up to `limit` downloadable Jamendo tracks.

    With no query/tags: popular tracks (surprise-me).
    query: freetext search against track name.
    tags:  comma-separated genre tags (e.g. "pop", "rock,upbeat").

    Each returned track's download URL is HEAD-checked so broken CDN
    entries are silently filtered out before reaching the caller.
    """
    params: dict = {
        "client_id": _client_id(),
        "format":    "json",
        "limit":     limit * 3,   # over-fetch: room to filter flagged + broken
        "boost":     "popularity_month",
    }
    if query:
        params["namesearch"] = query
    if tags:
        params["tags"] = tags

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{JAMENDO_BASE}/tracks/", params=params)
        r.raise_for_status()
        data = r.json()

        candidates = [_shape(t) for t in data.get("results", [])
                      if t.get("audiodownload_allowed") is True
                      and t.get("audiodownload")]

        # Parallel HEAD checks — filter any with broken CDN URLs
        checks = await asyncio.gather(
            *[_head_ok(client, t["audiodownload"]) for t in candidates]
        )

    live = [t for t, ok in zip(candidates, checks) if ok]
    return live[:limit]


# ── Pull ──────────────────────────────────────────────────────────────────────

def _ffmpeg_convert(src: str, dst: str) -> list[str]:
    """44.1kHz stereo pcm_s16le — synchronous, run in executor."""
    cmd = ["ffmpeg", "-y", "-i", src, "-ar", "44100", "-ac", "2",
           "-c:a", "pcm_s16le", dst]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-800:])
    return [f"ffmpeg 44100Hz stereo pcm_s16le → {Path(dst).name}", "✓ conversion complete"]


async def pull(track_id: str, lib_dir: Path) -> dict:
    """Download a Jamendo track, convert to WAV, store in lib_dir with attribution.

    Returns a dict: {stem, wav_path, attribution, log_lines}
    Raises:
        RuntimeError("JAMENDO_CLIENT_ID not configured")
        PermissionError  — audiodownload_allowed is False
        FileExistsError  — a track with this stem already exists in lib
        RuntimeError     — ffmpeg failure or download error
    """
    log_lines: list[str] = []

    # 1. Fetch metadata
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{JAMENDO_BASE}/tracks/",
            params={"client_id": _client_id(), "format": "json", "id": track_id},
        )
        r.raise_for_status()
        results = r.json().get("results", [])

    if not results:
        raise ValueError(f"Jamendo track {track_id!r} not found")

    raw = results[0]
    if not raw.get("audiodownload_allowed"):
        raise PermissionError(
            f"Track {track_id} is not available for download "
            f"(audiodownload_allowed=False) — skipped."
        )
    download_url = raw.get("audiodownload", "")
    if not download_url:
        raise PermissionError(f"Track {track_id} has no download URL.")

    stem = _stem(raw.get("name", "track"))
    wav_path = lib_dir / f"{stem}.wav"
    attr_path = lib_dir / f"{stem}.attribution.json"

    if wav_path.exists():
        raise FileExistsError(f"'{stem}' already in library — delete it first to re-pull.")

    log_lines.append(f"pulling '{raw['name']}' by {raw.get('artist_name', '?')} (id {track_id})")

    # 2. Download to tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", download_url) as resp:
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"Jamendo CDN returned {resp.status_code} for track {track_id}. "
                        "This track's download URL is currently broken — try another."
                    )
                with open(tmp_path, "wb") as fh:
                    async for chunk in resp.aiter_bytes(65536):
                        fh.write(chunk)

        size_kb = Path(tmp_path).stat().st_size // 1024
        log_lines.append(f"✓ downloaded {size_kb} KB")

        # 3. Convert
        new_lines = await asyncio.get_event_loop().run_in_executor(
            None, _ffmpeg_convert, tmp_path, str(wav_path)
        )
        log_lines.extend(new_lines)

    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 4. Write attribution atomically (write to tmp, then rename)
    attribution = {
        "source":         "jamendo",
        "track_id":       str(track_id),
        "track_name":     raw.get("name", ""),
        "artist_name":    raw.get("artist_name", ""),
        "artist_id":      str(raw.get("artist_id", "")),
        "album_name":     raw.get("album_name", ""),
        "license_cc_url": raw.get("license_ccurl", ""),
        "jamendo_url":    raw.get("shareurl", ""),
        "fetched_at":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp_attr = attr_path.with_suffix(".tmp")
    tmp_attr.write_text(json.dumps(attribution, indent=2))
    tmp_attr.rename(attr_path)
    log_lines.append("✓ attribution saved")

    return {
        "stem":        stem,
        "wav_path":    str(wav_path),
        "attribution": attribution,
        "log":         log_lines,
    }
