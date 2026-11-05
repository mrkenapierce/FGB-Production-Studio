#!/usr/bin/env bash
# Owned CNT browser session only; never search or kill by command-line pattern.
start_browser_group() {
  setsid "$@" 8>&- 9>&- &
  CHROME_PID=$!
}

stop_browser_group() {
  local pid="${CHROME_PID:-}" group own
  [[ "$pid" =~ ^[1-9][0-9]+$ ]] && [ "$pid" -gt 1 ] || return 0
  group=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
  own=$(ps -o pgid= -p "$$" | tr -d ' ')
  # A dead session leader can leave children in its still-owned session.
  if [ -n "$group" ] && [ "$group" != "$pid" ]; then return 1; fi
  [ "$pid" != "$own" ] || return 1
  kill -TERM -- "-$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 -- "-$pid" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL -- "-$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  # Zombies cannot render; live descendants must be gone before replacement.
  if ps -eo pgid=,stat= | awk -v p="$pid" '$1 == p && $2 !~ /^Z/ {found=1} END {exit !found}'; then
    return 1
  fi
}