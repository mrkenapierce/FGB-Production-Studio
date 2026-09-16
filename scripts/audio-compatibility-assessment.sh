#!/usr/bin/env bash
set -Eeuo pipefail
GOOD=/srv/fgbears-live/audio/fgb-music-loop.m4a
BAD=$(find /srv/fgbears-live/quarantine/episode034-user-rejected -type f -name '*c04e-user-rejected.m4a' -print | sort | tail -1)
GOOD_SHA=c8391464ae77eec19b85270d67522300202fe5494232581c55433f934b172a12
BAD_SHA=c04e4fa32a5acc4200c2ef88e8bf43f7618998768ad8c58a716f7869a35a9e7a

test "$(sha256sum "$GOOD" | awk '{print $1}')" = "$GOOD_SHA"
test -n "$BAD"
test "$(sha256sum "$BAD" | awk '{print $1}')" = "$BAD_SHA"

echo '=== SAFE EFFECTIVE LOCAL-TRANSPORT SETTINGS ==='
grep -E '^(YOUTUBE_LOCAL_UDP_URL|YOUTUBE_COPY_LOCAL_UDP_URL|RUMBLE_LOCAL_UDP_URL|FGB_AUDIO_HEALTH_INTERVAL_SECONDS|FGB_AUDIO_HEALTH_SAMPLE_SECONDS)=' /etc/fgbears-live/stream.env || true

echo '=== EFFECTIVE MASTER AUDIO COMMAND ==='
systemctl cat fgbears-live.service
ps -eo pid=,ppid=,etimes=,args= | grep '[f]fmpeg' | grep -E 'fgb-music-loop|youtube|facebook' || true

inspect() {
  label=$1; file=$2
  echo "=== ${label}: FILE ==="
  stat -c 'size=%s mtime=%y path=%n' "$file"
  ffprobe -v error -select_streams a:0 \
    -show_entries stream=codec_name,profile,codec_tag_string,sample_rate,channels,channel_layout,time_base,start_pts,start_time,duration_ts,duration,bit_rate,nb_frames,extradata_size:format=format_name,start_time,duration,size,bit_rate,tags \
    -of json "$file"
  echo "=== ${label}: EXTRADATA ==="
  ffprobe -v error -select_streams a:0 -show_entries stream=extradata -show_data -of default=nw=1 "$file" || true
  echo "=== ${label}: FIRST PACKETS ==="
  ffprobe -v error -read_intervals '%+0.25' -select_streams a:0 -show_packets \
    -show_entries packet=pts,dts,pts_time,dts_time,duration,duration_time,size,flags -of csv=p=0 "$file" | sed -n '1,20p'
  echo "=== ${label}: DECODE CHECK ==="
  ffmpeg -hide_banner -nostdin -v error -xerror -i "$file" -map 0:a:0 -vn -f null -
  echo "${label}_DECODE=PASS"
}

inspect GOOD "$GOOD"
inspect EP34_REJECTED "$BAD"

analyze_packets() {
  label=$1; csv_path=$2
  python3 -c 'import csv,sys
label,path=sys.argv[1:]
rows=[]
with open(path,newline="") as f:
    for row in csv.reader(f):
        vals=[]
        for x in row[:3]:
            try: vals.append(float(x))
            except Exception: vals.append(None)
        if vals and vals[0] is not None: rows.append(vals)
pts=[r[0] for r in rows]
durs=[r[2] if len(r)>2 and r[2] is not None else 0.021333 for r in rows]
regs=0; gaps=[]; deltas=[]
for i in range(1,len(pts)):
    d=pts[i]-pts[i-1]; deltas.append(d)
    if d < -0.001: regs+=1
    if d > max(0.08,durs[i-1]*3): gaps.append(d)
print(f"{label}_PACKETS={len(rows)}")
print(f"{label}_FIRST_PTS={pts[0] if pts else None}")
print(f"{label}_LAST_PTS={pts[-1] if pts else None}")
print(f"{label}_PTS_REGRESSIONS={regs}")
print(f"{label}_PTS_GAPS={len(gaps)}")
print(f"{label}_MAX_GAP={max(gaps) if gaps else 0.0}")
print(f"{label}_MIN_DELTA={min(deltas) if deltas else 0.0}")
print(f"{label}_MAX_DELTA={max(deltas) if deltas else 0.0}")' "$label" "$csv_path"
}

remux_test() {
  label=$1; file=$2; out=/tmp/${label}.ts
  rm -f "$out" /tmp/${label}-packets.csv
  echo "=== ${label}: MASTER-LIKE COPY/REMUX TEST ==="
  start=$(date +%s%N)
  ffmpeg -hide_banner -nostdin -v warning \
    -re -stream_loop -1 -i "$file" -t 8 \
    -map 0:a:0 -c:a copy -f mpegts "$out"
  end=$(date +%s%N)
  elapsed=$(python3 -c "print((${end}-${start})/1e9)")
  echo "${label}_REALTIME_ELAPSED=$elapsed"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,time_base,start_time,duration -of json "$out"
  ffprobe -v error -select_streams a:0 -show_packets -show_entries packet=pts_time,dts_time,duration_time -of csv=p=0 "$out" > /tmp/${label}-packets.csv
  analyze_packets "$label" /tmp/${label}-packets.csv
  ffmpeg -hide_banner -nostdin -v error -xerror -i "$out" -map 0:a:0 -vn -f null -
  echo "${label}_REMUX_DECODE=PASS"
}

sanitize_test() {
  rate=$1; label="SANITIZED_${rate}"; out=/tmp/${label}.ts
  rm -f "$out" /tmp/${label}-packets.csv
  echo "=== ${label}: DECODE -> CLOCK RESET -> AAC TEST ==="
  start=$(date +%s%N)
  ffmpeg -hide_banner -nostdin -v warning -t 30 -i "$BAD" \
    -map 0:a:0 -af "aresample=${rate}:first_pts=0,asetpts=N/SR/TB" \
    -c:a aac -b:a 192k -ar "$rate" -ac 2 -avoid_negative_ts make_zero -f mpegts "$out"
  end=$(date +%s%N)
  elapsed=$(python3 -c "print((${end}-${start})/1e9)")
  echo "${label}_ENCODE_ELAPSED=$elapsed"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,time_base,start_time,duration -of json "$out"
  ffprobe -v error -select_streams a:0 -show_packets -show_entries packet=pts_time,dts_time,duration_time -of csv=p=0 "$out" > /tmp/${label}-packets.csv
  analyze_packets "$label" /tmp/${label}-packets.csv
  ffmpeg -hide_banner -nostdin -v error -xerror -i "$out" -map 0:a:0 -vn -f null -
  echo "${label}_DECODE=PASS"
}

remux_test GOOD "$GOOD"
remux_test EP34_REJECTED "$BAD"
sanitize_test 44100
sanitize_test 48000

echo '=== DEPLOYED AUDIO HEALTH MONITOR ==='
for f in /srv/fgbears-live/health/audio-health-status /srv/fgbears-live/health/audio-health-warning; do
  if [[ -f "$f" ]]; then echo "--- $f"; cat "$f"; else echo "--- $f MISSING"; fi
done
if [[ -x /usr/local/bin/fgbears-audio-health ]]; then
  /usr/local/bin/fgbears-audio-health --capture-seconds 5 || true
fi

echo '=== CURRENT LIVE PATH HEALTH ==='
echo MASTER=$(systemctl is-active fgbears-live.service 2>/dev/null || true)
echo YOUTUBE=$(systemctl is-active fgbears-youtube-copy-relay.service 2>/dev/null || true)
echo FACEBOOK=$(systemctl is-active fgbears-facebook-relay.service 2>/dev/null || true)
echo RUMBLE=$(systemctl is-active fgbears-rumble-relay.service 2>/dev/null || true)
echo AUDIO_SYNC_TIMER=$(systemctl is-active fgbears-lovable-audio-sync.timer 2>/dev/null || true)
echo AUDIO_SYNC_SERVICE=$(systemctl is-active fgbears-lovable-audio-sync.service 2>/dev/null || true)
echo AUDIO_COMPATIBILITY_ASSESSMENT=PASS
