#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 77; }
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
[[ -x /usr/local/bin/fgbears-rumble-relay ]] || { echo "Rumble relay is not installed." >&2; exit 66; }
[[ -f /etc/systemd/system/fgbears-rumble-relay.service ]] || { echo "Rumble service is not installed." >&2; exit 66; }

IFS= read -r RUMBLE_STREAM_KEY
[[ -n "$RUMBLE_STREAM_KEY" ]] || { echo "Rumble stream key was empty." >&2; exit 78; }
[[ "$RUMBLE_STREAM_KEY" != *$'\r'* ]] || { echo "Rumble stream key must be one line." >&2; exit 78; }
[[ "$RUMBLE_STREAM_KEY" != "REPLACE_WITH_RUMBLE_STREAM_KEY" ]] || { echo "Rumble stream key is still the placeholder." >&2; exit 78; }

temporary=$(mktemp /etc/fgbears-live/stream.env.XXXXXX)
trap 'rm -f "$temporary"' EXIT
found=0
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" == RUMBLE_STREAM_KEY=* ]]; then
    if ((found == 0)); then
      printf 'RUMBLE_STREAM_KEY=%s\n' "$RUMBLE_STREAM_KEY" >> "$temporary"
      found=1
    fi
  else
    printf '%s\n' "$line" >> "$temporary"
  fi
done < "$ENV_FILE"
if ((found == 0)); then
  printf 'RUMBLE_STREAM_KEY=%s\n' "$RUMBLE_STREAM_KEY" >> "$temporary"
fi

chown root:fgbears "$temporary"
chmod 0640 "$temporary"
mv -f "$temporary" "$ENV_FILE"
trap - EXIT
unset RUMBLE_STREAM_KEY

systemctl daemon-reload
systemctl enable fgbears-rumble-relay.service
systemctl reset-failed fgbears-rumble-relay.service || true
systemctl restart fgbears-rumble-relay.service
echo "Rumble relay configured and started."
