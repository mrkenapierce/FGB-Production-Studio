#!/usr/bin/env python3
"""Upload closed FGB livestream archive segments to YouTube without touching the live ingest.

Uses only the Python standard library. OAuth secrets are read from the existing
FGB environment and are never printed. Uploads use YouTube's resumable protocol
in bounded chunks so hour-long files are not loaded into memory.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_START = "https://www.googleapis.com/upload/youtube/v3/videos"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_PLAYLIST = "FGB Daily Livestream Archive"
DEFAULT_ARCHIVE_DIR = "/srv/fgbears-live/archive"
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024
FILENAME_RE = re.compile(r"^(?P<mode>test|live)-(?P<stamp>\d{8}-\d{6})\.mp4$")


class YouTubeAPIError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
              body: dict | None = None, form: dict[str, str] | None = None,
              timeout: int = 30) -> tuple[dict, dict[str, str]]:
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
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"error": raw[:1000]}
        raise YouTubeAPIError(
            f"YouTube API request failed ({exc.code}): {json.dumps(detail, separators=(',', ':'))}"
        ) from exc
    except urllib.error.URLError as exc:
        raise YouTubeAPIError(f"YouTube API network error: {exc.reason}") from exc

    if not raw:
        return {}, response_headers
    return json.loads(raw), response_headers


def get_access_token() -> str:
    payload, _ = http_json(
        TOKEN_URL,
        method="POST",
        form={
            "client_id": require_env("FGB_YOUTUBE_CLIENT_ID"),
            "client_secret": require_env("FGB_YOUTUBE_CLIENT_SECRET"),
            "refresh_token": require_env("FGB_YOUTUBE_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token", "")
    if not token:
        raise YouTubeAPIError("Google OAuth token refresh succeeded without returning an access token.")
    return token


class YouTube:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def request(self, resource: str, *, method: str = "GET", params: dict[str, str] | None = None,
                body: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        url = f"{API_BASE}/{resource}"
        if query:
            url += f"?{query}"
        payload, _ = http_json(url, method=method, headers=self.headers, body=body)
        return payload

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
                return items

    def ensure_playlist(self, title: str, privacy: str) -> str:
        playlists = self.list_all(
            "playlists",
            {"part": "id,snippet,status", "mine": "true", "maxResults": "50"},
        )
        for playlist in playlists:
            if playlist.get("snippet", {}).get("title", "") == title:
                playlist_id = playlist["id"]
                existing_privacy = playlist.get("status", {}).get("privacyStatus", "")
                if privacy == "public" and existing_privacy != "public":
                    self.request(
                        "playlists",
                        method="PUT",
                        params={"part": "status"},
                        body={"id": playlist_id, "status": {"privacyStatus": "public"}},
                    )
                return playlist_id

        created = self.request(
            "playlists",
            method="POST",
            params={"part": "snippet,status"},
            body={
                "snippet": {
                    "title": title,
                    "description": "Automatic archive of the Football's Greatest Bears continuous livestream.",
                },
                "status": {"privacyStatus": privacy},
            },
        )
        playlist_id = created.get("id", "")
        if not playlist_id:
            raise YouTubeAPIError("Playlist creation returned no playlist id.")
        return playlist_id

    def add_to_playlist(self, playlist_id: str, video_id: str) -> None:
        self.request(
            "playlistItems",
            method="POST",
            params={"part": "snippet"},
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )

    def get_video_privacy(self, video_id: str) -> str:
        payload = self.request(
            "videos",
            params={"part": "status", "id": video_id, "maxResults": "1"},
        )
        items = payload.get("items", [])
        if not items:
            raise YouTubeAPIError(f"Uploaded video {video_id} could not be retrieved for verification.")
        return items[0].get("status", {}).get("privacyStatus", "unknown")

    def start_resumable_upload(self, file_path: Path, metadata: dict) -> str:
        query = urllib.parse.urlencode(
            {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "false"}
        )
        body = json.dumps(metadata).encode("utf-8")
        req = urllib.request.Request(
            f"{UPLOAD_START}?{query}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_path.stat().st_size),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                location = response.headers.get("Location", "")
                response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise YouTubeAPIError(f"YouTube resumable upload start failed ({exc.code}): {raw[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise YouTubeAPIError(f"YouTube resumable upload start network error: {exc.reason}") from exc
        if not location.startswith("https://"):
            raise YouTubeAPIError("YouTube resumable upload did not return a secure session URL.")
        return location

    @staticmethod
    def _put_chunk(session_url: str, data: bytes, start: int, total: int) -> tuple[int, dict[str, str], bytes]:
        parts = urllib.parse.urlsplit(session_url)
        if parts.scheme != "https":
            raise YouTubeAPIError("Refusing non-HTTPS YouTube upload session URL.")
        path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
        end = start + len(data) - 1
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=180)
        try:
            conn.request(
                "PUT",
                path,
                body=data,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end}/{total}",
                },
            )
            response = conn.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            conn.close()

    @staticmethod
    def _query_offset(session_url: str, total: int) -> tuple[int, dict | None]:
        parts = urllib.parse.urlsplit(session_url)
        path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=60)
        try:
            conn.request(
                "PUT",
                path,
                body=b"",
                headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"},
            )
            response = conn.getresponse()
            raw = response.read()
            if response.status in (200, 201):
                return total, json.loads(raw.decode("utf-8")) if raw else {}
            if response.status == 308:
                range_header = response.getheader("Range", "")
                if range_header.startswith("bytes=0-"):
                    return int(range_header.split("-", 1)[1]) + 1, None
                return 0, None
            raise YouTubeAPIError(
                f"YouTube upload status query failed ({response.status}): {raw[:1000].decode('utf-8', errors='replace')}"
            )
        finally:
            conn.close()

    def upload_file(self, file_path: Path, metadata: dict, chunk_bytes: int) -> dict:
        total = file_path.stat().st_size
        if total <= 0:
            raise YouTubeAPIError(f"Refusing to upload empty file: {file_path.name}")
        session_url = self.start_resumable_upload(file_path, metadata)
        offset = 0
        final_payload: dict | None = None
        with file_path.open("rb") as handle:
            while offset < total:
                handle.seek(offset)
                data = handle.read(min(chunk_bytes, total - offset))
                if not data:
                    raise YouTubeAPIError("Unexpected EOF while reading archive segment.")
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        status, headers, raw = self._put_chunk(session_url, data, offset, total)
                        if status in (200, 201):
                            final_payload = json.loads(raw.decode("utf-8")) if raw else {}
                            offset = total
                            break
                        if status == 308:
                            range_header = headers.get("Range", headers.get("range", ""))
                            if range_header.startswith("bytes=0-"):
                                offset = int(range_header.split("-", 1)[1]) + 1
                            else:
                                offset += len(data)
                            break
                        if status in (500, 502, 503, 504) and attempt < 6:
                            time.sleep(min(30, 2 ** attempt))
                            continue
                        raise YouTubeAPIError(
                            f"YouTube upload failed ({status}): {raw[:1000].decode('utf-8', errors='replace')}"
                        )
                    except (OSError, http.client.HTTPException) as exc:
                        if attempt >= 6:
                            raise YouTubeAPIError(f"YouTube upload network failure after retries: {exc}") from exc
                        time.sleep(min(30, 2 ** attempt))
                        try:
                            offset, completed = self._query_offset(session_url, total)
                        except Exception:
                            continue
                        if completed is not None:
                            final_payload = completed
                            offset = total
                            break
                if final_payload is not None and offset >= total:
                    break

        if final_payload is None:
            offset, final_payload = self._query_offset(session_url, total)
        if offset != total or final_payload is None:
            raise YouTubeAPIError("YouTube upload ended without a completed video resource.")
        return final_payload


def parse_segment_time(path: Path, timezone_name: str) -> tuple[str, dt.datetime]:
    match = FILENAME_RE.match(path.name)
    if not match:
        raise ValueError(f"Unexpected archive filename: {path.name}")
    local = dt.datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S").replace(
        tzinfo=ZoneInfo(timezone_name)
    )
    return match.group("mode"), local


def build_metadata(path: Path, privacy: str, timezone_name: str) -> dict:
    mode, local = parse_segment_time(path, timezone_name)
    zone = local.tzname() or "CT"
    if mode == "test":
        title = f"FGB Archive Test | {local:%b %d, %Y | %I:%M %p} {zone}"
    else:
        title = f"Football's Greatest Bears Live Archive | {local:%b %d, %Y | %I:%M %p} {zone}"
    description = (
        "Automatic archive from the continuous Football's Greatest Bears livestream.\n\n"
        f"Archive segment began {local:%B %d, %Y at %I:%M:%S %p} {zone}.\n"
        "Created without stopping or restarting the live broadcast.\n\n"
        "Live: https://youtube.com/@FootballsGreatestBears/live"
    )
    return {
        "snippet": {"title": title[:100], "description": description, "categoryId": "17"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def archive_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024 ** 3)


def stop_recorder_for_low_disk() -> None:
    try:
        proc = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", "fgbears-archive-recorder.service"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        pid_text = proc.stdout.strip()
        if pid_text.isdigit() and int(pid_text) > 1:
            os.kill(int(pid_text), signal.SIGINT)
            log("ARCHIVE_RECORDER_PAUSED_LOW_DISK=true")
    except Exception as exc:
        log(f"ARCHIVE_LOW_DISK_SIGNAL_ERROR={type(exc).__name__}")


def ready_segments(archive_dir: Path, stable_age: int) -> list[Path]:
    cutoff = time.time() - stable_age
    candidates = []
    for path in sorted(archive_dir.glob("*.mp4")):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if stat.st_size > 0 and stat.st_mtime <= cutoff and FILENAME_RE.match(path.name):
            candidates.append(path)
    return candidates


def process_segment(path: Path, *, state_dir: Path, yt: YouTube, playlist_title: str,
                    privacy: str, timezone_name: str, chunk_bytes: int) -> None:
    state_path = state_dir / f"{path.name}.json"
    state = load_state(state_path)
    video_id = state.get("video_id", "")

    if not video_id:
        metadata = build_metadata(path, privacy, timezone_name)
        log(f"ARCHIVE_UPLOAD_START={path.name}")
        uploaded = yt.upload_file(path, metadata, chunk_bytes)
        video_id = uploaded.get("id", "")
        if not video_id:
            raise YouTubeAPIError("YouTube upload completed without a video id.")
        actual_privacy = yt.get_video_privacy(video_id)
        state.update(
            {
                "file": path.name,
                "video_id": video_id,
                "requested_privacy": privacy,
                "actual_privacy": actual_privacy,
                "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "playlist_added": False,
                "complete": False,
            }
        )
        save_state(state_path, state)
        log(f"ARCHIVE_UPLOAD_VIDEO_ID={video_id}")
        log(f"ARCHIVE_UPLOAD_PRIVACY={actual_privacy}")
        if actual_privacy != privacy:
            raise YouTubeAPIError(
                f"YouTube returned privacyStatus={actual_privacy}, expected {privacy}. "
                "The API project may require a YouTube upload compliance audit before non-private uploads are allowed."
            )

    actual_privacy = yt.get_video_privacy(video_id)
    state["actual_privacy"] = actual_privacy
    save_state(state_path, state)
    if actual_privacy != privacy:
        raise YouTubeAPIError(
            f"YouTube returned privacyStatus={actual_privacy}, expected {privacy}. "
            "The API project may require a YouTube upload compliance audit before non-private uploads are allowed."
        )

    if not state.get("playlist_added"):
        playlist_privacy = "public" if privacy == "public" else "unlisted"
        playlist_id = yt.ensure_playlist(playlist_title, playlist_privacy)
        yt.add_to_playlist(playlist_id, video_id)
        state["playlist_id"] = playlist_id
        state["playlist_added"] = True
        save_state(state_path, state)
        log(f"ARCHIVE_PLAYLIST_ADDED={playlist_id}")

    state["complete"] = True
    state["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_state(state_path, state)
    path.unlink(missing_ok=True)
    log(f"ARCHIVE_UPLOAD_COMPLETE={path.name}")


def main() -> int:
    archive_dir = Path(os.environ.get("FGB_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR)).resolve()
    state_dir = archive_dir / "state"
    archive_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    privacy = os.environ.get("FGB_ARCHIVE_PRIVACY", "unlisted").strip()
    if privacy not in {"private", "unlisted", "public"}:
        raise SystemExit("FGB_ARCHIVE_PRIVACY must be private, unlisted, or public.")
    playlist_title = os.environ.get("FGB_ARCHIVE_PLAYLIST_TITLE", DEFAULT_PLAYLIST).strip() or DEFAULT_PLAYLIST
    timezone_name = os.environ.get("FGB_ARCHIVE_TIMEZONE", "America/Chicago").strip()
    ZoneInfo(timezone_name)
    poll_seconds = max(10, int(os.environ.get("FGB_ARCHIVE_POLL_SECONDS", "20")))
    stable_age = max(10, int(os.environ.get("FGB_ARCHIVE_STABLE_AGE_SECONDS", "30")))
    min_free_gb = float(os.environ.get("FGB_ARCHIVE_MIN_FREE_GB", "5"))
    chunk_bytes = int(os.environ.get("FGB_ARCHIVE_UPLOAD_CHUNK_BYTES", str(DEFAULT_CHUNK_BYTES)))
    if chunk_bytes < 256 * 1024 or chunk_bytes % (256 * 1024) != 0:
        raise SystemExit("FGB_ARCHIVE_UPLOAD_CHUNK_BYTES must be a multiple of 256 KiB.")

    require_env("FGB_YOUTUBE_CLIENT_ID")
    require_env("FGB_YOUTUBE_CLIENT_SECRET")
    require_env("FGB_YOUTUBE_REFRESH_TOKEN")

    log(f"ARCHIVE_UPLOADER_PRIVACY={privacy}")
    log(f"ARCHIVE_UPLOADER_PLAYLIST={playlist_title}")

    consecutive_errors = 0
    while True:
        try:
            free_gb = archive_free_gb(archive_dir)
            if free_gb < min_free_gb:
                log(f"ARCHIVE_LOW_DISK_FREE_GB={free_gb:.2f}")
                stop_recorder_for_low_disk()

            segments = ready_segments(archive_dir, stable_age)
            if not segments:
                time.sleep(poll_seconds)
                continue

            yt = YouTube(get_access_token())
            for segment in segments:
                process_segment(
                    segment,
                    state_dir=state_dir,
                    yt=yt,
                    playlist_title=playlist_title,
                    privacy=privacy,
                    timezone_name=timezone_name,
                    chunk_bytes=chunk_bytes,
                )
            consecutive_errors = 0
        except (YouTubeAPIError, OSError, ValueError) as exc:
            consecutive_errors += 1
            log(f"ARCHIVE_UPLOADER_ERROR={type(exc).__name__}:{exc}")
            time.sleep(min(300, max(poll_seconds, 5 * consecutive_errors)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
