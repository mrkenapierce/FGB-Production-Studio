#!/usr/bin/env bash
set -Eeuo pipefail
CONTRACT=https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing
AUDIO=/srv/fgbears-live/audio/fgb-music-loop.m4a
STATE=/srv/fgbears-live/runtime/lovable-audio-pipeline.json
TIMER=fgbears-lovable-audio-sync.timer
SYNC=fgbears-lovable-audio-sync.service
MASTER=fgbears-live.service

printf '%s\n' '=== LOVABLE AUDIO CONTRACT ==='
curl -fsS --max-time 20 "$CONTRACT" -o /tmp/fgb-contract.json
jq '{audio:.presentation.audio}' /tmp/fgb-contract.json

printf '%s\n' '=== ORACLE LIVE AUDIO ==='
echo LIVE_SHA=$(sha256sum "$AUDIO" | awk '{print $1}')
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,bit_rate,start_time,duration -of json "$AUDIO"

echo MASTER=$(systemctl is-active "$MASTER" 2>/dev/null || true)
echo MASTER_PID=$(systemctl show -p MainPID --value "$MASTER" 2>/dev/null || true)
echo SYNC_TIMER_ACTIVE=$(systemctl is-active "$TIMER" 2>/dev/null || true)
echo SYNC_TIMER_ENABLED=$(systemctl is-enabled "$TIMER" 2>/dev/null || true)
echo SYNC_SERVICE_ACTIVE=$(systemctl is-active "$SYNC" 2>/dev/null || true)

printf '%s\n' '=== PIPELINE STATE ==='
if [[ -s "$STATE" ]]; then cat "$STATE"; else echo STATE_MISSING; fi

printf '%s\n' '=== RECENT SYNC LOG ==='
journalctl -u "$SYNC" --since '-24 hours' --no-pager -n 120 || true

printf '%s\n' '=== INCOMING REVISIONS ==='
find /srv/fgbears-live/audio/incoming -maxdepth 2 -type f -printf '%TY-%Tm-%TdT%TH:%TM:%TSZ %s %p\n' 2>/dev/null | sort | tail -30 || true

echo CURRENT_AUDIO_DEPLOYMENT_PROBE=PASS
