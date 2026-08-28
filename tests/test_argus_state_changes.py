"""
Argus state-change transitions — edge-triggered notification for silent devices.

WHY. The RHEA backup drive read SILENT for eight consecutive nights
(2026-08-21..28). Argus derived that state correctly the whole time — the
contract, the evaluate() logic and the fleet() enumeration were all right, and
this was verified before anything was written. What was missing is that nothing
recorded the MOMENT it changed, so nobody was told and "how long has this been
broken" had no answer outside the systemd journal.

The design constraint that matters: EDGE-triggered, not level-triggered. A drive
deliberately unplugged for a fortnight is reported once, not every tick for
fourteen days.
"""
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules"))

import argus  # noqa: E402

CONTRACTS = {"defaults": {"type": "service", "heartbeat_s": 30, "silent_after_s": 120},
             "devices": {"rhea": {"type": "service", "heartbeat_s": 86400,
                                  "silent_after_s": 93600}}}


@pytest.fixture
def store(tmp_path):
    return argus.ArgusStore(db_path=tmp_path / "argus.db")


def _states(store, dev="rhea"):
    return [(c["from_state"], c["to_state"]) for c in reversed(store.changes(device_id=dev))]


# ── the baseline ─────────────────────────────────────────────────────────────
def test_first_observation_records_a_baseline_not_an_alarm(store):
    """from_state NULL is a real transition (nothing -> something) but it is not
    news, and a caller deciding whether to interrupt a human must be able to
    tell the difference."""
    ch = store.record_transitions(CONTRACTS, now=1000.0)
    rhea = [c for c in ch if c["device_id"] == "rhea"]
    assert len(rhea) == 1
    assert rhea[0]["from_state"] is None
    assert rhea[0]["to_state"] == argus.SILENT      # never reported yet


# ── the whole point ──────────────────────────────────────────────────────────
def test_a_device_silent_for_eight_nights_is_reported_once(store):
    """The RHEA scenario, replayed. Eight days of ticks, one notification."""
    t = 1000.0
    store.record_transitions(CONTRACTS, now=t)       # baseline: SILENT
    fired = 0
    for _ in range(8 * 24 * 60):                     # eight days, one tick a minute
        t += 60
        fired += len(store.record_transitions(CONTRACTS, now=t))
    assert fired == 0, "a state that has not changed must not re-notify"
    assert len(store.changes(device_id="rhea")) == 1


def test_recovery_and_failure_are_both_reported(store):
    t = 1000.0
    store.record_transitions(CONTRACTS, now=t)       # baseline SILENT
    store.record_heartbeat("rhea", ts=int(t + 60))   # the backup runs
    ch = store.record_transitions(CONTRACTS, now=t + 120)
    assert ("SILENT", "HEALTHY") in [(c["from_state"], c["to_state"]) for c in ch]

    # ...then the drive is unplugged and the nightly run stops. 27h later:
    ch2 = store.record_transitions(CONTRACTS, now=t + 60 + 97200)
    assert ("HEALTHY", "SILENT") in [(c["from_state"], c["to_state"]) for c in ch2]
    assert _states(store) == [(None, "SILENT"), ("SILENT", "HEALTHY"), ("HEALTHY", "SILENT")]


def test_flapping_records_every_edge_but_never_a_repeat(store):
    t = 1000.0
    store.record_transitions(CONTRACTS, now=t)
    for i in range(3):
        store.record_heartbeat("rhea", ts=int(t + 1))
        store.record_transitions(CONTRACTS, now=t + 2)          # -> HEALTHY
        store.record_transitions(CONTRACTS, now=t + 2)          # same tick, no dupe
        t += 97200                                              # age past contract
        store.record_transitions(CONTRACTS, now=t)              # -> SILENT
    seq = _states(store)
    assert seq == [(None, "SILENT")] + [("SILENT", "HEALTHY"), ("HEALTHY", "SILENT")] * 3
    for a, b in zip(seq, seq[1:]):
        assert a[1] != b[1], "consecutive rows must differ — that is the edge rule"


# ── the question the heartbeat ring buffer cannot answer ─────────────────────
def test_last_healthy_survives_heartbeat_pruning(store):
    """Heartbeats are a pruned ring buffer; transitions are not. 'When did this
    last work' must still be answerable after the heartbeats are gone."""
    t = 1000.0
    store.record_transitions(CONTRACTS, now=t)
    store.record_heartbeat("rhea", ts=int(t + 60))
    store.record_transitions(CONTRACTS, now=t + 120)
    healthy_at = store.last_healthy("rhea")
    assert healthy_at is not None

    store.prune(days=0, now=t + 10_000_000)          # wipe the ring buffer
    assert store.history("rhea") == [], "precondition: heartbeats gone"
    assert store.last_healthy("rhea") == healthy_at, "transition history was pruned away"


def test_prune_never_deletes_transitions(store):
    store.record_transitions(CONTRACTS, now=1000.0)
    before = len(store.changes())
    store.prune(days=0, now=10_000_000.0)
    assert len(store.changes()) == before


# ── read surface ─────────────────────────────────────────────────────────────
def test_changes_is_most_recent_first_and_filterable(store):
    t = 1000.0
    store.record_transitions(CONTRACTS, now=t)
    store.record_heartbeat("rhea", ts=int(t + 60))
    store.record_transitions(CONTRACTS, now=t + 120)
    rows = store.changes(device_id="rhea")
    assert rows[0]["ts"] >= rows[-1]["ts"]
    assert {r["device_id"] for r in rows} == {"rhea"}


def test_observing_never_writes_a_heartbeat(store):
    """Read-only w.r.t. the fleet: recording a transition must not fabricate a
    check-in, or a silent device would appear to report by being observed."""
    store.record_transitions(CONTRACTS, now=1000.0)
    assert store.history("rhea") == []
    assert store.latest("rhea") is None
