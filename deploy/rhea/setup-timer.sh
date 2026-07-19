#!/usr/bin/env bash
# One-time: install + enable the nightly Rhea backup timer. Run with sudo:
#   sudo bash deploy/rhea/setup-timer.sh
set -euo pipefail
D="/home/astroson/Desktop/ph3b3_v2/deploy/rhea"

install -m 0644 "$D/rhea-backup.service" /etc/systemd/system/rhea-backup.service
install -m 0644 "$D/rhea-backup.timer"   /etc/systemd/system/rhea-backup.timer
systemctl daemon-reload
systemctl enable --now rhea-backup.timer

echo "── installed ──"
systemctl list-timers rhea-backup.timer --no-pager || true
echo "run a manual backup now with:  systemctl start rhea-backup.service  (then: journalctl -u rhea-backup -e)"
