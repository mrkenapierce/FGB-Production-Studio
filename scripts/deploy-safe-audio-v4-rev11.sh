#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_SHA=c6bb57ad24bd8f06bc60c12afa534093e07afffb17ac7bf6c241f092d36d9ebd
OLD_SHA=c8391464ae77eec19b85270d67522300202fe5494232581c55433f934b172a12
CONTRACT=https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing
AUDIO=/srv/fgbears-live/audio/fgb-music-loop.m4a
STATE=/srv/fgbears-live/runtime/lovable-audio-pipeline.json
START=/usr/local/bin/fgbears-start-stream
SAFE_BIN=/usr/local/bin/fgbears-lovable-audio-v4-sync
LEGACY_BIN=/usr/local/bin/fgbears-lovable-audio-pipeline
LEGACY_Q=/srv/fgbears-live/quarantine/legacy-lovable-audio-preparation
QROOT=/srv/fgbears-live/quarantine/safe-audio-v4

for cmd in curl jq ffmpeg ffprobe sha256sum systemctl python3; do
  command -v "$cmd" >/dev/null
done

curl -fsS --max-time 20 "$CONTRACT" -o /tmp/fgb-rev11-contract.json
test "$(jq -r '.presentation.audio.revision' /tmp/fgb-rev11-contract.json)" = 11
test "$(jq -r '.presentation.audio.approvalState' /tmp/fgb-rev11-contract.json)" = approved
test "$(jq -r '.presentation.audio.sourceSha256' /tmp/fgb-rev11-contract.json)" = "$EXPECTED_SHA"
test "$(jq -r '.presentation.audio.activeTrackName' /tmp/fgb-rev11-contract.json)" = FGB_Episode_034_SOUNDS_GREAT_STANDARD.m4a
test "$(jq -r '.presentation.audio.volumeGainDb' /tmp/fgb-rev11-contract.json)" = 0
systemctl is-active --quiet fgbears-live.service
systemctl is-active --quiet fgbears-youtube-copy-relay.service

current_sha=$(sha256sum "$AUDIO" | awk '{print $1}')
case "$current_sha" in
  "$OLD_SHA"|"$EXPECTED_SHA") ;;
  *) echo "Refusing cutover: unexpected current live audio SHA $current_sha" >&2; exit 1 ;;
esac

# Hard-quarantine only the legacy 48 kHz preparation route. The safe v4 route
# uses a different executable and different systemd units.
before_pid=$(systemctl show -p MainPID --value fgbears-live.service)
systemctl disable --now fgbears-lovable-audio-sync.timer >/dev/null 2>&1 || true
systemctl stop fgbears-lovable-audio-sync.service >/dev/null 2>&1 || true
rm -f /etc/fgbears-live/UNQUARANTINE_LEGACY_AUDIO_PREPARATION
install -d -m 0755 "$LEGACY_Q"
if [[ -f "$LEGACY_BIN" ]] && ! grep -Fq 'QUARANTINED. Refusing execution' "$LEGACY_BIN"; then
  cp -a "$LEGACY_BIN" "$LEGACY_Q/fgbears-lovable-audio-pipeline.legacy.$(date -u +%Y%m%dT%H%M%SZ)"
fi
printf '%s\n' '#!/usr/bin/env bash' "echo 'FGB legacy Lovable 48 kHz audio preparation pathway is QUARANTINED. Refusing execution.' >&2" 'exit 78' > "$LEGACY_BIN"
chmod 0755 "$LEGACY_BIN"
test ! -e /etc/fgbears-live/UNQUARANTINE_LEGACY_AUDIO_PREPARATION
test "$(systemctl is-active fgbears-lovable-audio-sync.timer 2>/dev/null || true)" != active
test "$(systemctl is-active fgbears-lovable-audio-sync.service 2>/dev/null || true)" != active
test "$(systemctl show -p MainPID --value fgbears-live.service)" = "$before_pid"
test "$(sha256sum "$AUDIO" | awk '{print $1}')" = "$current_sha"
echo LEGACY_AUDIO_PATHWAY=QUARANTINED

# Preserve rollback set before any production executable or media changes.
stamp=$(date -u +%Y%m%dT%H%M%SZ)
qdir="$QROOT/${stamp}-rev11"
install -d -m 0755 "$qdir"
cp -a "$AUDIO" "$qdir/fgb-music-loop.m4a"
cp -a "$START" "$qdir/fgbears-start-stream"
printf '%s\n' "$qdir" > /tmp/fgb-safe-v4-qdir

# Fetch and verify the exact Lovable-approved asset.
asset=$(jq -r '.presentation.audio.assetUrl' /tmp/fgb-rev11-contract.json)
case "$asset" in
  http://*|https://*) asset_url=$asset ;;
  /*) asset_url="https://epiccontentcreatorgrants.org${asset}" ;;
  *) echo "Unexpected asset URL: $asset" >&2; exit 1 ;;
esac
curl -fsSL --max-time 90 "$asset_url" -o /tmp/fgb-rev11-approved.m4a
test "$(sha256sum /tmp/fgb-rev11-approved.m4a | awk '{print $1}')" = "$EXPECTED_SHA"
test "$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nk=1:nw=1 /tmp/fgb-rev11-approved.m4a)" = aac
test "$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=nk=1:nw=1 /tmp/fgb-rev11-approved.m4a)" = 44100
test "$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=nk=1:nw=1 /tmp/fgb-rev11-approved.m4a)" = 2
test "$(ffprobe -v error -select_streams a:0 -show_entries stream=start_time -of default=nk=1:nw=1 /tmp/fgb-rev11-approved.m4a)" = 0.000000
first_pts=$(ffprobe -v error -read_intervals '%+0.10' -select_streams a:0 -show_packets -show_entries packet=pts_time -of csv=p=0 /tmp/fgb-rev11-approved.m4a | sed -n '1p' | cut -d, -f1)
test "$first_pts" = 0.000000
ffmpeg -hide_banner -nostdin -v error -xerror -i /tmp/fgb-rev11-approved.m4a -map 0:a:0 -vn -f null -
ffprobe -v error -select_streams a:0 -show_packets -show_entries packet=pts_time,duration_time -of csv=p=0 /tmp/fgb-rev11-approved.m4a > /tmp/fgb-rev11-source-packets.csv
python3 -c 'import csv,sys; rows=[]
for r in csv.reader(open(sys.argv[1])):
    try: rows.append((float(r[0]),float(r[1])))
    except Exception: pass
assert len(rows)>100; regs=[]; gaps=[]
for i in range(1,len(rows)):
    d=rows[i][0]-rows[i-1][0]
    if d < -0.001: regs.append(d)
    if d > max(0.08,rows[i-1][1]*3): gaps.append(d)
print(f"SOURCE_PACKETS={len(rows)} SOURCE_REGRESSIONS={len(regs)} SOURCE_GAPS={len(gaps)}")
assert not regs and not gaps' /tmp/fgb-rev11-source-packets.csv

# Shadow the exact master-owned clock design before touching production.
rm -f /tmp/fgb-safe-v4-shadow.ts /tmp/fgb-safe-v4-shadow-packets.csv
ffmpeg -hide_banner -nostdin -v error \
  -re -f lavfi -i color=c=black:s=320x180:r=30 \
  -thread_queue_size 512 -re -stream_loop -1 -i /tmp/fgb-rev11-approved.m4a \
  -t 20 -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 60 -r 30 -fps_mode cfr \
  -af 'aresample=44100:async=1:first_pts=0,asetpts=N/SR/TB' \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -f mpegts /tmp/fgb-safe-v4-shadow.ts
ffprobe -v error -select_streams a:0 -show_packets -show_entries packet=pts_time,duration_time -of csv=p=0 /tmp/fgb-safe-v4-shadow.ts > /tmp/fgb-safe-v4-shadow-packets.csv
python3 -c 'import csv,sys; rows=[]
for r in csv.reader(open(sys.argv[1])):
    try: rows.append((float(r[0]),float(r[1])))
    except Exception: pass
assert len(rows)>100; regs=[]; gaps=[]
for i in range(1,len(rows)):
    d=rows[i][0]-rows[i-1][0]
    if d < -0.001: regs.append(d)
    if d > max(0.08,rows[i-1][1]*3): gaps.append(d)
print(f"SHADOW_PACKETS={len(rows)} SHADOW_REGRESSIONS={len(regs)} SHADOW_GAPS={len(gaps)}")
assert not regs and not gaps' /tmp/fgb-safe-v4-shadow-packets.csv
ffmpeg -hide_banner -nostdin -v error -xerror -i /tmp/fgb-safe-v4-shadow.ts -map 0:a:0 -vn -f null -
echo SAFE_AUDIO_V4_SHADOW=PASS

# Install the new safe namespace without interrupting the running master.
install -m 0755 /tmp/start-stream.sh "$START"
install -d -m 0755 /usr/local/lib/fgbears-live
install -m 0644 /tmp/lovable-audio-pipeline-v4.py /usr/local/lib/fgbears-live/lovable-audio-pipeline-v4.py
install -m 0755 /tmp/lovable-audio-pipeline-v4-runner.py "$SAFE_BIN"
install -m 0755 /tmp/audio-health-standard-v4.py /usr/local/bin/fgbears-audio-health
install -m 0644 /tmp/fgbears-lovable-audio-v4-sync.service /etc/systemd/system/fgbears-lovable-audio-v4-sync.service
install -m 0644 /tmp/fgbears-lovable-audio-v4-sync.timer /etc/systemd/system/fgbears-lovable-audio-v4-sync.timer
systemctl daemon-reload
test "$(systemctl show -p MainPID --value fgbears-live.service)" = "$before_pid"
test "$(sha256sum "$AUDIO" | awk '{print $1}')" = "$current_sha"

tmp=$(mktemp)
jq '.failedRevisions = ([.failedRevisions[]? | select(. != 11)]) | .status="retry_armed" | .message="Revision 11 armed for isolated safe audio v4 cutover"' "$STATE" > "$tmp"
mv -f "$tmp" "$STATE"

echo SAFE_AUDIO_V4_INSTALL_NO_INTERRUPTION=PASS

rollback_all() {
  rc=$?
  set +e
  systemctl disable --now fgbears-lovable-audio-v4-sync.timer >/dev/null 2>&1 || true
  cp -f "$qdir/fgbears-start-stream" "$START"
  chmod 0755 "$START"
  cp -f "$qdir/fgb-music-loop.m4a" "${AUDIO}.rollback-safe-v4"
  chown fgbears:fgbears "${AUDIO}.rollback-safe-v4"
  chmod 0644 "${AUDIO}.rollback-safe-v4"
  mv -f "${AUDIO}.rollback-safe-v4" "$AUDIO"
  systemctl restart fgbears-live.service
  sleep 10
  restored=$(sha256sum "$AUDIO" | awk '{print $1}')
  tmp=$(mktemp)
  jq '.failedRevisions = ((.failedRevisions // []) + [11] | unique) | .status="rolled_back" | .message="Revision 11 isolated safe v4 cutover failed; prior audio/master restored"' "$STATE" > "$tmp" && mv -f "$tmp" "$STATE"
  echo "SAFE_AUDIO_V4_ROLLBACK=COMPLETE restored_sha=$restored"
  exit "$rc"
}
trap rollback_all ERR

# v4 detects this file as direct-ready and promotes it byte-for-byte. Restarting
# the master activates the master-owned 44.1 kHz AAC clock and refreshes YouTube.
"$SAFE_BIN"
test "$(sha256sum "$AUDIO" | awk '{print $1}')" = "$EXPECTED_SHA"
test "$(jq -r '.appliedRevision' "$STATE")" = 11
test "$(jq -r '.canonicalSha256' "$STATE")" = "$EXPECTED_SHA"
test "$(jq -r '.ingestMode' "$STATE")" = direct_byte_for_byte
systemctl is-active --quiet fgbears-live.service
systemctl is-active --quiet fgbears-youtube-copy-relay.service

main=$(systemctl show -p MainPID --value fgbears-live.service)
ffpid=$(pgrep -P "$main" -x ffmpeg | sed -n '1p')
test -n "$ffpid"
tr '\0' ' ' < "/proc/$ffpid/cmdline" > /tmp/fgb-safe-v4-master-cmdline
grep -Fq -- '-c:a aac' /tmp/fgb-safe-v4-master-cmdline
grep -Fq -- '-b:a 128k' /tmp/fgb-safe-v4-master-cmdline
grep -Fq -- '-ar 44100' /tmp/fgb-safe-v4-master-cmdline
grep -Fq -- 'aresample=44100:async=1:first_pts=0,asetpts=N/SR/TB' /tmp/fgb-safe-v4-master-cmdline
! grep -Fq -- '-c:a copy' /tmp/fgb-safe-v4-master-cmdline

# Verify the platform-bound program twice after the relay has settled.
sleep 12
health_epoch=$(date +%s)
for pass in 1 2; do
  /usr/local/bin/fgbears-audio-health --capture-seconds 15 | tee "/tmp/fgb-safe-v4-health-${pass}.txt"
  grep -Fqx 'audio_sample_rate=44100' "/tmp/fgb-safe-v4-health-${pass}.txt"
  grep -Fqx 'audio_pts_regressions=0' "/tmp/fgb-safe-v4-health-${pass}.txt"
  grep -Fqx 'audio_large_pts_gaps=0' "/tmp/fgb-safe-v4-health-${pass}.txt"
  grep -Fqx 'AUDIO_WARNINGS=NONE' "/tmp/fgb-safe-v4-health-${pass}.txt"
  grep -Fqx 'OVERALL_STATUS=OK' "/tmp/fgb-safe-v4-health-${pass}.txt"
  sleep 4
done
if journalctl -u fgbears-youtube-copy-relay.service --since "@$health_epoch" --no-pager | grep -Ei 'timestamp discontinuity|DTS .* out of order|Packet corrupt|dropping it|non.monoton'; then
  echo 'YouTube relay reported timestamp corruption after v4 cutover.' >&2
  false
fi

# Only after all gates pass do we enable future approvals on the isolated v4 timer.
test ! -e /etc/fgbears-live/UNQUARANTINE_LEGACY_AUDIO_PREPARATION
test "$(systemctl is-active fgbears-lovable-audio-sync.timer 2>/dev/null || true)" != active
test "$(systemctl is-active fgbears-lovable-audio-sync.service 2>/dev/null || true)" != active
grep -Fq 'QUARANTINED. Refusing execution' "$LEGACY_BIN"
systemctl enable --now fgbears-lovable-audio-v4-sync.timer
test "$(systemctl is-enabled fgbears-lovable-audio-v4-sync.timer)" = enabled
systemctl is-active --quiet fgbears-lovable-audio-v4-sync.timer
systemctl start fgbears-lovable-audio-v4-sync.service
sleep 3
test "$(sha256sum "$AUDIO" | awk '{print $1}')" = "$EXPECTED_SHA"
test "$(jq -r '.appliedRevision' "$STATE")" = 11
journalctl -u fgbears-lovable-audio-v4-sync.service --since '-2 minutes' --no-pager | grep -Fq 'FGB_AUDIO_PIPELINE_V4 no_change revision=11 already_live'
systemctl is-active --quiet fgbears-live.service
systemctl is-active --quiet fgbears-youtube-copy-relay.service
trap - ERR

echo LIVE_SHA=$(sha256sum "$AUDIO" | awk '{print $1}')
echo APPLIED_REVISION=$(jq -r '.appliedRevision' "$STATE")
echo INGEST_MODE=$(jq -r '.ingestMode' "$STATE")
echo SAFE_AUDIO_V4_TIMER=$(systemctl is-active fgbears-lovable-audio-v4-sync.timer)
echo LEGACY_AUDIO_PATHWAY=QUARANTINED
echo FGB_SAFE_AUDIO_V4=PASS
