#!/usr/bin/env bash
# ── Rhea: ROTATE the restic repository (destroys every existing snapshot) ─────────
#
# One-shot, deliberate operation. Deletes the repo on the RHEA drive and re-creates
# it under a NEW passphrase, then takes the first backup so you are protected again
# before this script exits. Use when the old snapshots or the old passphrase must
# not survive — NOT for routine maintenance.
#
# RUN WITH sudo (the repo is root-owned; the nightly job runs as root):
#   sudo /home/astroson/Desktop/ph3b3_v2/deploy/rhea/rhea-rotate.sh --burn
#
# THE OLD SNAPSHOTS ARE UNRECOVERABLE AFTERWARD. There is no second copy.
set -euo pipefail

RHEA_MNT="/mnt/rhea"
RHEA_UUID="dd7ef2c9-196c-4a15-ae8d-2c5a1dd9ef6f"   # the real drive; a same-labelled impostor must not match
RESTIC_REPO="$RHEA_MNT/restic"
RESTIC_BIN="$RHEA_MNT/bin/restic"
PASSFILE="/home/astroson/.config/rhea/passphrase"
BACKUP_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/rhea-backup.sh"

log()  { echo "[rhea-rotate] $*"; }
fail() { echo "[rhea-rotate] FAIL: $*" >&2; exit 1; }

# ── Guards ───────────────────────────────────────────────────────────────────────
[ "${1:-}" = "--burn" ] || fail "refusing to run without --burn (this destroys every snapshot)"
[ "$(id -u)" -eq 0 ]    || fail "run with sudo — the repo is root-owned"

mountpoint -q "$RHEA_MNT" || fail "RHEA is not mounted at $RHEA_MNT.
  The drive is present but unmounted → mount it first:  sudo mount $RHEA_MNT
  Never point this at the internal SSD."

ACTUAL_UUID="$(findmnt -no UUID "$RHEA_MNT")"
[ "$ACTUAL_UUID" = "$RHEA_UUID" ] || fail "wrong device on $RHEA_MNT (got $ACTUAL_UUID, want $RHEA_UUID)"
[ -x "$RESTIC_BIN" ] || fail "restic binary missing at $RESTIC_BIN — is this really the RHEA drive?"
[ -r "$BACKUP_SH" ]  || fail "cannot find rhea-backup.sh next to this script"

# ── What is about to be destroyed ────────────────────────────────────────────────
if [ -d "$RESTIC_REPO" ]; then
  log "existing repo: $RESTIC_REPO  ($(du -sh "$RESTIC_REPO" | cut -f1))"
  if [ -r "$PASSFILE" ] && SNAPS="$("$RESTIC_BIN" -r "$RESTIC_REPO" -p "$PASSFILE" snapshots --json 2>/dev/null)"; then
    log "snapshots to be destroyed: $(echo "$SNAPS" | grep -o '"short_id"' | wc -l)"
  else
    log "snapshots to be destroyed: unknown (current passphrase does not open this repo)"
  fi
else
  log "no existing repo at $RESTIC_REPO — this is an init, not a rotation"
fi

printf '\n  Type BURN to destroy the above and start a new encrypted repo: '
read -r CONFIRM
[ "$CONFIRM" = "BURN" ] || fail "aborted — nothing was touched"

# ── Rotate ───────────────────────────────────────────────────────────────────────
STAMP="$(date +%Y%m%d-%H%M%S)"
if [ -f "$PASSFILE" ]; then
  cp -a "$PASSFILE" "$PASSFILE.retired-$STAMP"
  chmod 600 "$PASSFILE.retired-$STAMP"
  log "old passphrase kept at $PASSFILE.retired-$STAMP (delete it once you are sure)"
fi

NEWPASS="$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | cut -c1-40)"
umask 077
printf '%s' "$NEWPASS" > "$PASSFILE"
chown astroson:astroson "$PASSFILE"
chmod 600 "$PASSFILE"

log "removing old repo..."
rm -rf "$RESTIC_REPO"

log "initialising new repo..."
"$RESTIC_BIN" init -r "$RESTIC_REPO" -p "$PASSFILE" >/dev/null || fail "restic init failed"

cat <<BANNER

  ╔══════════════════════════════════════════════════════════════════════════╗
  ║  NEW RHEA PASSPHRASE — RECORD IT OFFLINE NOW, BEFORE YOU CLOSE THIS      ║
  ║  Paper or password vault. The copy on this SSD dies with this SSD, and   ║
  ║  without an offline copy the new backups are dead weight.                ║
  ╚══════════════════════════════════════════════════════════════════════════╝

      $NEWPASS

BANNER
printf '  Type RECORDED once it is written down somewhere off this machine: '
read -r ACK
[ "$ACK" = "RECORDED" ] || log "WARN: not acknowledged — the passphrase is still at $PASSFILE, go copy it"

# ── First backup, so the rotation does not leave a protection gap ────────────────
log "taking the first backup into the new repo..."
"$BACKUP_SH" || fail "first backup failed — repo is initialised but EMPTY; fix and re-run rhea-backup.sh"

COUNT="$("$RESTIC_BIN" -r "$RESTIC_REPO" -p "$PASSFILE" snapshots --json | grep -o '"short_id"' | wc -l)"
[ "$COUNT" -ge 1 ] || fail "no snapshot present after the backup — you are UNPROTECTED, investigate now"
log "DONE — new repo holds $COUNT snapshot(s). Old snapshots are gone for good."
