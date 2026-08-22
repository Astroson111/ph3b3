#!/usr/bin/env bash
# Rhea — put the passphrase where a restore can actually reach it.
#
# THE PROBLEM THIS FIXES: the passphrase lived only at
# ~/.config/rhea/passphrase, on Nyx. Nyx is the machine the backup exists
# because you no longer have. Its disk dying took the only copy of the key, and
# every snapshot on the drive became permanently unreadable — Rhea defeated by
# Rhea's own key management.
#
# This copies the key onto the RHEA drive beside the repo it opens, so
# rhea-restore.sh needs nothing but the drive, and prints a paper copy so the key
# survives losing the drive as well.
#
#   sudo ./rhea-seed-key.sh            copy the key to the drive, show the paper copy
#   sudo ./rhea-seed-key.sh --check    report where the key exists, change nothing
#
# BE CLEAR ABOUT THE TRADE: with the key on the drive, encryption no longer
# protects you against someone taking the drive. It still covers an RMA, a
# resale, or an image taken in passing — and the repo stays encrypted, so this
# is reversible by deleting the keyfile.
set -euo pipefail

RHEA_MNT="${RHEA_MNT:-/mnt/rhea}"
PASSFILE="${PASSFILE:-/home/astroson/.config/rhea/passphrase}"
KEYFILE="$RHEA_MNT/rhea-passphrase.txt"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

echo "── Rhea key placement ───────────────────────────────────────────"

have_source=0
[ -r "$PASSFILE" ] && have_source=1
echo "  on Nyx   ($PASSFILE): $([ "$have_source" = 1 ] && echo present || echo MISSING)"

mounted=0
if findmnt -no TARGET "$RHEA_MNT" >/dev/null 2>&1; then
  if [ "$(findmnt -no LABEL "$RHEA_MNT")" = "RHEA" ]; then
    mounted=1
  else
    echo "  FATAL: $RHEA_MNT is mounted but is NOT the RHEA drive (label mismatch)" >&2
    exit 1
  fi
fi
echo "  drive    ($RHEA_MNT): $([ "$mounted" = 1 ] && echo mounted || echo "not mounted")"
[ "$mounted" = 1 ] && echo "  keyfile  ($KEYFILE): $([ -r "$KEYFILE" ] && echo present || echo absent)"

if [ "$CHECK" = 1 ]; then
  echo
  if [ "$mounted" = 1 ] && [ -r "$KEYFILE" ]; then
    if [ "$have_source" = 1 ] && ! diff -q <(tr -d '\r\n' < "$PASSFILE") <(tr -d '\r\n' < "$KEYFILE") >/dev/null; then
      echo "  WARNING: the key on the drive does NOT match the key on Nyx."
      echo "  The drive's copy is the one a restore will use. Work out which is right"
      echo "  before touching either — a wrong key here is an unreadable backup."
      exit 1
    fi
    echo "  OK — a restore from this drive needs nothing else."
  else
    echo "  NOT plug and play yet: run without --check to place the key."
  fi
  exit 0
fi

[ "$have_source" = 1 ] || { echo "FATAL: no passphrase at $PASSFILE to copy" >&2; exit 1; }
[ "$mounted" = 1 ]     || { echo "FATAL: plug in the RHEA drive first" >&2; exit 1; }

if [ -r "$KEYFILE" ] && ! diff -q <(tr -d '\r\n' < "$PASSFILE") <(tr -d '\r\n' < "$KEYFILE") >/dev/null; then
  echo "REFUSING: a DIFFERENT key is already on the drive." >&2
  echo "Overwriting it could orphan every existing snapshot. Investigate first." >&2
  exit 1
fi

umask 077
tr -d '\r\n' < "$PASSFILE" > "$KEYFILE"
chmod 600 "$KEYFILE"
sync
echo "  wrote $KEYFILE"

cat <<BANNER

══════════════════════════════════════════════════════════════════════
  PRINT THIS AND PUT IT SOMEWHERE PHYSICAL.

  It is the only copy that survives losing the drive itself. A go-bag,
  a fireproof box, taped inside something that does not leave the house
  — anywhere that is not Nyx and not the drive.

      RHEA passphrase:  $(cat "$KEYFILE")

  Restore is now: plug the drive in, run rhea-restore.sh. Nothing typed.
══════════════════════════════════════════════════════════════════════

BANNER
echo "Verify any time with: sudo ./rhea-seed-key.sh --check"
