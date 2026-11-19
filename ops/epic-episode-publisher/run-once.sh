#!/usr/bin/env bash
# Isolated EPIC standalone publisher. No stream/recorder management.
set -euo pipefail
if [[ "${EPIC_PUBLISHER_ARMED:-no}" != "yes" ]]; then
  echo 'EPIC_PUBLISHER_DISABLED=true'
  exit 0
fi
test -s /opt/epic-episode-publisher/epic-episode-cutter.py
test -r /etc/epic-cnt/archive-key
test -d /srv/cnt-archive/rolling
exec /usr/bin/docker run --rm --pull never --name epic-episode-publisher-once \
  --user 1000:1000 --network bridge --read-only \
  --tmpfs /tmp:rw,nosuid,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 100 --memory 384m --cpus 0.7 \
  --mount type=bind,src=/srv/cnt-archive,dst=/cnt-archive \
  --mount type=bind,src=/etc/epic-cnt/archive-key,dst=/run/secrets/cnt_archive_key,readonly \
  --mount type=bind,src=/opt/epic-episode-publisher/epic-episode-cutter.py,dst=/opt/cnt/epic-episode-cutter.py,readonly \
  -e CNT_ARCHIVE_DIR=/cnt-archive -e CNT_ARCHIVE_KEY_FILE=/run/secrets/cnt_archive_key \
  -e CNT_ARCHIVE_URL=https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/archive \
  -e EPIC_EPISODE_RUN=yes \
  --entrypoint /bin/bash epic-cnt-phase2:staged -lc \
  'export CNT_ARCHIVE_HMAC_SECRET="$(cat /run/secrets/cnt_archive_key)"; exec python3 -B /opt/cnt/epic-episode-cutter.py'
