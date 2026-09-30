#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw docker.io docker-compose-v2
systemctl enable --now docker
install -d -m 0755 /opt/fgb-transport
rm -rf /tmp/fgb-prod-studio
git clone --depth 1 --filter=blob:none --sparse https://github.com/mrkenapierce/FGB-Production-Studio.git /tmp/fgb-prod-studio
cd /tmp/fgb-prod-studio
git sparse-checkout set ops/transport-ovh
cp -a ops/transport-ovh/. /opt/fgb-transport/
chmod +x /opt/fgb-transport/run-output.sh /opt/fgb-transport/heartbeat.sh /opt/fgb-transport/bootstrap-ovh.sh
if [ ! -f /opt/fgb-transport/.env ]; then cp /opt/fgb-transport/.env.example /opt/fgb-transport/.env; chmod 600 /opt/fgb-transport/.env; fi
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

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/fgb-transport
ExecStart=/usr/bin/docker compose up -d youtube
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable fgb-transport.service
# Safety gate: do not start the transport until the host-only secrets are populated.
if grep -q '^YOUTUBE_DESTINATIONS=$' /opt/fgb-transport/.env || grep -q '^FGB_TRANSPORT_HEARTBEAT_SECRET=REPLACE_SECURELY_ON_HOST$' /opt/fgb-transport/.env; then
  touch /opt/fgb-transport/NEEDS_SECRETS
else
  rm -f /opt/fgb-transport/NEEDS_SECRETS
fi
printf 'FGB transport bootstrap complete at %s\n' "$(date -u +%FT%TZ)" >/opt/fgb-transport/BOOTSTRAP_COMPLETE
