#!/usr/bin/env bash
# Independent EPIC only. Does not signal or restart live capture/recorder.
set -euo pipefail
if [[ "${EPIC_OBSERVER_ARMED:-no}" != yes ]]; then
  echo 'EPIC_AIR_OBSERVER_DISABLED=true'
  exit 0
fi
test -s /opt/epic-episode-publisher/epic-air-observer.py
test -r /etc/epic-cnt/archive-hmac
test -f /srv/cnt-archive/state/chrome.log
exec /usr/bin/docker run --rm --pull never --name epic-air-observer \
  --user 1000:1000 --network bridge --read-only \
  --tmpfs /tmp:rw,nosuid,size=32m \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 40 --memory 192m --cpus 0.25 \
  --mount type=bind,src=/srv/cnt-archive,dst=/cnt-archive \
  --mount type=bind,src=/etc/epic-cnt/archive-hmac,dst=/run/secrets/epic_archive_hmac,readonly \
  --mount type=bind,src=/opt/epic-episode-publisher/epic-air-observer.py,dst=/opt/cnt/epic-air-observer.py,readonly \
  -e CNT_AIR_LOG=/cnt-archive/state/chrome.log \
  -e CNT_AIR_STATE=/cnt-archive/state/epic-air-observer.json \
  -e CNT_ARCHIVE_URL=https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/archive \
  -e CNT_BROADCAST_ORIGIN=https://epiccontentcreatorgrants.org \
  --entrypoint /bin/bash epic-cnt-phase2:staged -lc \
  'export CNT_ARCHIVE_HMAC_SECRET="$(cat /run/secrets/epic_archive_hmac)"; exec python3 -B /opt/cnt/epic-air-observer.py'
