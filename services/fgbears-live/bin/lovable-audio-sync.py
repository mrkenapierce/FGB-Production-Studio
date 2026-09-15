#!/usr/bin/env python3
"""Apply Lovable's active FGB audio intent to the shared Oracle master.

One-shot by design. A systemd timer invokes this every 30 seconds.
No network I/O occurs inside the FFmpeg/media loop.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

ENDPOINTS = (
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
    "https://grant-gems-today.lovable.app/api/public/fgbears/stream-routing",
)
MASTER_SERVICE = "fgbears-live.service"
AUDIO_FILE = Path("/srv/fgbears-live/audio/fgb-music-loop.m4a")
STATE_FILE = Path("/srv/fgbears-live/runtime/lovable-audio-sync.json")
LOCK_FILE = Path("/run/fgbears-lovable-audio-sync.lock")
QUARANTINE = Path("/srv/fgbears-live/quarantine/lovable-audio-sync")
PROGRESS_FILE = Path("/srv/fgbears-live/logs/ffmpeg-progress.log")
MAX_SOURCE_BYTES = 50 * 1024 * 1024
HTTP_TIMEOUT = 25


def run(cmd: list[str], *, check: bool = True, capture: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=capture, timeout=timeout)


def log(message: str) -> None:
    print(f"FGB_AUDIO_SYNC {message}", flush=True)


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_state(payload: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def fetch_contract() -> tuple[str, dict]:
    last_error = ""
    for endpoint in ENDPOINTS:
        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": "FGB-Oracle-Audio-Sync/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))
            audio = data.get("presentation", {}).get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("revision"), int):
                return endpoint, audio
            last_error = f"{endpoint}: missing presentation.audio"
        except Exception as exc:
            last_error = f"{endpoint}: {type(exc).__name__}: {exc}"
    raise RuntimeError(f"No valid Lovable audio contract. Last error: {last_error}")


def download(url: str, destination: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "FGB-Oracle-Audio-Sync/1.0"})
    total = 0
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response, destination.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise RuntimeError("Audio source exceeded the 50 MB Lovable ceiling.")
            out.write(chunk)
    if total <= 0:
        raise RuntimeError("Downloaded audio source is empty.")


def ffprobe_audio(path: Path) -> dict:
    cp = run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", str(path)])
    data = json.loads(cp.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("No audio stream found in selected asset.")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Selected audio has no positive duration.")
    return {"codec": str(streams[0].get("codec_name") or ""), "rate": int(streams[0].get("sample_rate") or 0), "channels": int(streams[0].get("channels") or 0), "duration": duration}


def build_canonical(source: Path | None, destination: Path, gain_db: float, muted: bool) -> dict:
    if muted:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2", "-c:a", "aac", "-b:a", "256k", str(destination)]
    else:
        assert source is not None
        source_meta = ffprobe_audio(source)
        if source_meta["codec"] == "aac" and source_meta["channels"] == 2 and abs(gain_db) < 0.05:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-map", "0:a:0", "-c:a", "copy", str(destination)]
        else:
            af = f"volume={gain_db:.1f}dB,aresample=48000"
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "256k", str(destination)]
    run(cmd, timeout=600)
    meta = ffprobe_audio(destination)
    if meta["codec"] != "aac" or meta["channels"] != 2:
        raise RuntimeError(f"Canonical audio validation failed: {meta}")
    return meta


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def service_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def running_destination_units() -> list[str]:
    cp = run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager", "fgbears-*"], check=False)
    units: list[str] = []
    for line in cp.stdout.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if unit == MASTER_SERVICE or unit == "fgbears-lovable-audio-sync.service":
            continue
        if any(token in unit for token in ("youtube", "rumble", "facebook", "relay", "uplink")):
            units.append(unit)
    return sorted(set(units))


def master_ffmpeg_pid() -> int:
    cp = run(["systemctl", "show", "-p", "MainPID", "--value", MASTER_SERVICE])
    main = int((cp.stdout or "0").strip() or "0")
    if main <= 0:
        raise RuntimeError("Master service has no MainPID.")
    child = run(["pgrep", "-P", str(main), "-x", "ffmpeg"], check=False)
    pids = [p for p in child.stdout.split() if p.isdigit()]
    if not pids:
        raise RuntimeError("Master service has no FFmpeg child.")
    return int(pids[0])


def verify_master_uses_audio() -> None:
    import shlex
    pid = master_ffmpeg_pid()
    cp = run(["bash", "-lc", f"ls -l /proc/{pid}/fd 2>/dev/null | grep -F -- {shlex.quote(str(AUDIO_FILE))}"], check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"Master FFmpeg is not reading {AUDIO_FILE}.")


def progress_value() -> int:
    if not PROGRESS_FILE.exists():
        return 0
    value = 0
    for line in PROGRESS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("out_time_ms="):
            try:
                value = int(line.split("=", 1)[1])
            except ValueError:
                pass
    return value


def restart_and_verify(previous_destinations: list[str]) -> None:
    run(["systemctl", "restart", MASTER_SERVICE])
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
        raise RuntimeError(f"Master did not reopen selected audio: {last}")
    before = progress_value()
    time.sleep(7)
    after = progress_value()
    if before <= 0 or after <= before:
        raise RuntimeError(f"Program clock did not advance after audio switch ({before} -> {after}).")
    deadline = time.time() + 30
    missing: list[str] = []
    while time.time() < deadline:
        missing = [u for u in previous_destinations if not service_active(u)]
        if not missing:
            return
        time.sleep(2)
    raise RuntimeError("Previously active destination service(s) stopped: " + ", ".join(missing))


def _uid(name: str) -> int:
    import pwd
    return pwd.getpwnam(name).pw_uid


def _gid(name: str) -> int:
    import grp
    return grp.getgrnam(name).gr_gid


def promote(canonical: Path, audio: dict, endpoint: str, meta: dict) -> None:
    AUDIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    previous_destinations = running_destination_units()
    revision = int(audio["revision"])
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup_dir = QUARANTINE / f"{stamp}-rev{revision}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / AUDIO_FILE.name
    had_old = AUDIO_FILE.exists()
    if had_old:
        shutil.copy2(AUDIO_FILE, backup)
    staged = AUDIO_FILE.with_suffix(".new")
    shutil.copy2(canonical, staged)
    os.chown(staged, _uid("fgbears"), _gid("fgbears"))
    os.chmod(staged, 0o644)
    os.replace(staged, AUDIO_FILE)
    try:
        restart_and_verify(previous_destinations)
    except Exception:
        log("apply_failed; rolling back previous audio")
        if had_old and backup.exists():
            rollback = AUDIO_FILE.with_suffix(".rollback")
            shutil.copy2(backup, rollback)
            os.chown(rollback, _uid("fgbears"), _gid("fgbears"))
            os.chmod(rollback, 0o644)
            os.replace(rollback, AUDIO_FILE)
            run(["systemctl", "restart", MASTER_SERVICE], check=False)
        raise
    write_state({"appliedRevision": revision, "activeTrackId": audio.get("activeTrackId"), "activeTrackName": audio.get("activeTrackName"), "mode": audio.get("mode"), "enabled": bool(audio.get("enabled")), "loop": bool(audio.get("loop", True)), "volumeGainDb": float(audio.get("volumeGainDb") or 0), "canonicalSha256": sha256(AUDIO_FILE), "canonical": meta, "controlEndpoint": endpoint, "appliedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "destinationsObserved": previous_destinations, "rollbackBackup": str(backup) if had_old else None, "status": "applied"})


def main() -> int:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("already_running")
            return 0
        endpoint, audio = fetch_contract()
        revision = int(audio["revision"])
        previous = read_state()
        if int(previous.get("appliedRevision", -1)) == revision:
            log(f"no_change revision={revision}")
            return 0
        if audio.get("mode") == "track" and audio.get("enabled") is True:
            asset = audio.get("assetUrl")
            if not isinstance(asset, str) or not asset:
                raise RuntimeError("Active audio track has no assetUrl.")
            if audio.get("loop") is not True:
                raise RuntimeError("Oracle master currently requires loop=true; retaining current audio.")
            asset_url = urllib.parse.urljoin(endpoint, asset)
            gain = float(audio.get("volumeGainDb") or 0)
            with tempfile.TemporaryDirectory(prefix="fgb-audio-sync-") as td:
                source = Path(td) / "source"
                canonical = Path(td) / "canonical.m4a"
                download(asset_url, source)
                source_meta = ffprobe_audio(source)
                meta = build_canonical(source, canonical, gain, muted=False)
                log(f"candidate revision={revision} track={audio.get('activeTrackName')!r} source={source_meta['codec']}/{source_meta['rate']}Hz/{source_meta['channels']}ch")
                promote(canonical, audio, endpoint, meta)
        else:
            with tempfile.TemporaryDirectory(prefix="fgb-audio-sync-") as td:
                canonical = Path(td) / "silence.m4a"
                meta = build_canonical(None, canonical, 0, muted=True)
                log(f"candidate revision={revision} mode=muted")
                promote(canonical, audio, endpoint, meta)
        log(f"applied revision={revision} all_active_destinations_preserved")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"error={type(exc).__name__}:{exc}")
        raise
