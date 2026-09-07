#!/usr/bin/env python3
import array
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

SRC = Path('/home/ubuntu/fgbears-upload/FGBears-Episode-01.mp4')
PROD = Path('/srv/fgbears-live/media/FGBears-Episode-01.mp4')
GAIN_DB = 3.12
SR = 48000
CH = 2


def run(cmd, check=True):
    p = subprocess.run(cmd, text=True, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{p.stderr[-2000:]}")
    return p


def probe(path):
    p = run(['ffprobe','-v','error','-select_streams','a:0','-show_entries','stream=codec_name,sample_rate,channels,bit_rate','-of','json',str(path)])
    return json.loads(p.stdout)['streams'][0]


def loudnorm_metrics(path):
    p = run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vn','-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json','-f','null','-'], check=False)
    blocks = re.findall(r'\{\s*"input_i".*?\}', p.stderr, re.S)
    if not blocks:
        return None
    d = json.loads(blocks[-1])
    return {'i_lufs':float(d['input_i']),'tp_dbtp':float(d['input_tp']),'lra_lu':float(d['input_lra']),'threshold_lufs':float(d['input_thresh'])}


def astats(path):
    p = run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vn','-af','astats=metadata=0:reset=0','-f','null','-'], check=False)
    text = p.stderr
    def last(label):
        ms = re.findall(rf'{re.escape(label)}:\s*([-+0-9.eE]+)', text)
        return float(ms[-1]) if ms else None
    return {
        'dc_offset': last('DC offset'),
        'peak_level_db': last('Peak level dB'),
        'rms_level_db': last('RMS level dB'),
        'rms_peak_db': last('RMS peak dB'),
        'rms_trough_db': last('RMS trough dB'),
        'crest_factor': last('Crest factor'),
        'flat_factor': last('Flat factor'),
        'peak_count': last('Peak count'),
    }


def make_pcm(path, out, source=False, seek=60, duration=15):
    af = f'volume={GAIN_DB}dB,aresample={SR}:resampler=soxr:precision=28' if source else f'aresample={SR}:resampler=soxr:precision=28'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(seek),'-t',str(duration),'-i',str(path),'-vn','-af',af,'-ac',str(CH),'-ar',str(SR),'-f','s16le',out])


def read_pcm(path):
    a = array.array('h')
    with open(path,'rb') as f:
        a.frombytes(f.read())
    if os.sys.byteorder != 'little':
        a.byteswap()
    return a


def envelope(samples, frames_per_bin=480):
    nframes = len(samples)//CH
    bins=[]
    for s in range(0,nframes,frames_per_bin):
        e=min(nframes,s+frames_per_bin)
        acc=0.0; n=0
        for i in range(s,e):
            l=samples[i*2]; r=samples[i*2+1]
            m=(l+r)*0.5
            acc += m*m; n += 1
        bins.append(math.sqrt(acc/n) if n else 0.0)
    mean=sum(bins)/len(bins) if bins else 0
    return [x-mean for x in bins]


def best_lag(a,b,max_lag=20):
    ea=envelope(a); eb=envelope(b)
    best=(None,-2.0)
    for lag in range(-max_lag,max_lag+1):
        xs=[]; ys=[]
        for i,x in enumerate(ea):
            j=i+lag
            if 0<=j<len(eb):
                xs.append(x); ys.append(eb[j])
        if len(xs)<20: continue
        num=sum(x*y for x,y in zip(xs,ys))
        den=math.sqrt(sum(x*x for x in xs)*sum(y*y for y in ys))
        c=num/den if den else 0
        if c>best[1]: best=(lag,c)
    return best


def waveform_compare(ref, test, lag_bins):
    shift=lag_bins*480*CH
    if shift>=0:
        r0=0; t0=shift
    else:
        r0=-shift; t0=0
    n=min(len(ref)-r0,len(test)-t0)
    n=min(n, SR*CH*8)
    if n<=0: return None
    # Compare after removing any tiny residual scalar level mismatch.
    dot=sum(float(ref[r0+i])*float(test[t0+i]) for i in range(n))
    rr=sum(float(ref[r0+i])**2 for i in range(n))
    tt=sum(float(test[t0+i])**2 for i in range(n))
    scale=dot/rr if rr else 1.0
    err=sum((test[t0+i]-scale*ref[r0+i])**2 for i in range(n))
    sig=sum((scale*ref[r0+i])**2 for i in range(n))
    corr=dot/math.sqrt(rr*tt) if rr and tt else 0.0
    snr=10*math.log10(sig/err) if err>0 and sig>0 else 99.0
    return {'lag_ms':lag_bins*10.0,'correlation':corr,'best_scale':scale,'residual_snr_db':snr,'compared_seconds':n/(SR*CH)}


def current_live_identity():
    # Reuse the proven passive comparison diagnostic if present on host.
    return None


def main():
    if not SRC.is_file() or not PROD.is_file():
        raise SystemExit('Episode 01 source or production file missing')
    result={
        'diagnostic':'episode01-quality-v1',
        'source_path':str(SRC),
        'production_path':str(PROD),
        'source_probe':probe(SRC),
        'production_probe':probe(PROD),
        'source_loudness':loudnorm_metrics(SRC),
        'production_loudness':loudnorm_metrics(PROD),
        'source_astats':astats(SRC),
        'production_astats':astats(PROD),
    }
    with tempfile.TemporaryDirectory(prefix='ep01-quality-') as td:
        ref=os.path.join(td,'ref.s16')
        tst=os.path.join(td,'prod.s16')
        make_pcm(SRC,ref,source=True)
        make_pcm(PROD,tst,source=False)
        a=read_pcm(ref); b=read_pcm(tst)
        lag,c=best_lag(a,b)
        result['envelope_best_lag_bins']=lag
        result['envelope_correlation']=c
        result['production_vs_source_reference']=waveform_compare(a,b,lag)
    marker=Path(str(PROD)+'.audio-profile.json')
    if marker.is_file():
        result['profile']=json.loads(marker.read_text())
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':
    main()
