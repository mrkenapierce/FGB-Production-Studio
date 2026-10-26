#!/usr/bin/env bash
# Shared helpers for audio → YouTube episodes and the CNT archive (FGB or CNT).
# Sourced, never run. Each channel only ever uses its own endpoint and secret:
#   EPISODE_CHANNEL=fgb -> FGB_TRANSPORT_HEARTBEAT_SECRET (x-fgb-*), ARCHIVE_URL
#   EPISODE_CHANNEL=cnt -> CNT_ARCHIVE_HMAC_SECRET (x-cnt-*), CNT_ARCHIVE_URL
#
# Recording layout (matches production FGB-Production-Studio recorder, which
# is NOT replaced): files are live-YYYYMMDD-HHMMSS-±HHMM.ts written by ffmpeg's
# segment muxer, the newest file is still being written.
#   FGB: /archive/hourly  (host /srv/fgb-archive/hourly)
#   CNT: /cnt-archive/rolling (host /srv/cnt-archive/rolling)
# EP_DRY_RUN=1 makes ep_api print the request instead of sending it (tests).

ep_channel() { echo "${EPISODE_CHANNEL:-fgb}"; }

ep_seg_dir() {
  if [ -n "${EPISODE_SEGMENT_DIR:-}" ]; then echo "$EPISODE_SEGMENT_DIR"
  elif [ "$(ep_channel)" = cnt ]; then echo "${CNT_ARCHIVE_DIR:-/cnt-archive}/rolling"
  else echo "${FGB_ARCHIVE_DIR:-/archive}/hourly"; fi
}
ep_state_dir() {
  if [ "$(ep_channel)" = cnt ]; then echo "${CNT_ARCHIVE_DIR:-/cnt-archive}/state"
  else echo "${FGB_ARCHIVE_DIR:-/archive}/state"; fi
}

ep_api() {
  local body="$1" ts sig url secret prefix
  ts=$(date +%s)
  if [ "$(ep_channel)" = cnt ]; then
    url="${CNT_ARCHIVE_URL:?CNT_ARCHIVE_URL required}"; prefix=x-cnt
    [ "${EP_DRY_RUN:-0}" = 1 ] || secret="${CNT_ARCHIVE_HMAC_SECRET:?CNT_ARCHIVE_HMAC_SECRET required}"
  else
    url="${ARCHIVE_URL:?ARCHIVE_URL required}"; prefix=x-fgb
    [ "${EP_DRY_RUN:-0}" = 1 ] || secret="${FGB_TRANSPORT_HEARTBEAT_SECRET:?FGB_TRANSPORT_HEARTBEAT_SECRET required}"
  fi
  if [ "${EP_DRY_RUN:-0}" = 1 ]; then echo "DRY_RUN $prefix $body" >&2; echo '{"ok":true,"dryRun":true}'; return 0; fi
  sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$secret" -hex | awk '{print $NF}')
  curl --fail -sS -m 30 -X POST "$url" -H 'content-type: application/json' \
    -H "$prefix-timestamp: $ts" -H "$prefix-signature: $sig" --data "$body"
}

# Segment file name -> epoch seconds. Accepts the production name
# live-20261026-140000--0500.ts (ffmpeg strftime "live-%Y%m%d-%H%M%S-%z",
# so the separator hyphen is followed by the sign), and the legacy 20261026T140000-0500.ts.
ep_seg_epoch() {
  local n; n="$(basename "$1")"; n="${n%.ts}"
  if [[ "$n" =~ ^live-([0-9]{8})-([0-9]{6})-?([+-][0-9]{4})$ ]]; then
    n="${BASH_REMATCH[1]}T${BASH_REMATCH[2]}${BASH_REMATCH[3]}"
  fi
  [[ "$n" =~ ^[0-9]{8}T[0-9]{6}[+-][0-9]{4}$ ]] || return 1
  date -d "${n:0:4}-${n:4:2}-${n:6:2} ${n:9:2}:${n:11:2}:${n:13:2} ${n:15}" +%s 2>/dev/null
}

# Epoch -> archive segment id YYYYMMDDTHHMMSS±HHMM in the given zone.
ep_segment_id() { TZ="${2:-America/Chicago}" date -d "@$1" +%Y%m%dT%H%M%S%z; }

ep_duration() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null | cut -d. -f1; }

# Closed segments, oldest first: every live-*.ts except the newest (still being
# written) and anything modified in the last EP_STABLE_SECONDS (default 30).
ep_closed_segments() {
  local dir; dir="$(ep_seg_dir)"
  local stable="${EP_STABLE_SECONDS:-30}" now; now=$(date +%s)
  local all=() f
  while IFS= read -r f; do all+=("$f"); done < <(
    for f in "$dir"/live-*.ts; do [ -f "$f" ] && [ ! -L "$f" ] && printf '%s %s\n' "$(ep_seg_epoch "$f" || echo x)" "$f"; done |
      awk '$1 ~ /^[0-9]+$/' | sort -n | cut -d' ' -f2-)
  local n=${#all[@]} i
  for ((i = 0; i < n - 1; i++)); do
    f="${all[$i]}"
    [ $((now - $(stat -c %Y "$f"))) -ge "$stable" ] && echo "$f"
  done
}

# Prints "OK <firstEpoch>" then the covering files, or one of
# NOT_CLOSED (window not fully recorded yet), GAP (hole > 2 s), MISSING
# (no recording at or before the window start). Returns 0 only for OK.
ep_cover() {
  local ws="$1" we="$2" f s d prev_end="" first="" last_end=0 out=()
  while IFS= read -r f; do
    s=$(ep_seg_epoch "$f") || continue
    d=$(ep_duration "$f"); [ -n "$d" ] || continue
    [ $((s + d)) -le "$ws" ] && continue
    [ "$s" -ge "$we" ] && break
    if [ -n "$prev_end" ] && [ $((s - prev_end)) -gt 2 ]; then echo GAP; return 1; fi
    [ -z "$first" ] && first="$s"
    out+=("$f"); prev_end=$((s + d)); last_end=$prev_end
  done < <(ep_closed_segments)
  if [ ${#out[@]} -eq 0 ]; then
    # Nothing closed overlaps yet: still recording if the window is recent.
    [ $(( $(date +%s) - we )) -lt "${EP_MISSING_AFTER_SECONDS:-10800}" ] && { echo NOT_CLOSED; return 1; }
    echo MISSING; return 1
  fi
  [ "$first" -le "$((ws + 1))" ] || { echo MISSING; return 1; }
  if [ "$last_end" -lt "$((we - 1))" ]; then
    # Recording resumed later than where closed footage stops -> real hole.
    local nf ns=0; for nf in "$(ep_seg_dir)"/live-*.ts; do s=$(ep_seg_epoch "$nf") || continue; [ "$s" -gt "$ns" ] && ns=$s; done
    [ "$ns" -gt $((last_end + 2)) ] && [ "$ns" -lt "$we" ] && { echo GAP; return 1; }
    [ "$ns" -ge "$we" ] && [ "$ns" -gt $((last_end + 2)) ] && { echo GAP; return 1; }
    echo NOT_CLOSED; return 1
  fi
  echo "OK $first"; printf '%s\n' "${out[@]}"
}

# ep_cut <ws> <we> <out.ts> <files...first epoch...>: stream-copy cut (no
# re-encode). Start is keyframe-aligned; the app's 3 s margin covers that.
ep_cut() {
  local ws="$1" we="$2" out="$3" first="$4"; shift 4
  local list="$out.list" f
  : > "$list"
  for f in "$@"; do printf "file '%s'\n" "$(printf '%s' "$f" | sed "s/'/'\\\\''/g")" >> "$list"; done
  ffmpeg -nostdin -hide_banner -loglevel error -y -f concat -safe 0 -i "$list" \
    -ss $((ws - first)) -t $((we - ws)) -map 0 -c copy -f mpegts "$out.part" || { rm -f "$out.part" "$list"; return 1; }
  mv "$out.part" "$out"; rm -f "$list"
}

# Atomically replace a hold list (basenames, one per line). Cleanup must keep
# every listed file; a missing or stale (>10 min) list means "hold everything".
ep_write_hold() {
  local dest="$1" tmp="$1.tmp.$$"; shift
  mkdir -p "$(dirname "$dest")"
  (
    flock -x 9 || exit 1
    { for f in "$@"; do basename "$f"; done; } | sort -u > "$tmp" && mv "$tmp" "$dest"
  ) 9>"$(dirname "$dest")/retention.lock"
}

ep_dependency() {
  local root; root="$(dirname "$(ep_state_dir)")"
  python3 "$here/archive-retention.py" "$1" --root "$root" --channel "$(ep_channel)" "${@:2}"
}

# ep_resumable_upload <file> <metadataJson> <stateFile> <token>
# Prints the YouTube video id. Persists the session URL so a restart resumes
# instead of starting a second upload; a known video id is never re-uploaded.
ep_resumable_upload() {
  local file="$1" meta="$2" sf="$3" tok="$4" size loc code range off resp vid hdr
  size=$(stat -c %s "$file")
  vid=$(jq -r '.videoId // empty' "$sf" 2>/dev/null); [ -n "$vid" ] && { echo "$vid"; return 0; }
  loc=$(jq -r '.sessionUrl // empty' "$sf" 2>/dev/null)
  if [ -n "$loc" ]; then
    hdr=$(mktemp)
    code=$(curl -sS -m 60 -o "$hdr.body" -D "$hdr" -w '%{http_code}' -X PUT "$loc" \
      -H "authorization: Bearer $tok" -H "content-range: bytes */$size" -H 'content-length: 0')
    case "$code" in
      200|201) vid=$(jq -r '.id // empty' "$hdr.body"); rm -f "$hdr" "$hdr.body"
               [ -n "$vid" ] && { jq -n --arg v "$vid" '{videoId:$v}' > "$sf"; echo "$vid"; return 0; } ;;
      308) range=$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="range:"{print $2}'); rm -f "$hdr" "$hdr.body"
           off=0; [ -n "$range" ] && off=$(( ${range##*-} + 1 ))
           resp=$(tail -c +"$((off + 1))" "$file" | curl -sS -m 14400 -X PUT "$loc" -H "authorization: Bearer $tok" \
             -H "content-range: bytes $off-$((size - 1))/$size" --data-binary @-)
           vid=$(echo "$resp" | jq -r '.id // empty' 2>/dev/null)
           [ -n "$vid" ] && { jq -n --arg v "$vid" '{videoId:$v}' > "$sf"; echo "$vid"; return 0; }
           return 1 ;;
      404|410) rm -f "$hdr" "$hdr.body"; loc="" ;;   # session expired without completing
      *) rm -f "$hdr" "$hdr.body"; return 1 ;;
    esac
  fi
  loc=$(echo "$meta" | curl -sS -m 60 -D - -o /dev/null -X POST \
      "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status" \
      -H "authorization: Bearer $tok" -H 'content-type: application/json; charset=UTF-8' \
      -H 'x-upload-content-type: video/mp2t' -H "x-upload-content-length: $size" --data-binary @- |
    tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')
  [ -n "$loc" ] || return 1
  jq -n --arg u "$loc" '{sessionUrl:$u}' > "$sf"
  resp=$(curl -sS -m 14400 -X PUT --upload-file "$file" -H "authorization: Bearer $tok" -H 'content-type: video/mp2t' "$loc")
  vid=$(echo "$resp" | jq -r '.id // empty' 2>/dev/null)
  [ -n "$vid" ] || return 1   # session kept: the next run resumes it
  jq -n --arg v "$vid" '{videoId:$v}' > "$sf"; echo "$vid"
}