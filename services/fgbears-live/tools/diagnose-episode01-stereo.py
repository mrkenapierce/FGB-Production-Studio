#!/usr/bin/env python3
import array, math, subprocess, os
SRC='/home/ubuntu/fgbears-upload/FGBears-Episode-01.mp4'
PCM='/tmp/ep01-stereo.s16'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss','60','-t','60','-i',SRC,'-vn','-ac','2','-ar','48000','-f','s16le',PCM],check=True)
a=array.array('h'); a.frombytes(open(PCM,'rb').read()); os.remove(PCM)
l=a[0::2]; r=a[1::2]; n=min(len(l),len(r)); l=l[:n]; r=r[:n]
ml=sum(l)/n; mr=sum(r)/n
dl=[x-ml for x in l]; dr=[x-mr for x in r]
ll=sum(x*x for x in dl); rr=sum(x*x for x in dr); lr=sum(x*y for x,y in zip(dl,dr))
corr=lr/math.sqrt(ll*rr) if ll and rr else 0
rmsl=math.sqrt(sum(x*x for x in l)/n); rmsr=math.sqrt(sum(x*x for x in r)/n)
dbdiff=20*math.log10(rmsl/rmsr) if rmsl and rmsr else 0
mid=math.sqrt(sum(((l[i]+r[i])*0.5)**2 for i in range(n))/n)
side=math.sqrt(sum(((l[i]-r[i])*0.5)**2 for i in range(n))/n)
msdb=20*math.log10(side/mid) if side and mid else -99
step=48; L=[dl[i] for i in range(0,n,step)]; R=[dr[i] for i in range(0,n,step)]
best=(0,-2)
for lag in range(-20,21):
    if lag>=0:
        x=L[:len(L)-lag or None]; y=R[lag:]
    else:
        x=L[-lag:]; y=R[:len(R)+lag]
    if len(x)<100: continue
    num=sum(i*j for i,j in zip(x,y)); den=math.sqrt(sum(i*i for i in x)*sum(j*j for j in y))
    c=num/den if den else 0
    if c>best[1]: best=(lag,c)
print(f'LR_CORRELATION={corr:.9f}')
print(f'LEFT_RMS={rmsl:.3f}')
print(f'RIGHT_RMS={rmsr:.3f}')
print(f'LR_RMS_DIFF_DB={dbdiff:.4f}')
print(f'SIDE_TO_MID_DB={msdb:.3f}')
print(f'BEST_INTERCHANNEL_LAG_MS={best[0]}')
print(f'BEST_INTERCHANNEL_CORR={best[1]:.9f}')
