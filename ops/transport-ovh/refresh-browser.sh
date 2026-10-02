#!/usr/bin/env bash
set -euo pipefail

cd /opt/fgb-transport
URL='https://epiccontentcreatorgrants.org/fgb-broadcast?target=youtube'

cid_before=$(sudo docker compose --env-file .env ps -q youtube)
test -n "$cid_before"
restarts_before=$(sudo docker inspect -f '{{.RestartCount}}' "$cid_before")
ffmpeg_before=$(sudo docker compose --env-file .env exec -T youtube sh -lc 'pgrep -o ffmpeg')
state_before=$(sudo docker compose --env-file .env exec -T youtube sh -lc 'cat /tmp/fgb-transport.state 2>/dev/null || echo missing')
test "$state_before" = live

# Do not switch the captured browser unless the broadcast page itself is healthy now.
http_code=$(sudo docker compose --env-file .env exec -T youtube sh -lc "curl -sS -m 15 -o /tmp/fgb-origin-probe.html -w '%{http_code}' '$URL'")
case "$http_code" in
  2??) ;;
  *) echo "Broadcast page probe failed with HTTP $http_code; browser left untouched"; exit 20 ;;
esac
if sudo docker compose --env-file .env exec -T youtube sh -lc "grep -Eqi 'Error 1102|Cloudflare.*1102' /tmp/fgb-origin-probe.html"; then
  echo 'Broadcast page still contains Cloudflare Error 1102; browser left untouched'
  exit 21
fi

old_ids=$(sudo docker compose --env-file .env exec -T youtube sh -lc \
  "curl -fsS http://127.0.0.1:9222/json/list | grep -o '\"id\"[[:space:]]*:[[:space:]]*\"[^\"]*\"' | cut -d'\"' -f4" || true)

new_target=$(sudo docker compose --env-file .env exec -T youtube sh -lc \
  "curl -fsS -X PUT 'http://127.0.0.1:9222/json/new?$URL'")
new_id=$(printf '%s' "$new_target" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
test -n "$new_id"
echo "NEW_CHROMIUM_TARGET=$new_id"

sleep 12
sudo docker compose --env-file .env exec -T youtube sh -lc \
  "curl -fsS 'http://127.0.0.1:9222/json/activate/$new_id' >/dev/null"
sleep 3

# Once the healthy replacement is active, close stale page targets so X11 cannot fall back to them.
for old_id in $old_ids; do
  [ "$old_id" = "$new_id" ] && continue
  sudo docker compose --env-file .env exec -T youtube sh -lc \
    "curl -fsS 'http://127.0.0.1:9222/json/close/$old_id' >/dev/null" || true
done
sleep 2

targets_after=$(sudo docker compose --env-file .env exec -T youtube sh -lc 'curl -fsS http://127.0.0.1:9222/json/list')
printf '%s' "$targets_after" | grep -Fq "$new_id"
printf '%s\n' "$targets_after" | sed -n '1,120p'

cid_after=$(sudo docker compose --env-file .env ps -q youtube)
restarts_after=$(sudo docker inspect -f '{{.RestartCount}}' "$cid_after")
ffmpeg_after=$(sudo docker compose --env-file .env exec -T youtube sh -lc 'pgrep -o ffmpeg')
state_after=$(sudo docker compose --env-file .env exec -T youtube sh -lc 'cat /tmp/fgb-transport.state 2>/dev/null || echo missing')

test "$cid_after" = "$cid_before"
test "$restarts_after" = "$restarts_before"
test "$ffmpeg_after" = "$ffmpeg_before"
test "$state_after" = live

# Prove the display is still capturable after the page-only repair.
sudo docker compose --env-file .env exec -T youtube sh -lc \
  'ffmpeg -hide_banner -loglevel error -f x11grab -draw_mouse 0 -video_size 1280x720 -i :99.0 -frames:v 1 -f image2pipe -vcodec png -' > /tmp/fgb-browser-after.png
test -s /tmp/fgb-browser-after.png

echo "LIVE_STATE=$state_after"
echo 'CONTAINER_ID_UNCHANGED=yes'
echo "CONTAINER_RESTARTS=$restarts_after"
echo 'FFMPEG_PID_UNCHANGED=yes'
echo 'BROWSER_REFRESH=complete'
