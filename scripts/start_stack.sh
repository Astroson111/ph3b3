#!/usr/bin/env bash
# ☀ Wake Ph3b3 — manually bring up the WHOLE stack.
#
# As of 2026-07-20 all three come up on their own at boot via systemd (ph3b3.service
# + comfyui.service enabled; metis-searxng via container-metis-searxng.service +
# user linger), and Argus watches metis + comfyui so a failed launch shows SILENT on
# the fleet panel. So this script is no longer REQUIRED — it's a convenience to wake
# everything after a manual "Rest", without a reboot.
#
# Each start is independent: one failing never blocks the others, and the result is
# surfaced as a desktop notification.
set -u

up=(); fail=()
# Start, then judge by ACTUAL state — `systemctl start` on this box intermittently
# returns non-zero via a dbus hiccup even when the unit is (or becomes) active, and
# an already-running unit is a success, not a failure.
try_unit() {
    systemctl start "$1" 2>/dev/null
    if systemctl is-active --quiet "$1"; then up+=("$2"); else fail+=("$2"); fi
}

try_unit ph3b3.service   "Assistant"
try_unit comfyui.service "Video (ComfyUI)"
podman start metis-searxng >/dev/null 2>&1
if podman ps --filter name=metis-searxng --filter status=running --format '{{.Names}}' | grep -q .; then
    up+=("Search (Metis)"); else fail+=("Search (Metis)")
fi

msg="Up: ${up[*]:-none}"
[ "${#fail[@]}" -gt 0 ] && msg="$msg   —   FAILED: ${fail[*]}"
command -v notify-send >/dev/null 2>&1 && \
    notify-send -i "${HOME}/Downloads/ph3b3_face_wake_512.png" "☀ Wake Ph3b3" "$msg"
echo "$msg"
