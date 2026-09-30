#!/bin/sh
set -eu
mountpoint -q /mnt || mount /dev/sdb1 /mnt
install -d -m 700 /mnt/home/ubuntu/.ssh
touch /mnt/home/ubuntu/.ssh/authorized_keys
chmod 600 /mnt/home/ubuntu/.ssh/authorized_keys
KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII/NU/kySLt3lRJOcTRTxX1cmg13DVnNkbkHK5cVUPPq github-actions-ovh-deploy'
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys || printf '%s\n' "$KEY" >> /mnt/home/ubuntu/.ssh/authorized_keys
UID_NUM=$(awk -F: '$1=="ubuntu" {print $3}' /mnt/etc/passwd)
GID_NUM=$(awk -F: '$1=="ubuntu" {print $4}' /mnt/etc/passwd)
test -n "$UID_NUM" && test -n "$GID_NUM"
chown -R "$UID_NUM:$GID_NUM" /mnt/home/ubuntu/.ssh
chmod 700 /mnt/home/ubuntu/.ssh
chmod 600 /mnt/home/ubuntu/.ssh/authorized_keys
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys
sync
echo 'KEY_INSTALLED=true'
echo 'NEXT: switch OVH Boot to Normal mode, then restart from the OVH panel'
