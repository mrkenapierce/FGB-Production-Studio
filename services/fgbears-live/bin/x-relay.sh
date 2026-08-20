#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${X_RELAY_ENABLED:=0}"
: "${X_LOCAL_UDP_URL:=udp://127.0.0.1:1937?pkt_size=1316}"
: "${X_RTMP_BASE:=rtmps://ca.pscp.tv:443/x}"
: "${X_STREAM_KEY:=}"
: "${FFMPEG_LOGLEVEL:=warning}"

case "${X_RELAY_ENABLED,,}" in
  1|true|yes|on) ;;
  *) echo "X relay is disabled." >&2; exit 78 ;;
esac
[[ "$X_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "X_LOCAL_UDP_URL must remain loopback." >&2; exit 78; }
[[ "$X_RTMP_BASE" == rtmp://* || "$X_RTMP_BASE" == rtmps://* ]] || { echo "Invalid X RTMP base." >&2; exit 78; }
[[ -n "$X_STREAM_KEY" ]] || { echo "X_STREAM_KEY is required." >&2; exit 78; }
[[ "$X_RTMP_BASE$X_STREAM_KEY" != *"|"* ]] || { echo "Unsupported X credential character." >&2; exit 78; }

UPSTREAM_TARGET="${X_RTMP_BASE%/}/${X_STREAM_KEY}"
exec ffmpeg -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL"   -i "$X_LOCAL_UDP_URL"   -map 0:v:0 -map 0:a:0 -c copy   -f flv -flvflags no_duration_filesize "$UPSTREAM_TARGET"
