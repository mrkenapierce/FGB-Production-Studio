#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw openssh-server docker.io docker-compose-v2
systemctl enable --now ssh
systemctl enable --now docker

install -d -m 0755 /opt/fgb-transport
install -d -o 1000 -g 1000 -m 0750 /srv/fgb-archive
rm -rf /tmp/fgb-prod-studio
git clone --depth 1 --filter=blob:none --sparse https://github.com/mrkenapierce/FGB-Production-Studio.git /tmp/fgb-prod-studio
cd /tmp/fgb-prod-studio
git sparse-checkout set ops/transport-ovh
cp -a ops/transport-ovh/. /opt/fgb-transport/
chmod +x /opt/fgb-transport/run-output.sh /opt/fgb-transport/heartbeat.sh /opt/fgb-transport/bootstrap-ovh.sh /opt/fgb-transport/archive-recorder.sh /opt/fgb-transport/archive-uploader.py

if [ ! -f /opt/fgb-transport/.env ]; then
  cp /opt/fgb-transport/.env.example /opt/fgb-transport/.env
  chmod 600 /opt/fgb-transport/.env
fi

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw --force enable

cd /opt/fgb-transport
docker compose build

cat >/etc/systemd/system/fgb-transport.service <<'EOF'
[Unit]
Description=FGB YouTube Livestream Transport
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
ConditionPathExists=!/opt/fgb-transport/NEEDS_SECRETS

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/fgb-transport
ExecStart=/usr/bin/docker compose up -d youtube archive_uploader
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

# Safety gate: build and install everything, but never enable/start streaming
# until host-only credentials have been populated.
if grep -q '^YOUTUBE_DESTINATIONS=$' /opt/fgb-transport/.env || \
   grep -q '^FGB_TRANSPORT_HEARTBEAT_SECRET=REPLACE_SECURELY_ON_HOST$' /opt/fgb-transport/.env; then
  touch /opt/fgb-transport/NEEDS_SECRETS
  systemctl disable fgb-transport.service >/dev/null 2>&1 || true
  systemctl stop fgb-transport.service >/dev/null 2>&1 || true
else
  rm -f /opt/fgb-transport/NEEDS_SECRETS
  systemctl enable fgb-transport.service
fi

printf 'FGB transport bootstrap complete at %s\n' "$(date -u +%FT%TZ)" >/opt/fgb-transport/BOOTSTRAP_COMPLETE
