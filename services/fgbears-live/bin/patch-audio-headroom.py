#!/usr/bin/env python3
"""One-shot repository patch for FGB live audio headroom and health gates."""
from pathlib import Path


def replace_once(path_str: str, old: str, new: str) -> None:
    path = Path(path_str)
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected anchor missing in {path_str}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "services/fgbears-live/bin/start-stream.sh",
    ': "${PODCAST_AUDIO_FILTER:=aresample=48000:first_pts=0}"',
    ': "${PODCAST_AUDIO_FILTER:=volume=-2dB,aresample=48000:first_pts=0}"',
)
replace_once(
    "services/fgbears-live/config/stream.env.example",
    "PODCAST_AUDIO_FILTER=aresample=48000:first_pts=0",
    "PODCAST_AUDIO_FILTER=volume=-2dB,aresample=48000:first_pts=0",
)
replace_once(
    "services/fgbears-live/bin/install.sh",
    "install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck\ninstall -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status",
    "install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck\ninstall -m 0755 /opt/fgbears-live/bin/audio-health.py /usr/local/bin/fgbears-audio-health\ninstall -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status",
)
replace_once(
    "services/fgbears-live/bin/install.sh",
    'updates = {\n    "YOUTUBE_LOCAL_UDP_URL": "udp://127.0.0.1:1939?pkt_size=1316",',
    'updates = {\n    "PODCAST_AUDIO_FILTER": "volume=-2dB,aresample=48000:first_pts=0",\n    "YOUTUBE_LOCAL_UDP_URL": "udp://127.0.0.1:1939?pkt_size=1316",',
)

health = Path("services/fgbears-live/bin/healthcheck.sh")
text = health.read_text(encoding="utf-8")
env_anchor = "YOUTUBE_RELAY_SERVICE=${YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}\n"
env_block = """YOUTUBE_RELAY_SERVICE=${YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
AUDIO_HEALTH_INTERVAL_SECONDS=${FGB_AUDIO_HEALTH_INTERVAL_SECONDS:-900}
AUDIO_HEALTH_SAMPLE_SECONDS=${FGB_AUDIO_HEALTH_SAMPLE_SECONDS:-8}
AUDIO_HEALTH_EPOCH_FILE=${FGB_AUDIO_HEALTH_EPOCH_FILE:-$HEALTH_STATE_DIR/audio-health-epoch}
AUDIO_HEALTH_STATUS_FILE=${FGB_AUDIO_HEALTH_STATUS_FILE:-$HEALTH_STATE_DIR/audio-health-status}
AUDIO_HEALTH_WARNING_FILE=${FGB_AUDIO_HEALTH_WARNING_FILE:-$HEALTH_STATE_DIR/audio-health-warning}
"""
if env_anchor not in text:
    raise SystemExit("healthcheck env anchor missing")
text = text.replace(env_anchor, env_block, 1)

function_anchor = "reconcile_social_relay() {\n"
function_block = r'''run_audio_check() {
  local now last=0 output rc temporary
  [[ -x "$AUDIO_HEALTH_BIN" ]] || return 0
  now=$(date +%s)
  if [[ -s "$AUDIO_HEALTH_EPOCH_FILE" ]]; then
    last=$(cat "$AUDIO_HEALTH_EPOCH_FILE" 2>/dev/null || printf '0')
  fi
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  if (( now - last < AUDIO_HEALTH_INTERVAL_SECONDS )); then
    return 0
  fi

  if output=$("$AUDIO_HEALTH_BIN" --capture-seconds "$AUDIO_HEALTH_SAMPLE_SECONDS" 2>&1); then
    rc=0
  else
    rc=$?
  fi
  temporary="${AUDIO_HEALTH_STATUS_FILE}.partial"
  printf '%s\n' "$output" > "$temporary"
  mv -f "$temporary" "$AUDIO_HEALTH_STATUS_FILE"
  printf '%s\n' "$now" > "${AUDIO_HEALTH_EPOCH_FILE}.partial"
  mv -f "${AUDIO_HEALTH_EPOCH_FILE}.partial" "$AUDIO_HEALTH_EPOCH_FILE"

  if (( rc != 0 )); then
    printf '%s rc=%s %s\n' "$now" "$rc" "$(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)" > "$AUDIO_HEALTH_WARNING_FILE"
    logger -t fgbears-live-health "Audio quality warning: $(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)"
    return 0
  fi
  rm -f "$AUDIO_HEALTH_WARNING_FILE"
}

'''
if function_anchor not in text:
    raise SystemExit("healthcheck function anchor missing")
text = text.replace(function_anchor, function_block + function_anchor, 1)
call_anchor = "reconcile_social_relay instagram INSTAGRAM_RELAY_ENABLED\nrun_lag_check\nprintf '%s %s\\n' \"$now\" \"$out_time_us\""
call_replacement = "reconcile_social_relay instagram INSTAGRAM_RELAY_ENABLED\nrun_lag_check\nrun_audio_check\nprintf '%s %s\\n' \"$now\" \"$out_time_us\""
if call_anchor not in text:
    raise SystemExit("healthcheck call anchor missing")
text = text.replace(call_anchor, call_replacement, 1)
health.write_text(text, encoding="utf-8")

validate = Path(".github/workflows/fgbears-live-validate.yml")
text = validate.read_text(encoding="utf-8")
anchor = "      - name: Health monitor\n        run: bash services/fgbears-live/tests/test-health-monitor.sh\n"
if anchor not in text:
    raise SystemExit("validate workflow anchor missing")
text = text.replace(
    anchor,
    anchor + "      - name: Audio health thresholds\n        run: python3 services/fgbears-live/bin/audio-health.py --self-test\n",
    1,
)
validate.write_text(text, encoding="utf-8")

deploy = Path(".github/workflows/fgbears-live-deploy.yml")
text = deploy.read_text(encoding="utf-8")
anchor = "      - id: crawl_frame\n        name: Decode live rendered crawl frame on Oracle\n"
step = """      - id: audio_health
        name: Verify YouTube-bound audio headroom and continuity
        if: always() && steps.install.outcome == 'success'
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
        run: |
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo /usr/local/bin/fgbears-audio-health --capture-seconds 10'

"""
if anchor not in text:
    raise SystemExit("deploy workflow crawl anchor missing")
text = text.replace(anchor, step + anchor, 1)

env_anchor = "          PROGRAM_CLOCK_OUTCOME: ${{ steps.program_clock.outcome }}\n          CRAWL_FRAME_OUTCOME: ${{ steps.crawl_frame.outcome }}\n"
if env_anchor not in text:
    raise SystemExit("deploy status env anchor missing")
text = text.replace(
    env_anchor,
    "          PROGRAM_CLOCK_OUTCOME: ${{ steps.program_clock.outcome }}\n          AUDIO_HEALTH_OUTCOME: ${{ steps.audio_health.outcome }}\n          CRAWL_FRAME_OUTCOME: ${{ steps.crawl_frame.outcome }}\n",
    1,
)

ok_old = '&& "$PROGRAM_CLOCK_OUTCOME" == "success" && "$CRAWL_FRAME_OUTCOME" == "success"'
if ok_old not in text:
    raise SystemExit("deploy status success-condition anchor missing")
text = text.replace(
    ok_old,
    '&& "$PROGRAM_CLOCK_OUTCOME" == "success" && "$AUDIO_HEALTH_OUTCOME" == "success" && "$CRAWL_FRAME_OUTCOME" == "success"',
    1,
)

arg_anchor = '            --arg programClockOutcome "$PROGRAM_CLOCK_OUTCOME" \\\n            --arg crawlFrameOutcome "$CRAWL_FRAME_OUTCOME" \\\n'
if arg_anchor not in text:
    raise SystemExit("deploy jq arg anchor missing")
text = text.replace(
    arg_anchor,
    '            --arg programClockOutcome "$PROGRAM_CLOCK_OUTCOME" \\\n            --arg audioHealthOutcome "$AUDIO_HEALTH_OUTCOME" \\\n            --arg crawlFrameOutcome "$CRAWL_FRAME_OUTCOME" \\\n',
    1,
)

json_anchor = "youtubeRelayOutcome:$youtubeRelayOutcome,programClockOutcome:$programClockOutcome,crawlFrameOutcome:$crawlFrameOutcome"
if json_anchor not in text:
    raise SystemExit("deploy JSON status anchor missing")
text = text.replace(
    json_anchor,
    "youtubeRelayOutcome:$youtubeRelayOutcome,programClockOutcome:$programClockOutcome,audioHealthOutcome:$audioHealthOutcome,crawlFrameOutcome:$crawlFrameOutcome",
    1,
)
if "audioBitrateKbps:128," in text:
    text = text.replace(
        "audioBitrateKbps:128,",
        "audioBitrateKbps:128,audioPeakLimitDbfs:-1.0,audioLiveGainDb:-2.0,audioHealthIntervalSeconds:900,",
        1,
    )
deploy.write_text(text, encoding="utf-8")

print("audio_headroom_patch=OK")
