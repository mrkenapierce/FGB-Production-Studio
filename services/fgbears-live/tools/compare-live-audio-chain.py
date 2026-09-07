#!/usr/bin/env python3
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


def run(args, check=True, capture=True):
    p = subprocess.run(args, text=True, capture_output=capture)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(args)}\n{p.stderr[-1200:] if p.stderr else ''}")
    return p


def out(args):
    return run(args).stdout.strip()


def current_media(master_ffmpeg_pid):
    p = run([
        "sudo", "find", f"/proc/{master_ffmpeg_pid}/fd", "-maxdepth", "1", "-type", "l", "-printf", "%l\\n"
    ], check=False)
    matches = re.findall(r"^/srv/fgbears-live/media/FGBears-Episode-\d+\.mp4$", p.stdout, re.M)
    return matches[0] if matches else ""


def audio_props(path):
    return out([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate",
        "-of", "csv=p=0", path,
    ])


def parse_pcap_to_udp_payload(pcap_path, ts_path, port):
    data = Path(pcap_path).read_bytes()
    if len(data) < 24:
        raise RuntimeError("pcap too small")
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise RuntimeError(f"unknown pcap magic {magic.hex()}")
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    pos = 24
    chunks = []
    packets = 0
    while pos + 16 <= len(data):
        _, _, incl_len, _ = struct.unpack(endian + "IIII", data[pos:pos+16])
        pos += 16
        pkt = data[pos:pos+incl_len]
        pos += incl_len
        if linktype == 1:  # Ethernet
            if len(pkt) < 34 or pkt[12:14] != b"\x08\x00":
                continue
            off = 14
        elif linktype == 113:  # Linux cooked v1
            if len(pkt) < 36 or pkt[14:16] != b"\x08\x00":
                continue
            off = 16
        elif linktype == 276:  # Linux cooked v2
            if len(pkt) < 40 or pkt[0:2] != b"\x08\x00":
                continue
            off = 20
        elif linktype in (101, 12):  # raw IP
            off = 0
        else:
            continue
        if len(pkt) < off + 28 or (pkt[off] >> 4) != 4 or pkt[off + 9] != 17:
            continue
        ihl = (pkt[off] & 15) * 4
        u = off + ihl
        if len(pkt) < u + 8:
            continue
        _, dport, ulen, _ = struct.unpack("!HHHH", pkt[u:u+8])
        if dport != port:
            continue
        payload = pkt[u+8:u+ulen]
        if payload:
            chunks.append(payload)
            packets += 1
    blob = b"".join(chunks)
    Path(ts_path).write_bytes(blob)
    return linktype, packets, len(blob)


def adts_hashes(path):
    b = Path(path).read_bytes()
    frames = []
    i = 0
    while i + 7 <= len(b):
        if b[i] != 0xFF or (b[i+1] & 0xF6) != 0xF0:
            i += 1
            continue
        header = 7 if (b[i+1] & 1) else 9
        length = ((b[i+3] & 3) << 11) | (b[i+4] << 3) | ((b[i+5] & 0xE0) >> 5)
        if length < header or i + length > len(b):
            break
        frames.append(hashlib.sha256(b[i+header:i+length]).digest())
        i += length
    return frames


def match_frames(prod_frames, live_frames, sample_rate):
    if len(live_frames) < 20:
        return None
    skip = min(5, max(0, len(live_frames)//20))
    window = min(50, len(live_frames) - skip)
    needle = live_frames[skip:skip+window]
    found = -1
    for i, h in enumerate(prod_frames):
        if h == needle[0] and prod_frames[i:i+window] == needle:
            found = i
            break
    if found < 0:
        return None
    start = found - skip
    matched = 0
    compared = 0
    for j, h in enumerate(live_frames):
        i = start + j
        if 0 <= i < len(prod_frames):
            compared += 1
            matched += int(prod_frames[i] == h)
    offset = max(0, start) * 1024.0 / sample_rate
    pct = 100.0 * matched / compared if compared else 0.0
    return offset, matched, compared, pct


def loudness(path, seek, duration=8):
    args = [
        "ffmpeg", "-hide_banner", "-nostats", "-ss", f"{seek:.3f}", "-t", str(duration),
        "-i", path, "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"
    ]
    p = run(args, check=False)
    text = p.stderr or ""
    blocks = re.findall(r'\{\s*"input_i".*?\}', text, re.S)
    if not blocks:
        return None
    d = json.loads(blocks[-1])
    return {
        "i_lufs": float(d["input_i"]),
        "tp_dbtp": float(d["input_tp"]),
        "lra_lu": float(d["input_lra"]),
        "threshold_lufs": float(d["input_thresh"]),
    }


def main():
    result = {"diagnostic": "fgb-live-audio-chain-v1"}
    with tempfile.TemporaryDirectory(prefix="fgb-audio-chain-") as td:
        master_main = out(["systemctl", "show", "-p", "MainPID", "--value", "fgbears-live.service"])
        master_ffmpeg = out(["bash", "-lc", f"pgrep -P {master_main} -x ffmpeg | head -n1"])
        prod = current_media(master_ffmpeg)
        if not prod:
            raise RuntimeError("could not resolve current production media")
        ep = re.search(r"Episode-(\d+)\.mp4$", prod).group(1)
        orig = f"/home/ubuntu/fgbears-upload/FGBears-Episode-{ep}.mp4"
        result.update({
            "episode": ep,
            "production_path": prod,
            "original_path": orig,
            "original_present": Path(orig).is_file() and Path(orig).stat().st_size > 0,
            "production_audio": audio_props(prod),
        })
        if result["original_present"]:
            result["original_audio"] = audio_props(orig)

        yt_main = out(["systemctl", "show", "-p", "MainPID", "--value", "fgbears-youtube-copy-relay.service"])
        cmd_bytes = Path(f"/proc/{yt_main}/cmdline").read_bytes()
        cmd = cmd_bytes.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        safe_cmd = re.sub(r"(rtmps?://[^/]+/live2/)\S+", r"\1[REDACTED]", cmd)
        m = re.search(r"udp://(?:127\.0\.0\.1|localhost):(\d+)", cmd)
        if not m:
            raise RuntimeError("could not resolve YouTube relay UDP input")
        port = int(m.group(1))
        result["youtube_relay_active"] = out(["systemctl", "is-active", "fgbears-youtube-copy-relay.service"])
        result["youtube_input_port"] = port
        result["youtube_relay_cmd_redacted"] = safe_cmd
        result["youtube_copy_mode"] = bool(re.search(r"(?:^|\s)-c\s+copy(?:\s|$)", cmd))

        pcap = os.path.join(td, "in.pcap")
        ts = os.path.join(td, "in.ts")
        run(["sudo", "timeout", "12", "tcpdump", "-q", "-i", "lo", "-s", "0", "-U", "-w", pcap, f"udp dst port {port}"], check=False)
        run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", pcap], check=False)
        after = current_media(master_ffmpeg)
        result["segment_stable"] = after == prod
        if after != prod:
            result["result"] = "capture_crossed_episode_boundary"
            print(json.dumps(result, sort_keys=True))
            return

        linktype, packet_count, byte_count = parse_pcap_to_udp_payload(pcap, ts, port)
        result.update({"pcap_linktype": linktype, "capture_packets": packet_count, "capture_bytes": byte_count})
        if byte_count < 188 * 20:
            result["result"] = "insufficient_capture"
            print(json.dumps(result, sort_keys=True))
            return

        live_aac = os.path.join(td, "live.aac")
        prod_aac = os.path.join(td, "prod.aac")
        run(["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-y", "-probesize", "10M", "-analyzeduration", "10M", "-i", ts, "-map", "0:a:0", "-c:a", "copy", "-f", "adts", live_aac])
        run(["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-y", "-i", prod, "-map", "0:a:0", "-c:a", "copy", "-f", "adts", prod_aac])
        sr = int(out(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "default=nw=1:nk=1", prod]))
        pframes = adts_hashes(prod_aac)
        lframes = adts_hashes(live_aac)
        result["production_aac_frames"] = len(pframes)
        result["live_aac_frames"] = len(lframes)
        match = match_frames(pframes, lframes, sr)
        if not match:
            result["aac_packet_identity"] = False
            result["result"] = "live_audio_differs_before_youtube"
            print(json.dumps(result, sort_keys=True))
            return
        offset, matched, compared, pct = match
        result.update({
            "aac_packet_identity": True,
            "identity_pct": round(pct, 4),
            "matched_frames": matched,
            "compared_frames": compared,
            "episode_offset_sec": round(offset, 3),
        })

        seek = offset + 1.0
        result["production_same_section"] = loudness(prod, seek)
        if result["original_present"]:
            result["original_same_section"] = loudness(orig, seek)
        result["youtube_input_same_section"] = loudness(ts, 1.0)

        marker_path = prod + ".audio-profile.json"
        if Path(marker_path).is_file():
            marker = json.loads(Path(marker_path).read_text())
            result["mastering_profile"] = {
                k: marker.get(k) for k in (
                    "profile", "mastered", "mastering_chain", "target_i_lufs", "target_tp_dbtp",
                    "measured_i_lufs", "measured_tp_dbtp", "sample_rate_hz", "audio_bitrate_kbps"
                )
            }
        result["result"] = "complete"
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
