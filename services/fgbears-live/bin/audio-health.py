#!/usr/bin/env python3
"""Objective health check for the exact YouTube-bound FGB audio transport."""
from __future__ import annotations

import argparse
import array
import csv
import json
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SAMPLE_RATE = 48000
PEAK_LIMIT_DBFS = -1.0
CLIP_RATIO_LIMIT = 0.0001
SILENCE_RMS_DBFS = -55.0
SILENCE_NEARZERO_RATIO = 0.95
CHANNEL_IMBALANCE_DB = 6.0
DC_LIMIT = 0.02
PTS_GAP_SECONDS = 0.08


def channel_metrics(ch: array.array) -> dict[str, float]:
    if not ch:
        return {"peak_dbfs": -120.0, "rms_dbfs": -120.0, "clip_ratio": 0.0, "nearzero_ratio": 1.0, "dc": 0.0}
    peak = max(abs(value) for value in ch)
    rms = math.sqrt(sum(float(value) * value for value in ch) / len(ch))
    mean = sum(ch) / len(ch)
    return {
        "peak_dbfs": 20.0 * math.log10(max(peak, 1) / 32768.0),
        "rms_dbfs": 20.0 * math.log10(max(rms, 1e-9) / 32768.0),
        "clip_ratio": sum(abs(value) >= 32760 for value in ch) / len(ch),
        "nearzero_ratio": sum(abs(value) <= 8 for value in ch) / len(ch),
        "dc": mean / 32768.0,
    }


def analyze_pcm(raw: bytes) -> tuple[dict[str, float], list[str]]:
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    left = samples[0::2]
    right = samples[1::2]
    count = min(len(left), len(right))
    left, right = left[:count], right[:count]
    if count < SAMPLE_RATE:
        raise RuntimeError("decoded audio sample is shorter than one second")

    lm = channel_metrics(left)
    rm = channel_metrics(right)
    l2 = sum(float(value) * value for value in left)
    r2 = sum(float(value) * value for value in right)
    dot = sum(float(lval) * rval for lval, rval in zip(left, right))
    correlation = dot / math.sqrt(max(l2 * r2, 1.0))
    metrics = {
        "decoded_audio_seconds": count / SAMPLE_RATE,
        "left_peak_dbfs": lm["peak_dbfs"],
        "right_peak_dbfs": rm["peak_dbfs"],
        "left_rms_dbfs": lm["rms_dbfs"],
        "right_rms_dbfs": rm["rms_dbfs"],
        "channel_rms_difference_db": abs(lm["rms_dbfs"] - rm["rms_dbfs"]),
        "left_clip_ratio": lm["clip_ratio"],
        "right_clip_ratio": rm["clip_ratio"],
        "left_nearzero_ratio": lm["nearzero_ratio"],
        "right_nearzero_ratio": rm["nearzero_ratio"],
        "left_dc_fraction": lm["dc"],
        "right_dc_fraction": rm["dc"],
        "lr_correlation": correlation,
    }
    warnings: list[str] = []
    if max(lm["peak_dbfs"], rm["peak_dbfs"]) > PEAK_LIMIT_DBFS:
        warnings.append("PEAK_TOO_CLOSE_TO_0_DBFS")
    if max(lm["clip_ratio"], rm["clip_ratio"]) > CLIP_RATIO_LIMIT:
        warnings.append("CLIPPING")
    if max(lm["rms_dbfs"], rm["rms_dbfs"]) < SILENCE_RMS_DBFS and min(lm["nearzero_ratio"], rm["nearzero_ratio"]) > SILENCE_NEARZERO_RATIO:
        warnings.append("NEAR_SILENCE")
    if metrics["channel_rms_difference_db"] > CHANNEL_IMBALANCE_DB:
        warnings.append("CHANNEL_IMBALANCE")
    if max(abs(lm["dc"]), abs(rm["dc"])) > DC_LIMIT:
        warnings.append("DC_OFFSET")
    return metrics, warnings


def analyze_packet_csv(path: Path) -> tuple[dict[str, float | int], list[str]]:
    pts: list[float] = []
    durations: list[float] = []
    with path.open(newline="") as handle:
        for row in csv.reader(handle):
            numbers: list[float] = []
            for item in row:
                try:
                    numbers.append(float(item))
                except ValueError:
                    continue
            if numbers:
                pts.append(numbers[0])
                durations.append(numbers[1] if len(numbers) > 1 else 0.021333)
    regressions = 0
    gaps: list[float] = []
    for index in range(1, len(pts)):
        delta = pts[index] - pts[index - 1]
        expected = durations[index - 1] if index - 1 < len(durations) else 0.021333
        if delta < -0.001:
            regressions += 1
        if delta > max(PTS_GAP_SECONDS, expected * 3.0):
            gaps.append(delta)
    metrics: dict[str, float | int] = {
        "audio_pts_regressions": regressions,
        "audio_large_pts_gaps": len(gaps),
        "largest_audio_pts_gap_seconds": max(gaps) if gaps else 0.0,
    }
    warnings: list[str] = []
    if regressions:
        warnings.append("PTS_REGRESSION")
    if gaps:
        warnings.append("PTS_GAPS")
    return metrics, warnings


def capture_loopback(port: int, seconds: float, destination: Path) -> tuple[int, int]:
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    sock.bind(("lo", 0))
    sock.settimeout(0.5)
    deadline = time.monotonic() + seconds
    accepted = 0
    duplicates = 0
    last: bytes | None = None
    with destination.open("wb") as output:
        while time.monotonic() < deadline:
            try:
                frame, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            ip_offset = None
            for offset in (14, 16, 0):
                if len(frame) > offset + 28 and frame[offset] >> 4 == 4:
                    ip_offset = offset
                    break
            if ip_offset is None:
                continue
            ihl = (frame[ip_offset] & 0x0F) * 4
            if len(frame) < ip_offset + ihl + 8 or frame[ip_offset + 9] != 17:
                continue
            udp = ip_offset + ihl
            _source, destination_port, length = struct.unpack("!HHH", frame[udp : udp + 6])
            if destination_port != port:
                continue
            payload = frame[udp + 8 : udp + length]
            if len(payload) < 188 or payload[0] != 0x47 or len(payload) % 188:
                continue
            # Linux loopback exposes each packet twice. Drop only the immediate
            # identical copy so repeated but legitimate MPEG-TS packets survive.
            if payload == last:
                duplicates += 1
                continue
            last = payload
            output.write(payload)
            accepted += 1
    return accepted, duplicates


def run_checked(args: list[str], *, stdout=None) -> None:
    subprocess.run(args, check=True, stdout=stdout, stderr=subprocess.DEVNULL)


def read_udp_port(env_path: Path) -> int:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        prefix = "YOUTUBE_LOCAL_UDP_URL=udp://127.0.0.1:"
        if line.startswith(prefix):
            return int(line[len(prefix) :].split("?", 1)[0])
    return 1939


def self_test() -> None:
    healthy = array.array("h")
    hot = array.array("h")
    silent = array.array("h")
    for index in range(SAMPLE_RATE):
        healthy_value = int(12000 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE))
        hot_value = int(32767 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE))
        healthy.extend((healthy_value, healthy_value))
        hot.extend((hot_value, hot_value))
        silent.extend((0, 0))
    _, healthy_warnings = analyze_pcm(healthy.tobytes())
    _, hot_warnings = analyze_pcm(hot.tobytes())
    _, silent_warnings = analyze_pcm(silent.tobytes())
    assert "PEAK_TOO_CLOSE_TO_0_DBFS" not in healthy_warnings
    assert "PEAK_TOO_CLOSE_TO_0_DBFS" in hot_warnings
    assert "NEAR_SILENCE" in silent_warnings
    print("audio_health_self_test=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-seconds", type=float, default=8.0)
    parser.add_argument("--env-file", default="/etc/fgbears-live/stream.env")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if os.geteuid() != 0:
        print("OVERALL_STATUS=FAIL")
        print("REASON=ROOT_REQUIRED_FOR_LOOPBACK_CAPTURE")
        return 2

    port = read_udp_port(Path(args.env_file))
    with tempfile.TemporaryDirectory(prefix="fgb-audio-health-") as temp_dir:
        root = Path(temp_dir)
        capture = root / "sample.ts"
        pcm = root / "sample.pcm"
        packets = root / "audio-packets.csv"
        accepted, duplicates = capture_loopback(port, args.capture_seconds, capture)
        if accepted < 100:
            print("OVERALL_STATUS=FAIL")
            print("REASON=INSUFFICIENT_YOUTUBE_BOUND_PACKETS")
            print(f"captured_udp_packets={accepted}")
            return 3

        probe = subprocess.run(
            ["ffprobe", "-v", "fatal", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,channels,channel_layout", "-of", "json", str(capture)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        streams = json.loads(probe.stdout).get("streams") or []
        if not streams:
            print("OVERALL_STATUS=FAIL")
            print("REASON=AUDIO_STREAM_MISSING")
            return 4
        stream = streams[0]
        format_warnings: list[str] = []
        if stream.get("codec_name") != "aac":
            format_warnings.append("AUDIO_CODEC_NOT_AAC")
        if str(stream.get("sample_rate")) != "48000":
            format_warnings.append("AUDIO_SAMPLE_RATE_NOT_48KHZ")
        if int(stream.get("channels") or 0) != 2:
            format_warnings.append("AUDIO_NOT_STEREO")

        with packets.open("wb") as packet_output:
            run_checked(["ffprobe", "-v", "fatal", "-select_streams", "a:0", "-show_packets", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", str(capture)], stdout=packet_output)
        with pcm.open("wb") as pcm_output:
            run_checked(["ffmpeg", "-hide_banner", "-v", "fatal", "-i", str(capture), "-vn", "-map", "0:a:0", "-ac", "2", "-ar", "48000", "-f", "s16le", "-"], stdout=pcm_output)

        signal_metrics, signal_warnings = analyze_pcm(pcm.read_bytes())
        timing_metrics, timing_warnings = analyze_packet_csv(packets)
        warnings = format_warnings + signal_warnings + timing_warnings
        print(f"captured_udp_packets={accepted}")
        print(f"deduplicated_loopback_packets={duplicates}")
        print(f"audio_codec={stream.get('codec_name', '')}")
        print(f"audio_sample_rate={stream.get('sample_rate', '')}")
        print(f"audio_channels={stream.get('channels', '')}")
        for key, value in {**signal_metrics, **timing_metrics}.items():
            if isinstance(value, float):
                print(f"{key}={value:.8f}")
            else:
                print(f"{key}={value}")
        print("AUDIO_WARNINGS=" + (",".join(warnings) if warnings else "NONE"))
        print("OVERALL_STATUS=" + ("FAIL" if warnings else "OK"))
        return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
