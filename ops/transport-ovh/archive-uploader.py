#!/usr/bin/env python3
"""Assemble hourly FGB capture chunks into daily YouTube archive videos.

The live encoder never depends on this process. Hourly MPEG-TS chunks are
created by archive-recorder.sh from a loopback UDP copy of the already encoded
program. This worker waits until a Central-time calendar day is closed, remuxes
those chunks into YouTube-ready MP4 parts, uploads them resumably, verifies the
requested privacy, adds them to the archive playlist, and only then removes the
raw chunks.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_START = "https://www.googleapis.com/upload/youtube/v3/videos"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHUNK_RE = re.compile(r"^live-(?P<date>\d{8})-(?P<time>\d{6})-(?P<offset>[+-]\d{4})\.ts$")
UPLOAD_CHUNK = 8 * 1024 * 1024


class ArchiveError(RuntimeError):
    pass


class YouTubeError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def oauth_ready() -> bool:
    return all(env(name) for name in (
        "FGB_YOUTUBE_CLIENT_ID",
        "FGB_YOUTUBE_CLIENT_SECRET",
        "FGB_YOUTUBE_REFRESH_TOKEN",
    ))


def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
              body: dict | None = None, form: dict[str, str] | None = None,
              timeout: int = 60) -> tuple[dict, dict[str, str]]:
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
            raw = response.read().decode("utf-8", errors="replace")
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise YouTubeError(f"HTTP {exc.code}: {raw[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise YouTubeError(f"Network error: {exc.reason}") from exc
    if not raw:
        return {}, response_headers
    return json.loads(raw), response_headers


def access_token() -> str:
    if not oauth_ready():
        raise YouTubeError("YouTube OAuth credentials are not configured")
    payload, _ = http_json(
        TOKEN_URL,
        method="POST",
        form={
            "client_id": env("FGB_YOUTUBE_CLIENT_ID"),
            "client_secret": env("FGB_YOUTUBE_CLIENT_SECRET"),
            "refresh_token": env("FGB_YOUTUBE_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token", "")
    if not token:
        raise YouTubeError("OAuth refresh returned no access token")
    return token


class YouTube:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    def request(self, resource: str, *, method: str = "GET",
                params: dict[str, str] | None = None, body: dict | None = None) -> dict:
        query = urllib.parse.urlencode(params or {})
        url = f"{API_BASE}/{resource}"
        if query:
            url += f"?{query}"
        payload, _ = http_json(url, method=method, headers=self.headers, body=body)
        return payload

    def verify_channel(self) -> tuple[str, str]:
        payload = self.request("channels", params={"part": "id,snippet", "mine": "true", "maxResults": "1"})
        items = payload.get("items", [])
        if not items:
            raise YouTubeError("OAuth token is valid but no YouTube channel is available")
        item = items[0]
        return item.get("id", ""), item.get("snippet", {}).get("title", "")

    def ensure_playlist(self, title: str, privacy: str) -> str:
        page = ""
        while True:
            params = {"part": "id,snippet,status", "mine": "true", "maxResults": "50"}
            if page:
                params["pageToken"] = page
            payload = self.request("playlists", params=params)
            for item in payload.get("items", []):
                if item.get("snippet", {}).get("title") == title:
                    playlist_id = item.get("id", "")
                    current = item.get("status", {}).get("privacyStatus", "")
                    if playlist_id and privacy == "public" and current != "public":
                        self.request(
                            "playlists",
                            method="PUT",
                            params={"part": "status"},
                            body={"id": playlist_id, "status": {"privacyStatus": "public"}},
                        )
                    return playlist_id
            page = payload.get("nextPageToken", "")
            if not page:
                break
        created = self.request(
            "playlists",
            method="POST",
            params={"part": "snippet,status"},
            body={
                "snippet": {
                    "title": title,
                    "description": "Daily archive of the Football's Greatest Bears continuous livestream.",
                },
                "status": {"privacyStatus": "public" if privacy == "public" else "unlisted"},
            },
        )
        playlist_id = created.get("id", "")
        if not playlist_id:
            raise YouTubeError("Playlist creation returned no id")
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

    def video_privacy(self, video_id: str) -> str:
        payload = self.request("videos", params={"part": "status", "id": video_id, "maxResults": "1"})
        items = payload.get("items", [])
        if not items:
            raise YouTubeError(f"Video {video_id} could not be verified")
        return items[0].get("status", {}).get("privacyStatus", "unknown")

    def delete_video(self, video_id: str) -> None:
        self.request("videos", method="DELETE", params={"id": video_id})

    def start_upload(self, path: Path, metadata: dict) -> str:
        query = urllib.parse.urlencode({
            "uploadType": "resumable",
            "part": "snippet,status",
            "notifySubscribers": "false",
        })
        body = json.dumps(metadata).encode("utf-8")
        req = urllib.request.Request(
            f"{UPLOAD_START}?{query}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(path.stat().st_size),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                location = response.headers.get("Location", "")
                response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise YouTubeError(f"Upload session start failed ({exc.code}): {raw[:1200]}") from exc
        except urllib.error.URLError as exc:
            raise YouTubeError(f"Upload session network error: {exc.reason}") from exc
        if not location.startswith("https://"):
            raise YouTubeError("YouTube did not return a secure upload session URL")
        return location

    @staticmethod
    def put_chunk(session_url: str, data: bytes, start: int, total: int) -> tuple[int, dict[str, str], bytes]:
        parts = urllib.parse.urlsplit(session_url)
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
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    @staticmethod
    def query_offset(session_url: str, total: int) -> tuple[int, dict | None]:
        parts = urllib.parse.urlsplit(session_url)
        path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
        conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=60)
        try:
            conn.request("PUT", path, body=b"", headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"})
            response = conn.getresponse()
            raw = response.read()
            if response.status in (200, 201):
                return total, json.loads(raw.decode("utf-8")) if raw else {}
            if response.status == 308:
                value = response.getheader("Range", "")
                if value.startswith("bytes=0-"):
                    return int(value.split("-", 1)[1]) + 1, None
                return 0, None
            raise YouTubeError(f"Upload status query failed ({response.status}): {raw[:800]!r}")
        finally:
            conn.close()

    def upload(self, path: Path, metadata: dict, chunk_bytes: int = UPLOAD_CHUNK) -> dict:
        total = path.stat().st_size
        if total <= 0:
            raise YouTubeError(f"Refusing to upload empty file {path}")
        session = self.start_upload(path, metadata)
        offset = 0
        final: dict | None = None
        with path.open("rb") as handle:
            while offset < total:
                handle.seek(offset)
                data = handle.read(min(chunk_bytes, total - offset))
                if not data:
                    raise YouTubeError("Unexpected EOF during upload")
                for attempt in range(1, 7):
                    try:
                        status, headers, raw = self.put_chunk(session, data, offset, total)
                        if status in (200, 201):
                            final = json.loads(raw.decode("utf-8")) if raw else {}
                            offset = total
                            break
                        if status == 308:
                            value = headers.get("Range", headers.get("range", ""))
                            offset = int(value.split("-", 1)[1]) + 1 if value.startswith("bytes=0-") else offset + len(data)
                            break
                        if status in (500, 502, 503, 504) and attempt < 6:
                            time.sleep(min(30, 2 ** attempt))
                            continue
                        raise YouTubeError(f"Upload failed ({status}): {raw[:800]!r}")
                    except (OSError, http.client.HTTPException) as exc:
                        if attempt >= 6:
                            raise YouTubeError(f"Upload network failure after retries: {exc}") from exc
                        time.sleep(min(30, 2 ** attempt))
                        try:
                            offset, completed = self.query_offset(session, total)
                            if completed is not None:
                                final = completed
                                offset = total
                                break
                        except Exception:
                            pass
                if final is not None and offset >= total:
                    break
        if final is None:
            offset, final = self.query_offset(session, total)
        if offset != total or final is None:
            raise YouTubeError("Upload did not complete")
        return final


def parse_chunk(path: Path) -> dt.datetime:
    match = CHUNK_RE.match(path.name)
    if not match:
        raise ArchiveError(f"Unexpected archive filename: {path.name}")
    stamp = f"{match.group('date')}{match.group('time')}{match.group('offset')}"
    return dt.datetime.strptime(stamp, "%Y%m%d%H%M%S%z")


def run_json(args: list[str]) -> dict:
    proc = subprocess.run(args, check=False, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise ArchiveError(f"Command failed ({proc.returncode}): {' '.join(args[:4])}: {proc.stderr[-1000:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ArchiveError(f"Invalid JSON from {' '.join(args[:2])}") from exc


def probe(path: Path) -> tuple[float, bool, bool]:
    payload = run_json([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_streams", "-of", "json", str(path)
    ])
    try:
        duration = float(payload.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    streams = payload.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return duration, has_video, has_audio


def stable_chunks(hourly: Path, stable_age: int) -> list[Path]:
    cutoff = time.time() - stable_age
    result: list[Path] = []
    for path in hourly.glob("live-*.ts"):
        if not CHUNK_RE.match(path.name):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if stat.st_size > 0 and stat.st_mtime <= cutoff:
            result.append(path)
    return sorted(result, key=parse_chunk)


def group_parts(chunks: list[Path], max_seconds: float) -> list[list[Path]]:
    parts: list[list[Path]] = []
    current: list[Path] = []
    elapsed = 0.0
    for path in chunks:
        duration, video, audio = probe(path)
        if duration <= 0 or not video or not audio:
            raise ArchiveError(f"Invalid archive chunk: {path.name}")
        # A one-second tolerance prevents harmless transport timestamp rounding
        # from turning an otherwise exact 12-hour half-day into a tiny third part.
        if current and elapsed + duration > max_seconds + 1.0:
            parts.append(current)
            current = []
            elapsed = 0.0
        current.append(path)
        elapsed += duration
    if current:
        parts.append(current)
    return parts


def concat_part(chunks: list[Path], output: Path, max_seconds: float) -> float:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(".tmp.mp4")
    manifest = output.with_suffix(".concat.txt")
    manifest.write_text("".join(f"file '{path}'\n" for path in chunks), encoding="utf-8")
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y",
                "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(manifest),
                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(tmp_output),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if proc.returncode != 0:
            raise ArchiveError(f"Daily remux failed: {proc.stderr[-2000:]}")
        duration, video, audio = probe(tmp_output)
        if duration <= 0 or not video or not audio:
            raise ArchiveError("Daily remux did not contain valid audio and video")
        if duration > max_seconds + 2.0:
            raise ArchiveError(f"Daily archive part exceeds 12-hour ceiling: {duration:.3f}s")
        os.replace(tmp_output, output)
        return duration
    finally:
        manifest.unlink(missing_ok=True)
        tmp_output.unlink(missing_ok=True)


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def title_for(day: dt.date, part: int, total: int) -> str:
    base = f"{day.strftime('%B')} {day.day}, {day.year} Livestream"
    return base if total == 1 else f"{base} — Part {part}"


def metadata_for(day: dt.date, part: int, total: int, privacy: str) -> dict:
    title = title_for(day, part, total)
    description = (
        "Football's Greatest Bears daily livestream archive.\n\n"
        f"Date: {day.strftime('%B')} {day.day}, {day.year}\n"
        f"Archive part: {part} of {total}\n"
        "The live broadcast continues independently while these daily archive videos are created.\n\n"
        "Live: https://youtube.com/@FootballsGreatestBears/live"
    )
    return {
        "snippet": {"title": title[:100], "description": description, "categoryId": "17"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }


def protect_disk(root: Path, hourly: Path, min_free_gb: float) -> None:
    free_gb = shutil.disk_usage(root).free / (1024 ** 3)
    if free_gb >= min_free_gb:
        return
    log(f"ARCHIVE_LOW_DISK_FREE_GB={free_gb:.2f}")
    # Preserve the live transport at all costs. If uploads have been blocked long
    # enough to threaten the host disk, discard the oldest archive chunks first.
    for path in sorted(hourly.glob("live-*.ts"), key=lambda p: p.stat().st_mtime):
        try:
            path.unlink()
            log(f"ARCHIVE_LOW_DISK_DROPPED={path.name}")
        except FileNotFoundError:
            pass
        free_gb = shutil.disk_usage(root).free / (1024 ** 3)
        if free_gb >= min_free_gb + 2.0:
            break


def process_day(day: dt.date, chunks: list[Path], root: Path, yt: YouTube,
                privacy: str, playlist_title: str, max_seconds: float) -> None:
    state_path = root / "state" / f"daily-{day:%Y%m%d}.json"
    state = load_state(state_path)
    if state.get("complete") is True:
        for path in chunks:
            path.unlink(missing_ok=True)
        return

    source_names = [p.name for p in chunks]
    previous_sources = state.get("source_files")
    if previous_sources and previous_sources != source_names and any(p.get("video_id") for p in state.get("parts", [])):
        raise ArchiveError(f"Source set changed after uploads began for {day}; refusing duplicate/misaligned uploads")

    groups = group_parts(chunks, max_seconds)
    if not groups:
        return
    state.setdefault("date", day.isoformat())
    state["source_files"] = source_names
    state["part_count"] = len(groups)
    state.setdefault("parts", [])
    while len(state["parts"]) < len(groups):
        state["parts"].append({})
    save_state(state_path, state)

    playlist_id = state.get("playlist_id", "")
    if not playlist_id:
        playlist_id = yt.ensure_playlist(playlist_title, privacy)
        state["playlist_id"] = playlist_id
        save_state(state_path, state)

    for index, group in enumerate(groups, start=1):
        part_state = state["parts"][index - 1]
        if part_state.get("complete") is True:
            continue
        output = root / "final" / f"{day:%Y%m%d}-part-{index:02d}.mp4"
        if not part_state.get("video_id"):
            duration = concat_part(group, output, max_seconds)
            log(f"ARCHIVE_PART_READY={output.name} duration={duration:.3f}")
            uploaded = yt.upload(output, metadata_for(day, index, len(groups), privacy))
            video_id = uploaded.get("id", "")
            if not video_id:
                raise YouTubeError("Upload completed without a video id")
            actual = yt.video_privacy(video_id)
            part_state.update({
                "video_id": video_id,
                "requested_privacy": privacy,
                "actual_privacy": actual,
                "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "playlist_added": False,
                "complete": False,
                "title": title_for(day, index, len(groups)),
            })
            save_state(state_path, state)
            log(f"ARCHIVE_UPLOAD_VIDEO_ID={video_id}")
            if actual != privacy:
                raise YouTubeError(
                    f"YouTube returned privacyStatus={actual}, expected {privacy}; public API uploads may require project audit"
                )
        else:
            video_id = part_state["video_id"]
            actual = yt.video_privacy(video_id)
            if actual != privacy:
                raise YouTubeError(f"Existing archive video {video_id} privacy is {actual}, expected {privacy}")

        if not part_state.get("playlist_added"):
            yt.add_to_playlist(playlist_id, video_id)
            part_state["playlist_added"] = True
            save_state(state_path, state)

        part_state["complete"] = True
        part_state["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_state(state_path, state)
        output.unlink(missing_ok=True)
        log(f"ARCHIVE_PART_COMPLETE={day:%Y%m%d}:{index}/{len(groups)}")

    if all(item.get("complete") is True for item in state["parts"][:len(groups)]):
        state["complete"] = True
        state["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_state(state_path, state)
        for path in chunks:
            path.unlink(missing_ok=True)
        log(f"ARCHIVE_DAY_COMPLETE={day:%Y%m%d} parts={len(groups)}")


def closed_days(chunks: list[Path], timezone: ZoneInfo, grace_seconds: int) -> list[dt.date]:
    now = dt.datetime.now(timezone)
    dates = sorted({parse_chunk(path).astimezone(timezone).date() for path in chunks})
    result: list[dt.date] = []
    for day in dates:
        next_midnight = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=timezone)
        if now >= next_midnight + dt.timedelta(seconds=grace_seconds):
            result.append(day)
    return result


def check_auth() -> int:
    yt = YouTube(access_token())
    channel_id, title = yt.verify_channel()
    log(f"ARCHIVE_OAUTH_READY=true channel_id={channel_id} channel_title={title}")
    return 0


def test_upload(root: Path) -> int:
    yt = YouTube(access_token())
    yt.verify_channel()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tempdir:
        sample = Path(tempdir) / "fgb-archive-test.mp4"
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "6",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(sample),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise ArchiveError(f"Could not create upload test: {proc.stderr[-1000:]}")
        metadata = {
            "snippet": {
                "title": "FGB Archive Automation Test",
                "description": "Automated deployment verification. This temporary video is deleted after validation.",
                "categoryId": "17",
            },
            "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False},
        }
        uploaded = yt.upload(sample, metadata)
        video_id = uploaded.get("id", "")
        if not video_id:
            raise YouTubeError("Test upload returned no video id")
        try:
            actual = yt.video_privacy(video_id)
            if actual != "unlisted":
                raise YouTubeError(f"Test upload privacy is {actual}, expected unlisted")
            log(f"ARCHIVE_TEST_UPLOAD_PASS=true video_id={video_id}")
        finally:
            try:
                yt.delete_video(video_id)
                log("ARCHIVE_TEST_VIDEO_DELETED=true")
            except Exception as exc:
                log(f"ARCHIVE_TEST_DELETE_WARNING={type(exc).__name__}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-auth", action="store_true")
    parser.add_argument("--test-upload", action="store_true")
    args = parser.parse_args()

    root = Path(env("FGB_ARCHIVE_DIR", "/archive")).resolve()
    hourly = root / "hourly"
    final = root / "final"
    state = root / "state"
    for directory in (root, hourly, final, state):
        directory.mkdir(parents=True, exist_ok=True)

    if args.check_auth:
        return check_auth()
    if args.test_upload:
        return test_upload(root)

    timezone_name = env("FGB_ARCHIVE_TIMEZONE", "America/Chicago")
    timezone = ZoneInfo(timezone_name)
    privacy = env("FGB_ARCHIVE_PRIVACY", "public")
    if privacy not in {"private", "unlisted", "public"}:
        raise SystemExit("FGB_ARCHIVE_PRIVACY must be private, unlisted, or public")
    playlist_title = env("FGB_ARCHIVE_PLAYLIST_TITLE", "FGB Daily Livestream Archive") or "FGB Daily Livestream Archive"
    poll_seconds = max(15, int(env("FGB_ARCHIVE_POLL_SECONDS", "60")))
    stable_age = max(20, int(env("FGB_ARCHIVE_STABLE_AGE_SECONDS", "90")))
    grace_seconds = max(60, int(env("FGB_ARCHIVE_DAY_CLOSE_GRACE_SECONDS", "180")))
    max_seconds = min(43200.0, max(3600.0, float(env("FGB_ARCHIVE_MAX_PART_SECONDS", "43200"))))
    min_free_gb = max(2.0, float(env("FGB_ARCHIVE_MIN_FREE_GB", "8")))
    upload_enabled = env("FGB_ARCHIVE_UPLOAD_ENABLED", "1") == "1"

    log(f"ARCHIVE_UPLOADER_STARTED=true timezone={timezone_name} privacy={privacy}")
    consecutive_errors = 0
    oauth_notice_at = 0.0
    while True:
        try:
            protect_disk(root, hourly, min_free_gb)
            chunks = stable_chunks(hourly, stable_age)
            days = closed_days(chunks, timezone, grace_seconds)
            if not upload_enabled:
                time.sleep(poll_seconds)
                continue
            if not oauth_ready():
                if time.time() - oauth_notice_at > 900:
                    log("ARCHIVE_UPLOADER_WAITING_FOR_OAUTH=true")
                    oauth_notice_at = time.time()
                time.sleep(poll_seconds)
                continue
            if not days:
                time.sleep(poll_seconds)
                continue
            yt = YouTube(access_token())
            yt.verify_channel()
            for day in days:
                day_chunks = [p for p in chunks if parse_chunk(p).astimezone(timezone).date() == day]
                process_day(day, day_chunks, root, yt, privacy, playlist_title, max_seconds)
            consecutive_errors = 0
        except (ArchiveError, YouTubeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            consecutive_errors += 1
            log(f"ARCHIVE_UPLOADER_ERROR={type(exc).__name__}:{exc}")
            time.sleep(min(300, max(poll_seconds, 10 * consecutive_errors)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
