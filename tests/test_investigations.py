"""
Ghost Hunting investigation-sync HTTP tests (standalone, like test_kadmos_endpoint.py).

Imports the real server + FastAPI TestClient and drives the sync contract Dio
uses: upload each file of a bundle, then finalize, then list. Covers the three
recording modes' differing bundle shapes, the path refusals (the session id and
X-Inv-Path both arrive from a device header, so both are untrusted), and the
crash-truncated manifest case that NDJSON exists to survive.

INVESTIGATIONS_DIR is redirected at module scope — nothing here touches the real
~/Desktop/investigations.

Run:  .venv/bin/python tests/test_investigations.py
"""

import sys
import json
import base64
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))
sys.path.insert(0, str(REPO / "agent"))

import server
from fastapi.testclient import TestClient

_TMP = Path(tempfile.mkdtemp(prefix="inv_test_"))
server.INVESTIGATIONS_DIR = _TMP

client = TestClient(server.app)
_auth = base64.b64encode(f"{server.AUTH_USER}:{server.AUTH_PASS}".encode()).decode()
HEADERS = {"Authorization": f"Basic {_auth}"}

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}  {detail}")


def put(sid, rel, data: bytes):
    return client.post(f"/investigations/{sid}/file", content=data,
                       headers={**HEADERS, "X-Inv-Path": rel})


def ndjson(*objs) -> bytes:
    return ("".join(json.dumps(o) + "\n" for o in objs)).encode()


def env(t=18.4, h=52.0, p=101325.0, age=0, src="sht30"):
    return {"temp_c": t, "humidity_pct": h, "pressure_pa": p,
            "temp_source": src, "env_age_ms": age}


# ── 1. Record Room: ENV only, no media ───────────────────────────────────────
print("\n[1] Record Room — env only")
SID = "dio_20260729_210000"
lines = ndjson(
    {"type": "session_start", "ms": 0, "rtc": "2026-07-29T21:00:00",
     "session_id": SID, "device": "dio", "mode": "record_room",
     "env_unit": "env-iii", "audio": False, "photos": False,
     "sample_rate": 16000, "chunk_sec": 10},
    {"type": "env", "ms": 12, "rtc": "2026-07-29T21:00:00", **env()},
    {"type": "env", "ms": 5012, "rtc": "2026-07-29T21:00:05", **env(t=18.1)},
    {"type": "session_end", "ms": 9000, "rtc": "2026-07-29T21:00:09",
     "reason": "stopped", "env_samples": 2, "audio_chunks": 0, "photos": 0,
     "audio_gaps": 0, "duration_ms": 9000},
)
check("upload manifest.ndjson", put(SID, "manifest.ndjson", lines).status_code == 200)
r = client.post(f"/investigations/{SID}/finalize", headers=HEADERS)
check("finalize 200", r.status_code == 200, r.text)
check("mode is record_room", r.json()["mode"] == "record_room")

m = json.loads((_TMP / SID / "manifest.json").read_text())
check("2 env readings", m["counts"]["env"] == 2, m["counts"])
check("no captures", m["captures"] == [])
check("marked complete", m["complete"] is True)
check("started_at from RTC", m["started_at"] == "2026-07-29T21:00:00")
check("env readings carry values", m["env_readings"][0]["temp_c"] == 18.4)
# The bundle shape is identical across modes — empty dirs, not missing ones.
check("photos/ exists though empty", (_TMP / SID / "photos").is_dir())
check("audio/ exists though empty", (_TMP / SID / "audio").is_dir())
check("files listing empty", m["files"] == {"photos": [], "audio": []}, m["files"])


# ── 2. Live Capture: audio + photos, each carrying an ENV snapshot ───────────
print("\n[2] Live Capture — audio + photos + env per capture")
SID2 = "dio_20260729_213000"
lines = ndjson(
    {"type": "session_start", "ms": 0, "rtc": "2026-07-29T21:30:00",
     "session_id": SID2, "device": "dio", "mode": "live_capture",
     "env_unit": "env-iii", "audio": True, "photos": True,
     "sample_rate": 16000, "chunk_sec": 10},
    {"type": "env", "ms": 10, "rtc": "2026-07-29T21:30:00", **env()},
    {"type": "audio", "ms": 10120, "rtc": "2026-07-29T21:30:10",
     "file": "audio/chunk_0001.wav", "start_ms": 120, "duration_ms": 10000,
     "sample_rate": 16000, "channels": 1, "bits": 16, **env(age=10110)},
    {"type": "photo", "ms": 12000, "rtc": "2026-07-29T21:30:12",
     "file": "photos/photo_0001.jpg", "bytes": 8400, **env(age=11990)},
    {"type": "audio_gap", "ms": 12050, "rtc": "2026-07-29T21:30:12",
     "what": "mic_queue_underrun", "gaps": 1},
    {"type": "session_end", "ms": 20000, "rtc": "2026-07-29T21:30:20",
     "reason": "stopped", "env_samples": 1, "audio_chunks": 1, "photos": 1,
     "audio_gaps": 1, "duration_ms": 20000},
)
check("upload manifest", put(SID2, "manifest.ndjson", lines).status_code == 200)
check("upload wav",   put(SID2, "audio/chunk_0001.wav", b"RIFF" + b"\0" * 400).status_code == 200)
check("upload jpeg",  put(SID2, "photos/photo_0001.jpg", b"\xff\xd8\xff" + b"\0" * 200).status_code == 200)
r = client.post(f"/investigations/{SID2}/finalize", headers=HEADERS)
check("finalize 200", r.status_code == 200, r.text)

m = json.loads((_TMP / SID2 / "manifest.json").read_text())
kinds = [c["kind"] for c in m["captures"]]
check("one audio + one photo capture", kinds == ["audio", "photo"], kinds)
aud = m["captures"][0]
check("audio capture keeps its file path", aud["file"] == "audio/chunk_0001.wav")
check("audio capture has nested env", aud["env"]["temp_c"] == 18.4, aud["env"])
check("env age travels with the capture", aud["env"]["env_age_ms"] == 10110)
check("env fields not left at capture top level", "temp_c" not in aud, aud.keys())
check("photo bytes preserved", m["captures"][1]["bytes"] == 8400)
check("audio_gap counted", m["counts"]["audio_gap"] == 1, m["counts"])
check("files listing reflects disk", m["files"] == {"photos": ["photo_0001.jpg"],
                                                    "audio": ["chunk_0001.wav"]}, m["files"])
check("wav bytes landed intact", (_TMP / SID2 / "audio" / "chunk_0001.wav").stat().st_size == 404)
check("no .part leftovers", not list((_TMP / SID2 / "audio").glob("*.part")))


# ── 3. EVP Recorder cut short mid-session (flat battery) ─────────────────────
# The last line is a fragment, exactly what an append-only log looks like when
# power dies mid-write. Everything before it must still be recovered.
print("\n[3] EVP Recorder — crash-truncated manifest")
SID3 = "dio_20260729_220000"
good = ndjson(
    {"type": "session_start", "ms": 0, "rtc": "2026-07-29T22:00:00",
     "session_id": SID3, "device": "dio", "mode": "evp_recorder",
     "env_unit": "env-iii", "audio": True, "photos": False,
     "sample_rate": 16000, "chunk_sec": 10},
    {"type": "env", "ms": 8, "rtc": "2026-07-29T22:00:00", **env()},
)
truncated = good + b'{"type":"audio","ms":10008,"rtc":"2026-07-2'
check("upload truncated manifest", put(SID3, "manifest.ndjson", truncated).status_code == 200)
r = client.post(f"/investigations/{SID3}/finalize", headers=HEADERS)
check("finalize survives truncation", r.status_code == 200, r.text)
m = json.loads((_TMP / SID3 / "manifest.json").read_text())
check("whole lines recovered", m["counts"]["env"] == 1, m["counts"])
check("fragment counted, not fatal", m["truncated_lines"] == 1, m["truncated_lines"])
check("flagged incomplete (no session_end)", m["complete"] is False)
check("mode still readable", m["mode"] == "evp_recorder")


# ── 4. Untrusted-path refusals ───────────────────────────────────────────────
print("\n[4] path refusals")
for bad in ("../../../etc/passwd", "/etc/passwd", "audio/../../escape.wav",
            "..", ".hidden", "notes.txt", "audio/sub/dir/x.wav", ""):
    code = put(SID, bad, b"x").status_code
    check(f"refuse X-Inv-Path {bad!r}", code == 400, f"got {code}")
check("refuse manifest.json at root", put(SID, "manifest.json", b"{}").status_code == 400)
for bad_sid in ("../escape", "a/b", ".hidden", "with space"):
    code = client.post(f"/investigations/{bad_sid}/file", content=b"x",
                       headers={**HEADERS, "X-Inv-Path": "manifest.ndjson"}).status_code
    check(f"refuse session id {bad_sid!r}", code in (400, 404), f"got {code}")
check("nothing escaped the sandbox", not (_TMP.parent / "escape.wav").exists())

check("empty upload refused", put(SID, "manifest.ndjson", b"").status_code == 400)
check("finalize on unknown session 404",
      client.post("/investigations/dio_nope/finalize", headers=HEADERS).status_code == 404)


# ── 5. Idempotence + listing ─────────────────────────────────────────────────
print("\n[5] re-sync and listing")
before = json.loads((_TMP / SID2 / "manifest.json").read_text())
check("re-upload same file ok", put(SID2, "audio/chunk_0001.wav", b"RIFF" + b"\0" * 400).status_code == 200)
r2 = client.post(f"/investigations/{SID2}/finalize", headers=HEADERS)
check("re-finalize ok", r2.status_code == 200)
after = json.loads((_TMP / SID2 / "manifest.json").read_text())
# Only synced_at may move; a repeated sync must not duplicate captures or events.
check("re-finalize is stable", {k: v for k, v in after.items() if k != "synced_at"}
                            == {k: v for k, v in before.items() if k != "synced_at"})
check("still one wav on disk", len(list((_TMP / SID2 / "audio").glob("*.wav"))) == 1)

r = client.get("/investigations", headers=HEADERS)
check("listing 200", r.status_code == 200)
sids = [s["session_id"] for s in r.json()["sessions"]]
check("all three sessions listed", set(sids) == {SID, SID2, SID3}, sids)
check("newest first", sids == sorted(sids, reverse=True), sids)
check("listing carries mode", all(s.get("finalized") for s in r.json()["sessions"]))

check("auth required", client.get("/investigations").status_code in (401, 403))


shutil.rmtree(_TMP, ignore_errors=True)
print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
