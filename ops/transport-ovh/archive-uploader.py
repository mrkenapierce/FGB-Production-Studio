#!/usr/bin/env python3
"""FGB hourly YouTube archive publisher.

This process is isolated from the live encoder. It scans completed, clock-aligned
MPEG-TS segments written by archive-recorder.sh, remuxes each full hour to MP4
with stream copy, uploads exactly one YouTube video per hour, and asks the
application archive endpoint to add that video to the archive playlist.

The application owns YouTube OAuth, title/description generation, playlist
creation, and the authoritative idempotency ledger. This host receives only
short-lived access tokens.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
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
from typing import Any

API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_START = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_RE = re.compile(r"^live-(?P<date>\d{8})-(?P<time>\d{6})-(?P<offset>[+-]\d{4})\.ts$")
UPLOAD_CHUNK = 8 * 1024 * 1024
EXPECTED_CHANNEL_ID = "UC3qyMq_KCg7aF08x7LZyVtg"


class ArchiveError(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


class YouTubeError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def api_call(payload: dict[str, Any], timeout: int = 45) -> dict[str, Any]:
    url = env("FGB_ARCHIVE_CONTROL_URL", "https://epiccontentcreatorgrants.org/api/public/fgbears/archive")
    secret = env("FGB_TRANSPORT_HEARTBEAT_SECRET")
    if not secret:
        raise ApiError("FGB_TRANSPORT_HEARTBEAT_SECRET is not configured")
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ts = str(int(time.time()))
    signature = hmac.new(secret.encode("utf-8"), ts.encode("ascii") + b"." + raw, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        url,
        data=raw,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-fgb-timestamp": ts,
            "x-fgb-signature": signature,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"archive endpoint HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"archive endpoint network error: {exc.reason}") from exc
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError("archive endpoint returned non-JSON response") from exc
    if not isinstance(result, dict):
        raise ApiError("archive endpoint returned invalid JSON shape")
    return result


def youtube_json(
    token: str,
    resource: str,
    *,
    method: str = "GET",
    params: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{API_BASE}/{resource}"
    if query:
        url += f"?{query}"
    data = None
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise YouTubeError(f"YouTube HTTP {exc.code}: {raw[:800]}") from exc
    except urllib.error.URLError as exc:
        raise YouTubeError(f"YouTube network error: {exc.reason}") from exc
    if not raw:
        return {}
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise YouTubeError("YouTube returned non-JSON response") from exc
    return result if isinstance(result, dict) else {}


def get_token() -> tuple[str, dict[str, Any]]:
    response = api_call({"action": "token"})
    if not response.get("ok"):
        raise ApiError(f"token request rejected: {response.get('error', 'unknown')}")
    token = str(response.get("accessToken") or "")
    if not token:
        raise ApiError("token response contained no accessToken")
    return token, response


def verify_channel(token: str) -> tuple[str, str]:
    payload = youtube_json(token, "channels", params={"part": "id,snippet", "mine": "true", "maxResults": "1"})
    items = payload.get("items") or []
    if not items:
        raise YouTubeError("OAuth token has no YouTube channel")
    item = items[0]
    cid = str(item.get("id") or "")
    title = str((item.get("snippet") or {}).get("title") or "")
    expected = env("FGB_EXPECTED_YOUTUBE_CHANNEL_ID", EXPECTED_CHANNEL_ID)
    if expected and cid != expected:
        raise YouTubeError(f"OAuth channel mismatch: expected {expected}, got {cid}")
    return cid, title


def parse_chunk(path: Path) -> tuple[dt.datetime, str]:
    match = CHUNK_RE.match(path.name)
    if not match:
        raise ArchiveError(f"unexpected filename: {path.name}")
    stamp = f"{match.group('date')}{match.group('time')}{match.group('offset')}"
    start = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S%z")
    segment_id = f"{match.group('date')}T{match.group('time')}{match.group('offset')}"
    return start, segment_id


def probe(path: Path) -> tuple[float, bool, bool]:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type", "-of", "json", str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise ArchiveError(f"ffprobe failed for {path.name}: {proc.stderr[-500:]}")
    try:
        data = json.loads(proc.stdout)
        duration = float((data.get("format") or {}).get("duration") or 0)
        streams = data.get("streams") or []
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ArchiveError(f"invalid ffprobe response for {path.name}") from exc
    return (
        duration,
        any(s.get("codec_type") == "video" for s in streams),
        any(s.get("codec_type") == "audio" for s in streams),
    )


def stable_chunks(hourly: Path, stable_age: int) -> list[Path]:
    cutoff = time.time() - stable_age
    found: list[Path] = []
    for path in hourly.glob("live-*.ts"):
        if not CHUNK_RE.match(path.name):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if stat.st_size > 0 and stat.st_mtime <= cutoff:
            found.append(path)
    return sorted(found, key=lambda p: parse_chunk(p)[0])


def state_path_for(state_dir: Path, segment_id: str) -> Path:
    safe = segment_id.replace("+", "p").replace("-", "m").replace(":", "")
    return state_dir / f"hourly-{safe}.json"


def remux(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.mp4")
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-y",
            "-fflags", "+genpts", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
            "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(tmp),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise ArchiveError(f"remux failed for {source.name}: {proc.stderr[-1200:]}")
    duration, video, audio = probe(tmp)
    if duration <= 0 or not video or not audio:
        tmp.unlink(missing_ok=True)
        raise ArchiveError(f"remux validation failed for {source.name}")
    os.replace(tmp, output)


def start_upload_session(token: str, path: Path, title: str, description: str, privacy: str) -> str:
    query = urllib.parse.urlencode(
        {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "false"}
    )
    metadata = {
        "snippet": {"title": title[:100], "description": description, "categoryId": "17"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    raw = json.dumps(metadata).encode("utf-8")
    req = urllib.request.Request(
        f"{UPLOAD_START}?{query}",
        data=raw,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(raw)),
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(path.stat().st_size),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            location = response.headers.get("Location", "")
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise YouTubeError(f"upload session start failed ({exc.code}): {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise YouTubeError(f"upload session network error: {exc.reason}") from exc
    if not location.startswith("https://"):
        raise YouTubeError("YouTube returned no secure upload session URL")
    return location


def upload_request(session_url: str, data: bytes, start: int, total: int) -> tuple[int, dict[str, str], bytes]:
    parts = urllib.parse.urlsplit(session_url)
    path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=240)
    try:
        end = start + len(data) - 1
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


def query_session(session_url: str, total: int) -> tuple[str, int, dict[str, Any] | None]:
    parts = urllib.parse.urlsplit(session_url)
    path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=60)
    try:
        conn.request(
            "PUT", path, body=b"",
            headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"},
        )
        response = conn.getresponse()
        raw = response.read()
        if response.status in (200, 201):
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            return "complete", total, payload if isinstance(payload, dict) else {}
        if response.status == 308:
            value = response.getheader("Range", "")
            offset = int(value.rsplit("-", 1)[1]) + 1 if value.startswith("bytes=0-") else 0
            return "resume", offset, None
        if response.status in (404, 410):
            return "expired", 0, None
        raise YouTubeError(f"upload status query failed ({response.status}): {raw[:500]!r}")
    finally:
        conn.close()


def resumable_upload(path: Path, state_path: Path, state: dict[str, Any], title: str,
                     description: str, privacy: str) -> tuple[str, dict[str, Any]]:
    total = path.stat().st_size
    if total <= 0:
        raise YouTubeError("refusing empty upload")

    token, _ = get_token()
    session = str(state.get("upload_session") or "")
    offset = int(state.get("upload_offset") or 0)

    if session:
        status, offset, completed = query_session(session, total)
        if status == "complete":
            video_id = str((completed or {}).get("id") or state.get("video_id") or "")
            if not video_id:
                raise YouTubeError("completed resumable session returned no video id")
            state["video_id"] = video_id
            state["upload_offset"] = total
            state["uploaded_at"] = state.get("uploaded_at") or now_iso()
            atomic_json(state_path, state)
            return video_id, state
        if status == "expired":
            session = ""
            offset = 0
            state.pop("upload_session", None)
            state["upload_offset"] = 0
            atomic_json(state_path, state)

    if not session:
        session = start_upload_session(token, path, title, description, privacy)
        state["upload_session"] = session
        state["upload_offset"] = 0
        state["upload_started_at"] = now_iso()
        atomic_json(state_path, state)
        offset = 0

    final: dict[str, Any] | None = None
    with path.open("rb") as handle:
        while offset < total:
            handle.seek(offset)
            data = handle.read(min(UPLOAD_CHUNK, total - offset))
            if not data:
                raise YouTubeError("unexpected EOF during upload")
            for attempt in range(1, 7):
                try:
                    status, headers, raw = upload_request(session, data, offset, total)
                    if status in (200, 201):
                        payload = json.loads(raw.decode("utf-8")) if raw else {}
                        final = payload if isinstance(payload, dict) else {}
                        offset = total
                        break
                    if status == 308:
                        value = headers.get("Range", headers.get("range", ""))
                        offset = int(value.rsplit("-", 1)[1]) + 1 if value.startswith("bytes=0-") else offset + len(data)
                        break
                    if status in (404, 410):
                        state.pop("upload_session", None)
                        state["upload_offset"] = 0
                        atomic_json(state_path, state)
                        raise YouTubeError("resumable upload session expired; retry will create a new session")
                    if status in (500, 502, 503, 504) and attempt < 6:
                        time.sleep(min(30, 2 ** attempt))
                        continue
                    raise YouTubeError(f"upload failed ({status}): {raw[:500]!r}")
                except (OSError, http.client.HTTPException) as exc:
                    if attempt >= 6:
                        raise YouTubeError(f"upload network failure: {exc}") from exc
                    time.sleep(min(30, 2 ** attempt))
                    try:
                        qstatus, qoffset, completed = query_session(session, total)
                        if qstatus == "complete":
                            final = completed or {}
                            offset = total
                            break
                        if qstatus == "resume":
                            offset = qoffset
                            break
                    except Exception:
                        pass
            state["upload_offset"] = offset
            atomic_json(state_path, state)
            if final is not None:
                break

    if final is None:
        qstatus, qoffset, completed = query_session(session, total)
        if qstatus == "complete":
            final = completed or {}
            offset = total
        else:
            offset = qoffset

    video_id = str((final or {}).get("id") or "")
    if offset != total or not video_id:
        raise YouTubeError("resumable upload did not complete with a video id")
    state["video_id"] = video_id
    state["upload_offset"] = total
    state["uploaded_at"] = now_iso()
    atomic_json(state_path, state)
    return video_id, state


def verify_video(token: str, video_id: str, expected_privacy: str | None = None) -> str:
    payload = youtube_json(token, "videos", params={"part": "status", "id": video_id, "maxResults": "1"})
    items = payload.get("items") or []
    if not items:
        raise YouTubeError(f"video {video_id} could not be verified")
    privacy = str((items[0].get("status") or {}).get("privacyStatus") or "unknown")
    if expected_privacy and privacy != expected_privacy:
        raise YouTubeError(f"video {video_id} privacy is {privacy}, expected {expected_privacy}")
    return privacy


def delete_video(token: str, video_id: str) -> None:
    youtube_json(token, "videos", method="DELETE", params={"id": video_id})


def notify_failed(segment_id: str, message: str) -> None:
    try:
        api_call({"action": "failed", "segmentId": segment_id, "error": message[:290]})
    except Exception:
        pass


def backoff_state(state_path: Path, state: dict[str, Any], exc: Exception) -> None:
    attempts = int(state.get("attempts") or 0) + 1
    delay = min(3600, max(60, 60 * (2 ** min(attempts - 1, 6))))
    state["attempts"] = attempts
    state["next_try"] = int(time.time()) + delay
    state["last_error"] = f"{type(exc).__name__}: {str(exc)[:260]}"
    state["last_error_at"] = now_iso()
    atomic_json(state_path, state)
    log(f"ARCHIVE_RETRY_IN={delay} error={type(exc).__name__}:{str(exc)[:220]}")


def cleanup_confirmed(root: Path, retention_hours: int) -> None:
    state_dir = root / "state"
    cutoff = time.time() - retention_hours * 3600
    for path in state_dir.glob("hourly-*.json"):
        state = load_json(path)
        confirmed_epoch = state.get("confirmed_epoch")
        if not isinstance(confirmed_epoch, (int, float)) or confirmed_epoch > cutoff:
            continue
        for key in ("source", "mp4"):
            value = state.get(key)
            if value:
                try:
                    Path(str(value)).unlink(missing_ok=True)
                except OSError:
                    pass
        if not state.get("media_removed"):
            state["media_removed"] = True
            state["media_removed_at"] = now_iso()
            atomic_json(path, state)


def ignore_short_file(path: Path, state_dir: Path, duration: float, retention_hours: int) -> None:
    _, segment_id = parse_chunk(path)
    state_path = state_path_for(state_dir, segment_id)
    state = load_json(state_path)
    state.update({
        "segment_id": segment_id,
        "source": str(path),
        "ignored": True,
        "ignored_reason": f"duration {duration:.3f}s below full-hour minimum",
        "updated_at": now_iso(),
    })
    atomic_json(state_path, state)
    if path.stat().st_mtime < time.time() - retention_hours * 3600:
        path.unlink(missing_ok=True)
        state["media_removed"] = True
        state["media_removed_at"] = now_iso()
        atomic_json(state_path, state)


def process_segment(source: Path, root: Path, minimum_duration: float) -> bool:
    start, segment_id = parse_chunk(source)
    state_dir = root / "state"
    final_dir = root / "final"
    state_path = state_path_for(state_dir, segment_id)
    state = load_json(state_path)

    if state.get("confirmed"):
        return True
    if int(state.get("next_try") or 0) > int(time.time()):
        return False

    duration, video, audio = probe(source)
    if duration < minimum_duration:
        ignore_short_file(source, state_dir, duration, int(env("FGB_ARCHIVE_RETENTION_HOURS", "24")))
        return True
    if not video or not audio:
        raise ArchiveError(f"{source.name} does not contain both video and audio")

    state.update({
        "segment_id": segment_id,
        "source": str(source),
        "duration": duration,
        "starts_at": start.isoformat(),
        "updated_at": now_iso(),
    })
    atomic_json(state_path, state)

    register = api_call({"action": "register", "segmentId": segment_id})
    if not register.get("ok"):
        raise ApiError(f"register rejected: {register.get('error', 'unknown')}")
    if register.get("paused"):
        log(f"ARCHIVE_PUBLISHING_PAUSED=true segment={segment_id}")
        return False

    title = str(register.get("title") or "")
    description = str(register.get("description") or "")
    privacy = str(register.get("privacy") or "unlisted")
    server_status = str(register.get("status") or "")
    server_video_id = str(register.get("videoId") or "")
    if not title:
        raise ApiError("register returned no title")
    if privacy not in {"private", "unlisted", "public"}:
        raise ApiError(f"invalid privacy from control endpoint: {privacy}")

    state.update({"title": title, "privacy": privacy, "server_status": server_status, "updated_at": now_iso()})
    if server_video_id and not state.get("video_id"):
        state["video_id"] = server_video_id
    atomic_json(state_path, state)

    if server_status == "confirmed":
        state["confirmed"] = True
        state["confirmed_at"] = state.get("confirmed_at") or now_iso()
        state["confirmed_epoch"] = state.get("confirmed_epoch") or int(time.time())
        state["attempts"] = 0
        state["next_try"] = 0
        atomic_json(state_path, state)
        log(f"ARCHIVE_SEGMENT_CONFIRMED={segment_id} video_id={state.get('video_id','')}")
        return True

    video_id = str(state.get("video_id") or "")
    output = final_dir / f"{segment_id.replace('+', 'p').replace('-', 'm')}.mp4"
    state["mp4"] = str(output)

    if not video_id:
        if not output.exists():
            remux(source, output)
            log(f"ARCHIVE_HOUR_READY={segment_id} file={output.name}")
        marker = f"[FGB-ARCHIVE-ID:{segment_id}]"
        full_description = description.rstrip() + "\n\n" + marker
        video_id, state = resumable_upload(output, state_path, state, title, full_description, privacy)
        token, _ = get_token()
        verify_video(token, video_id, privacy)
        log(f"ARCHIVE_UPLOAD_COMPLETE={segment_id} video_id={video_id} privacy={privacy}")

    uploaded = api_call({"action": "uploaded", "segmentId": segment_id, "videoId": video_id})
    if not uploaded.get("ok") or not uploaded.get("confirmed"):
        raise ApiError(f"playlist confirmation failed: {uploaded.get('error', 'unconfirmed')}")

    state["video_id"] = video_id
    state["confirmed"] = True
    state["confirmed_at"] = now_iso()
    state["confirmed_epoch"] = int(time.time())
    state["attempts"] = 0
    state["next_try"] = 0
    state.pop("last_error", None)
    atomic_json(state_path, state)
    log(f"ARCHIVE_SEGMENT_CONFIRMED={segment_id} video_id={video_id} title={title}")
    return True


def post_status(root: Path, current_id: str | None, pending: int, last_error: str = "") -> None:
    try:
        free_mb = shutil.disk_usage(root).free / (1024 * 1024)
        recorder: dict[str, Any] = {
            "state": "running",
            "segmentSeconds": 3600,
            "pendingUploads": pending,
            "testMode": False,
            "diskFreeMb": free_mb,
            "host": env("HOST_LABEL", "ovh-archive-uploader"),
        }
        if current_id:
            recorder["currentSegmentId"] = current_id
        if last_error:
            recorder["lastError"] = last_error[:290]
        api_call({"action": "status", "recorder": recorder}, timeout=20)
    except Exception:
        pass


def check_auth() -> int:
    token, control = get_token()
    cid, title = verify_channel(token)
    privacy = control.get("privacy", "unknown")
    log(f"ARCHIVE_OAUTH_READY=true channel_id={cid} channel_title={title} privacy={privacy}")
    return 0


def test_upload(root: Path) -> int:
    token, _ = get_token()
    verify_channel(token)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tempdir:
        sample = Path(tempdir) / "fgb-hourly-archive-test.mp4"
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
            raise ArchiveError(f"could not create test file: {proc.stderr[-800:]}")
        session = start_upload_session(
            token, sample, "FGB Hourly Archive Automation Test",
            "Temporary unlisted validation video. Deleted automatically after verification.",
            "unlisted",
        )
        state_path = Path(tempdir) / "test-state.json"
        state = {"upload_session": session, "upload_offset": 0}
        atomic_json(state_path, state)
        vid, _ = resumable_upload(
            sample, state_path, state, "FGB Hourly Archive Automation Test",
            "Temporary unlisted validation video. Deleted automatically after verification.", "unlisted"
        )
        try:
            verify_video(token, vid, "unlisted")
            log(f"ARCHIVE_TEST_UPLOAD_PASS=true video_id={vid}")
        finally:
            try:
                delete_video(token, vid)
                log("ARCHIVE_TEST_VIDEO_DELETED=true")
            except Exception as exc:
                log(f"ARCHIVE_TEST_DELETE_WARNING={type(exc).__name__}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-auth", action="store_true")
    parser.add_argument("--test-upload", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    root = Path(env("FGB_ARCHIVE_DIR", "/archive")).resolve()
    hourly = root / "hourly"
    final = root / "final"
    state_dir = root / "state"
    for directory in (root, hourly, final, state_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if args.check_auth:
        return check_auth()
    if args.test_upload:
        return test_upload(root)

    stable_age = max(30, int(env("FGB_ARCHIVE_STABLE_AGE_SECONDS", "90")))
    poll_seconds = max(15, int(env("FGB_ARCHIVE_POLL_SECONDS", "30")))
    min_duration = max(60.0, float(env("FGB_ARCHIVE_MIN_FULL_HOUR_SECONDS", "3000")))
    retention_hours = max(1, int(env("FGB_ARCHIVE_RETENTION_HOURS", "24")))
    min_free_gb = max(2.0, float(env("FGB_ARCHIVE_MIN_FREE_GB", "8")))

    log("ARCHIVE_HOURLY_UPLOADER_STARTED=true")
    last_status = 0.0
    last_error = ""

    while True:
        try:
            free_gb = shutil.disk_usage(root).free / (1024 ** 3)
            if free_gb < min_free_gb:
                log(f"ARCHIVE_LOW_DISK_FREE_GB={free_gb:.2f}")
            cleanup_confirmed(root, retention_hours)
            chunks = stable_chunks(hourly, stable_age)
            pending = 0
            current_id: str | None = None
            for path in chunks:
                _, sid = parse_chunk(path)
                current_id = sid
                s = load_json(state_path_for(state_dir, sid))
                if not s.get("confirmed") and not s.get("ignored"):
                    pending += 1

            if time.time() - last_status >= 30:
                post_status(root, current_id, pending, last_error)
                last_status = time.time()

            for source in chunks:
                _, sid = parse_chunk(source)
                s_path = state_path_for(state_dir, sid)
                s = load_json(s_path)
                if s.get("confirmed") or s.get("ignored"):
                    continue
                if int(s.get("next_try") or 0) > int(time.time()):
                    continue
                try:
                    process_segment(source, root, min_duration)
                    last_error = ""
                except (ArchiveError, ApiError, YouTubeError, OSError, ValueError, subprocess.SubprocessError) as exc:
                    state = load_json(s_path)
                    state.setdefault("segment_id", sid)
                    state.setdefault("source", str(source))
                    backoff_state(s_path, state, exc)
                    notify_failed(sid, str(exc))
                    last_error = f"{sid}: {type(exc).__name__}: {str(exc)[:180]}"
                    break

            if args.once:
                return 0
            time.sleep(poll_seconds)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            log(f"ARCHIVE_UPLOADER_LOOP_ERROR={type(exc).__name__}:{str(exc)[:250]}")
            if args.once:
                return 1
            time.sleep(min(300, poll_seconds * 2))


if __name__ == "__main__":
    raise SystemExit(main())
