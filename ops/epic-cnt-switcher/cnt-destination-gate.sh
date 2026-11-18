# Sourced by run-cnt.sh. Fail-closed gate for destination switching; never logs secret values.
# Requires log(). Sets/exports CNT_DESTINATION_SWITCHING=on only when the agent can actually run.
cnt_destination_gate() {
  local url="${CNT_DESTINATION_AGENT_URL:-}" secret="${CNT_DESTINATION_AGENT_SECRET:-}"
  if [ "${CNT_DESTINATION_SWITCHING:-off}" != on ]; then
    CNT_DESTINATION_SWITCHING=off; export CNT_DESTINATION_SWITCHING; return 0
  fi
  local why=""
  if [ -z "$url" ]; then why="CNT_DESTINATION_AGENT_URL missing"
  elif ! [[ "$url" =~ ^https://[a-z0-9.-]+/api/public/channels/cruisenewstrivia/destination-agent$ ]]; then why="CNT_DESTINATION_AGENT_URL not the fixed agent endpoint"
  elif [ -z "$secret" ]; then why="CNT_DESTINATION_AGENT_SECRET missing"
  elif [ "${#secret}" -lt 32 ]; then why="CNT_DESTINATION_AGENT_SECRET too short"
  fi
  if [ -n "$why" ]; then
    log "WARNING destination switching forced off ($why); using original CNT ingest"
    CNT_DESTINATION_SWITCHING=off; export CNT_DESTINATION_SWITCHING; return 0
  fi
  export CNT_DESTINATION_SWITCHING=on
}