#!/usr/bin/env bash
# Audio → YouTube episode cutter. NOT INSTALLED on any host.
# Runs beside a channel's recorder and reads CLOSED segments only (never the
# file still being written, never the live encoder). The app returns each job's
# window, which already includes the 3 s margin before and after the play; the
# cutter does not pad again.
#
#  * Writes $STATE/episode_hold BEFORE cutting: every segment overlapping any
#    pending job. Cleanup must skip these (FGB: see patches/; CNT retention
#    script honours it). Released only after the app confirms the upload.
#  * Recording not closed yet -> waits (no failure counted). Gap/missing -> one
#    failure report with a clear reason.
#  * Resumable upload with persisted session; the video id is stored locally
#    the moment YouTube returns it, so restarts never upload twice.
#
# Env: EPISODE_CHANNEL=fgb|cnt, FGB_ARCHIVE_DIR or CNT_ARCHIVE_DIR, channel
#      endpoint+secret (episode-lib.sh). EPISODE_ONCE=1 runs one pass.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; . "$here/episode-lib.sh"
STATE="$(ep_state_dir)"; WORK="$STATE/../episodes"
mkdir -p "$WORK" "$STATE"
log() { echo "[$(date -u +%FT%TZ)] [episode:$(ep_channel)] $*"; }
iso() { date -d "$1" +%s; }

report_fail() {
  ep_api "$(jq -cn --arg i "$1" --arg e "${2:0:290}" '{action:"episode_failed",episodeId:$i,error:$e}')" >/dev/null || true
  log "failed $1: $2"
}

held_for_window() { # files overlapping [ws,we], closed or not
  local ws="$1" we="$2" f s
  for f in "$(ep_seg_dir)"/live-*.ts; do
    [ -f "$f" ] || continue; s=$(ep_seg_epoch "$f") || continue
    [ "$s" -lt "$we" ] && [ "$s" -ge $((ws - 7200)) ] && echo "$f"
  done
}

process_job() {
  local job="$1" id title desc privacy ws we cover first files out tok meta vid sf resp
  id=$(jq -r .episodeId <<<"$job"); sf="$WORK/$id.json"
  [[ "$id" =~ ^[0-9a-f-]{36}$ ]] || return 1
  title=$(jq -r .title <<<"$job"); desc=$(jq -r '.description // ""' <<<"$job"); privacy=$(jq -r .privacy <<<"$job")
  ws=$(iso "$(jq -r .windowStart <<<"$job")"); we=$(iso "$(jq -r .windowEnd <<<"$job")")
  vid=$(jq -r '.videoId // empty' "$sf" 2>/dev/null)
  if [ -z "$vid" ]; then
    out="$WORK/$id.ts"
    if [ ! -s "$out" ]; then
      cover=$(ep_cover "$ws" "$we")
      case "$(head -1 <<<"$cover")" in
        NOT_CLOSED) log "$id waiting for recording to close"; return 0 ;;
        GAP) report_fail "$id" "recording has a gap during the aired window"; return 1 ;;
        MISSING) report_fail "$id" "no local recording covers the aired window"; return 1 ;;
      esac
      first=$(head -1 <<<"$cover" | cut -d' ' -f2); mapfile -t files < <(tail -n +2 <<<"$cover")
      ep_cut "$ws" "$we" "$out" "$first" "${files[@]}" || { report_fail "$id" "cut failed"; return 1; }
    fi
    [ "${EP_DRY_RUN:-0}" = 1 ] && { log "DRY_RUN cut ready $out ($(ep_duration "$out")s)"; return 0; }
    tok=$(ep_api '{"action":"token"}' | jq -r '.accessToken // empty')
    [ -n "$tok" ] || { log "$id no upload token (paused or channel lacks upload permission); will retry"; return 0; }
    meta=$(jq -cn --arg t "$title" --arg d "$desc" --arg p "$privacy" \
      '{snippet:{title:$t,description:$d,categoryId:"17"},status:{privacyStatus:$p,selfDeclaredMadeForKids:false}}')
    vid=$(ep_resumable_upload "$out" "$meta" "$sf" "$tok") || { log "$id upload incomplete; will resume"; return 0; }
    log "uploaded $id -> $vid"
  fi
  resp=$(ep_api "$(jq -cn --arg i "$id" --arg v "$vid" '{action:"episode_uploaded",episodeId:$i,videoId:$v}')")
  # Current endpoint's {ok,posted} is NOT a processing receipt. Do not release
  # sources/cut on that weak signal. Future host protocol must echo identifiers
  # and affirm all processing; source-only preparation, no endpoint changed here.
  if jq -e --arg i "$id" --arg v "$vid" '.ok == true and .receipt.episodeId == $i and .receipt.videoId == $v and .receipt.processingComplete == true' <<<"$resp" >/dev/null; then
    ep_dependency complete --kind episode --id "$id" --video "$vid" --evidence episode_processing_confirmed || return 1
    jq '. + {confirmed:true}' "$sf" > "$sf.t" && mv "$sf.t" "$sf" || return 1
    rm -f "$WORK/$id.ts"; log "posted $id"
  else log "$id awaiting complete processing receipt; sources retained"; fi
}

pass() {
  local jobs job f holds=() ws we
  local response
  if [ -n "${EP_JOBS_FILE:-}" ]; then response=$(cat "$EP_JOBS_FILE")   # tests only
  else response=$(ep_api '{"action":"episode_jobs"}') || { log "jobs unavailable; old holds retained"; return 1; }; fi
  jq -e '(.ok == true or has("ok") == false) and (.jobs | type == "array") and all(.jobs[]; (.episodeId | type == "string") and (.windowStart | type == "string") and (.windowEnd | type == "string"))' <<<"$response" >/dev/null || { log "invalid jobs; old holds retained"; return 1; }
  jobs=$(jq -c '.jobs[]' <<<"$response")
  # Hold first, then work, so cleanup can never remove a needed file mid-cut.
  while IFS= read -r job; do
    [ -n "$job" ] || continue
    ws=$(iso "$(jq -r .windowStart <<<"$job")"); we=$(iso "$(jq -r .windowEnd <<<"$job")")
    ep_dependency register --kind episode --id "$(jq -r .episodeId <<<"$job")" --start "$ws" --end "$we" || return 1
    mapfile -t -O "${#holds[@]}" holds < <(held_for_window "$ws" "$we")
  done <<<"$jobs"
  # Union with old holds: absence in the capped API job list is not completion.
  # Persistent pending windows, rather than an ever-growing basename union,
  # protect jobs omitted/disabled/exhausted from the bounded API response.
  while IFS= read -r f; do
    ws=$(jq -r .start "$f"); we=$(jq -r .end "$f")
    mapfile -t -O "${#holds[@]}" holds < <(held_for_window "$ws" "$we")
  done < <(for f in "$STATE"/dependencies/episode-*.json; do [ -f "$f" ] && jq -e '.status != "confirmed"' "$f" >/dev/null && echo "$f"; done)
  ep_write_hold "$STATE/episode_hold" "${holds[@]}" || return 1
  while IFS= read -r job; do [ -n "$job" ] && { process_job "$job" || true; }; done <<<"$jobs"
}

# Lock the worker, NOT retention.lock during a potentially hours-long upload.
exec 8>"$STATE/episode-worker.lock"; flock -n 8 || exit 75
if [ "${EPISODE_ONCE:-0}" = 1 ]; then pass; exit $?; fi
while true; do pass; sleep 60; done