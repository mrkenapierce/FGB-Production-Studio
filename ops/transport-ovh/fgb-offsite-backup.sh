#!/usr/bin/env bash
# Offsite backup only. Never delete local video, stop FFmpeg or affect CNT.
set -Eeuo pipefail
umask 077
exec 9>/run/lock/fgb-offsite-archive.lock
flock -n 9 || { echo "FGB_OFFSITE_SKIP=prior_backup_active"; exit 0; }
CONFIG=/etc/fgb-archive-offsite.env
test -s "$CONFIG" || { echo "FGB_OFFSITE_NOT_CONFIGURED=true"; exit 4; }
# Configuration file must be owned by root and not group/world accessible.
test "$(stat -c '%u' "$CONFIG")" = 0
mode=$(stat -c '%a' "$CONFIG")
[[ "$mode" == 600 || "$mode" == 400 ]] || { echo "FGB_OFFSITE_CONFIG_PERMISSIONS=invalid"; exit 4; }
source "$CONFIG"
: "${FGB_OFFSITE_BUCKET:?Missing bucket}"
: "${FGB_OFFSITE_ENDPOINT:?Missing endpoint}"
: "${FGB_OFFSITE_REGION:?Missing region}"
: "${FGB_OFFSITE_ACCESS_KEY_ID:?Missing access key}"
: "${FGB_OFFSITE_SECRET_ACCESS_KEY:?Missing secret key}"
[[ "$FGB_OFFSITE_BUCKET" =~ ^[a-z0-9][a-z0-9.-]{2,62}$ ]]
[[ "$FGB_OFFSITE_ENDPOINT" =~ ^https://[A-Za-z0-9.-]+/?$ ]]
[[ "$FGB_OFFSITE_REGION" =~ ^[a-z0-9-]+$ ]]
command -v rclone >/dev/null
export RCLONE_CONFIG_FGBARCHIVE_TYPE=s3
export RCLONE_CONFIG_FGBARCHIVE_PROVIDER=Other
export RCLONE_CONFIG_FGBARCHIVE_ENV_AUTH=false
export RCLONE_CONFIG_FGBARCHIVE_ACCESS_KEY_ID="$FGB_OFFSITE_ACCESS_KEY_ID"
export RCLONE_CONFIG_FGBARCHIVE_SECRET_ACCESS_KEY="$FGB_OFFSITE_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_FGBARCHIVE_ENDPOINT="$FGB_OFFSITE_ENDPOINT"
export RCLONE_CONFIG_FGBARCHIVE_REGION="$FGB_OFFSITE_REGION"
ROOT=/srv/fgb-archive
RECEIPTS="$ROOT/offsite"
mkdir -p "$RECEIPTS"
done_count=0
while IFS= read -r -d '' local_file; do
  base=$(basename "$local_file")
  [[ "$base" =~ ^live-[0-9]{8}-[0-9]{6}-[+-][0-9]{4}\.ts$ ]] || continue
  receipt="$RECEIPTS/$base.sha256"
  local_hash=$(sha256sum "$local_file" | awk '{print $1}')
  if [ -s "$receipt" ] && [ "$(cut -d' ' -f1 "$receipt")" = "$local_hash" ]; then
    continue
  fi
  # Immutable remote object per hour. No remote delete, no source deletion.
  remote="FGBARCHIVE:$FGB_OFFSITE_BUCKET/fgb/hourly/$base"
  rclone copyto "$local_file" "$remote" --transfers=1 --checkers=1 --bwlimit=8M --s3-no-check-bucket --immutable --retries=2 --low-level-retries=3 --quiet
  # Byte-for-byte check after upload. ETag alone is not reliable for multipart S3.
  remote_hash=$(rclone cat "$remote" --quiet | sha256sum | awk '{print $1}')
  if [ "$local_hash" != "$remote_hash" ]; then
    echo "FGB_OFFSITE_CHECKSUM_MISMATCH=$base"
    exit 8
  fi
  printf '%s %s %s\n' "$local_hash" "$base" "$(date -u +%FT%TZ)" > "$receipt.tmp"
  mv -f "$receipt.tmp" "$receipt"
  done_count=$((done_count+1))
  echo "FGB_OFFSITE_BACKUP_VERIFIED=$base"
  [ "$done_count" -lt 2 ] || break
done < <(find "$ROOT/hourly" -maxdepth 1 -type f -name 'live-*.ts' -mmin +120 -print0 | sort -z)
echo "FGB_OFFSITE_VERIFIED_FILES=$done_count"
