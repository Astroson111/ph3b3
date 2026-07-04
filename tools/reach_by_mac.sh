#!/usr/bin/env bash
# MAC-keyed reach watcher — confirms a device reaches the Ph3b3 server on :7331
# by resolving its LAN IP from its MAC FIRST (never IP-heuristic → no ghosts).
# Usage: reach_by_mac.sh <MAC> <NAME> [seconds]   (run on the server host, e.g. Nyx)
MAC="${1:?mac}"; NAME="${2:?name}"; SECS="${3:-1500}"
mac_ip=""
for i in $(seq 1 "$SECS"); do
  line=$(ip neigh 2>/dev/null | grep -i "$MAC" | grep -viE 'FAILED|INCOMPLETE')
  ip=$(echo "$line" | awk '{print $1}' | head -1)
  [ -n "$ip" ] && mac_ip="$ip"
  if [ -n "$mac_ip" ]; then
    hit=$(ss -tanH 'sport = :7331' 2>/dev/null | grep -E "[[:space:]]${mac_ip}:")
    if [ -n "$hit" ]; then
      echo "REACH ${NAME} (${MAC} @ ${mac_ip}) -> :7331 after ${i}s"; echo "$hit" | head -2; exit 0
    fi
  fi
  sleep 1
done
echo "NO_REACH ${NAME} (${MAC}) in ${SECS}s; last MAC-resolved IP=${mac_ip:-none}"
