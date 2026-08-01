#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${PLAYLIST_FILE:=/srv/fgbears-live/playlist.ffconcat}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ -s "$PLAYLIST_FILE" ]] || { echo "Playlist is missing or empty: $PLAYLIST_FILE" >&2; exit 66; }

exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -map 0:v:0 -map 0:a:0 \
  -c:v copy -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
