#!/usr/bin/env bash
set -Eeuo pipefail

: "${RELEASE_SHA:?RELEASE_SHA is required}"
MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
V2=fgbears-youtube-v2.service
V2T=fgbears-youtube-v2-health.timer
SOURCE=fgbears-youtube-v3-source.service
V3=fgbears-youtube-v3.service
SUP=fgbears-youtube-v3-supervisor.service
RETIRED=(fgbears-youtube-output.service fgbears-youtube-relay.service fgbears-youtube-router.service fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer)
ROOT=/run/fgbears-youtube-v3
RELEASE="/opt/fgbears-live/releases/${RELEASE_SHA}/youtube-v3"
CUTOVER=0

pid(){ systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
nr(){ systemctl show -p NRestarts --value "$1" 2>/dev/null || echo 0; }
conn(){ local p=$1 port=$2; [[ "$p" =~ ^[1-9][0-9]*$ ]] && ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v x=":$port" 'index($0,q)&&index($0,x){ok=1} END{exit(ok?0:1)}'; }
fail(){ echo "V3_6_DEPLOY_FAIL=$1" >&2; exit 1; }
progress(){ local key=$1; grep -E "^${key}=" "$ROOT/output.progress" 2>/dev/null | tail -1 | cut -d= -f2 || echo 0; }

cleanup_failure(){
  rc=$?
  if ((rc != 0)); then
    systemctl stop "$SUP" "$V3" "$SOURCE" 2>/dev/null || true
    if ((CUTOVER == 1)); then
      echo 'V3_6_ROLLBACK=BEGIN' >&2
      systemctl reset-failed "$V2" 2>/dev/null || true
      systemctl start "$V2" 2>/dev/null || true
      systemctl enable --now "$V2T" 2>/dev/null || true
      echo 'V3_6_ROLLBACK=V2_RESTORED' >&2
    fi
  fi
  exit "$rc"
}
trap cleanup_failure EXIT

# Install immutable v3.6 release; this does not touch active transport.
install -d -o root -g root -m755 "$RELEASE"
for f in run-youtube-v3-source.sh run-youtube-v3.sh make-youtube-v3-cover.py youtube-v3-supervisor.py; do
  install -o root -g root -m755 "/tmp/$f" "$RELEASE/$f"
done
ln -sfn "$RELEASE" /opt/fgbears-live/youtube-v3
PYTHONPATH=/opt/fgbears-live/exact-card-pylib /opt/fgbears-live/youtube-v3/make-youtube-v3-cover.py
python3 -c 'from PIL import Image; im=Image.open("/opt/fgbears-live/youtube-v3/youtube-trivia-cover.png"); assert im.size==(798,470)'
install -o root -g root -m644 /tmp/fgbears-youtube-v3-source.service /etc/systemd/system/fgbears-youtube-v3-source.service
install -o root -g root -m644 /tmp/fgbears-youtube-v3.service /etc/systemd/system/fgbears-youtube-v3.service
install -o root -g root -m644 /tmp/fgbears-youtube-v3-supervisor.service /etc/systemd/system/fgbears-youtube-v3-supervisor.service
systemctl daemon-reload

# Exact host capability preflight.
bash -n "$RELEASE/run-youtube-v3-source.sh"
bash -n "$RELEASE/run-youtube-v3.sh"
python3 -m py_compile "$RELEASE/youtube-v3-supervisor.py"
ffmpeg -hide_banner -h demuxer=hls 2>/dev/null | grep -q live_start_index
ffmpeg -hide_banner -h muxer=hls 2>/dev/null | grep -q program_date_time
FILTER="[0:v:0]setpts=PTS-STARTPTS,fps=30,setsar=1[base];[1:v:0]format=rgba[cover];[base][cover]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat:enable='lt(mod(t+0,1200),300)+gte(mod(t+0,1200),1192)'[v];[2:a:0]aresample=48000:async=1:first_pts=0,asetpts=PTS-STARTPTS[a]"
ffmpeg -hide_banner -nostdin -loglevel error \
  -f lavfi -i 'testsrc2=size=1280x720:rate=30' \
  -loop 1 -framerate 1 -i /opt/fgbears-live/youtube-v3/youtube-trivia-cover.png \
  -f lavfi -i 'anullsrc=r=48000:cl=stereo' \
  -filter_complex "$FILTER" -map '[v]' -map '[a]' -t 0.5 -f null -
echo "V3_6_HOST_PREFLIGHT=PASS release=$RELEASE filter=yes hls=yes cover=798x470"

# Pre-migration invariants.
systemctl is-active --quiet "$MASTER" || fail master_inactive
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive
systemctl is-active --quiet "$V2" || fail v2_inactive_before_shadow
M0=$(pid "$MASTER"); R0=$(pid "$RUMBLE"); V20=$(pid "$V2")
RN0=$(nr "$RUMBLE"); V2N0=$(nr "$V2")
conn "$R0" 1935 || fail rumble_socket_missing
conn "$V20" 443 || fail v2_socket_missing
for u in "${RETIRED[@]}"; do
  ! systemctl is-active --quiet "$u" || fail "legacy_active:$u"
  s=$(systemctl is-enabled "$u" 2>/dev/null || true)
  [[ "$s" == masked* ]] || fail "legacy_not_masked:$u:$s"
done
speed=$(grep '^speed=' /srv/fgbears-live/logs/ffmpeg-progress.log | tail -1 | cut -d= -f2 | tr -d x)
python3 -c 'import sys; assert float(sys.argv[1] or 0)>=.985' "$speed"

# Add one independent loopback destination. One bounded master restart is the
# only shared-path mutation in the migration.
stamp=$(date -u +%Y%m%dT%H%M%SZ)
q="/opt/fgbears-live/quarantine/v3-6-$stamp"
install -d -m755 "$q"
cp -a /opt/fgbears-live/bin/start-stream.sh "$q/start-stream.sh.pre-v3"
install -o root -g root -m755 /tmp/start-stream-v3.sh /opt/fgbears-live/bin/start-stream.sh
systemctl restart "$MASTER"
for _ in $(seq 1 30); do systemctl is-active --quiet "$MASTER" && break; sleep 1; done
systemctl is-active --quiet "$MASTER" || fail master_failed_after_export
sleep 12
M1=$(pid "$MASTER"); [[ "$M1" =~ ^[1-9][0-9]*$ ]] || fail invalid_new_master_pid
speed=$(grep '^speed=' /srv/fgbears-live/logs/ffmpeg-progress.log | tail -1 | cut -d= -f2 | tr -d x)
python3 -c 'import sys; assert float(sys.argv[1] or 0)>=.985' "$speed"
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive_after_master_restart
systemctl is-active --quiet "$V2" || fail v2_inactive_after_master_restart
conn "$(pid "$RUMBLE")" 1935 || fail rumble_socket_lost_after_master_restart
conn "$(pid "$V2")" 443 || fail v2_socket_lost_after_master_restart
[[ "$(pid "$RUMBLE")" == "$R0" && "$(nr "$RUMBLE")" == "$RN0" ]] || fail rumble_process_changed_during_master_export
[[ "$(pid "$V2")" == "$V20" && "$(nr "$V2")" == "$V2N0" ]] || fail v2_process_changed_during_master_export
echo "V3_6_MASTER_EXPORT=PASS old_master=$M0 new_master=$M1 rumble=$R0 v2=$V20 speed=${speed}x"

# Shadow source validation while v2 still owns YouTube.
systemctl stop "$SUP" "$V3" "$SOURCE" 2>/dev/null || true
systemctl reset-failed "$SOURCE" "$V3" "$SUP" 2>/dev/null || true
systemctl start "$SOURCE"
for _ in $(seq 1 50); do
  [[ -s "$ROOT/source/live.m3u8" ]] && grep -q '^#EXT-X-PROGRAM-DATE-TIME:' "$ROOT/source/live.m3u8" && break
  sleep 0.5
done
PLAY="$ROOT/source/live.m3u8"
[[ -s "$PLAY" ]] || fail source_playlist_missing
grep -q '^#EXT-X-INDEPENDENT-SEGMENTS' "$PLAY" || fail independent_segment_contract_missing
grep -q '^#EXT-X-PROGRAM-DATE-TIME:' "$PLAY" || fail program_date_time_missing
latest=$(ls -1t "$ROOT"/source/seg-*.ts 2>/dev/null | head -1)
[[ -n "$latest" && -s "$latest" ]] || fail no_source_segment
ffmpeg -hide_banner -nostdin -loglevel error -i "$latest" -t 1 -f null - || fail source_segment_decode_failed
dims=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,avg_frame_rate -of csv=p=0 "$latest")
[[ "$dims" == 1280,720,* ]] || fail "source_geometry:$dims"
acodec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nk=1:nw=1 "$latest")
[[ -n "$acodec" ]] || fail source_audio_missing
echo "V3_6_SOURCE_SHADOW=PASS segment=$(basename "$latest") video=$dims audio=$acodec"

# Exact output graph shadow test, still leaving v2 live.
rm -f "$ROOT/shadow.flv"
set +e
sudo -u fgbears env YOUTUBE_V3_TARGET="$ROOT/shadow.flv" timeout --signal=INT 35 /opt/fgbears-live/youtube-v3/run-youtube-v3.sh
rc=$?
set -e
[[ "$rc" == 0 || "$rc" == 124 || "$rc" == 130 ]] || fail "shadow_encoder_rc:$rc"
[[ -s "$ROOT/shadow.flv" ]] || fail shadow_output_missing
ffmpeg -hide_banner -nostdin -loglevel error -i "$ROOT/shadow.flv" -t 2 -f null - || fail shadow_decode_failed
v=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,avg_frame_rate -of csv=p=0 "$ROOT/shadow.flv")
a=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels -of csv=p=0 "$ROOT/shadow.flv")
[[ "$v" == h264,1280,720,* ]] || fail "shadow_video_contract:$v"
[[ "$a" == aac,48000,2* ]] || fail "shadow_audio_contract:$a"
[[ "$(pid "$V2")" == "$V20" && "$(nr "$V2")" == "$V2N0" ]] || fail v2_changed_during_shadow
conn "$V20" 443 || fail v2_socket_lost_during_shadow
[[ "$(pid "$RUMBLE")" == "$R0" && "$(nr "$RUMBLE")" == "$RN0" ]] || fail rumble_changed_during_shadow
conn "$R0" 1935 || fail rumble_socket_lost_during_shadow
echo "V3_6_OUTPUT_SHADOW=PASS video=$v audio=$a v2_unchanged=yes rumble_unchanged=yes"

# Single-owner cutover. v2 remains installed and unmasked for deployment rollback.
systemctl disable --now "$V2T" 2>/dev/null || true
systemctl stop "$V2"
CUTOVER=1
systemctl reset-failed "$V3" 2>/dev/null || true
systemctl start "$V3"
connected=0
for _ in $(seq 1 45); do
  P=$(pid "$V3")
  if systemctl is-active --quiet "$V3" && conn "$P" 443; then connected=1; break; fi
  sleep 1
done
((connected==1)) || fail v3_ingest_not_established
Y0=$(pid "$V3")
F0=$(progress frame); T0=$(progress out_time_us)
sleep 12
F1=$(progress frame); T1=$(progress out_time_us)
[[ "$F1" -gt "$F0" && "$T1" -gt "$T0" ]] || fail "v3_media_not_advancing:$F0,$F1,$T0,$T1"
conn "$Y0" 443 || fail v3_socket_lost
[[ "$(pid "$V3")" == "$Y0" ]] || fail v3_pid_changed
! systemctl is-active --quiet "$V2" || fail v2_still_active
[[ "$(pid "$MASTER")" == "$M1" ]] || fail master_changed_during_cutover
[[ "$(pid "$RUMBLE")" == "$R0" && "$(nr "$RUMBLE")" == "$RN0" ]] || fail rumble_changed_during_cutover
conn "$R0" 1935 || fail rumble_socket_lost_during_cutover
for u in "${RETIRED[@]}"; do ! systemctl is-active --quiet "$u" || fail "legacy_reactivated:$u"; done

systemctl disable "$V2" 2>/dev/null || true
systemctl enable "$SOURCE" "$V3" "$SUP"
systemctl start "$SUP"
sleep 32
systemctl is-active --quiet "$SOURCE" || fail source_inactive_after_hold
systemctl is-active --quiet "$V3" || fail v3_inactive_after_hold
systemctl is-active --quiet "$SUP" || fail supervisor_inactive_after_hold
[[ "$(pid "$V3")" == "$Y0" ]] || fail v3_restarted_during_hold
conn "$Y0" 443 || fail v3_socket_missing_after_hold
F2=$(progress frame); T2=$(progress out_time_us)
[[ "$F2" -gt "$F1" && "$T2" -gt "$T1" ]] || fail v3_progress_stalled_after_hold
[[ "$(pid "$MASTER")" == "$M1" ]] || fail master_changed_after_hold
[[ "$(pid "$RUMBLE")" == "$R0" && "$(nr "$RUMBLE")" == "$RN0" ]] || fail rumble_changed_after_hold
conn "$R0" 1935 || fail rumble_socket_missing_after_hold

# Supervisor must have emitted at least one healthy line and no recovery.
journalctl -u "$SUP" --since '-40 seconds' --no-pager | grep -q 'V3_HEALTH' || fail supervisor_no_health_sample
! journalctl -u "$SUP" --since '-40 seconds' --no-pager | grep -q 'V3_RECOVERY' || fail supervisor_recovered_during_acceptance

CUTOVER=0
trap - EXIT
echo "YOUTUBE_V3_6_DEPLOY=PASS master=$M1 rumble=$R0 youtube=$Y0 source=$(pid "$SOURCE") supervisor=$(pid "$SUP") frame=$F2 out_us=$T2 v2=disabled_not_masked legacy=masked"
