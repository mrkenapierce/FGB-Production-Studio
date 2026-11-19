#!/usr/bin/env python3
"""Opt-in standalone sidecar. No encoder control, media deletion, legacy job edits.
Requires existing CNT signed endpoint, recorder and dependency journal. Never
run with shell tracing; tokens/session URLs are private and never logged.
"""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

TARGET = 'UCxtESG21aQASGiuQQzd87UA'
HERE = Path(__file__).resolve().parent

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def http(url, method, headers, body=None):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=120) as r:
            return r.status, dict(r.headers), r.read(65536)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(65536)

def api(payload):
    url = os.environ['CNT_ARCHIVE_URL']
    u = urllib.parse.urlparse(url)
    if u.scheme != 'https' or u.path != '/api/public/channels/cruisenewstrivia/archive':
        raise RuntimeError('signed_endpoint_invalid')
    body = json.dumps(payload, separators=(',', ':')).encode()
    ts = str(int(time.time()))
    sig = hmac.new(os.environ['CNT_ARCHIVE_HMAC_SECRET'].encode(), ts.encode()+b'.'+body, hashlib.sha256).hexdigest()
    code, _, raw = http(url, 'POST', {'content-type':'application/json','x-cnt-timestamp':ts,'x-cnt-signature':sig}, body)
    if code != 200:
        try:
            reason=json.loads(raw).get('error')
            if reason in {'permission_denied','identity_mismatch','upload_unavailable','receipt_unverified'}:
                raise RuntimeError(reason)
        except (ValueError,AttributeError):
            pass
        raise RuntimeError('signed_endpoint_unavailable')
    return json.loads(raw)

def save(path, state):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        os.chmod(tmp, 0o600)
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def valid_session(url):
    u = urllib.parse.urlparse(url)
    return u.scheme == 'https' and u.netloc == 'www.googleapis.com' and u.path == '/upload/youtube/v3/videos' and 'upload_id' in urllib.parse.parse_qs(u.query)

def upload(file, state, persist, token, register_session, request=http):
    """An existing session is probed, never replaced, even on 404/410.
    Initiation intent is durable BEFORE POST, so a lost response blocks rather
    than creating another video. Same owner and session survive interruptions.
    """
    if state.get('videoId'):
        return state['videoId']
    size = file.stat().st_size
    session = state.get('sessionUrl')
    auth = {'authorization':'Bearer '+token}
    if not session:
        if state.get('initiating'):
            raise RuntimeError('upload_ambiguous')
        state['initiating'] = True
        persist(state)
        meta = {'snippet':{'title':state['title'],'description':state['description'],'categoryId':'22'},'status':{'privacyStatus':'public','selfDeclaredMadeForKids':False}}
        code, headers, _ = request('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', 'POST', {**auth,'content-type':'application/json','x-upload-content-type':'video/mp2t','x-upload-content-length':str(size)},json.dumps(meta).encode())
        if code not in (200,201):
            # Explicit permission rejection created no session; recovery can retry.
            if code in (401,403):
                state.pop('initiating',None); persist(state)
                raise RuntimeError('permission_denied')
            raise RuntimeError('upload_ambiguous')
        session = next((v for k,v in headers.items() if k.lower()=='location'),None)
        if not session or not valid_session(session):
            raise RuntimeError('upload_ambiguous')
        state['sessionUrl'] = session
        persist(state)
    if not valid_session(session):
        raise RuntimeError('upload_ambiguous')
    if not register_session(session):
        raise RuntimeError('upload_unavailable')
    code, headers, raw = request(session,'PUT',{**auth,'content-range':f'bytes */{size}','content-length':'0'},b'')
    if code in (404,410):
        raise RuntimeError('session_expired')
    if code in (401,403):
        raise RuntimeError('permission_denied')
    if code in (200,201):
        video = json.loads(raw).get('id')
        if not isinstance(video,str) or len(video)!=11:
            raise RuntimeError('upload_ambiguous')
        state['videoId']=video; persist(state); return video
    if code != 308:
        raise RuntimeError('upload_unavailable')
    offset = 0
    rg = next((v for k,v in headers.items() if k.lower()=='range'),None)
    if rg:
        offset = int(rg.rsplit('-',1)[1])+1
    with open(file,'rb') as f:
        f.seek(offset)
        while offset < size:
            chunk=f.read(8*1024*1024)
            code, _, raw=request(session,'PUT',{**auth,'content-type':'video/mp2t','content-range':f'bytes {offset}-{offset+len(chunk)-1}/{size}'},chunk)
            if code in (200,201):
                video=json.loads(raw).get('id')
                if not isinstance(video,str) or len(video)!=11: raise RuntimeError('upload_ambiguous')
                state['videoId']=video; persist(state); return video
            if code in (401,403): raise RuntimeError('permission_denied')
            if code != 308: raise RuntimeError('upload_unavailable')
            offset += len(chunk)
    raise RuntimeError('upload_unavailable')

def source_cut(job, out, reuse=False):
    # Reuse CLOSED-segment parser/coverage and durable CNT retention journal.
    ws=int(datetime.fromisoformat(job['windowStart'].replace('Z','+00:00')).timestamp())
    we=int(datetime.fromisoformat(job['windowEnd'].replace('Z','+00:00')).timestamp())
    script='''set -eu
here="$1"; . "$here/episode-lib.sh"
ep_dependency register --kind episode --id "$2" --start "$3" --end "$4" >/dev/null
cover=$(ep_cover "$3" "$4") || { printf '%s' "$cover"; exit 2; }
mapfile -t files < <(tail -n +2 <<<"$cover")
first=$(head -1 <<<"$cover" | cut -d' ' -f2)
if [ "$6" != yes ]; then ep_cut "$3" "$4" "$5" "$first" "${files[@]}"; fi
duration=$(ep_duration "$5")
[ "$duration" -ge "$(( $4 - $3 - 2 ))" ] || { echo NOT_CLOSED; exit 2; }
'''
    env={**os.environ,'EPISODE_CHANNEL':'cnt'}
    r=subprocess.run(['bash','-c',script,'epic-source',str(HERE),job['episodeId'],str(ws),str(we),str(out),'yes' if reuse else 'no'],env=env,capture_output=True,text=True)
    if r.returncode:
        reason='recording_gap' if 'GAP' in r.stdout else 'recording_missing' if 'MISSING' in r.stdout else 'recording_partial'
        raise RuntimeError(reason)

def pass_once(root):
    response=api({'action':'epic_episode_jobs'})
    if response.get('ok') is not True: raise RuntimeError('publication_disabled')
    for job in response.get('jobs',[]):
        if job.get('targetChannelId')!=TARGET: raise RuntimeError('identity_mismatch')
        id=str(uuid.UUID(job['episodeId']))
        sf=root/(id+'.json'); out=root/(id+'.ts')
        # Corrupt/missing local state for a claimed job cannot steal its owner.
        state=json.loads(sf.read_text()) if sf.exists() else {'owner':str(uuid.uuid4()),'title':job['title'],'description':job['description']}
        save(sf,state)
        base={'episodeId':id,'owner':state['owner']}
        claim=api({'action':'epic_episode_claim',**base})
        if claim.get('ok') is not True: continue
        for key in ('sessionUrl','videoId'):
            if claim.get(key):
                if state.get(key) and state[key]!=claim[key]: raise RuntimeError('receipt_unverified')
                state[key]=claim[key]
        save(sf,state)
        try:
            if not state.get('videoId'):
                # Always reverify complete closed coverage, even for a cached cut.
                if state.get('sessionUrl') and not state.get('cutSha256'): raise RuntimeError('upload_ambiguous')
                source_cut(job,out,reuse=bool(state.get('cutSha256')))
                with open(out,'rb') as cut:
                    digest=hashlib.file_digest(cut,'sha256').hexdigest()
                if state.get('cutSha256') and state['cutSha256']!=digest: raise RuntimeError('upload_ambiguous')
                state['cutSha256']=digest; save(sf,state)
                token=api({'action':'epic_episode_token',**base})
                if token.get('ok') is not True or token.get('targetChannelId')!=TARGET or not token.get('accessToken'): raise RuntimeError('permission_denied')
                video=upload(out,state,lambda s:save(sf,s),token['accessToken'],lambda u:api({'action':'epic_episode_session','sessionUrl':u,**base}).get('ok') is True)
            else: video=state['videoId']
            receipt=api({'action':'epic_episode_uploaded','videoId':video,**base})
            if receipt.get('confirmed') is not True: raise RuntimeError('receipt_unverified')
            state['confirmed']=True; save(sf,state)
            print('EPIC episode confirmed:',id,flush=True)
            # Intentionally retain BOTH source dependencies and cut. No deletes.
        except (RuntimeError,OSError,ValueError) as e:
            allowed={'recording_missing','recording_gap','recording_partial','permission_denied','identity_mismatch','upload_unavailable','upload_ambiguous','session_expired','receipt_unverified'}
            reason=str(e) if str(e) in allowed else 'upload_unavailable'
            api({'action':'epic_episode_failed','reason':reason,**base})
            print('EPIC episode blocked/retry:',id,reason,flush=True)

def main():
    if os.environ.get('EPIC_EPISODE_RUN')!='yes': raise SystemExit('EPIC_EPISODE_RUN=yes required; no actions performed')
    os.umask(0o077)
    root=Path(os.environ['CNT_ARCHIVE_DIR'])/'state'/'epic-episodes'
    root.mkdir(parents=True,exist_ok=True)
    with open(root/'worker.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        pass_once(root)

if __name__=='__main__': main()