#!/usr/bin/env python3
"""Prepare one FGB production episode with minimal audio processing.

Audio policy: preserve source character and dynamics. The only permitted audio
operations are a constant gain, sample-rate/channel-layout conversion required
by the live transport, and one AAC delivery encode. No EQ, de-essing,
compression, limiting, denoising, or dynamic loudness processing is allowed.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, tempfile, time
from pathlib import Path

PROFILE = "fgb-clean-static-v3"
TARGET_I = -16.0
PREENCODE_TP = -3.0
MAX_OUTPUT_TP = -1.5
TARGET_LRA = 11.0  # measurement parameter only; never applied dynamically
BITRATE_KBPS = 256


def run(cmd, capture=False, check=True):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if check and p.returncode:
        if capture:
            sys.stderr.write(p.stderr or "")
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p


def ffprobe(path):
    p = run(["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name,sample_rate,channels,bit_rate,width,height,r_frame_rate,pix_fmt",
             "-of", "json", str(path)], capture=True)
    d = json.loads(p.stdout)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return d, a, v


def measure(path):
    p = run(["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-v", "info",
             "-i", str(path), "-map", "0:a:0", "-vn",
             "-af", f"loudnorm=I={TARGET_I}:TP={PREENCODE_TP}:LRA={TARGET_LRA}:print_format=json",
             "-f", "null", "-"], capture=True)
    blocks = re.findall(r'\{\s*"input_i".*?\}', p.stderr or "", flags=re.S)
    if not blocks:
        raise RuntimeError(f"loudness measurement unavailable: {path}")
    d = json.loads(blocks[-1])
    return {"i_lufs": float(d["input_i"]), "tp_dbtp": float(d["input_tp"]), "lra_lu": float(d["input_lra"])}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def video_hash(path):
    p = run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path),
             "-map", "0:v:0", "-c:v", "copy", "-f", "hash", "-hash", "sha256", "-"], capture=True)
    return p.stdout.strip()


def video_signature(v):
    return "|".join(str(v.get(k, "")) for k in ("codec_name", "width", "height", "r_frame_rate", "pix_fmt"))


def encode(video_source, audio_source, temp_output, gain_db, copy_video):
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "warning",
           "-i", str(video_source), "-i", str(audio_source), "-map", "0:v:0", "-map", "1:a:0"]
    if copy_video:
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-vf", "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.0",
                "-b:v", "4000k", "-maxrate", "4000k", "-bufsize", "8000k", "-g", "60",
                "-keyint_min", "60", "-sc_threshold", "0", "-pix_fmt", "yuv420p", "-threads", "1"]
    cmd += ["-c:a", "aac", "-b:a", f"{BITRATE_KBPS}k", "-ar", "48000", "-ac", "2",
            "-af", f"volume={gain_db:.3f}dB,aresample=48000:first_pts=0",
            "-shortest", "-movflags", "+faststart", "-map_metadata", "-1", str(temp_output)]
    run(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-source", required=True)
    ap.add_argument("--audio-source", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--source-kind", required=True, choices=["original_master", "retained_pre_v2", "new_original"])
    args = ap.parse_args()

    video_source = Path(args.video_source)
    audio_source = Path(args.audio_source)
    output = Path(args.output)
    for p in (video_source, audio_source):
        if not p.is_file():
            raise SystemExit(f"missing source: {p}")
    output.parent.mkdir(parents=True, exist_ok=True)

    _, source_audio, _ = ffprobe(audio_source)
    if source_audio.get("codec_name") != "aac":
        print(f"NOTE=source_audio_codec_{source_audio.get('codec_name')}; clean delivery encode remains AAC")
    source_metrics = measure(audio_source)
    desired_gain = TARGET_I - source_metrics["i_lufs"]
    peak_safe_gain = PREENCODE_TP - source_metrics["tp_dbtp"]
    gain_db = min(desired_gain, peak_safe_gain)
    peak_limited = gain_db < desired_gain - 0.01

    _, _, video_stream = ffprobe(video_source)
    copy_video = video_signature(video_stream) == "h264|1280|720|30/1|yuv420p"
    source_video_hash = video_hash(video_source) if copy_video else None

    temp_output = output.with_name(output.name + ".partial.mp4")
    temp_marker = output.with_name(output.name + ".audio-profile.json.partial")
    for p in (temp_output, temp_marker):
        try: p.unlink()
        except FileNotFoundError: pass

    encode(video_source, audio_source, temp_output, gain_db, copy_video)
    output_metrics = measure(temp_output)
    # AAC/resampling may create small intersample overshoot. If necessary, lower
    # the single static gain and re-encode; never invoke a limiter/compressor.
    if output_metrics["tp_dbtp"] > MAX_OUTPUT_TP:
        adjustment = -2.0 - output_metrics["tp_dbtp"]
        gain_db += adjustment
        temp_output.unlink()
        encode(video_source, audio_source, temp_output, gain_db, copy_video)
        output_metrics = measure(temp_output)

    _, out_audio, out_video = ffprobe(temp_output)
    audio_sig = (out_audio.get("codec_name"), str(out_audio.get("sample_rate")), int(out_audio.get("channels", 0) or 0))
    if audio_sig != ("aac", "48000", 2):
        raise SystemExit(f"invalid output audio signature: {audio_sig}")
    if video_signature(out_video) != "h264|1280|720|30/1|yuv420p":
        raise SystemExit(f"invalid output video signature: {video_signature(out_video)}")
    if copy_video and video_hash(temp_output) != source_video_hash:
        raise SystemExit("video packet hash changed during audio-only remediation")
    if output_metrics["tp_dbtp"] > MAX_OUTPUT_TP:
        raise SystemExit(f"output true peak unsafe: {output_metrics['tp_dbtp']:.2f} dBTP")
    if abs(output_metrics["lra_lu"] - source_metrics["lra_lu"]) > 0.6:
        raise SystemExit(f"dynamic range changed unexpectedly: source LRA={source_metrics['lra_lu']:.2f}, output LRA={output_metrics['lra_lu']:.2f}")
    expected_i = source_metrics["i_lufs"] + gain_db
    if abs(output_metrics["i_lufs"] - expected_i) > 0.75:
        raise SystemExit(f"static-gain loudness mismatch: expected {expected_i:.2f}, got {output_metrics['i_lufs']:.2f}")

    marker = {
        "profile": PROFILE,
        "quality_verified": True,
        "processing_mode": "static_gain_only",
        "dynamic_processing": False,
        "processing_chain": ["constant_gain", "aresample_48000", "stereo_delivery", "aac_encode_256k"],
        "forbidden_processing_absent": ["equalizer", "deesser", "compressor", "limiter", "denoise", "dynamic_loudnorm"],
        "source_kind": args.source_kind,
        "source_path": str(audio_source),
        "source_sha256": sha256(audio_source),
        "source_audio_codec": source_audio.get("codec_name"),
        "source_sample_rate_hz": int(source_audio.get("sample_rate", 0) or 0),
        "source_channels": int(source_audio.get("channels", 0) or 0),
        "source_metrics": source_metrics,
        "target_i_lufs": TARGET_I,
        "preencode_peak_ceiling_dbtp": PREENCODE_TP,
        "max_output_tp_dbtp": MAX_OUTPUT_TP,
        "static_gain_db": round(gain_db, 3),
        "peak_limited": peak_limited,
        "output_metrics": output_metrics,
        "audio_codec": "aac",
        "audio_bitrate_kbps": BITRATE_KBPS,
        "sample_rate_hz": 48000,
        "channels": 2,
        "video_mode": "packet_copy" if copy_video else "offline_normalize",
        "created_at_epoch": int(time.time()),
    }
    marker["sha256"] = sha256(temp_output)
    temp_marker.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_output, output)
    os.replace(temp_marker, Path(str(output) + ".audio-profile.json"))
    print("PREPARED=" + str(output))
    print("PROFILE=" + PROFILE)
    print(f"SOURCE_I={source_metrics['i_lufs']:.2f}")
    print(f"SOURCE_TP={source_metrics['tp_dbtp']:.2f}")
    print(f"SOURCE_LRA={source_metrics['lra_lu']:.2f}")
    print(f"STATIC_GAIN_DB={gain_db:.3f}")
    print(f"OUTPUT_I={output_metrics['i_lufs']:.2f}")
    print(f"OUTPUT_TP={output_metrics['tp_dbtp']:.2f}")
    print(f"OUTPUT_LRA={output_metrics['lra_lu']:.2f}")
    print("VIDEO_MODE=" + marker["video_mode"])

if __name__ == "__main__":
    main()
