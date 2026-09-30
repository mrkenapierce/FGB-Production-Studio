#!/usr/bin/env bash
set -uo pipefail
: "${HEARTBEAT_URL:?}" "${FGB_TRANSPORT_HEARTBEAT_SECRET:?}" "${OUTPUT:?}"
beat() {
  local status restarts uptime fps kbps dests ts body sig ff src up
  status=$(cat /tmp/fgb-transport.state 2>/dev/null || echo starting)
  restarts=$(cat /tmp/fgb-restarts 2>/dev/null || echo 0)
  uptime=$(( $(date +%s) - ${STARTED:-$(date +%s)} ))
  fps=$(grep -E '^fps=' /tmp/fgb-ffmpeg.progress 2>/dev/null | tail -1 | cut -d= -f2 | cut -d. -f1)
  kbps=$(grep -E '^bitrate=' /tmp/fgb-ffmpeg.progress 2>/dev/null | tail -1 | tr -dc '0-9.' | cut -d. -f1)
  dests=$(echo "${DESTINATIONS:-}" | wc -w)
  if pgrep -x ffmpeg >/dev/null 2>&1; then ff=true; else ff=false; fi
  if curl -sf -m 4 -o /dev/null "${BROADCAST_ORIGIN%/}/api/public/fgbears/game-screen"; then src=true; else src=false; fi
  case "$status" in live) up=connected ;; starting) up=connecting ;; degraded) up=disconnected ;; *) up=unknown ;; esac
  [ "$ff" = false ] && [ "$status" != stopped ] && up=error
  ts=$(date +%s)
  body=$(printf '{"output":"%s","status":"%s","host":"%s","detail":{"mode":"%s","restarts":%d,"uptimeSeconds":%d,"destinations":%d,"fps":%d,"bitrateKbps":%d,"ffmpegRunning":%s,"sourceReachable":%s,"upstreamState":"%s"}}' "$OUTPUT" "$status" "${HOST_LABEL:-transport}" "${MODE:-$OUTPUT}" "$restarts" "$uptime" "$dests" "${fps:-0}" "${kbps:-0}" "$ff" "$src" "$up")
  sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$FGB_TRANSPORT_HEARTBEAT_SECRET" -hex | awk '{print $NF}')
  curl -sf -m 5 -X POST "$HEARTBEAT_URL" -H 'content-type: application/json' -H "x-fgb-timestamp: $ts" -H "x-fgb-signature: $sig" --data "$body" >/dev/null || true
}
if [ "${1:-loop}" = once ]; then beat; exit 0; fi
while true; do beat; sleep 15; done
