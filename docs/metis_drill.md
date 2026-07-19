# Metis — container-kill drill

Operational verification that a dead search backend degrades safely, is visible to
the operator, speaks honestly, and self-heals. This is a **verification of shipped
behavior** — no code changed. Re-run it after any change to `modules/metis.py`,
the `_metis_heartbeat` task, or the `metis` Argus contract.

## Procedure

1. Baseline: `metis` HEALTHY in Argus, `searxng_up()` True, egress OFF (default).
2. `podman stop metis-searxng`.
3. Observe degradation, loud-on-broken, and the Argus SILENT transition.
4. `podman start metis-searxng`; observe recovery.

## Result — RUN + PASSED 2026-07-19

| Stage | Expected | Observed |
|---|---|---|
| Kill container | `searxng_up()` → False | flipped True→False instantly |
| Graceful degradation | search still serves via DDG fallback | `search()` returned 6 real results via DuckDuckGo |
| Loud-on-broken | both backends down → `SearchBroken`, never silent zero | raised `SearchBroken`; server speaks *"Web search is broken right now… That's broken, not empty; try again in a bit."* |
| Argus visibility | heartbeat freezes → `metis` SILENT at `silent_after_s=180` | flipped to SILENT once >180s since last beat |
| Restart | `searxng_up()` recovers | True again in 2s |
| Argus recovery | `metis` → HEALTHY on next heartbeat | HEALTHY within 10s |

Egress stayed OFF (shipped default) throughout.

## Timing note

The heartbeat records every 60s only while `searxng_up()` is True, and Argus marks
`metis` SILENT when it's been >180s since the last beat. A poll started *after* the
last beat will see SILENT sooner than 180s from its own start — that's the 180s
clock having begun before the poll, **not** an early false alarm. Measure the
window from the last recorded heartbeat, not from when you started watching.
