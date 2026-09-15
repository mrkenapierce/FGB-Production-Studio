#!/usr/bin/env python3
"""Staged Lovable -> Oracle audio approval pipeline.

One-shot worker invoked by a systemd timer. Lovable expresses immutable approval
intent; Oracle downloads, prepares, validates, then atomically deploys. No
network request or conversion runs inside the live FFmpeg media loop.
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
ROOT = Path("/srv/fgbears-live/audio/incoming")
STATE_FILE = Path("/srv/fgbears-live/runtime/lovable-audio-pipeline.json")
LOCK_FILE = Path("/run/fgbears-lovable-audio-pipeline.lock")
QUARANTINE = Path("/srv/fgbears-live/quarantine/lovable-audio-pipeline")
PROGRESS_FILE = Path("/srv/fgbears-live/logs/ffmpeg-progress.log")
PREPARE_TOOL = Path("/usr/local/lib/fgbears-live/prepare-audio-track-v3.py")
MAX_SOURCE_BYTES = 50 * 1024 * 1024
HTTP_TIMEOUT = 25
PACING_MIN = 0.98
PACING_MAX = 1.02
VERIFY_SECONDS = 15


def run(cmd: list[str], *, check: bool = True, capture: bool = True, timeout: int = 900):
    return subprocess.run(cmd, check=check, text=True, capture_output=capture, timeout=timeout)


def log(msg: str) -> None:
    print(f"FGB_AUDIO_PIPELINE {msg}", flush=True)


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
            req = urllib.request.Request(endpoint, headers={"User-Agent": "FGB-Oracle-Audio-Pipeline/1.0", "Accept": "application/json"})
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
    req = urllib.request.Request(url, headers={"User-Agent": "FGB-Oracle-Audio-Pipeline/1.0"})
    total = 0
    partial = dest.with_suffix(dest.suffix + ".partial")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response, partial.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise RuntimeError("Approved source exceeds 50 MB ceiling")
            out.write(chunk)
    if total <= 0:
        raise RuntimeError("Approved source downloaded empty")
    os.replace(partial, dest)


def probe(path: Path) -> dict:
    cp = run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=duration",
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
    return {
        "codec": str(s.get("codec_name") or ""),
        "sampleRate": int(s.get("sample_rate") or 0),
        "channels": int(s.get("channels") or 0),
        "bitRate": int(s.get("bit_rate") or 0),
        "duration": duration,
    }


def full_decode(path: Path) -> None:
    run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-vn", "-f", "null", "-"], timeout=900)


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
            count += 1
            parts = [p.strip() for p in line.strip().split(",")]
            vals = []
            for p in parts[:2]:
                try:
                    vals.append(float(p))
                except Exception:
                    vals.append(None)
            pts = vals[0] if vals else None
            dts = vals[1] if len(vals) > 1 else None
            if pts is not None and last_pts is not None and pts + 1e-6 < last_pts:
                raise RuntimeError(f"Non-monotonic audio PTS at packet {count}: {pts} < {last_pts}")
            if dts is not None and last_dts is not None and dts + 1e-6 < last_dts:
                raise RuntimeError(f"Non-monotonic audio DTS at packet {count}: {dts} < {last_dts}")
            if pts is not None:
                last_pts = pts
            if dts is not None:
                last_dts = dts
        rc = proc.wait(timeout=30)
        if rc != 0:
            err = (proc.stderr.read() if proc.stderr else "")[:500]
            raise RuntimeError(f"Packet probe failed rc={rc}: {err}")
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
        raise
    if count == 0:
        raise RuntimeError("No audio packets found during timestamp validation")


def load_profile(candidate: Path) -> dict:
    marker = Path(str(candidate) + ".audio-profile.json")
    if not marker.exists():
        raise RuntimeError("Canonical profile marker missing")
    return json.loads(marker.read_text(encoding="utf-8"))


def validate_candidate(source: Path, candidate: Path) -> tuple[dict, dict]:
    source_meta = probe(source)
    candidate_meta = probe(candidate)
    full_decode(candidate)
    validate_monotonic_packets(candidate)
    if candidate_meta["codec"] != "aac":
        raise RuntimeError(f"Candidate codec is {candidate_meta['codec']}, expected AAC")
    if candidate_meta["sampleRate"] != 48000 or candidate_meta["channels"] != 2:
        raise RuntimeError(f"Candidate signature invalid: {candidate_meta}")
    tolerance = max(0.5, source_meta["duration"] * 0.0025)
    drift = abs(candidate_meta["duration"] - source_meta["duration"])
    if drift > tolerance:
        raise RuntimeError(f"Duration drift {drift:.3f}s exceeds {tolerance:.3f}s")
    profile = load_profile(candidate)
    if profile.get("quality_verified") is not True or profile.get("dynamic_processing") is not False:
        raise RuntimeError("Canonical production profile did not verify")
    metrics = profile.get("output_metrics") or {}
    i_lufs = float(metrics.get("i_lufs"))
    tp = float(metrics.get("tp_dbtp"))
    if not (-18.0 <= i_lufs <= -14.5):
        raise RuntimeError(f"Integrated loudness {i_lufs:.2f} LUFS outside production tolerance")
    if tp > -1.5:
        raise RuntimeError(f"True peak {tp:.2f} dBTP exceeds -1.5 dBTP ceiling")
    return candidate_meta, profile


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


def measure_pacing(seconds: int = VERIFY_SECONDS) -> float:
    if not service_active(MASTER_SERVICE):
        raise RuntimeError("Master service not active")
    m0 = progress_us()
    w0 = time.monotonic()
    time.sleep(seconds)
    m1 = progress_us()
    w1 = time.monotonic()
    if m1 <= m0:
        raise RuntimeError(f"Master media clock did not advance ({m0} -> {m1})")
    return ((m1 - m0) / 1_000_000.0) / (w1 - w0)


def assert_pacing(label: str, seconds: int = VERIFY_SECONDS) -> float:
    ratio = measure_pacing(seconds)
    if not PACING_MIN <= ratio <= PACING_MAX:
        raise RuntimeError(f"{label} pacing ratio {ratio:.4f} outside {PACING_MIN:.2f}-{PACING_MAX:.2f}")
    return ratio


def verify_youtube_copy_path(destinations: list[str]) -> None:
    yt = [u for u in destinations if "youtube" in u.lower()]
    if not yt:
        return
    ps = run(["ps", "-eo", "pid=,ppid=,args="], check=False).stdout
    for unit in yt:
        main = int((run(["systemctl", "show", "-p", "MainPID", "--value", unit], check=False).stdout or "0").strip() or "0")
        if main <= 0:
            raise RuntimeError(f"YouTube destination {unit} has no MainPID")
        related = [line for line in ps.splitlines() if re.search(rf"^\s*\d+\s+{main}\s+", line) or re.search(rf"^\s*{main}\s+", line)]
        joined = "\n".join(related).lower()
        if "gstreamer" in joined or "gst-launch" in joined:
            raise RuntimeError(f"YouTube destination {unit} is using retired GStreamer path")
        if "ffmpeg" in joined and "-c copy" not in joined and "-c:a copy" not in joined:
            raise RuntimeError(f"YouTube destination {unit} is not visibly copy/remuxing")


def own(path: Path) -> None:
    os.chown(path, pwd.getpwnam("fgbears").pw_uid, grp.getgrnam("fgbears").gr_gid)
    os.chmod(path, 0o644)


def prepare_revision(endpoint: str, audio: dict, revision: int) -> tuple[Path, dict, dict, float]:
    track_id = str(audio.get("activeTrackId") or "")
    track_name = str(audio.get("activeTrackName") or "")
    asset = audio.get("assetUrl")
    expected_hash = str(audio.get("sourceSha256") or "").lower()
    if audio.get("mode") != "track" or audio.get("enabled") is not True:
        raise RuntimeError("Only explicit approved track revisions are handled by this pipeline")
    if audio.get("loop") is not True:
        raise RuntimeError("Approved track must use loop=true")
    if not track_id or not track_name or not isinstance(asset, str) or not asset:
        raise RuntimeError("Approved track contract is incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise RuntimeError("Approved track is missing a valid sourceSha256")

    work = ROOT / f"rev-{revision}"
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source"
    candidate = work / "candidate.m4a"
    manifest = work / "manifest.json"
    for p in (source, candidate, Path(str(candidate) + ".audio-profile.json"), manifest):
        p.unlink(missing_ok=True)

    write_state(status="downloading", candidateRevision=revision, trackId=track_id, trackName=track_name, startedAt=utc(), message="Downloading approved Lovable asset")
    download(urllib.parse.urljoin(endpoint, asset), source)
    actual_hash = sha256(source)
    if actual_hash != expected_hash:
        raise RuntimeError(f"Source SHA-256 mismatch expected={expected_hash} actual={actual_hash}")
    source_meta = probe(source)

    before = progress_us()
    prep_start = time.monotonic()
    write_state(status="processing", message="Preparing canonical 48 kHz stereo AAC track")
    gain = float(audio.get("volumeGainDb") or 0)
    run([
        "python3", str(PREPARE_TOOL), "--source", str(source), "--output", str(candidate),
        "--source-kind", "new_original", "--source-label", track_name,
        "--source-file-sha256", actual_hash,
    ], timeout=900)
    prep_wall = max(0.001, time.monotonic() - prep_start)
    after = progress_us()
    live_ratio = ((after - before) / 1_000_000.0) / prep_wall
    if after <= before or not 0.97 <= live_ratio <= 1.03:
        raise RuntimeError(f"Live master pacing degraded during preparation: ratio={live_ratio:.4f}")

    # If the operator requested a non-zero extra gain, apply it once after the
    # canonical mastering step, then revalidate peak/loudness. Usually this is 0.
    if abs(gain) >= 0.05:
        adjusted = work / "candidate-adjusted.m4a"
        run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(candidate), "-map", "0:a:0", "-vn", "-af", f"volume={gain:.1f}dB,aresample=48000:first_pts=0", "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "256k", str(adjusted)], timeout=900)
        os.replace(adjusted, candidate)
        # The v3 marker no longer describes the output after extra gain. Fail safe
        # by rejecting extra gain until a future profile version models it exactly.
        raise RuntimeError("Non-zero Lovable volumeGainDb requires re-approval with a future mastering profile; set gain to 0 dB")

    write_state(status="validating", message="Running full decode, timing, loudness and timestamp gates")
    candidate_meta, profile = validate_candidate(source, candidate)
    candidate_hash = sha256(candidate)
    manifest_payload = {
        "revision": revision,
        "trackId": track_id,
        "trackName": track_name,
        "sourceSha256": actual_hash,
        "canonicalSha256": candidate_hash,
        "source": source_meta,
        "canonical": candidate_meta,
        "profile": profile,
        "masterPacingDuringPreparation": live_ratio,
        "preparedAt": utc(),
    }
    manifest.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    own(candidate)
    write_state(status="ready", message="Candidate passed all pre-deployment gates", canonicalSha256=candidate_hash, masterPacingDuringPreparation=live_ratio)
    return candidate, manifest_payload, source_meta, live_ratio


def deploy(candidate: Path, revision: int, manifest: dict) -> float:
    destinations = running_destinations()
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = QUARANTINE / f"{stamp}-rev{revision}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / AUDIO_FILE.name
    if not AUDIO_FILE.exists():
        raise RuntimeError("Current canonical live audio is missing; refusing cutover")
    shutil.copy2(AUDIO_FILE, backup)

    staged = AUDIO_FILE.with_suffix(".new")
    shutil.copy2(candidate, staged)
    own(staged)
    write_state(status="deploying", message="Atomically promoting validated candidate", rollbackBackup=str(backup), destinationsObserved=destinations)
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
        write_state(status="verifying", message="Verifying real-time program pacing")
        ratio = assert_pacing("new audio")
        missing = [u for u in destinations if not service_active(u)]
        if missing:
            raise RuntimeError("Previously active destination service(s) stopped: " + ", ".join(missing))
        verify_youtube_copy_path(destinations)
        return ratio
    except Exception as exc:
        log(f"deployment_failed revision={revision} rollback={backup} error={exc}")
        rollback_tmp = AUDIO_FILE.with_suffix(".rollback")
        shutil.copy2(backup, rollback_tmp)
        own(rollback_tmp)
        os.replace(rollback_tmp, AUDIO_FILE)
        run(["systemctl", "restart", MASTER_SERVICE], check=False, timeout=90)
        try:
            verify_master_uses_audio()
            rollback_ratio = assert_pacing("rollback audio", seconds=12)
            log(f"rollback_verified revision={revision} pacing={rollback_ratio:.4f}")
        except Exception as rollback_exc:
            raise RuntimeError(f"Deployment failed ({exc}); rollback verification also failed ({rollback_exc})") from rollback_exc
        mark_failed(revision, str(exc), rolled_back=True)
        raise


def main() -> int:
    if not PREPARE_TOOL.exists():
        raise RuntimeError(f"Missing preparation tool: {PREPARE_TOOL}")
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
            write_state(status="detected", candidateRevision=revision, controlEndpoint=endpoint, message="Explicit Lovable approval detected")
            candidate, manifest, _source, _prep_ratio = prepare_revision(endpoint, audio, revision)
            if os.getenv("FGB_AUDIO_SHADOW", "0") == "1":
                write_state(status="ready", shadow=True, message="Shadow preparation passed; live audio unchanged")
                log(f"shadow_pass revision={revision} candidate={candidate}")
                return 0
            ratio = deploy(candidate, revision, manifest)
            write_state(
                appliedRevision=revision,
                activeTrackId=audio.get("activeTrackId"),
                activeTrackName=audio.get("activeTrackName"),
                sourceSha256=audio.get("sourceSha256"),
                canonicalSha256=manifest["canonicalSha256"],
                pacingRatio=ratio,
                status="live",
                shadow=False,
                message="Validated audio deployed to shared master and verified",
                completedAt=utc(),
            )
            log(f"live revision={revision} pacing={ratio:.4f} destinations_preserved")
            return 0
        except Exception as exc:
            if read_state().get("status") != "rolled_back":
                mark_failed(revision, f"{type(exc).__name__}: {exc}")
            log(f"failed revision={revision} error={type(exc).__name__}:{exc}")
            raise


if __name__ == "__main__":
    raise SystemExit(main())
