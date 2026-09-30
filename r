#!/bin/sh
set -eu
mountpoint -q /mnt || mount /dev/sdb1 /mnt
install -d -m 700 /mnt/home/ubuntu/.ssh
touch /mnt/home/ubuntu/.ssh/authorized_keys
chmod 600 /mnt/home/ubuntu/.ssh/authorized_keys
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII/NU/kySLt3lRJOcTRTxX1cmg13DVnNkbkHK5cVUPPq github-actions-ovh-deploy'
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys || printf '%s\n' "$KEY" >> /mnt/home/ubuntu/.ssh/authorized_keys
chown -R --reference=/mnt/home/ubuntu /mnt/home/ubuntu/.ssh
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys
sync
echo 'KEY_INSTALLED=true'
sleep 2
reboot
