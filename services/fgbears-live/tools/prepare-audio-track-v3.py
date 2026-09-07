#!/usr/bin/env python3
import argparse, hashlib, json, re, subprocess, time
from pathlib import Path

PROFILE="fgb-clean-static-v3"
TARGET_I=-16.0
PREENCODE_TP=-3.0
MAX_OUTPUT_TP=-1.5
TARGET_LRA=11.0
BITRATE_KBPS=256

def run(cmd, capture=False):
    p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        if capture: print(p.stderr, end="", file=__import__('sys').stderr)
        raise SystemExit(f"command failed ({p.returncode}): {' '.join(cmd)}")
    return p

def measure(path):
    p=run(["ffmpeg","-hide_banner","-nostdin","-nostats","-v","info","-i",str(path),"-map","0:a:0","-vn","-af",f"loudnorm=I={TARGET_I}:TP={PREENCODE_TP}:LRA={TARGET_LRA}:print_format=json","-f","null","-"],capture=True)
    blocks=re.findall(r'\{\s*"input_i".*?\}',p.stderr or "",re.S)
    if not blocks: raise SystemExit(f"unable to measure {path}")
    d=json.loads(blocks[-1])
    return {"i_lufs":float(d["input_i"]),"tp_dbtp":float(d["input_tp"]),"lra_lu":float(d["input_lra"])}

def probe_audio(path):
    p=run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_name,sample_rate,channels,bit_rate","-of","json",str(path)],capture=True)
    return json.loads(p.stdout)["streams"][0]

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def encode(src,out,gain):
    run(["ffmpeg","-hide_banner","-nostdin","-y","-loglevel","warning","-i",str(src),"-map","0:a:0","-vn","-c:a","aac","-b:a",f"{BITRATE_KBPS}k","-ar","48000","-ac","2","-af",f"volume={gain:.3f}dB,aresample=48000:first_pts=0","-movflags","+faststart",str(out)])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--source-kind",required=True,choices=["original_master","retained_pre_v2","new_original"])
    ap.add_argument("--source-label",required=True)
    ap.add_argument("--source-file-sha256",required=True)
    a=ap.parse_args()
    src=Path(a.source); out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    sinfo=probe_audio(src); sm=measure(src)
    desired=TARGET_I-sm["i_lufs"]
    safe=PREENCODE_TP-sm["tp_dbtp"]
    gain=min(desired,safe)
    peak_limited=gain < desired-0.01
    tmp=out.with_name(out.name+".partial.m4a")
    tmp.unlink(missing_ok=True)
    encode(src,tmp,gain)
    om=measure(tmp)
    if om["tp_dbtp"]>MAX_OUTPUT_TP:
        gain += (-2.0-om["tp_dbtp"])
        tmp.unlink()
        encode(src,tmp,gain)
        om=measure(tmp)
    oinfo=probe_audio(tmp)
    sig=(oinfo.get("codec_name"),str(oinfo.get("sample_rate")),int(oinfo.get("channels",0)))
    if sig != ("aac","48000",2): raise SystemExit(f"bad output signature {sig}")
    if om["tp_dbtp"]>MAX_OUTPUT_TP: raise SystemExit(f"unsafe output peak {om['tp_dbtp']}")
    if abs(om["lra_lu"]-sm["lra_lu"])>0.6: raise SystemExit(f"LRA changed source={sm['lra_lu']} output={om['lra_lu']}")
    if abs(om["i_lufs"]-(sm["i_lufs"]+gain))>0.75: raise SystemExit("static gain verification failed")
    track_sha=sha(tmp)
    marker={
      "profile":PROFILE,"quality_verified":True,"processing_mode":"static_gain_only","dynamic_processing":False,
      "processing_chain":["constant_gain","aresample_48000","stereo_delivery","aac_encode_256k"],
      "forbidden_processing_absent":["equalizer","deesser","compressor","limiter","denoise","dynamic_loudnorm"],
      "source_kind":a.source_kind,"source_path":a.source_label,"source_sha256":a.source_file_sha256,
      "source_audio_codec":sinfo.get("codec_name"),"source_sample_rate_hz":int(sinfo.get("sample_rate",0)),"source_channels":int(sinfo.get("channels",0)),
      "source_metrics":sm,"target_i_lufs":TARGET_I,"preencode_peak_ceiling_dbtp":PREENCODE_TP,"max_output_tp_dbtp":MAX_OUTPUT_TP,
      "static_gain_db":round(gain,3),"peak_limited":peak_limited,"output_metrics":om,
      "audio_codec":"aac","audio_bitrate_kbps":BITRATE_KBPS,"sample_rate_hz":48000,"channels":2,
      "audio_track_sha256":track_sha,"created_at_epoch":int(time.time())
    }
    out_marker=Path(str(out)+".audio-profile.json")
    out_marker.write_text(json.dumps(marker,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    tmp.replace(out)
    print(f"TRACK_PREPARED={out.name} SOURCE_I={sm['i_lufs']:.2f} SOURCE_TP={sm['tp_dbtp']:.2f} SOURCE_LRA={sm['lra_lu']:.2f} GAIN={gain:.3f} OUTPUT_I={om['i_lufs']:.2f} OUTPUT_TP={om['tp_dbtp']:.2f} OUTPUT_LRA={om['lra_lu']:.2f}")
if __name__=="__main__": main()
