#!/usr/bin/env python3
import glob, json, os, re, subprocess

ORIG_DIR = "/home/ubuntu/fgbears-upload"
PROD_DIR = "/srv/fgbears-live/media"

def out(cmd):
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()

def probe(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration:stream=index,codec_type,codec_name,sample_rate,channels,bit_rate,width,height,r_frame_rate,pix_fmt",
        "-of", "json", path,
    ]
    try:
        d = json.loads(out(cmd))
    except Exception as e:
        return {"error": str(e)}
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": round(float(d.get("format", {}).get("duration", 0) or 0), 3),
        "audio": {k: a.get(k) for k in ("codec_name", "sample_rate", "channels", "bit_rate")},
        "video": {k: v.get(k) for k in ("codec_name", "width", "height", "r_frame_rate", "pix_fmt")},
        "size": os.path.getsize(path),
    }

def episodes(root):
    result = {}
    for path in glob.glob(os.path.join(root, "FGBears-Episode-*.mp4")):
        m = re.search(r"Episode-(\d+)\.mp4$", path)
        if m:
            result[int(m.group(1))] = path
    return result

originals = episodes(ORIG_DIR)
production = episodes(PROD_DIR)
all_eps = sorted(set(originals) | set(production))
print(f"ORIGINAL_COUNT={len(originals)}")
print(f"PRODUCTION_COUNT={len(production)}")
print("EPISODES=" + ",".join(map(str, all_eps)))
print("MISSING_ORIGINAL=" + ",".join(map(str, sorted(set(production) - set(originals)))))
print("MISSING_PRODUCTION=" + ",".join(map(str, sorted(set(originals) - set(production)))))
for n in all_eps:
    rec = {
        "episode": n,
        "original": probe(originals[n]) if n in originals else None,
        "production": probe(production[n]) if n in production else None,
    }
    print("EP=" + json.dumps(rec, separators=(",", ":")))

master_pid = int(out(["systemctl", "show", "-p", "MainPID", "--value", "fgbears-live.service"]) or 0)
current = []
if master_pid:
    try:
        ffmpeg_pid = int(out(["pgrep", "-P", str(master_pid), "-x", "ffmpeg"]).splitlines()[0])
        for fd in glob.glob(f"/proc/{ffmpeg_pid}/fd/*"):
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith(PROD_DIR + "/FGBears-Episode-") and target.endswith(".mp4"):
                current.append(target)
    except Exception:
        pass
print("CURRENT_FILES=" + json.dumps(sorted(set(current))))
print("MASTER_PID=" + str(master_pid))
youtube_pid = int(out(["systemctl", "show", "-p", "MainPID", "--value", "fgbears-youtube-copy-relay.service"]) or 0)
print("YOUTUBE_PID=" + str(youtube_pid))
