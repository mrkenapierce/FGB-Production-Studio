#!/usr/bin/env python3
"""CNT-only authenticated archive request. Secret stays outside the live browser.

Reads the key from a mounted root-managed file, never command-line arguments.
Host backend validates its SHA-256 digest with a timing-safe comparison.
"""
import json
import pathlib
import sys
import urllib.error
import urllib.request

def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: cnt-api-client.py <CNT endpoint> <private key filepath>")
    endpoint, secret_file = sys.argv[1:]
    if not endpoint.startswith("https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/archive"):
        raise SystemExit("refusing non-CNT archive endpoint")
    secret = pathlib.Path(secret_file).read_text(encoding="utf-8").strip()
    if len(secret) < 48 or "\r" in secret or "\n" in secret:
        raise SystemExit("invalid CNT private key")
    raw = sys.stdin.buffer.read(1048576)
    json.loads(raw)
    req = urllib.request.Request(endpoint, data=raw, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-cnt-archive-key": secret,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            sys.stdout.buffer.write(resp.read(1048576))
    except urllib.error.HTTPError as e:
        sys.stderr.write("CNT_ARCHIVE_HTTP_ERROR=" + str(e.code) + "\n")
        raise SystemExit(1)
if __name__ == "__main__":
    main()
