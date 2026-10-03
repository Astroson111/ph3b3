#!/usr/bin/env bash
# ── Rhea: nightly encrypted, deduplicated backup of Phoebe's irreplaceable data ──
# to the external RHEA drive (restic). No single point of failure: if Nyx's SSD
# dies, this + the offline passphrase restores Phoebe onto any machine.
#
# HARD RULE: if the RHEA drive is not mounted, FAIL LOUDLY and exit non-zero.
# NEVER fall back to the internal SSD — that would fake safety on the same disk
# that just died. A failed run sends no heartbeat → Argus flags 'rhea' SILENT.
set -euo pipefail

RHEA_MNT="${RHEA_MNT:-/mnt/rhea}"                 # overridable only to test the drive-missing guard
RESTIC_REPO="$RHEA_MNT/restic"
RESTIC_BIN="$RHEA_MNT/bin/restic"                 # binary lives ON the drive (self-contained restore)
PASSFILE="/home/astroson/.config/rhea/passphrase" # ABSOLUTE (service runs as root → $HOME is /root); on the INTERNAL SSD, not the drive (stolen drive ≠ decryptable)
PH3B3_DIR="/home/astroson/Desktop/ph3b3_v2"
DATA_DIR="/home/astroson/ph3b3_data"
V2DATA_DIR="/home/astroson/Desktop/ph3b3_v2_data"
THOTH_DIR="/home/astroson/ph3b3_thoth"            # sacred-text corpus + its vector index
HISTORY_ARCHIVE="/home/astroson/ph3b3-history-archive.git" # offline bare mirror of the git history; no remote, never pushed
DISK_SICK_PCT=80                                  # >this% used → Argus flags rhea SICK (space warning)

SQLITE_STAGE="$DATA_DIR/.rhea-db-snapshots"        # STABLE path (not mktemp) so restore can find them

log()  { echo "[rhea-backup] $*"; }
fail() { echo "[rhea-backup] FAIL: $*" >&2; exit 1; }   # no heartbeat on failure → SILENT within contract

# ── 1. GUARD — the drive must really be the RHEA drive, mounted. No SSD fallback ──
mountpoint -q "$RHEA_MNT"                       || fail "RHEA not mounted at $RHEA_MNT — refusing (NO internal-SSD fallback)"
[ "$(findmnt -no LABEL "$RHEA_MNT")" = "RHEA" ] || fail "$RHEA_MNT is mounted but is NOT the RHEA drive (label mismatch)"
[ -x "$RESTIC_BIN" ]                            || fail "restic binary missing at $RESTIC_BIN"
[ -r "$PASSFILE" ]                              || fail "passphrase file missing/unreadable at $PASSFILE"

export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD_FILE="$PASSFILE"

# ── 2. Consistent SQLite snapshots — NEVER a live-file copy mid-write ─────────────
# SQLite's online backup API checkpoints the WAL into a single consistent file
# (safe to run while the server holds the DB open). Uses python3's sqlite3 module
# — no sqlite3 CLI dependency, and python3 is present on any fresh Ubuntu restore
# box. The live *.db / *.db-wal / *.db-shm are EXCLUDED from the tree backup
# below; these snapshots are the authoritative copy.
log "snapshotting SQLite DBs (consistent online backup)..."
mkdir -p "$SQLITE_STAGE"
# NB: recipes.db is deliberately NOT here — it's the 2.7GB RecipeNLG *dataset*
# (re-downloadable bulk, same as the excluded RecipeNLG_code), not identity data.
for db in "$DATA_DIR"/mnemosyne.db "$DATA_DIR"/argus.db "$V2DATA_DIR"/generations.db "$THOTH_DIR"/thoth.db; do
  [ -f "$db" ] || continue
  name="$(basename "$db")"
  rm -f "$SQLITE_STAGE/$name"
  python3 -c 'import sqlite3,sys
s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2])
s.backup(d); d.close(); s.close()' "$db" "$SQLITE_STAGE/$name" || fail "sqlite online backup failed for $name"
  log "  snapshot: $name ($(du -h "$SQLITE_STAGE/$name" | cut -f1))"
done

# ── 3. restic backup — the irreplaceable set. Models/venvs/caches EXCLUDED ────────
# System configs (root-owned): WireGuard keys + the deployed systemd units. Only
# added if READABLE, so an astroson-run test skips them gracefully; the root
# service (its real home) captures them. Standing invariants — backed up, never modified.
SYS_PATHS=()
for p in /etc/wireguard \
         /etc/systemd/system/ph3b3.service \
         /etc/systemd/system/argus.service \
         /etc/systemd/system/rhea-backup.service \
         /etc/systemd/system/rhea-backup.timer; do
  [ -r "$p" ] && SYS_PATHS+=("$p")
done
[ "${#SYS_PATHS[@]}" -gt 0 ] && log "system configs: ${SYS_PATHS[*]}"

# Offline mirror of the git history — survives losing GitHub or the account, not just
# the SSD. It is bare with no remote, so this backup is its only copy off this disk;
# if it is missing we say so and keep going (optional, unlike Phoebe's data).
ARCHIVE_PATHS=()
if [ -d "$HISTORY_ARCHIVE" ]; then ARCHIVE_PATHS+=("$HISTORY_ARCHIVE"); log "history archive: $HISTORY_ARCHIVE"
else log "WARN: history archive not found at $HISTORY_ARCHIVE — skipping"; fi

log "restic backup..."
# THOTH (added 2026-10-03, Captain's call at Rung 1): the corpus texts are
# re-fetchable and the vectors re-derivable in ~3.5 min, so this was outside the
# sweep by a defensible decision. It stops being defensible at Rung 5, whose OCR
# works are NOT re-downloadable — and a manifest that says where a text came from
# is identity data even when the text is not. thoth.db rides the SQLite
# online-snapshot path above (the server holds it open); the live file and the
# re-derivable embedding cache are excluded from the tree copy.
#
# EXCLUDED ON PURPOSE (re-downloadable bulk, not identity data):
#   voices/  — ~1.3 GB of Piper .onnx models, re-fetched hash-pinned by setup.sh.
#              The voice REGISTRY that describes them (config/voices.yaml) IS backed
#              up via "$PH3B3_DIR/config" below, so the choice of voices survives; the
#              weights don't need to.
"$RESTIC_BIN" backup --tag nightly --exclude-caches \
  --exclude "$DATA_DIR"/'*.db' --exclude "$DATA_DIR"/'*.db-wal' --exclude "$DATA_DIR"/'*.db-shm' \
  --exclude "$V2DATA_DIR"/'*.db' --exclude "$V2DATA_DIR"/'*.db-wal' --exclude "$V2DATA_DIR"/'*.db-shm' \
  --exclude "$DATA_DIR/sd_backup_16gb_20260704" \
  --exclude "$DATA_DIR/RecipeNLG_code" \
  --exclude "$DATA_DIR/RecipeNLG_paper.pdf" \
  --exclude "$DATA_DIR/RecipeNLG_license.png" \
  --exclude "$DATA_DIR/edit_scratch" \
  --exclude "$DATA_DIR/voices" \
  --exclude "$THOTH_DIR"/'*.db' --exclude "$THOTH_DIR"/'*.db-wal' --exclude "$THOTH_DIR"/'*.db-shm' \
  --exclude "$THOTH_DIR"/'*.bak-*' \
  --exclude "$THOTH_DIR/cache" \
  "$DATA_DIR" \
  "$THOTH_DIR" \
  "$V2DATA_DIR" \
  "$PH3B3_DIR/.env" \
  "$PH3B3_DIR/soul" \
  "$PH3B3_DIR/config" \
  "$PH3B3_DIR/deploy" \
  ${ARCHIVE_PATHS[@]+"${ARCHIVE_PATHS[@]}"} \
  ${SYS_PATHS[@]+"${SYS_PATHS[@]}"} \
  || fail "restic backup failed"

# ── 4. Retention: 7 daily / 4 weekly / 6 monthly, auto-prune ──────────────────────
log "prune (keep 7d/4w/6m)..."
"$RESTIC_BIN" forget --tag nightly --prune \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6 || fail "restic prune failed"

# ── 5. Disk check → Argus heartbeat as device 'rhea' ──────────────────────────────
# free_heap carries the drive's FREE BYTES; the rhea contract's free_heap_below
# (= 20% of capacity) flags SICK when the drive exceeds 80% used. No new plumbing.
FREE_BYTES="$(df -B1 --output=avail "$RHEA_MNT" | tail -1 | tr -dc '0-9')"
USED_PCT="$(df --output=pcent "$RHEA_MNT" | tail -1 | tr -dc '0-9')"
UPTIME_S="$(cut -d. -f1 /proc/uptime)"
[ "${USED_PCT:-0}" -ge "$DISK_SICK_PCT" ] && log "WARNING: RHEA ${USED_PCT}% used (>= ${DISK_SICK_PCT}% → Argus SICK; revisit prune)"

set -a; . "$PH3B3_DIR/.env"; set +a           # PH3B3_USER / PH3B3_PASSWORD for the check-in
if curl -skf -u "${PH3B3_USER}:${PH3B3_PASSWORD}" \
      -H "X-Ph3b3-Device: rhea" -H "Content-Type: application/json" \
      -d "{\"free_heap\":${FREE_BYTES},\"uptime\":${UPTIME_S}}" \
      https://localhost:7331/argus/heartbeat >/dev/null; then
  log "Argus heartbeat sent (rhea, ${USED_PCT}% used)"
else
  log "WARN: Argus heartbeat POST failed — backup itself succeeded"
fi

log "DONE — backup + prune complete, RHEA ${USED_PCT}% used"
