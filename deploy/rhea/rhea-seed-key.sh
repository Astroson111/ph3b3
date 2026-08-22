#!/usr/bin/env bash
# Rhea — put the passphrase where a restore can actually reach it.
#
# THE PROBLEM THIS FIXES: the passphrase lived only at
# ~/.config/rhea/passphrase, on Nyx. Nyx is the machine the backup exists
# because you no longer have. Its disk dying took the only copy of the key, and
# every snapshot on the drive became permanently unreadable — Rhea defeated by
# Rhea's own key management.
#
# This puts the key somewhere a restore can reach WITHOUT Nyx: on paper by
# default, on the Flipper via rhea-make-badusb.sh, and — only if you ask — on the
# drive itself.
#
#   sudo ./rhea-seed-key.sh --check      report where the key exists, change nothing
#   sudo ./rhea-seed-key.sh --print      show the paper copy, touch nothing
#   sudo ./rhea-seed-key.sh --on-drive   ALSO put the key on the drive (see below)
#
# DEFAULT IS: PRINT, DO NOT PLACE. The key belongs somewhere that is not the
# drive it opens — on paper, and on the Flipper via rhea-make-badusb.sh. A key
# stored beside the repo means whoever picks up the drive has everything, and
# the encryption is decoration.
#
# --on-drive exists because there is a real case for it: if the drive lives in a
# safe and the threat you actually face is Nyx dying rather than burglary, a
# self-opening drive is the fastest restore there is. Choose it deliberately.
set -euo pipefail

RHEA_MNT="${RHEA_MNT:-/mnt/rhea}"
PASSFILE="${PASSFILE:-/home/astroson/.config/rhea/passphrase}"
KEYFILE="$RHEA_MNT/rhea-passphrase.txt"

CHECK=0; ONDRIVE=0; PRINTONLY=0
case "${1:---print}" in
  --check)    CHECK=1 ;;
  --print)    PRINTONLY=1 ;;
  --on-drive) ONDRIVE=1 ;;
  *) echo "usage: $0 [--check|--print|--on-drive]" >&2; exit 2 ;;
esac

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
    echo "  The drive does not self-open. That is the default and usually right:"
    echo "    ./rhea-make-badusb.sh     Flipper types the key at the prompt"
    echo "    sudo $0 --print           paper copy (the durable one)"
    echo "    sudo $0 --on-drive        self-opening drive (weaker, deliberate)"
  fi
  exit 0
fi

[ "$have_source" = 1 ] || { echo "FATAL: no passphrase at $PASSFILE to copy" >&2; exit 1; }

if [ "$PRINTONLY" = 1 ]; then
  cat <<BANNER

══════════════════════════════════════════════════════════════════════
  PRINT THIS AND PUT IT SOMEWHERE PHYSICAL.

  This is the copy that survives losing Nyx, the drive, AND the Flipper.
  A go-bag, a fireproof box, taped inside something that stays home.

      RHEA passphrase:  $(cat "$PASSFILE")

  Convenient copy:  ./rhea-make-badusb.sh   (Flipper types it at the prompt)
  Self-opening drive (weaker):  sudo $0 --on-drive
══════════════════════════════════════════════════════════════════════

BANNER
  exit 0
fi

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
