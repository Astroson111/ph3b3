#!/usr/bin/env bash
# Weekly ComfyUI restart — but only when it is genuinely idle.
#
# WHY THIS EXISTS: on 2026-08-23 ComfyUI had grown to 27.3 GB of host RAM over
# four days of uptime, saturating swap. Under that pressure /health stalled and
# the portal reported every service down while all four were running. Restarting
# it recovered 26 GB of RAM and 6.7 GB of swap.
#
# The growth is in HOST memory, not VRAM — Morpheus already calls /free with
# unload_models=True after every render and that works (VRAM sat at 258 MiB while
# RSS was 27 GB). So no ComfyUI flag addresses this; bounded uptime does.
#
# NEVER restarts mid-render. A wan-quality video is ~35 minutes, and killing one
# to save memory would be a worse outage than the one this prevents. If anything
# is queued or running, it logs and exits 0 — the timer tries again next week,
# and a machine busy enough to always be rendering has other signals.
set -uo pipefail          # NOT -e: a failed probe must skip the restart, not crash

COMFY="${COMFY_HOST:-http://127.0.0.1:8188}"
RSS_FLOOR_GB="${RSS_FLOOR_GB:-8}"      # below this, leave it alone — nothing to reclaim

log() { echo "[comfyui-restart] $*"; }

# ── 1. Is it even up? ────────────────────────────────────────────────────────
if ! curl -sf -m 10 -o /dev/null "$COMFY/system_stats"; then
  log "ComfyUI is not responding — leaving it to its own Restart=on-failure. Skipping."
  exit 0
fi

# ── 2. Is it busy? ───────────────────────────────────────────────────────────
queue="$(curl -sf -m 10 "$COMFY/queue" 2>/dev/null || echo '')"
if [ -z "$queue" ]; then
  log "could not read the queue — refusing to restart blind. Skipping."
  exit 0
fi
busy="$(printf '%s' "$queue" | python3 -c '
import json,sys
try:
    d = json.load(sys.stdin)
    print(len(d.get("queue_running", [])) + len(d.get("queue_pending", [])))
except Exception:
    print("unknown")
' 2>/dev/null)"

case "$busy" in
  0) : ;;
  unknown) log "queue unparseable — refusing to restart blind. Skipping."; exit 0 ;;
  *) log "$busy job(s) queued or running — NOT restarting. Next week."; exit 0 ;;
esac

# ── 3. Is there anything to reclaim? ─────────────────────────────────────────
# A restart costs a cold model load on the next render. Not worth paying weekly
# if the process has not actually grown.
pid="$(systemctl show comfyui -p MainPID --value 2>/dev/null)"
rss_gb=0
if [ -n "${pid:-}" ] && [ "$pid" != "0" ] && [ -r "/proc/$pid/status" ]; then
  rss_kb="$(awk '/^VmRSS:/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)"
  rss_gb=$(( rss_kb / 1048576 ))
fi
if [ "$rss_gb" -lt "$RSS_FLOOR_GB" ]; then
  log "RSS ${rss_gb} GB is under the ${RSS_FLOOR_GB} GB floor — nothing to reclaim. Skipping."
  exit 0
fi

# ── 4. Restart ───────────────────────────────────────────────────────────────
log "idle, RSS ${rss_gb} GB — restarting"
systemctl restart comfyui || { log "restart FAILED"; exit 1; }

for _ in $(seq 1 30); do
  sleep 2
  if curl -sf -m 5 -o /dev/null "$COMFY/system_stats"; then
    new_pid="$(systemctl show comfyui -p MainPID --value 2>/dev/null)"
    new_kb="$(awk '/^VmRSS:/{print $2}' "/proc/$new_pid/status" 2>/dev/null || echo 0)"
    log "back up — RSS ${rss_gb} GB -> $(( new_kb / 1048576 )) GB"
    exit 0
  fi
done
log "WARNING: restarted but /system_stats did not answer within 60s"
exit 1
