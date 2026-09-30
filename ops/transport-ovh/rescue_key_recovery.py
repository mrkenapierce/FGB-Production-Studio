import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import paramiko

HOST = "40.160.144.185"
USER = "root"
PASSWORD = os.environ["OVH_RESCUE_PASSWORD"]
PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAII/NU/kySLt3lRJOcTRTxX1cmg13DVnNkbkHK5cVUPPq github-actions-ovh-deploy"

RECOVERY_OK = False
RECOVERY_MESSAGE = "starting"


def wait_for_ssh(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, 22), timeout=5):
                return True
        except OSError:
            time.sleep(5)
    return False


def run_recovery():
    global RECOVERY_OK, RECOVERY_MESSAGE
    if not wait_for_ssh():
        RECOVERY_MESSAGE = "ssh-unreachable"
        print("RECOVERY_FAILED=ssh-unreachable", flush=True)
        return

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        look_for_keys=False,
        allow_agent=False,
        timeout=10,
        auth_timeout=10,
        banner_timeout=10,
    )

    command = f'''set -eu
mountpoint -q /mnt || mount /dev/sdb1 /mnt
test -d /mnt/home/ubuntu
install -d -m 700 /mnt/home/ubuntu/.ssh
touch /mnt/home/ubuntu/.ssh/authorized_keys
chmod 600 /mnt/home/ubuntu/.ssh/authorized_keys
KEY='{PUBLIC_KEY}'
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys || printf '%s\\n' "$KEY" >> /mnt/home/ubuntu/.ssh/authorized_keys
chown -R --reference=/mnt/home/ubuntu /mnt/home/ubuntu/.ssh
grep -qxF "$KEY" /mnt/home/ubuntu/.ssh/authorized_keys
sync
echo KEY_INSTALLED=true
'''
    stdin, stdout, stderr = client.exec_command(command, timeout=30)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if out:
        print(out.strip(), flush=True)
    if err:
        print(err.strip(), flush=True)
    if code != 0 or "KEY_INSTALLED=true" not in out:
        RECOVERY_MESSAGE = f"install-failed:{code}"
        print(f"RECOVERY_FAILED=install-failed:{code}", flush=True)
        client.close()
        return

    try:
        client.exec_command("nohup sh -c 'sleep 2; reboot' >/dev/null 2>&1 &", timeout=5)
    except Exception:
        pass
    client.close()
    RECOVERY_OK = True
    RECOVERY_MESSAGE = "key-installed-reboot-sent"
    print("REBOOT_SENT=true", flush=True)
    print("RECOVERY_OK=true", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"recovery_ok={str(RECOVERY_OK).lower()}\nmessage={RECOVERY_MESSAGE}\n".encode()
        self.send_response(200 if RECOVERY_OK else 503)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    try:
        run_recovery()
    except Exception as exc:
        RECOVERY_MESSAGE = f"exception:{type(exc).__name__}"
        print(f"RECOVERY_EXCEPTION={type(exc).__name__}:{exc}", flush=True)
    port = int(os.environ.get("PORT", "10000"))
    print(f"STATUS_SERVER_PORT={port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
