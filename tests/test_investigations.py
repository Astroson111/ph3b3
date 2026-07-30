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
import investigation_module
from fastapi.testclient import TestClient

_TMP = Path(tempfile.mkdtemp(prefix="inv_test_"))
server.INVESTIGATIONS_DIR = _TMP

# Redirect the investigation records too. The module reads INVEST_DIR at call
# time, so rebinding the module global steers the already-constructed instance —
# which means these tests never read or write the operator's real hunt records.
_INV_TMP = Path(tempfile.mkdtemp(prefix="inv_records_"))
investigation_module.INVEST_DIR = _INV_TMP
server.investigation._active = None

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
    # temp_f mirrors what the device writes: derived from temp_c, sent alongside.
    return {"temp_c": t, "temp_f": round(t * 9 / 5 + 32, 2), "humidity_pct": h,
            "pressure_pa": p, "temp_source": src, "env_age_ms": age}


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
check("fahrenheit carried alongside", m["env_readings"][0]["temp_f"] == 65.12,
      m["env_readings"][0])
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
check("temp_f nested too, not leaked", "temp_f" in aud["env"] and "temp_f" not in aud,
      aud)
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


# ── 6. Joining a bundle to the investigation it was recorded during ──────────
# The two halves share no id: Phoebe records what the operator noticed, Dio
# records what she heard. They join on wall-clock time, and the payoff is that
# an EVP mark resolves to the audio chunk that actually contains it.
print("\n[6] investigation join")
from datetime import datetime, timedelta

base_t = datetime(2026, 7, 29, 21, 0, 0)

def iso(dt): return dt.isoformat()

# A hunt that ran 20:58 -> 21:10, with an EVP mark 25 s into Dio's recording.
hunt = {
    "session_id": "20260729_205800", "location": "the old library",
    "investigator": "Operator", "started": iso(base_t - timedelta(minutes=2)),
    "ended": iso(base_t + timedelta(minutes=10)), "events": [],
    "evp_timestamps": [{"time": iso(base_t + timedelta(seconds=25)), "note": "whisper, back stairs"}],
    "emf_readings": [], "anomalies": [], "notes": [], "weather": None,
    "device_sessions": [],
}
(_INV_TMP / "20260729_205800.json").write_text(json.dumps(hunt, indent=2))

# Distinct from section 1's bundle — same wall-clock start (the join is on RTC,
# not on the id), but its own directory, so neither test overwrites the other.
SID6 = "dio_hunt_20260729_210000"
lines = ndjson(
    {"type": "session_start", "ms": 0, "rtc": iso(base_t),
     "session_id": SID6, "device": "dio", "mode": "evp_recorder",
     "env_unit": "env-iii", "audio": True, "photos": False,
     "sample_rate": 16000, "chunk_sec": 10},
    {"type": "env", "ms": 5, "rtc": iso(base_t), **env()},
    # chunk 1 covers 0-10 s, chunk 2 covers 10-20 s, chunk 3 covers 20-30 s
    {"type": "audio", "ms": 10000, "rtc": iso(base_t + timedelta(seconds=10)),
     "file": "audio/chunk_0001.wav", "start_ms": 0, "duration_ms": 10000,
     "sample_rate": 16000, "channels": 1, "bits": 16, **env()},
    {"type": "audio", "ms": 20000, "rtc": iso(base_t + timedelta(seconds=20)),
     "file": "audio/chunk_0002.wav", "start_ms": 10000, "duration_ms": 10000,
     "sample_rate": 16000, "channels": 1, "bits": 16, **env()},
    {"type": "audio", "ms": 30000, "rtc": iso(base_t + timedelta(seconds=30)),
     "file": "audio/chunk_0003.wav", "start_ms": 20000, "duration_ms": 10000,
     "sample_rate": 16000, "channels": 1, "bits": 16, **env()},
    {"type": "session_end", "ms": 30000, "rtc": iso(base_t + timedelta(seconds=30)),
     "reason": "stopped", "env_samples": 1, "audio_chunks": 3, "photos": 0,
     "audio_gaps": 0, "duration_ms": 30000},
)
check("upload", put(SID6, "manifest.ndjson", lines).status_code == 200)
r = client.post(f"/investigations/{SID6}/finalize", headers=HEADERS)
check("finalize 200", r.status_code == 200, r.text)
check("linked to the hunt", r.json()["investigation"] == "20260729_205800", r.json())
check("one mark carried over", r.json()["marks"] == 1, r.json())

m = json.loads((_TMP / SID6 / "manifest.json").read_text())
blk = m["investigation"]
check("location on the bundle", blk["location"] == "the old library")
check("matched by time window", blk["match"] == "time_window")
mark = blk["marks"][0]
check("mark offset is 25 s", mark["offset_ms"] == 25000, mark)
# 25 s falls in chunk 3 (20-30 s), 5 s into that file. This is the whole point.
check("EVP resolves to chunk_0003", mark["audio_file"] == "audio/chunk_0003.wav", mark)
check("and to 5 s into it", mark["offset_in_file_ms"] == 5000, mark)

rec = json.loads((_INV_TMP / "20260729_205800.json").read_text())
check("hunt record gained the bundle", len(rec["device_sessions"]) == 1, rec.get("device_sessions"))
check("back-link carries counts", rec["device_sessions"][0]["counts"]["audio"] == 3)
check("back-link carries the path", SID6 in rec["device_sessions"][0]["path"])

# Re-sync must update in place, not duplicate.
client.post(f"/investigations/{SID6}/finalize", headers=HEADERS)
rec = json.loads((_INV_TMP / "20260729_205800.json").read_text())
check("re-link is idempotent", len(rec["device_sessions"]) == 1, rec.get("device_sessions"))


# ── 7. What must NOT be linked ───────────────────────────────────────────────
print("\n[7] mislinking refused")
# A record left open before a restart is stale, not ongoing. There is a real one
# on disk from 2026-07-16, and it must not swallow every later recording.
stale = dict(hunt, session_id="20260716_220317",
             started="2026-07-16T22:03:17", ended=None,
             evp_timestamps=[], device_sessions=[])
(_INV_TMP / "20260716_220317.json").write_text(json.dumps(stale, indent=2))

SID7 = "dio_20260801_120000"
far = datetime(2026, 8, 1, 12, 0, 0)
lines = ndjson(
    {"type": "session_start", "ms": 0, "rtc": iso(far), "session_id": SID7,
     "device": "dio", "mode": "record_room", "env_unit": "env-iii",
     "audio": False, "photos": False, "sample_rate": 16000, "chunk_sec": 10},
    {"type": "env", "ms": 5, "rtc": iso(far), **env()},
    {"type": "session_end", "ms": 9000, "rtc": iso(far + timedelta(seconds=9)),
     "reason": "stopped", "env_samples": 1, "audio_chunks": 0, "photos": 0,
     "audio_gaps": 0, "duration_ms": 9000},
)
put(SID7, "manifest.ndjson", lines)
r = client.post(f"/investigations/{SID7}/finalize", headers=HEADERS)
check("stale open record does not claim it", r.json()["investigation"] is None, r.json())
m7 = json.loads((_TMP / SID7 / "manifest.json").read_text())
check("manifest says investigation: null", m7["investigation"] is None)
rec_stale = json.loads((_INV_TMP / "20260716_220317.json").read_text())
check("stale record untouched", not rec_stale.get("device_sessions"))

# A mark logged outside the recording's own span belongs to neither bundle.
hunt2 = json.loads((_INV_TMP / "20260729_205800.json").read_text())
hunt2["notes"] = [{"time": iso(base_t + timedelta(minutes=5)), "note": "after Dio stopped"}]
(_INV_TMP / "20260729_205800.json").write_text(json.dumps(hunt2, indent=2))
client.post(f"/investigations/{SID6}/finalize", headers=HEADERS)
m6 = json.loads((_TMP / SID6 / "manifest.json").read_text())
kinds = [k["kind"] for k in m6["investigation"]["marks"]]
check("out-of-span note excluded", "note" not in kinds, kinds)
check("in-span EVP still there", "evp" in kinds, kinds)

shutil.rmtree(_INV_TMP, ignore_errors=True)
shutil.rmtree(_TMP, ignore_errors=True)
print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
