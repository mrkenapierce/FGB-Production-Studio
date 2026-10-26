#!/usr/bin/env python3
"""CNT trusted playback-boundary observer. NOT INSTALLED. Stdlib only.

Runs on the CNT capture host next to Chromium (run-cnt.sh with CNT_AIR_LOG).
It tails Chromium's console log, accepts only EPIC_AIR_BOUNDARY markers from
the CNT broadcast origin, validates them against ITS OWN clock, and only then
signs reports with CNT_ARCHIVE_HMAC_SECRET (x-cnt-timestamp/x-cnt-signature over
"{ts}.{body}") to the CNT archive endpoint. The browser holds no secret.

Rules (crash/skip never qualifies):
  * start: unknown play id, mediaTime <= 1 s. A new start closes any open play
    as interrupted (one open play at a time).
  * tick: must arrive at least every 45 s; media progress may not run ahead of
    wall time by more than 5 s (a jump/seek interrupts).
  * end: only for the open play, mediaTime within 1.5 s of duration, and the
    observed wall time covers the media duration (minus 3 s). Otherwise it is
    reported as interrupted.
  * Chromium restart marker, a missing tick, observer restart with an open play,
    malformed or out-of-order markers -> interrupted.
  * occurredAt is the observer's receipt time, never browser- or schedule-time.
  * Each (playId, event) is sent at most once; reports are spooled to disk and
    retried, and the app also dedupes by (channel, play_id, event).
"""
from __future__ import annotations

import hashlib, hmac, json, os, re, sys, time, urllib.request
from datetime import datetime, timezone

MARKER = "EPIC_AIR_BOUNDARY "
RESTART = "EPIC_CHROME_RESTART"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SOURCE = re.compile(r'source: (https?://[^/\s"]+)/')
TICK_TIMEOUT = 45.0


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(t * 1000) % 1000:03d}Z"


class Observer:
    def __init__(self, allowed_origin: str, state: dict | None = None):
        self.origin = allowed_origin.rstrip("/")
        st = state or {}
        self.sent: set[str] = set(st.get("sent", []))
        self.open: dict | None = None
        # An open play persisted by a crashed observer can never complete.
        self.pending: list[dict] = list(st.get("pending", []))
        if st.get("open"):
            self._report(st["open"], "interrupted", time.time())

    def snapshot(self) -> dict:
        return {"sent": sorted(self.sent)[-5000:], "open": self.open, "pending": self.pending}

    def _report(self, play: dict, event: str, now: float) -> None:
        key = f"{play['playId']}:{event}"
        if key in self.sent:
            return
        self.sent.add(key)
        self.pending.append({"action": "episode_air", "trackId": play["trackId"], "playId": play["playId"],
                             "event": event, "occurredAt": iso(now)})

    def _interrupt(self, now: float) -> None:
        if self.open:
            self._report(self.open, "interrupted", now)
            self.open = None

    def line(self, raw: str, now: float) -> None:
        if RESTART in raw:
            self._interrupt(now)
            return
        i = raw.find(MARKER)
        if i < 0:
            return
        m = SOURCE.search(raw)
        if not m or m.group(1) != self.origin:
            return  # only our own broadcast page; ignore iframes/other origins
        body = raw[i + len(MARKER):]
        body = body[: body.rfind("}") + 1] if "}" in body else ""
        try:
            msg = json.loads(body.replace('\\"', '"'))
        except ValueError:
            return
        self.message(msg, now)

    def message(self, msg: dict, now: float) -> None:
        ok = (isinstance(msg, dict) and msg.get("v") == 1 and msg.get("channel") == "cnt"
              and isinstance(msg.get("trackId"), str) and UUID.match(msg["trackId"])
              and isinstance(msg.get("playId"), str) and UUID.match(msg["playId"])
              and msg.get("event") in ("start", "tick", "end", "interrupted")
              and isinstance(msg.get("seq"), int)
              and isinstance(msg.get("mediaTime"), (int, float)) and isinstance(msg.get("duration"), (int, float)))
        if not ok:
            return
        ev, pid, mt, dur = msg["event"], msg["playId"], float(msg["mediaTime"]), float(msg["duration"])
        if ev == "start":
            if f"{pid}:start" in self.sent or mt > 1.0:
                return
            self._interrupt(now)
            self.open = {"trackId": msg["trackId"], "playId": pid, "seq": msg["seq"], "t0": now,
                         "lastAt": now, "lastMedia": mt}
            self._report(self.open, "start", now)
            return
        o = self.open
        if not o or o["playId"] != pid or o["trackId"] != msg["trackId"]:
            return
        if msg["seq"] <= o["seq"]:
            self._interrupt(now)
            return
        o["seq"] = msg["seq"]
        if ev == "interrupted":
            self._interrupt(now)
            return
        wall = now - o["t0"]
        if mt > wall + 5.0:  # media ran ahead of real time: skipped/seeked
            self._interrupt(now)
            return
        if ev == "tick":
            o["lastAt"], o["lastMedia"] = now, mt
            return
        # end
        if dur > 0 and abs(dur - mt) <= 1.5 and wall >= dur - 3.0:
            self._report(o, "end", now)
            self.open = None
        else:
            self._interrupt(now)

    def watchdog(self, now: float) -> None:
        if self.open and now - self.open["lastAt"] > TICK_TIMEOUT:
            self._interrupt(now)


def sign_and_send(url: str, secret: str, report: dict) -> bool:
    body = json.dumps(report, separators=(",", ":"))
    key_path = os.environ.get("CNT_ARCHIVE_KEY_FILE", "")
    headers = {"content-type": "application/json"}
    if key_path:
        # Never expose the raw key to the Chromium browser or process args.
        try:
            key = open(key_path, encoding="utf-8").read().strip()
            if len(key) < 48:
                return False
            headers["x-cnt-archive-key"] = key
        except OSError:
            return False
    else:
        ts = str(int(time.time()))
        sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
        headers.update({"x-cnt-timestamp": ts, "x-cnt-signature": sig})
    req = urllib.request.Request(url, data=body.encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}").get("ok") is True
    except Exception:
        return False


def main() -> None:
    log_path = os.environ["CNT_AIR_LOG"]
    url = os.environ.get("CNT_ARCHIVE_URL", "https://epiccontentcreatorgrants.org/api/public/channels/cruisenewstrivia/archive")
    secret = os.environ.get("CNT_ARCHIVE_HMAC_SECRET", "")
    dry = os.environ.get("EP_DRY_RUN") == "1"
    if not secret and not os.environ.get("CNT_ARCHIVE_KEY_FILE") and not dry:
        sys.exit("CNT archive key file or HMAC secret required")
    if "/fgbears/" in url:
        sys.exit("refusing FGB endpoint")
    state_path = os.environ.get("CNT_AIR_STATE", "/cnt-archive/state/air-observer.json")
    origin = os.environ.get("CNT_BROADCAST_ORIGIN", "https://epiccontentcreatorgrants.org")
    try:
        state = json.load(open(state_path))
    except (OSError, ValueError):
        state = None
    obs = Observer(origin, state)
    pos, last_save = 0, 0.0
    while True:
        try:
            size = os.path.getsize(log_path)
            if size < pos:
                pos = 0  # truncated/rotated
            with open(log_path, "r", errors="replace") as fh:
                fh.seek(pos)
                for raw in fh:
                    obs.line(raw, time.time())
                pos = fh.tell()
        except OSError:
            pass
        obs.watchdog(time.time())
        while obs.pending:
            rep = obs.pending[0]
            if dry:
                print("DRY_RUN", json.dumps(rep), flush=True)
            elif not sign_and_send(url, secret, rep):
                break
            obs.pending.pop(0)
        if time.time() - last_save > 2:
            tmp = state_path + ".tmp"
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(tmp, "w") as fh:
                json.dump(obs.snapshot(), fh)
            os.replace(tmp, state_path)
            last_save = time.time()
        time.sleep(0.5)


if __name__ == "__main__":
    main()