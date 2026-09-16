#!/usr/bin/env python3
"""FGB Lovable -> Oracle audio pipeline v4.

Contract:
- Lovable approval is authoritative.
- A source that already matches the proven FGB delivery profile is deployed
  byte-for-byte: AAC-LC, 44.1 kHz, stereo, ~128 kbps, zero-based monotonic PTS.
- Other approved audio is transport-sanitized only: decode, resample to 44.1 kHz,
  reset timestamps, AAC encode at 128 kbps, then remux to M4A so packet 0 starts
  at timestamp zero. No EQ, compression, denoise, limiting or loudness processing.
- Network/download/processing occurs outside the live FFmpeg loop.
- Deployment is atomic with rollback, and previously-active destination relays
  are returned to a fresh timeline after the master restarts.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

ENDPOINTS = (
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
    "https://grant-gems-today.lovable.app/api/public/fgbears/stream-routing",
)
MASTER_SERVICE = "fgbears-live.service"
AUDIO_FILE = Path("/srv/fgbears-live/audio/fgb-music-loop.m4a")
ROOT = Path("/srv/fgbears-live/audio/incoming-v4")
STATE_FILE = Path("/srv/fgbears-live/runtime/lovable-audio-pipeline.json")
LOCK_FILE = Path("/run/fgbears-lovable-audio-pipeline.lock")
QUARANTINE = Path("/srv/fgbears-live/quarantine/lovable-audio-pipeline-v4")
PROGRESS_FILE = Path("/srv/fgbears-live/logs/ffmpeg-progress.log")
MAX_SOURCE_BYTES = 512 * 1024 * 1024
HTTP_TIMEOUT = 30
VERIFY_SECONDS = 15
PACING_MIN = 0.97
PACING_MAX = 1.03
TARGET_RATE = 44100
TARGET_CHANNELS = 2
TARGET_BITRATE = 128000
DIRECT_BITRATE_MIN = 110000
DIRECT_BITRATE_MAX = 150000


def run(cmd: list[str], *, check: bool = True, capture: bool = True, timeout: int = 1200):
    return subprocess.run(cmd, check=check, text=True, capture_output=capture, timeout=timeout)


def log(msg: str) -> None:
    print(f"FGB_AUDIO_PIPELINE_V4 {msg}", flush=True)


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"failedRevisions": []}


def write_state(**patch) -> dict:
    state = read_state()
    state.update(patch)
    state.setdefault("failedRevisions", [])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_FILE)
    return state


def mark_failed(revision: int, message: str, rolled_back: bool = False) -> None:
    state = read_state()
    failed = {int(x) for x in state.get("failedRevisions", []) if str(x).isdigit()}
    failed.add(revision)
    write_state(
        failedRevisions=sorted(failed),
        candidateRevision=revision,
        status="rolled_back" if rolled_back else "failed",
        message=message[:1000],
        completedAt=utc(),
    )


def fetch_contract() -> tuple[str, dict]:
    last = ""
    for endpoint in ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "FGB-Oracle-Audio-Pipeline-V4/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
            audio = payload.get("presentation", {}).get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("revision"), int):
                return endpoint, audio
            last = f"{endpoint}: no presentation.audio"
        except Exception as exc:
            last = f"{endpoint}: {type(exc).__name__}: {exc}"
    raise RuntimeError(f"No valid Lovable audio contract. Last error: {last}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "FGB-Oracle-Audio-Pipeline-V4/1.0"})
    total = 0
    partial = dest.with_suffix(dest.suffix + ".partial")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response, partial.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise RuntimeError("Approved source exceeds 512 MB ceiling")
            out.write(chunk)
    if total <= 0:
        raise RuntimeError("Approved source downloaded empty")
    os.replace(partial, dest)


def probe(path: Path) -> dict:
    cp = run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,profile,sample_rate,channels,bit_rate,start_time:format=duration",
        "-of", "json", str(path),
    ])
    data = json.loads(cp.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"No audio stream in {path}")
    s = streams[0]
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Audio duration is not positive")
    try:
        bitrate = int(s.get("bit_rate") or 0)
    except Exception:
        bitrate = 0
    try:
        start = float(s.get("start_time") or 0)
    except Exception:
        start = 0.0
    return {
        "codec": str(s.get("codec_name") or ""),
        "profile": str(s.get("profile") or ""),
        "sampleRate": int(s.get("sample_rate") or 0),
        "channels": int(s.get("channels") or 0),
        "bitRate": bitrate,
        "startTime": start,
        "duration": duration,
    }


def first_packet_pts(path: Path) -> float:
    cp = run([
        "ffprobe", "-v", "error", "-read_intervals", "%+0.10", "-select_streams", "a:0",
        "-show_packets", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path),
    ])
    for line in cp.stdout.splitlines():
        token = line.split(",", 1)[0].strip()
        try:
            return float(token)
        except Exception:
            continue
    raise RuntimeError("No audio packet PTS found")


def full_decode(path: Path) -> None:
    run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-vn", "-f", "null", "-"], timeout=1200)


def validate_monotonic_packets(path: Path) -> None:
    proc = subprocess.Popen(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_packets", "-show_entries", "packet=pts_time,dts_time", "-of", "csv=p=0", str(path)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    last_pts = None
    last_dts = None
    count = 0
    try:
        for line in proc.stdout:
            parts = [p.strip() for p in line.strip().split(",")]
            vals = []
            for p in parts[:2]:
                try:
                    vals.append(float(p))
                except Exception:
                    vals.append(None)
            pts = vals[0] if vals else None
            dts = vals[1] if len(vals) > 1 else None
            if pts is None and dts is None:
                continue
            count += 1
            if pts is not None and last_pts is not None and pts + 1e-6 < last_pts:
                raise RuntimeError(f"Non-monotonic audio PTS at packet {count}: {pts} < {last_pts}")
            if dts is not None and last_dts is not None and dts + 1e-6 < last_dts:
                raise RuntimeError(f"Non-monotonic audio DTS at packet {count}: {dts} < {last_dts}")
            if pts is not None:
                last_pts = pts
            if dts is not None:
                last_dts = dts
        rc = proc.wait(timeout=60)
        if rc != 0:
            err = (proc.stderr.read() if proc.stderr else "")[:500]
            raise RuntimeError(f"Packet probe failed rc={rc}: {err}")
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
        raise
    if count == 0:
        raise RuntimeError("No audio packets found during timestamp validation")


def validate_delivery(path: Path) -> dict:
    meta = probe(path)
    full_decode(path)
    validate_monotonic_packets(path)
    first = first_packet_pts(path)
    if meta["codec"] != "aac":
        raise RuntimeError(f"Delivery codec is {meta['codec']}, expected AAC")
    if meta["sampleRate"] != TARGET_RATE or meta["channels"] != TARGET_CHANNELS:
        raise RuntimeError(f"Delivery signature invalid: {meta}")
    if abs(meta["startTime"]) > 0.001:
        raise RuntimeError(f"Delivery start_time is {meta['startTime']}, expected 0")
    if abs(first) > 0.001:
        raise RuntimeError(f"First audio packet PTS is {first}, expected 0")
    return meta


def is_direct_ready(source: Path) -> tuple[bool, dict]:
    meta = probe(source)
    first = first_packet_pts(source)
    ready = (
        meta["codec"] == "aac"
        and meta["sampleRate"] == TARGET_RATE
        and meta["channels"] == TARGET_CHANNELS
        and abs(meta["startTime"]) <= 0.001
        and abs(first) <= 0.001
        and DIRECT_BITRATE_MIN <= meta["bitRate"] <= DIRECT_BITRATE_MAX
    )
    return ready, {**meta, "firstPacketPts": first}


def own(path: Path) -> None:
    os.chown(path, pwd.getpwnam("fgbears").pw_uid, grp.getgrnam("fgbears").gr_gid)
    os.chmod(path, 0o644)


def sanitize(source: Path, candidate: Path) -> None:
    adts = candidate.with_suffix(".aac")
    adts.unlink(missing_ok=True)
    candidate.unlink(missing_ok=True)
    # Transport-only conversion. No loudness, EQ, dynamics, denoise or limiting.
    run([
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(source),
        "-map", "0:a:0", "-vn", "-af", f"aresample={TARGET_RATE}:first_pts=0,asetpts=N/SR/TB",
        "-c:a", "aac", "-b:a", "128k", "-ar", str(TARGET_RATE), "-ac", str(TARGET_CHANNELS),
        "-f", "adts", str(adts),
    ], timeout=1200)
    run([
        "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-fflags", "+genpts", "-i", str(adts),
        "-map", "0:a:0", "-c:a", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(candidate),
    ], timeout=1200)
    adts.unlink(missing_ok=True)


def service_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def running_destinations() -> list[str]:
    cp = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager", "fgbears-*"], check=False)
    found = []
    for line in cp.stdout.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if unit in {MASTER_SERVICE, "fgbears-lovable-audio-pipeline.service", "fgbears-lovable-audio-sync.service"}:
            continue
        if any(x in unit for x in ("youtube", "rumble", "facebook", "relay", "uplink")):
            found.append(unit)
    return sorted(set(found))


def master_ffmpeg_pid() -> int:
    main = int((run(["systemctl", "show", "-p", "MainPID", "--value", MASTER_SERVICE]).stdout or "0").strip() or "0")
    if main <= 0:
        raise RuntimeError("Master service has no MainPID")
    child = run(["pgrep", "-P", str(main), "-x", "ffmpeg"], check=False)
    pids = [int(p) for p in child.stdout.split() if p.isdigit()]
    if not pids:
        raise RuntimeError("Master service has no FFmpeg child")
    return pids[0]


def verify_master_uses_audio() -> None:
    pid = master_ffmpeg_pid()
    cp = run(["bash", "-lc", f"ls -l /proc/{pid}/fd 2>/dev/null | grep -F -- '{AUDIO_FILE}'"], check=False)
    if cp.returncode != 0:
        raise RuntimeError("Master FFmpeg is not reading canonical audio file")


def progress_us() -> int:
    if not PROGRESS_FILE.exists():
        raise RuntimeError("FFmpeg progress file missing")
    value = None
    for line in PROGRESS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                value = int(line.split("=", 1)[1])
            except ValueError:
                pass
    if value is None:
        raise RuntimeError("FFmpeg progress clock missing")
    return value


def assert_pacing(label: str, seconds: int = VERIFY_SECONDS) -> float:
    if not service_active(MASTER_SERVICE):
        raise RuntimeError("Master service not active")
    m0 = progress_us()
    w0 = time.monotonic()
    time.sleep(seconds)
    m1 = progress_us()
    w1 = time.monotonic()
    if m1 <= m0:
        raise RuntimeError(f"{label} media clock did not advance ({m0} -> {m1})")
    ratio = ((m1 - m0) / 1_000_000.0) / (w1 - w0)
    if not PACING_MIN <= ratio <= PACING_MAX:
        raise RuntimeError(f"{label} pacing ratio {ratio:.4f} outside {PACING_MIN:.2f}-{PACING_MAX:.2f}")
    return ratio


def prepare_revision(endpoint: str, audio: dict, revision: int) -> tuple[Path, dict]:
    track_id = str(audio.get("activeTrackId") or "")
    track_name = str(audio.get("activeTrackName") or "")
    asset = audio.get("assetUrl")
    expected_hash = str(audio.get("sourceSha256") or "").lower()
    gain = float(audio.get("volumeGainDb") or 0)
    if audio.get("mode") != "track" or audio.get("enabled") is not True:
        raise RuntimeError("Only explicit approved track revisions are handled")
    if audio.get("loop") is not True:
        raise RuntimeError("Approved track must use loop=true")
    if abs(gain) >= 0.01:
        raise RuntimeError("v4 transport standard requires Lovable volumeGainDb=0")
    if not track_id or not track_name or not isinstance(asset, str) or not asset:
        raise RuntimeError("Approved track contract is incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("Approved track is missing a valid sourceSha256")

    work = ROOT / f"rev-{revision}"
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source"
    candidate = work / "candidate.m4a"
    manifest = work / "manifest.json"
    for p in (source, candidate, candidate.with_suffix(".aac"), manifest):
        p.unlink(missing_ok=True)

    write_state(status="downloading", candidateRevision=revision, trackId=track_id, trackName=track_name, startedAt=utc(), message="Downloading approved Lovable asset under audio standard v4")
    download(urllib.parse.urljoin(endpoint, asset), source)
    actual_hash = sha256(source)
    if actual_hash != expected_hash:
        raise RuntimeError(f"Source SHA-256 mismatch expected={expected_hash} actual={actual_hash}")
    full_decode(source)
    validate_monotonic_packets(source)

    direct, source_meta = is_direct_ready(source)
    if direct:
        shutil.copy2(source, candidate)
        mode = "direct_byte_for_byte"
        log(f"direct_ready revision={revision} sha={actual_hash}")
    else:
        write_state(status="processing", message="Transport-sanitizing approved source to 44.1 kHz stereo AAC 128 kbps; no mastering")
        sanitize(source, candidate)
        mode = "transport_sanitized"

    candidate_meta = validate_delivery(candidate)
    candidate_hash = sha256(candidate)
    if direct and candidate_hash != actual_hash:
        raise RuntimeError("Byte-for-byte direct candidate hash changed unexpectedly")
    manifest_payload = {
        "revision": revision,
        "trackId": track_id,
        "trackName": track_name,
        "sourceSha256": actual_hash,
        "canonicalSha256": candidate_hash,
        "mode": mode,
        "source": source_meta,
        "canonical": candidate_meta,
        "processing": [] if direct else ["decode", "aresample_44100_first_pts_0", "asetpts_zero_based", "aac_128k_stereo", "m4a_zero_based_remux"],
        "forbiddenProcessingAbsent": ["loudness_normalization", "equalizer", "compressor", "limiter", "denoise", "tempo_change", "pitch_change"],
        "preparedAt": utc(),
    }
    manifest.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    own(candidate)
    write_state(status="ready", message=f"v4 candidate passed delivery gates ({mode})", canonicalSha256=candidate_hash, ingestMode=mode)
    return candidate, manifest_payload


def deploy(candidate: Path, revision: int, manifest: dict) -> float:
    destinations = running_destinations()
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = QUARANTINE / f"{stamp}-rev{revision}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / AUDIO_FILE.name
    if not AUDIO_FILE.exists():
        raise RuntimeError("Current live audio is missing; refusing cutover")
    shutil.copy2(AUDIO_FILE, backup)
    old_hash = sha256(backup)

    staged = AUDIO_FILE.with_suffix(".new")
    shutil.copy2(candidate, staged)
    own(staged)
    write_state(status="deploying", message="Atomically promoting v4 candidate", rollbackBackup=str(backup), previousLiveSha256=old_hash, destinationsObserved=destinations)
    os.replace(staged, AUDIO_FILE)
    try:
        run(["systemctl", "restart", MASTER_SERVICE], timeout=90)
        deadline = time.time() + 60
        last = ""
        while time.time() < deadline:
            if service_active(MASTER_SERVICE):
                try:
                    verify_master_uses_audio()
                    break
                except Exception as exc:
                    last = str(exc)
            time.sleep(1)
        else:
            raise RuntimeError(f"Master failed to reopen canonical audio: {last}")

        # The YouTube relay is already tied to the master lifecycle. Other active
        # destinations are explicitly reset so no relay carries a stale timeline.
        for unit in destinations:
            if "youtube" not in unit.lower() and service_active(unit):
                run(["systemctl", "restart", unit], check=False, timeout=60)
        deadline = time.time() + 60
        while time.time() < deadline:
            missing = [u for u in destinations if not service_active(u)]
            if not missing:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Previously active destination service(s) did not recover: " + ", ".join(missing))

        if sha256(AUDIO_FILE) != manifest["canonicalSha256"]:
            raise RuntimeError("Live audio hash changed after promotion")
        validate_delivery(AUDIO_FILE)
        ratio = assert_pacing("new audio")
        return ratio
    except Exception as exc:
        log(f"deployment_failed revision={revision} rollback={backup} error={exc}")
        rollback_tmp = AUDIO_FILE.with_suffix(".rollback")
        shutil.copy2(backup, rollback_tmp)
        own(rollback_tmp)
        os.replace(rollback_tmp, AUDIO_FILE)
        run(["systemctl", "restart", MASTER_SERVICE], check=False, timeout=90)
        mark_failed(revision, str(exc), rolled_back=True)
        raise


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("already_running")
            return 0

        endpoint, audio = fetch_contract()
        revision = int(audio["revision"])
        approval = str(audio.get("approvalState") or "unapproved")
        state = read_state()
        failed = {int(x) for x in state.get("failedRevisions", []) if str(x).isdigit()}
        if int(state.get("appliedRevision", -1)) == revision:
            log(f"no_change revision={revision} already_live")
            return 0
        if revision in failed:
            log(f"no_retry revision={revision} previously_failed")
            return 0
        if approval != "approved":
            log(f"no_action revision={revision} approvalState={approval}")
            write_state(status="idle", observedRevision=revision, message="Waiting for explicit Lovable approval")
            return 0
        if not audio.get("approvedAt") or not audio.get("sourceSha256"):
            log(f"no_action revision={revision} approved_contract_incomplete")
            write_state(status="idle", observedRevision=revision, message="Approved contract missing approvedAt/sourceSha256")
            return 0

        try:
            write_state(status="detected", candidateRevision=revision, observedRevision=revision, controlEndpoint=endpoint, message="Explicit Lovable approval detected by audio standard v4")
            candidate, manifest = prepare_revision(endpoint, audio, revision)
            if os.getenv("FGB_AUDIO_SHADOW", "0") == "1":
                write_state(status="ready", shadow=True, message="v4 shadow preparation passed; live audio unchanged")
                log(f"shadow_pass revision={revision} candidate={candidate}")
                return 0
            ratio = deploy(candidate, revision, manifest)
            write_state(
                appliedRevision=revision,
                activeTrackId=audio.get("activeTrackId"),
                activeTrackName=audio.get("activeTrackName"),
                trackId=audio.get("activeTrackId"),
                trackName=audio.get("activeTrackName"),
                sourceSha256=audio.get("sourceSha256"),
                canonicalSha256=manifest["canonicalSha256"],
                ingestMode=manifest["mode"],
                pacingRatio=ratio,
                status="live",
                shadow=False,
                message="Audio standard v4 deployed and verified",
                completedAt=utc(),
            )
            log(f"live revision={revision} mode={manifest['mode']} pacing={ratio:.4f}")
            return 0
        except Exception as exc:
            if read_state().get("status") != "rolled_back":
                mark_failed(revision, f"{type(exc).__name__}: {exc}")
            log(f"failed revision={revision} error={type(exc).__name__}:{exc}")
            raise


if __name__ == "__main__":
    raise SystemExit(main())
