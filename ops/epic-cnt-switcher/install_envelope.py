#!/usr/bin/env python3
"""Install a host-encrypted EPIC ingest envelope into private CNT env. Does not restart.
Private payload is decrypted only on the OVH host holding the RSA private key.
Never print payload, credentials, URLs with keys, or contents of the env file.
"""
import base64, fcntl, json, os, re, subprocess, sys, tempfile
from pathlib import Path

PAIR = Path("/root/.config/epic-cnt-credential-pairing")
ENV = Path("/opt/cnt-transport/.env.cnt")
PIN = "UCxtESG21aQASGiuQQzd87UA"
STREAM = "xtESG21aQASGiuQQzd87UA1795042630906870"
AGENT_URL = "https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/destination-agent"
INGEST_URL = "rtmps://a.rtmps.youtube.com/live2"
KEYS = {"CNT_DESTINATION_SWITCHING", "CNT_DESTINATION_AGENT_URL",
        "CNT_DESTINATION_AGENT_SECRET", "EPIC_YOUTUBE_INGEST_URL",
        "EPIC_YOUTUBE_STREAM_KEY"}

def main():
    if len(sys.argv) != 2: sys.exit("usage: install_envelope.py encrypted-envelope-file")
    os.umask(0o077)
    PAIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(PAIR / "install.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        data = Path(sys.argv[1]).read_text(encoding="ascii").strip()
        if len(data) > 8192 or not re.fullmatch(r"[A-Za-z0-9+/=]+", data):
            sys.exit("ENVELOPE_FORMAT_INVALID")
        cipher = base64.b64decode(data, validate=True)
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-decrypt", "-inkey", str(PAIR / "private.pem"),
             "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256"],
            input=cipher, capture_output=True, check=False)
        if proc.returncode != 0: sys.exit("DECRYPTION_FAILED")
        try: obj = json.loads(proc.stdout.decode("utf8"))
        except (ValueError, UnicodeDecodeError): sys.exit("ENVELOPE_NOT_JSON")
        if obj.get("channelId") != PIN or obj.get("streamId") != STREAM:
            sys.exit("CHANNEL_OR_STREAM_PIN_MISMATCH")
        secret = obj.get("agentHmacSecret", "")
        stream_name = obj.get("epicStreamName", "")
        if not isinstance(secret, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", secret):
            sys.exit("CONTROL_SECRET_FORMAT_INVALID")
        if not isinstance(stream_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,256}", stream_name):
            sys.exit("STREAM_NAME_FORMAT_INVALID")
        if not ENV.exists(): sys.exit("CNT_ENV_MISSING")
        stat = ENV.stat()
        lines = ENV.read_text(encoding="utf8").splitlines()
        if not any(line.startswith("CNT_YOUTUBE_STREAM_KEY=") for line in lines):
            sys.exit("EXISTING_CNT_KEY_MISSING")
        clean = [x for x in lines if x.split("=", 1)[0] not in KEYS]
        clean.extend([
            "CNT_DESTINATION_SWITCHING=off",
            "CNT_DESTINATION_AGENT_URL=" + AGENT_URL,
            "CNT_DESTINATION_AGENT_SECRET=" + secret,
            "EPIC_YOUTUBE_INGEST_URL=" + INGEST_URL,
            "EPIC_YOUTUBE_STREAM_KEY=" + stream_name,
        ])
        fd, tmp = tempfile.mkstemp(prefix=".cnt-env-stage-", dir=str(ENV.parent))
        try:
            os.fchmod(fd, 0o600)
            os.fchown(fd, stat.st_uid, stat.st_gid)
            with os.fdopen(fd, "w", encoding="utf8") as handle:
                handle.write("\n".join(clean) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, ENV)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        print("ENCRYPTED_EPIC_INGEST_INSTALLED=true")
        print("CONTROL_SECRET_INSTALLED=true")
        print("SWITCHING_REMAINS_OFF=true")
        print("CURRENT_CNT_KEY_PRESERVED=true")
        print("ENCODER_RESTARTED=false")
if __name__ == "__main__": main()
