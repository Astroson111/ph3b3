#!/usr/bin/env bash
# ── Rhea RESTORE — MANUAL ONLY. Never auto-runs. ─────────────────────────────────
# Fresh Ubuntu + the RHEA drive → Phoebe's data back. This script is COPIED ONTO
# the drive (alongside a bundled restic binary), so it runs on a bare machine with
# zero dependencies. You supply the OFFLINE passphrase; it is never stored here.
#
#   sudo ./restore.sh                 # full restore to real locations (/)
#   sudo ./restore.sh --scratch DIR   # fire-drill: restore under DIR, touch nothing live
#
# RUN WITH sudo. The nightly backup runs as root (to capture /etc/wireguard), so
# restic writes its repo files mode 400 root-owned — only root can read them. Root
# is also needed to write /etc/wireguard and /home on a real restore. A full
# restore chowns the recovered user data back to astroson at the end.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "FATAL: run with sudo — the repo is root-owned (backup runs as root for /etc/wireguard)." >&2
  exit 1
fi

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"     # RHEA drive root (this script lives on the drive)
RESTIC_BIN="$SELF_DIR/bin/restic"
RESTIC_REPO="$SELF_DIR/restic"
REPO_URL="https://github.com/Astroson111/ph3b3.git"
FW_REPO_URL="https://github.com/Astroson111/Dionysus.git"

TARGET="/"; SCRATCH=0
if [ "${1:-}" = "--scratch" ]; then TARGET="${2:?--scratch needs a target dir}"; SCRATCH=1; fi
T="${TARGET%/}"                                # "" for /, "/scratch" otherwise
DATA="$T/home/astroson/ph3b3_data"
V2="$T/home/astroson/Desktop/ph3b3_v2_data"

echo "══════════════════════════════════════════════════════════════════════"
echo "  RHEA RESTORE — Phoebe's irreplaceable data from the encrypted backup"
[ "$SCRATCH" = 1 ] && echo "  SCRATCH/FIRE-DRILL MODE → $TARGET (nothing live is touched)"
echo "  You need the OFFLINE encryption passphrase. Ctrl-C to abort."
echo "══════════════════════════════════════════════════════════════════════"
read -r -p "Type YES to proceed: " ok; [ "$ok" = "YES" ] || { echo "aborted"; exit 1; }

[ -x "$RESTIC_BIN" ] || RESTIC_BIN="$(command -v restic || true)"
[ -n "$RESTIC_BIN" ] && [ -x "$RESTIC_BIN" ] || { echo "FATAL: no restic binary (expected $SELF_DIR/bin/restic)"; exit 1; }
[ -d "$RESTIC_REPO" ] || { echo "FATAL: restic repo not found at $RESTIC_REPO"; exit 1; }
export RESTIC_REPOSITORY="$RESTIC_REPO"
read -r -s -p "RHEA passphrase: " RESTIC_PASSWORD; echo; export RESTIC_PASSWORD

echo "── snapshots in the repo ──"
"$RESTIC_BIN" snapshots --compact || { echo "FATAL: cannot open repo (wrong passphrase?)"; exit 1; }

echo "── restoring latest snapshot → $TARGET ──"
mkdir -p "$TARGET"
"$RESTIC_BIN" restore latest --target "$TARGET"

# Put the CONSISTENT SQLite snapshots back over the live DB locations. A restored
# live *.db was excluded from the backup (only these .backup snapshots exist), and
# any stale -wal/-shm beside the destination must be removed or SQLite mis-reads.
SNAP="$DATA/.rhea-db-snapshots"
if [ -d "$SNAP" ]; then
  echo "── restoring SQLite DBs from consistent snapshots ──"
  for db in "$SNAP"/*.db; do
    [ -e "$db" ] || continue
    n="$(basename "$db")"
    if [ "$n" = "generations.db" ]; then dest="$V2/$n"; else dest="$DATA/$n"; fi
    mkdir -p "$(dirname "$dest")"
    cp -f "$db" "$dest"; rm -f "${dest}-wal" "${dest}-shm"
    echo "   DB → $dest"
  done
fi

if [ "$SCRATCH" = 1 ]; then
  echo ""
  echo "✔ SCRATCH restore complete under $TARGET — data + configs are there."
  echo "  Inspect it (e.g. sqlite3 $DATA/mnemosyne.db '.tables'), then delete the dir."
  exit 0
fi

# ── FULL restore: data is back. Restored as root → hand the user's data back. ──
echo "── restoring ownership of recovered user data to astroson ──"
for d in /home/astroson/ph3b3_data /home/astroson/Desktop/ph3b3_v2_data \
         /home/astroson/.config/rhea; do
  [ -e "$d" ] && chown -R astroson:astroson "$d" 2>/dev/null || true
done
# WireGuard / system units were restored under /etc — correctly root-owned; leave them.

echo ""
echo "✔ DATA + secrets restored to real locations (WireGuard → /etc/wireguard)."
echo ""
echo "REMAINING STEPS (code + models + services — machine-specific, do by hand):"
echo "  1. Clone the code:"
echo "       git clone $REPO_URL      ~/Desktop/ph3b3_v2"
echo "       git clone $FW_REPO_URL   ~/Desktop/Dionysus   # Dio firmware (optional)"
echo "     (.env, soul/, config/ were just restored — copy them into the fresh clone if newer.)"
echo "  2. Python env:  cd ~/Desktop/ph3b3_v2 && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
echo "  3. Re-pull models (NOT in this backup — re-downloadable):"
echo "       ollama pull ph3b3-chat:latest llava:latest hermes3:latest   # + whisper 'medium' auto-downloads"
echo "  4. Re-link services (need sudo):"
echo "       sudo cp ~/Desktop/ph3b3_v2/deploy/*.service ~/Desktop/ph3b3_v2/deploy/rhea/rhea-backup.* /etc/systemd/system/"
echo "       sudo systemctl daemon-reload && sudo systemctl enable --now ph3b3 argus rhea-backup.timer"
echo "  5. Verify: https://localhost:7331/panel  →  'Made with Soul' greeting, Mnemosyne recall, gating active."
echo ""
echo "See README.md on this drive for the full runbook."
