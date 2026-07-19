#!/usr/bin/env bash
# One-time: create the mount point, add the fstab entry (by UUID + nofail), mount,
# and hand ownership to astroson so the backup job can write. Run with sudo:
#   sudo bash deploy/rhea/setup-mount.sh
set -euo pipefail

UUID="dd7ef2c9-196c-4a15-ae8d-2c5a1dd9ef6f"
MNT="/mnt/rhea"
LINE="UUID=$UUID $MNT ext4 defaults,nofail,x-systemd.device-timeout=10 0 2"

mkdir -p "$MNT"

# Add the fstab entry only if it's not already there (idempotent).
if grep -q "$UUID" /etc/fstab; then
  echo "fstab already has the RHEA UUID — leaving it."
else
  printf '%s\n' "$LINE" >> /etc/fstab
  echo "fstab entry added: $LINE"
fi

systemctl daemon-reload
mount "$MNT"
chown astroson:astroson "$MNT"

echo "MOUNTED:"
df -h "$MNT" | tail -1
findmnt -no SOURCE,TARGET,FSTYPE,LABEL "$MNT"
