#!/usr/bin/env python3
"""
argus_daemon.py — Argus's own heartbeat + ring-buffer pruner.

Runs as a SEPARATE systemd service (argus.service, Restart=always), independent
of the main ph3b3 server and the fleet. Killing this daemon leaves device
check-ins and the main server untouched — only Argus's own liveness row stops,
and that gap is visible in the argus_self table until systemd revives it.

Each tick it writes a self-heartbeat and, hourly, prunes the ring buffer to the
retention window. Read-only w.r.t. the fleet: it observes and records, never acts
on any device (no restart / reflash / delete anywhere).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "modules"))
from argus import ArgusStore, RETENTION_D   # noqa: E402

SELF_INTERVAL_S  = 30      # write our own heartbeat this often
PRUNE_INTERVAL_S = 3600    # prune the ring buffer hourly


def _nyx_stats():
    """Free system memory (bytes) + uptime (s) — the daemon runs ON Nyx, so it is
    the Nyx-local heartbeat source. free_heap here is the Nyx leak canary."""
    free = up = None
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                free = int(line.split()[1]) * 1024
                break
    except Exception:
        pass
    try:
        up = int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        pass
    return free, up


def main() -> None:
    store = ArgusStore()
    last_prune = 0.0
    while True:
        now = time.time()
        try:
            store.record_self(ts=int(now))
            free, up = _nyx_stats()               # Nyx-local heartbeat (this host)
            store.record_heartbeat("nyx", free_heap=free, uptime=up, ts=int(now))
            if now - last_prune >= PRUNE_INTERVAL_S:
                store.prune(days=RETENTION_D, now=now)
                last_prune = now
        except Exception as e:
            # Never die on a transient DB hiccup — systemd restart is the backstop,
            # but a single bad write shouldn't take the daemon down.
            print(f"[argus-daemon] tick error: {e}", flush=True)
        time.sleep(SELF_INTERVAL_S)


if __name__ == "__main__":
    main()
