#!/usr/bin/env python3
"""Target the permanent FGB YouTube broadcast without touching encoder transport.

This wrapper deliberately refuses to create a replacement broadcast. It binds the
currently active YouTube ingest to the configured permanent broadcast and moves
that broadcast to live when YouTube allows the transition.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import time

PREFERRED_BROADCAST_ID = "FxeMSzEB0_w"
CONTROLLER_PATH = Path("services/fgbears-live/bin/youtube-broadcast-control.py")


def load_controller():
    spec = importlib.util.spec_from_file_location("fgb_youtube_controller", CONTROLLER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load {CONTROLLER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    c = load_controller()
    client_id = c.require_env("FGB_YOUTUBE_CLIENT_ID")
    client_secret = c.require_env("FGB_YOUTUBE_CLIENT_SECRET")
    refresh_token = c.require_env("FGB_YOUTUBE_REFRESH_TOKEN")

    try:
        access_token = c.get_access_token(client_id, client_secret, refresh_token)
        yt = c.YouTube(access_token)
        channels = yt.request(
            "channels",
            params={"part": "id,snippet", "mine": "true", "maxResults": "1"},
        ).get("items", [])
        if not channels:
            raise c.YouTubeAPIError("OAuth credentials did not resolve to a YouTube channel.")

        channel = channels[0]
        stream = c.choose_active_stream(yt)
        stream_id = stream["id"]
        broadcast = c.get_broadcast(yt, PREFERRED_BROADCAST_ID)
        state = c.lifecycle(broadcast)

        if state in {"complete", "revoked"}:
            raise c.YouTubeAPIError(
                f"Preferred FGB broadcast {PREFERRED_BROADCAST_ID} is {state}; refusing to create or select a replacement."
            )

        if c.bound_stream_id(broadcast) != stream_id:
            broadcast = c.bind(yt, PREFERRED_BROADCAST_ID, stream_id)
            state = c.lifecycle(broadcast)

        if state != "live":
            # Give auto-start a short opportunity first.
            for _ in range(6):
                time.sleep(2)
                broadcast = c.get_broadcast(yt, PREFERRED_BROADCAST_ID)
                state = c.lifecycle(broadcast)
                if state == "live":
                    break
                if state not in {"ready", "testStarting", "testing", "liveStarting"}:
                    break

        if state != "live":
            broadcast = c.get_broadcast(yt, PREFERRED_BROADCAST_ID)
            state = c.lifecycle(broadcast)
            if state not in {"ready", "testing", "liveStarting", "testStarting"}:
                raise c.YouTubeAPIError(
                    f"Preferred FGB broadcast {PREFERRED_BROADCAST_ID} is {state}; refusing an invalid live transition."
                )
            c.transition_live(yt, PREFERRED_BROADCAST_ID)

            for _ in range(15):
                time.sleep(2)
                broadcast = c.get_broadcast(yt, PREFERRED_BROADCAST_ID)
                if c.lifecycle(broadcast) == "live":
                    state = "live"
                    break

        if state != "live":
            raise c.YouTubeAPIError(
                f"YouTube did not reach live state. Preferred broadcast {PREFERRED_BROADCAST_ID} is {c.lifecycle(broadcast)}."
            )

    except c.YouTubeAPIError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    print(f"CHANNEL={channel.get('snippet', {}).get('title', channel.get('id', 'unknown'))}")
    print(f"STREAM_ID={stream_id}")
    print(f"BROADCAST_ID={PREFERRED_BROADCAST_ID}")
    print("BROADCAST_ACTION=preferred")
    print(f"BROADCAST_STATE={c.lifecycle(broadcast)}")
    print(f"WATCH_URL=https://www.youtube.com/watch?v={PREFERRED_BROADCAST_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
