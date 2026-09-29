#!/usr/bin/env bash
set -uo pipefail
: "${HEARTBEAT_URL:?}" "${FGB_TRANSPORT_HEARTBEAT_SECRET:?}" "${OUTPUT:?}"
beat() {
  local status ts body sig
  status=$(cat /tmp/fgb-transport.state 2>/dev/null || echo starting)
  ts=$(date +%s)
  body=$(printf '{"output":"%s","status":"%s","host":"%s","detail":{}}' "$OUTPUT" "$status" "${HOST_LABEL:-transport}")
  sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$FGB_TRANSPORT_HEARTBEAT_SECRET" -hex | awk '{print $NF}')
  curl -sf -m 5 -X POST "$HEARTBEAT_URL" -H 'content-type: application/json' -H "x-fgb-timestamp: $ts" -H "x-fgb-signature: $sig" --data "$body" >/dev/null || true
}
while true; do beat; sleep 15; done