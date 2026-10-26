#!/usr/bin/env bash
# CNT DAILY archive publisher — at most ONE video per America/Chicago date.
# NOT INSTALLED. Requires cnt-rolling-recorder.sh to be running; this script
# never records or encodes on its own, it assembles the daily window from the
# rolling buffer (stream copy).
#
# Each cycle (60 s):
#   1. Signed `status` call (CNT secret only) returns the admin daily config.
#      If daily.active is false: release the daily hold, do nothing else.
#   2. While armed: hold every rolling segment overlapping today's window
#      (state/daily_hold) so retention cannot delete it.
#   3. After the window closes and all segments are closed: cut, `register`
#      the segment id (the app rejects a second episode per Chicago date),
#      fetch an upload token (blocked until CNT YouTube has upload permission),
#      resumable-upload, then `uploaded`. A local done marker per date makes
#      restarts idempotent. Gaps/missing footage mark the date missed; nothing
#      is posted for it.
# Disk: refuses to cut unless free space >= CNT_MIN_FREE_GB + window size.
set -uo pipefail
export EPISODE_CHANNEL=cnt
here="$(cd "$(dirname "$0")" && pwd)"; . "$here/episode-lib.sh"
DIR="${CNT_ARCHIVE_DIR:-/cnt-archive}"; STATE="$DIR/state"; WORK="$DIR/daily"
MIN_GB="${CNT_MIN_FREE_GB:-8}"
mkdir -p "$STATE" "$WORK"
log() { echo "[$(date -u +%FT%TZ)] [cnt-daily] $*"; }

# window <date YYYY-MM-DD> <hour> <durationHours> <tz> -> "startEpoch endEpoch"
window() { local s; s=$(TZ="$4" date -d "$1 $(printf %02d "$2"):00:00" +%s) || return 1; echo "$s $((s + $3 * 3600))"; }

cycle() {
  local now cfg active hour dur tz today ws we done sid cover first files out free need resp title desc tok meta vid
  now=$(date +%s)
  if [ -n "${CNT_DAILY_STATUS_FILE:-}" ]; then cfg=$(cat "$CNT_DAILY_STATUS_FILE")   # tests only
  else cfg=$(ep_api "$(jq -cn --argjson d "$(( $(df -Pk "$DIR" | awk 'NR==2{print $4}') / 1024 ))" \
        '{action:"status",recorder:{state:"running",segmentSeconds:600,diskFreeMb:$d,host:"cnt"}}')") || { log "status unavailable; holds retained"; return 1; }; fi
  jq -e '(.daily.active | type == "boolean") and (.daily.captureHour | type == "number") and (.daily.durationHours | type == "number") and .daily.timezone == "America/Chicago"' <<<"$cfg" >/dev/null || { log "invalid status; holds retained"; return 1; }
  active=$(jq -r '.daily.active // false' <<<"$cfg"); hour=$(jq -r '.daily.captureHour // 16' <<<"$cfg")
  dur=$(jq -r '.daily.durationHours // 1' <<<"$cfg"); tz=$(jq -r '.daily.timezone // "America/Chicago"' <<<"$cfg")
  [[ "$hour" =~ ^[0-9]+$ && "$dur" =~ ^[0-9]+$ && "$hour" -le 23 && "$dur" -ge 1 && "$dur" -le 6 ]] || { log "bad config"; return 0; }
  if [ "$active" != true ]; then ep_write_hold "$STATE/daily_hold"; return 0; fi
  today=$(TZ="$tz" date -d "@$now" +%F)
  read -r ws we < <(window "$today" "$hour" "$dur" "$tz")
  done="$WORK/$today.json"
  if jq -e '.confirmed == true' "$done" >/dev/null 2>&1; then ep_write_hold "$STATE/daily_hold"; return 0; fi
  [ "$now" -ge $((ws - 120)) ] || { ep_write_hold "$STATE/daily_hold"; return 0; }
  sid=$(ep_segment_id "$ws" "$tz")
  ep_dependency register --kind daily --id "$sid" --start "$ws" --end "$we" || return 1
  mapfile -t files < <(for f in "$(ep_seg_dir)"/live-*.ts; do s=$(ep_seg_epoch "$f") || continue; [ "$s" -lt "$we" ] && [ "$s" -ge $((ws - 3600)) ] && echo "$f"; done)
  ep_write_hold "$STATE/daily_hold" "${files[@]}"
  [ "$now" -ge $((we + 60)) ] || return 0
  sid=$(ep_segment_id "$ws" "$tz"); out="$WORK/$sid.ts"
  if [ ! -s "$out" ] && ! jq -e '.videoId' "$done" >/dev/null 2>&1; then
    cover=$(ep_cover "$ws" "$we")
    case "$(head -1 <<<"$cover")" in
      NOT_CLOSED) log "$today waiting for segments to close"; return 0 ;;
      GAP|MISSING) log "ALERT $today incomplete recording; dependency retained for recovery"; return 0 ;;
    esac
    free=$(df -Pk "$DIR" | awk 'NR==2{print $4}'); need=$(( (MIN_GB * 1024 * 1024) + dur * 1700 * 1024 ))
    [ "$free" -ge "$need" ] || { log "not enough disk to cut ($free KB < $need KB); waiting"; return 0; }
    first=$(head -1 <<<"$cover" | cut -d' ' -f2); mapfile -t files < <(tail -n +2 <<<"$cover")
    ep_cut "$ws" "$we" "$out" "$first" "${files[@]}" || { log "cut failed"; return 0; }
  fi
  [ "${EP_DRY_RUN:-0}" = 1 ] && { log "DRY_RUN daily cut ready $out ($(ep_duration "$out")s) id=$sid"; return 0; }
  resp=$(ep_api "$(jq -cn --arg s "$sid" '{action:"register",segmentId:$s}')")
  [ "$(jq -r .ok <<<"$resp")" = true ] || { log "register refused: $(jq -r '.error // "?"' <<<"$resp" | head -c 160)"; return 0; }
  vid=$(jq -r '.videoId // empty' <<<"$resp")
  if [ -n "$vid" ]; then
    jq -n --arg v "$vid" '{videoId:$v}' > "$done.t" && mv "$done.t" "$done" || return 1
  fi
  title=$(jq -r '.title // empty' <<<"$resp"); desc=$(jq -r '.description // ""' <<<"$resp")
  [ -n "$title" ] || { log "no title from app"; return 0; }
  tok=$(ep_api '{"action":"token"}' | jq -r '.accessToken // empty')
  [ -n "$tok" ] || { log "no upload token (CNT YouTube needs upload permission, or paused)"; return 0; }
  meta=$(jq -cn --arg t "$title" --arg d "$desc" --arg p "$(jq -r '.privacy // "public"' <<<"$cfg")" \
    '{snippet:{title:$t,description:$d,categoryId:"17"},status:{privacyStatus:$p,selfDeclaredMadeForKids:false}}')
  vid=$(ep_resumable_upload "$out" "$meta" "$done" "$tok") || { log "upload incomplete; will resume"; return 0; }
  resp=$(ep_api "$(jq -cn --arg s "$sid" --arg v "$vid" '{action:"uploaded",segmentId:$s,videoId:$v}')")
  # .ok alone can mean playlist failure. Exact membership in the authenticated
  # cleanup response is the existing CNT upload+playlist deletion authority.
  local cleanup
  cleanup=$(ep_api '{"action":"cleanup"}') || return 1
  if jq -e --arg s "$sid" '.ok == true and (.confirmedSegmentIds | type == "array") and (.confirmedSegmentIds | index($s) != null)' <<<"$cleanup" >/dev/null; then
    ep_dependency complete --kind daily --id "$sid" --video "$vid" --evidence cnt_cleanup_confirmed || return 1
    jq '. + {confirmed:true}' "$done" > "$done.t" && mv "$done.t" "$done" || return 1
    rm -f "$out"; ep_write_hold "$STATE/daily_hold"; log "$today posted $vid"
  else log "$today awaiting playlist confirmation; source and cut retained"; fi
}

exec 8>"$STATE/daily-worker.lock"; flock -n 8 || exit 75
if [ "${CNT_DAILY_ONCE:-0}" = 1 ]; then cycle; exit $?; fi
while true; do cycle; sleep 60; done