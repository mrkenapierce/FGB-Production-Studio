#!/usr/bin/env python3
"""One approved historical EPIC livestream, original TS bytes, exactly one upload.
Do not transcode, alter original CNT record, or touch live encoder.
Use only while regular EPIC timer is stopped. Root-only local resumable state.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import uuid
import urllib.parse

JOB_ID = "488db828-e266-402b-b2d9-6c0eb54c66fa"
TARGET = "UCxtESG21aQASGiuQQzd87UA"
SOURCE = Path("/srv/epic-publishing-recovery/2026-11-19-Play-Once-Qualify-Once.ts")
STATE_DIR = Path("/srv/epic-publishing-recovery/private-upload")
STATE_FILE = STATE_DIR / (JOB_ID + ".json")
MODULE = "/opt/epic-episode-publisher/epic-episode-cutter.py"

def run():
    os.umask(0o077)
    if os.geteuid() != 0:
        raise RuntimeError("must_run_as_root")
    if os.environ.get("EPIC_HISTORICAL_RECOVERY_APPROVED") != "yes":
        raise RuntimeError("not_authorized")
    if not SOURCE.is_file() or SOURCE.stat().st_size != 331723368:
        raise RuntimeError("recording_missing")
    with SOURCE.open("rb") as fh:
        digest = hashlib.file_digest(fh, "sha256").hexdigest()
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    lock = STATE_DIR / "historical-recovery.lock"
    with lock.open("w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        spec = importlib.util.spec_from_file_location("epic_original_uploader", MODULE)
        if not spec or not spec.loader:
            raise RuntimeError("uploader_unavailable")
        uploader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(uploader)
        response = uploader.api({"action": "epic_episode_jobs"})
        if response.get("ok") is not True:
            raise RuntimeError("publishing_not_enabled")
        matches = [j for j in response.get("jobs", []) if j.get("episodeId") == JOB_ID]
        if len(matches) != 1:
            raise RuntimeError("recovery_job_not_ready")
        job = matches[0]
        if job.get("targetChannelId") != TARGET or "windowStart" not in job:
            raise RuntimeError("identity_mismatch")
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None
        if state is None:
            state = {
                "owner": str(uuid.uuid4()),
                "title": job["title"],
                "description": job["description"],
                "sourceSha256": digest,
                "targetChannelId": TARGET,
            }
            uploader.save(STATE_FILE, state)
        if state.get("sourceSha256") != digest or state.get("targetChannelId") != TARGET or state.get("title") != job["title"]:
            raise RuntimeError("preserved_recording_conflict")
        print("ORIGINAL_720P_LIVESTREAM_BYTES_VERIFIED=331723368", flush=True)
        if state.get("confirmed") is True and state.get("videoId"):
            print("ALREADY_CONFIRMED_VIDEO_ID=" + state["videoId"], flush=True)
            return
        base = {"episodeId": JOB_ID, "owner": state["owner"]}
        result = uploader.api({"action": "epic_episode_claim", **base})
        if result.get("ok") is not True:
            raise RuntimeError("claim_conflict")
        for field in ("sessionUrl", "videoId"):
            if result.get(field):
                if state.get(field) and state[field] != result[field]:
                    raise RuntimeError("receipt_unverified")
                state[field] = result[field]
        uploader.save(STATE_FILE, state)
        print("ONE_TIME_EPIC_JOB_CLAIMED=true", flush=True)
        phase = 'preflight'
        try:
            if not state.get("videoId"):
                phase = 'token'
                response = uploader.api({"action": "epic_episode_token", **base})
                if response.get("ok") is not True or response.get("targetChannelId") != TARGET or not response.get("accessToken"):
                    raise RuntimeError("identity_mismatch")
                token = response["accessToken"]
                headers = {"authorization": "Bearer " + token}
                url = "https://www.googleapis.com/youtube/v3/channels?part=id,contentDetails&mine=true"
                phase = 'youtube_channel_check'
                code, _, body = uploader.http(url, "GET", headers)
                if code != 200:
                    raise RuntimeError("permission_denied")
                channel = json.loads(body).get("items") or []
                if len(channel) != 1 or channel[0].get("id") != TARGET:
                    raise RuntimeError("identity_mismatch")
                playlist = channel[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if not isinstance(playlist, str) or not playlist:
                    raise RuntimeError("identity_mismatch")
                phase = 'youtube_duplicate_check'
                # Before creating a video, check the channel's latest uploaded videos for this exact title.
                page = ""
                for _ in range(4):
                    params = {"part": "snippet", "playlistId": playlist, "maxResults": "50", "fields": "nextPageToken,items(snippet(title))"}
                    if page:
                        params["pageToken"] = page
                    p_url = "https://www.googleapis.com/youtube/v3/playlistItems?" + urllib.parse.urlencode(params)
                    status, _, result_body = uploader.http(p_url, "GET", headers)
                    if status != 200:
                        raise RuntimeError("upload_unavailable")
                    data = json.loads(result_body)
                    for item in data.get("items", []):
                        if item.get("snippet", {}).get("title", "").strip() == job["title"].strip():
                            raise RuntimeError("potential_duplicate_on_youtube")
                    page = data.get("nextPageToken", "")
                    if not page:
                        break
                print("EPIC_CHANNEL_ID_AND_DUPLICATE_CHECK_PASSED=true", flush=True)
                phase = 'youtube_upload'
                video_id = uploader.upload(
                    SOURCE, state, lambda s: uploader.save(STATE_FILE, s), token,
                    lambda url: uploader.api({"action": "epic_episode_session", "sessionUrl": url, **base}).get("ok") is True,
                )
            else:
                video_id = state["videoId"]
            print("YOUTUBE_RETURNED_VIDEO_ID=" + video_id, flush=True)
            phase = 'youtube_receipt_verification'
            receipt = uploader.api({"action": "epic_episode_uploaded", "videoId": video_id, **base})
            if receipt.get("confirmed") is not True:
                raise RuntimeError("receipt_unverified")
            state["confirmed"] = True
            uploader.save(STATE_FILE, state)
            print("EPIC_PUBLIC_VIDEO_CONFIRMED=true", flush=True)
            print("EPIC_PUBLIC_URL=https://www.youtube.com/watch?v=" + video_id, flush=True)
            print("SOURCE_RECORDING_PRESERVED=true", flush=True)
        except Exception as err:
            print('RECOVERY_FAILURE_PHASE=' + phase, flush=True)
            print('RECOVERY_FAILURE_CLASS=' + type(err).__name__, flush=True)
            reason = str(err)
            allowed = {
                "permission_denied", "identity_mismatch", "upload_unavailable",
                "upload_ambiguous", "session_expired", "receipt_unverified",
                "recording_missing", "recording_gap", "recording_partial",
            }
            if reason not in allowed:
                print("RECOVERY_SAFETY_STOP=" + (
                    reason if reason in {"potential_duplicate_on_youtube", "preserved_recording_conflict", "claim_conflict"} else "unclassified"
                ), flush=True)
            # Never discard a returned video ID or an ambiguous initiation; durable state permits reconciliation only.
            if reason in allowed:
                try:
                    uploader.api({"action": "epic_episode_failed", "reason": reason, **base})
                except Exception:
                    pass
            raise RuntimeError(reason if reason in allowed or reason == "potential_duplicate_on_youtube" else "recovery_failed")

if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        msg = str(exc)
        safe = {
            "must_run_as_root", "not_authorized", "recording_missing",
            "uploader_unavailable", "publishing_not_enabled", "recovery_job_not_ready",
            "identity_mismatch", "preserved_recording_conflict", "claim_conflict",
            "receipt_unverified", "permission_denied", "upload_unavailable",
            "upload_ambiguous", "session_expired", "potential_duplicate_on_youtube",
            "recording_gap", "recording_partial", "recovery_failed",
        }
        print("RECOVERY_RESULT=" + (msg if msg in safe else "blocked_unknown_error"), flush=True)
        sys.exit(1)
