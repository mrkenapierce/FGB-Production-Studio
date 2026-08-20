#!/usr/bin/env python3
"""Create/bind/start the FGB YouTube broadcast for an already-active ingest stream.

Authentication is OAuth 2.0 using a refresh token stored outside the repository.
No stream keys, refresh tokens, access tokens, or OAuth client secrets are printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TITLE = "Football’s Greatest Bears Live | 24/7 Chicago Bears Talk, Episodes & Updates"


class YouTubeAPIError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
              body: dict | None = None, form: dict[str, str] | None = None) -> dict:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"error": raw[:1000]}
        raise YouTubeAPIError(f"YouTube API request failed ({exc.code}): {json.dumps(detail, separators=(',', ':'))}") from exc
    except urllib.error.URLError as exc:
        raise YouTubeAPIError(f"YouTube API network error: {exc.reason}") from exc

    if not raw:
        return {}
    return json.loads(raw)


def get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    payload = http_json(
        TOKEN_URL,
        method="POST",
        form={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token", "")
    if not token:
        raise YouTubeAPIError("Google OAuth token refresh succeeded without returning an access token.")
    return token


class YouTube:
    def __init__(self, access_token: str):
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def request(self, resource: str, *, method: str = "GET", params: dict[str, str] | None = None,
                body: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        url = f"{API_BASE}/{resource}"
        if query:
            url += f"?{query}"
        return http_json(url, method=method, headers=self.headers, body=body)

    def list_all(self, resource: str, params: dict[str, str]) -> list[dict]:
        items: list[dict] = []
        page_token = ""
        while True:
            request_params = dict(params)
            if page_token:
                request_params["pageToken"] = page_token
            payload = self.request(resource, params=request_params)
            items.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                break
        return items


def lifecycle(broadcast: dict) -> str:
    return broadcast.get("status", {}).get("lifeCycleStatus", "unknown")


def bound_stream_id(broadcast: dict) -> str:
    return broadcast.get("contentDetails", {}).get("boundStreamId", "")


def choose_active_stream(yt: YouTube) -> dict:
    streams = yt.list_all(
        "liveStreams",
        {
            "part": "id,snippet,cdn,status",
            "mine": "true",
            "maxResults": "50",
        },
    )
    active = [s for s in streams if s.get("status", {}).get("streamStatus") == "active"]
    if not active:
        raise YouTubeAPIError(
            "YouTube reports no active liveStream ingest. Keep the Oracle encoder running before starting the broadcast controller."
        )
    if len(active) > 1:
        titles = [s.get("snippet", {}).get("title", s.get("id", "unknown")) for s in active]
        raise YouTubeAPIError(f"More than one YouTube ingest stream is active; refusing to guess: {titles}")
    return active[0]


def find_existing_broadcast(yt: YouTube, stream_id: str) -> dict | None:
    active = yt.list_all(
        "liveBroadcasts",
        {
            "part": "id,snippet,status,contentDetails",
            "broadcastStatus": "active",
            "mine": "true",
            "maxResults": "50",
        },
    )
    for broadcast in active:
        if bound_stream_id(broadcast) == stream_id:
            return broadcast

    upcoming = yt.list_all(
        "liveBroadcasts",
        {
            "part": "id,snippet,status,contentDetails",
            "broadcastStatus": "upcoming",
            "mine": "true",
            "maxResults": "50",
        },
    )
    for broadcast in upcoming:
        if bound_stream_id(broadcast) == stream_id:
            return broadcast
    return None


def create_broadcast(yt: YouTube, title: str, privacy: str) -> dict:
    scheduled = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return yt.request(
        "liveBroadcasts",
        method="POST",
        params={"part": "snippet,status,contentDetails"},
        body={
            "snippet": {
                "title": title,
                "scheduledStartTime": scheduled,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": False,
                "enableDvr": True,
                "recordFromStart": True,
            },
        },
    )


def bind(yt: YouTube, broadcast_id: str, stream_id: str) -> dict:
    return yt.request(
        "liveBroadcasts/bind",
        method="POST",
        params={
            "id": broadcast_id,
            "streamId": stream_id,
            "part": "id,snippet,status,contentDetails",
        },
    )


def get_broadcast(yt: YouTube, broadcast_id: str) -> dict:
    payload = yt.request(
        "liveBroadcasts",
        params={
            "part": "id,snippet,status,contentDetails",
            "id": broadcast_id,
            "maxResults": "1",
        },
    )
    items = payload.get("items", [])
    if not items:
        raise YouTubeAPIError(f"Broadcast disappeared after creation/binding: {broadcast_id}")
    return items[0]


def transition_live(yt: YouTube, broadcast_id: str) -> dict:
    return yt.request(
        "liveBroadcasts/transition",
        method="POST",
        params={
            "broadcastStatus": "live",
            "id": broadcast_id,
            "part": "id,snippet,status,contentDetails",
        },
    )


def ensure_live(yt: YouTube, title: str, privacy: str) -> tuple[dict, dict, str]:
    stream = choose_active_stream(yt)
    stream_id = stream["id"]

    broadcast = find_existing_broadcast(yt, stream_id)
    action = "reused"
    if broadcast is None:
        broadcast = create_broadcast(yt, title, privacy)
        broadcast = bind(yt, broadcast["id"], stream_id)
        action = "created"

    broadcast_id = broadcast["id"]
    state = lifecycle(broadcast)
    if state == "live":
        return stream, broadcast, action

    # Auto-start may transition the broadcast shortly after binding. Give it a
    # brief chance before making an explicit transition request.
    for _ in range(6):
        time.sleep(2)
        broadcast = get_broadcast(yt, broadcast_id)
        state = lifecycle(broadcast)
        if state == "live":
            return stream, broadcast, action
        if state not in {"ready", "testStarting", "testing", "liveStarting"}:
            break

    broadcast = get_broadcast(yt, broadcast_id)
    state = lifecycle(broadcast)
    if state != "live":
        transition_live(yt, broadcast_id)

    for _ in range(15):
        time.sleep(2)
        broadcast = get_broadcast(yt, broadcast_id)
        if lifecycle(broadcast) == "live":
            return stream, broadcast, action

    raise YouTubeAPIError(
        f"YouTube did not reach live state. Broadcast {broadcast_id} is {lifecycle(broadcast)}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure the FGB YouTube ingest has a public live broadcast.")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--privacy", choices=("public", "unlisted", "private"), default="public")
    args = parser.parse_args()

    client_id = require_env("FGB_YOUTUBE_CLIENT_ID")
    client_secret = require_env("FGB_YOUTUBE_CLIENT_SECRET")
    refresh_token = require_env("FGB_YOUTUBE_REFRESH_TOKEN")

    try:
        access_token = get_access_token(client_id, client_secret, refresh_token)
        yt = YouTube(access_token)
        channels = yt.request("channels", params={"part": "id,snippet", "mine": "true", "maxResults": "1"}).get("items", [])
        if not channels:
            raise YouTubeAPIError("OAuth credentials did not resolve to a YouTube channel.")
        channel = channels[0]
        stream, broadcast, action = ensure_live(yt, args.title, args.privacy)
    except YouTubeAPIError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        return 1

    broadcast_id = broadcast["id"]
    watch_url = f"https://www.youtube.com/watch?v={broadcast_id}"
    print(f"CHANNEL={channel.get('snippet', {}).get('title', channel.get('id', 'unknown'))}")
    print(f"STREAM_ID={stream['id']}")
    print(f"BROADCAST_ID={broadcast_id}")
    print(f"BROADCAST_ACTION={action}")
    print(f"BROADCAST_STATE={lifecycle(broadcast)}")
    print(f"WATCH_URL={watch_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
