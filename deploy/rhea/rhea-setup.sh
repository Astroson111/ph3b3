#!/usr/bin/env bash
# Rhea — preflight and bootstrap. Answers one question: "if Nyx died right now,
# could this drive actually bring her back on the machine in front of me?"
#
#   ./rhea-setup.sh            check everything, report, change nothing
#   ./rhea-setup.sh --install  additionally install what is missing (needs sudo)
#
# Designed to run FROM THE DRIVE on a bare machine, where nothing of Ph3b3 is
# installed yet and you are having a bad day. Every check says what it found,
# what it needs, and the exact command that fixes it.
#
# ON AUTORUN: Linux does not auto-execute anything from removable media, and
# that is correct — an autorunning backup drive is a malware delivery mechanism.
# Plugging the drive in opens a file-manager window; START-HERE.desktop next to
# this script is the thing to double-click from there.
set -uo pipefail          # NOT -e: a failed check must report, not abort the report

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL=0
[ "${1:-}" = "--install" ] && INSTALL=1

ok=0; warn=0; bad=0
say()  { printf '  %-34s %s\n' "$1" "$2"; }
good() { say "$1" "OK — $2";      ok=$((ok+1)); }
soft() { say "$1" "WARN — $2";    warn=$((warn+1)); }
hard() { say "$1" "MISSING — $2"; bad=$((bad+1)); }

echo "══════════════════════════════════════════════════════════════════"
echo "  RHEA preflight — can this drive restore Phoebe onto this machine?"
echo "  running from: $SELF_DIR"
[ "$INSTALL" = 1 ] && echo "  --install: missing packages WILL be installed"
echo "══════════════════════════════════════════════════════════════════"
echo

# ── 1. restic — the one thing with no substitute ─────────────────────────────
RESTIC=""
for cand in "$SELF_DIR/bin/restic" "$SELF_DIR/../bin/restic" "$(command -v restic || true)"; do
  [ -n "$cand" ] && [ -x "$cand" ] && { RESTIC="$cand"; break; }
done
if [ -n "$RESTIC" ]; then
  good "restic" "$("$RESTIC" version 2>/dev/null | head -1) at $RESTIC"
else
  hard "restic" "no binary on the drive or on PATH"
  echo "      The drive is supposed to carry one at bin/restic precisely so a"
  echo "      bare machine needs no package manager. Fix: apt install restic"
  [ "$INSTALL" = 1 ] && { echo "      installing…"; sudo apt-get install -y restic >/dev/null 2>&1 \
    && good "restic" "installed" || hard "restic" "apt install failed"; }
fi

# ── 2. the repo itself ───────────────────────────────────────────────────────
REPO_DIR="$SELF_DIR/restic"
[ -d "$REPO_DIR" ] && [ -f "$REPO_DIR/config" ] \
  && good "restic repo" "$REPO_DIR" \
  || hard "restic repo" "not found at $REPO_DIR — is this the RHEA drive?"

# ── 3. the key — the failure that made this script exist ─────────────────────
# The passphrase used to live only on Nyx. Nyx dying took it, and every snapshot
# became permanently unreadable. Any ONE of these three is enough to restore.
key_paths=0
[ -r "$SELF_DIR/rhea-passphrase.txt" ] && { good "key: on this drive" "self-opening restore"; key_paths=$((key_paths+1)); }
[ -r "/home/astroson/.config/rhea/passphrase" ] && { good "key: on this machine" "~/.config/rhea/passphrase"; key_paths=$((key_paths+1)); }
if [ "$key_paths" -eq 0 ]; then
  soft "key" "not on the drive and not on this machine"
  echo "      That is FINE if you have the Flipper or the printed copy — the"
  echo "      restore will prompt. It is FATAL if you have neither."
  echo "      Flipper:  Apps → USB → Bad USB → rhea-unlock → Run, at the prompt."
fi

# ── 4. things the restore script uses ────────────────────────────────────────
for pkg in python3 git rsync; do
  if command -v "$pkg" >/dev/null 2>&1; then
    good "$pkg" "$(command -v $pkg)"
  else
    hard "$pkg" "needed by the restore"
    [ "$INSTALL" = 1 ] && { sudo apt-get install -y "$pkg" >/dev/null 2>&1 \
      && good "$pkg" "installed" || hard "$pkg" "apt install failed"; }
  fi
done

# python3 must have sqlite3 — the DB snapshots are restored through it.
if command -v python3 >/dev/null 2>&1; then
  python3 -c "import sqlite3" 2>/dev/null \
    && good "python3 sqlite3" "present" \
    || hard "python3 sqlite3" "stdlib module missing — unusual; check the python install"
fi

# ── 5. space ─────────────────────────────────────────────────────────────────
if [ -d "$REPO_DIR" ]; then
  repo_kb="$(du -sk "$REPO_DIR" 2>/dev/null | cut -f1)"
  free_kb="$(df -Pk / | awk 'NR==2{print $4}')"
  if [ -n "$repo_kb" ] && [ -n "$free_kb" ]; then
    if [ "$free_kb" -gt "$repo_kb" ]; then
      good "free space" "$((free_kb/1024/1024)) GB free, repo is $((repo_kb/1024/1024)) GB"
    else
      soft "free space" "$((free_kb/1024/1024)) GB free vs a $((repo_kb/1024/1024)) GB repo — likely not enough"
    fi
  fi
fi

# ── 6. is this even the right drive ──────────────────────────────────────────
label="$(findmnt -no LABEL --target "$SELF_DIR" 2>/dev/null || true)"
[ "$label" = "RHEA" ] && good "drive label" "RHEA" || soft "drive label" "got '${label:-none}' — expected RHEA"

echo
echo "══════════════════════════════════════════════════════════════════"
echo "  $ok ok · $warn warnings · $bad missing"
if [ "$bad" -gt 0 ]; then
  echo
  echo "  NOT ready to restore. Re-run with --install to fix what apt can fix:"
  echo "      sudo $0 --install"
  exit 1
fi
echo
echo "  Ready. Fire-drill it before you need it — this touches nothing live:"
echo "      sudo $SELF_DIR/rhea-restore.sh --scratch /tmp/rhea-drill"
echo "══════════════════════════════════════════════════════════════════"
