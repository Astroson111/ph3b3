# Argus — spoof-heartbeat rejection verify

Closeout of the last item on the Argus brief's verify list: proof that a forged
or unverified heartbeat is **rejected and logged**, never silently ingested. This
is a **verification of shipped behavior** — no code changed. Re-run after any change
to the `/argus/heartbeat` handler (`agent/server.py`) or the auth middleware.

## Threat model

Two layers guard heartbeat ingest:

1. **Perimeter — shared Basic-auth.** Every heartbeat must carry the portal cred.
   An external attacker without it cannot inject *any* heartbeat (a forged
   `stackchan` included). This is the primary defense.
2. **Defense-in-depth — Dio IP-pin.** An *already-authenticated* LAN client that
   forges `X-Ph3b3-Device: stackchan` is rejected unless it originates from the
   camera-verified `dio_host` IP. Only Dio is IP-pinned; other devices ride the
   shared-cred trust model.

## Result — RUN + PASSED 2026-07-19

| Forgery | Expected | Observed |
|---|---|---|
| Unauthenticated heartbeat | 401 | **401** (perimeter fail-closed) |
| Oversize payload (>512 B) | 413 | **413** |
| Malformed JSON | 400 | **400** |
| Authed `stackchan` from IP ≠ `dio_host` | 403 + logged | **403 "unverified device identity"** + `[ARGUS] rejected spoofed heartbeat: 'stackchan' from 127.0.0.1 (verified dio_host=192.168.0.22)` |
| Genuine `stackchan` from the pinned IP | accepted, no false-reject | **accepted** `{"ok": true}` |

The 401/413/400 cases were exercised against the live server. The IP-pin 403 was
proven by invoking the real `argus_heartbeat` handler
(`agent/server.py`, guard at the `device == "stackchan"` check) in isolation with
`vision.dio_host` stubbed, so the result doesn't depend on Dio's live IP.

## Gotcha for re-runs

The real handler's **accept** path calls `argus_store.record_heartbeat`, which
writes to the shared `~/ph3b3_data/argus.db`. When testing the accept case in
isolation, **stub `argus_store.record_heartbeat` first** — otherwise the test
injects a real heartbeat row (and scrubbing it can collide with a device that is
genuinely beating at that moment). The reject paths (401/403/413/400) write
nothing and are always safe to run live.
