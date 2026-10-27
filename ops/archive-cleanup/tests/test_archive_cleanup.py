import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location("ac", Path(__file__).resolve().parents[1] / "archive-cleanup.py")
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)

NOW = 1_800_000_000
OLD = "live-20261027-080001--0500.ts"   # 20261027T080001-0500
MID = "live-20261027-090001--0500.ts"
NEW = "live-20261027-100001--0500.ts"


def ok_fetch(ids):
    return lambda body: {"ok": True, "confirmedSegmentIds": ids}


class Env:
    def __init__(self, channel="fgb"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / channel
        self.scan = self.root / ac.CHANNELS[channel]["scan"]
        self.state = self.root / "state"
        self.scan.mkdir(parents=True); self.state.mkdir()
        self.channel = channel
        for n in (OLD, MID, NEW):
            p = self.scan / n; p.write_bytes(b"x" * 10)
            os.utime(p, (NOW - 4 * 3600, NOW - 4 * 3600))
        for h in ("episode_hold", "daily_hold"):
            (self.state / h).write_text(""); os.utime(self.state / h, (NOW - 5, NOW - 5))

    def run(self, fetch, **env):
        base = {"CLEANUP_ROOT": str(self.root)}
        base.update(env)
        ac.run(self.channel, env=base, fetch=fetch, now=NOW)
        return json.loads((self.state / "cleanup-status.json").read_text())


class Tests(unittest.TestCase):
    def test_segment_id_mapping(self):
        self.assertEqual(ac.segment_id(OLD), "20261027T080001-0500")
        self.assertIsNone(ac.segment_id("20261027T080001--0500.ts"))

    def test_dry_run_is_default(self):
        e = Env(); s = e.run(ok_fetch(["20261027T080001-0500"]))
        self.assertEqual((s["mode"], s["candidate_count"], s["deleted_count"]), ("dry-run", 1, 0))
        self.assertTrue((e.scan / OLD).exists())

    def test_dry_run_false_alone_does_not_delete(self):
        e = Env(); s = e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false")
        self.assertEqual(s["deleted_count"], 0); self.assertTrue((e.scan / OLD).exists())

    def test_apply_deletes_only_confirmed(self):
        e = Env(); s = e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertEqual(s["deleted_count"], 1)
        self.assertFalse((e.scan / OLD).exists()); self.assertTrue((e.scan / MID).exists())

    def test_newest_file_never_deleted_even_if_confirmed(self):
        e = Env(); e.run(ok_fetch(["20261027T100001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertTrue((e.scan / NEW).exists())

    def test_recently_modified_file_protected(self):
        e = Env(); os.utime(e.scan / OLD, (NOW - 10, NOW - 10))
        s = e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertEqual(s["deleted_count"], 0)

    def test_unpublished_old_file_kept_with_overdue_alert(self):
        e = Env(); s = e.run(ok_fetch([]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertEqual(s["deleted_count"], 0); self.assertGreaterEqual(s["overdue_count"], 2)

    def test_endpoint_failure_deletes_nothing(self):
        def boom(body): raise OSError("down")
        e = Env(); s = e.run(boom, DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertEqual(s["deleted_count"], 0); self.assertIn("receipts", s["error"])

    def test_refused_or_malformed_receipts_delete_nothing(self):
        for fetch in (lambda b: {"ok": False}, lambda b: {"ok": True, "confirmedSegmentIds": ["../x"]}):
            e = Env(); s = e.run(fetch, DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
            self.assertEqual(s["deleted_count"], 0)

    def test_stale_or_missing_hold_fails_closed(self):
        e = Env(); os.utime(e.state / "episode_hold", (NOW - 3600, NOW - 3600))
        self.assertEqual(e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")["deleted_count"], 0)
        e = Env(); (e.state / "daily_hold").unlink()
        self.assertEqual(e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")["deleted_count"], 0)

    def test_held_file_kept(self):
        e = Env(); (e.state / "episode_hold").write_text(OLD + "\n"); os.utime(e.state / "episode_hold", (NOW, NOW))
        self.assertEqual(e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")["deleted_count"], 0)

    def test_symlinks_dirs_and_odd_names_protected(self):
        e = Env(); target = Path(e.tmp.name) / "outside.ts"; target.write_text("x")
        (e.scan / "live-20261027-070001--0500.ts").symlink_to(target)
        (e.scan / "live-20261027-060001--0500.ts").mkdir()
        (e.scan / "notes.ts").write_text("x"); os.utime(e.scan / "notes.ts", (NOW - 9000, NOW - 9000))
        e.run(ok_fetch(["20261027T070001-0500", "20261027T060001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        self.assertTrue(target.exists()); self.assertTrue((e.scan / "live-20261027-060001--0500.ts").is_dir())
        self.assertTrue((e.scan / "notes.ts").exists())

    def test_overlapping_run_skips(self):
        import fcntl
        e = Env()
        with (e.state / "cleanup.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ac.run("fgb", env={"CLEANUP_ROOT": str(e.root), "DRY_RUN": "false", "CLEANUP_CONFIRM_DELETE": "yes"},
                   fetch=ok_fetch(["20261027T080001-0500"]), now=NOW)
        self.assertTrue((e.scan / OLD).exists())

    def test_idempotent_second_run(self):
        e = Env(); kw = dict(DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        e.run(ok_fetch(["20261027T080001-0500"]), **kw)
        self.assertEqual(e.run(ok_fetch(["20261027T080001-0500"]), **kw)["deleted_count"], 0)

    def test_channel_path_isolation(self):
        with self.assertRaises(SystemExit):
            ac.check_root("cnt", "/srv/fgb-archive/hourly")
        with self.assertRaises(SystemExit):
            ac.check_root("fgb", "/cnt-archive")

    def _age(self, seconds):
        e = Env(); os.utime(e.scan / OLD, (NOW - seconds, NOW - seconds))
        s = e.run(ok_fetch(["20261027T080001-0500"]), DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes")
        return e, s

    def test_confirmed_just_under_three_hours_protected(self):
        e, s = self._age(3 * 3600 - 1)
        self.assertEqual(s["deleted_count"], 0); self.assertTrue((e.scan / OLD).exists())

    def test_confirmed_exactly_three_hours_deleted(self):
        e, s = self._age(3 * 3600)
        self.assertEqual(s["deleted_count"], 1); self.assertFalse((e.scan / OLD).exists())

    def test_confirmed_over_three_hours_deleted(self):
        e, s = self._age(3 * 3600 + 600)
        self.assertEqual(s["deleted_count"], 1)

    def test_within_retention_reason(self):
        out = ac.classify([{"name": OLD, "kind": "file", "size": 1, "mtime": NOW - 3600},
                           {"name": NEW, "kind": "file", "size": 1, "mtime": NOW - 7200}],
                          now=NOW, receipts={"20261027T080001-0500"}, held=set(), holds_ok=True, grace=120, retention=10800)
        self.assertEqual(out[0][1:3], ("PROTECT", "confirmed_within_retention"))

    def _capture(self, channel, env):
        import io
        captured = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=None):
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = req.data.decode()
            return Resp(b'{"ok": true}')

        orig = ac.urllib.request.urlopen
        ac.urllib.request.urlopen = fake_urlopen
        try:
            ac.signed_post("https://example.invalid/x", channel, env, '{"action":"cleanup"}')
        finally:
            ac.urllib.request.urlopen = orig
        return captured["headers"], captured["body"]

    def test_fgb_static_key_request(self):
        h, _ = self._capture("fgb", {"FGB_ARCHIVE_API_KEY": "k-fake", "FGB_TRANSPORT_HEARTBEAT_SECRET": "h-fake"})
        self.assertEqual(h.get("x-fgb-archive-key"), "k-fake")
        self.assertNotIn("x-fgb-signature", h); self.assertNotIn("x-fgb-timestamp", h)

    def test_fgb_hmac_request(self):
        import hashlib, hmac as hm
        h, body = self._capture("fgb", {"FGB_TRANSPORT_HEARTBEAT_SECRET": "h-fake"})
        self.assertNotIn("x-fgb-archive-key", h)
        expected = hm.new(b"h-fake", f"{h['x-fgb-timestamp']}.{body}".encode(), hashlib.sha256).hexdigest()
        self.assertTrue(hm.compare_digest(h["x-fgb-signature"], expected))

    def test_cnt_key_only_request(self):
        h, _ = self._capture("cnt", {"CNT_ARCHIVE_HMAC_SECRET": "c-fake"})
        self.assertEqual(h.get("x-cnt-archive-key"), "c-fake")
        self.assertNotIn("x-cnt-timestamp", h); self.assertNotIn("x-cnt-signature", h)

    def test_channel_separation(self):
        h, _ = self._capture("cnt", {"CNT_ARCHIVE_HMAC_SECRET": "c-fake", "FGB_ARCHIVE_API_KEY": "k-fake"})
        self.assertFalse(any(k.startswith("x-fgb-") for k in h))
        h, _ = self._capture("fgb", {"FGB_ARCHIVE_API_KEY": "k-fake", "CNT_ARCHIVE_HMAC_SECRET": "c-fake"})
        self.assertFalse(any(k.startswith("x-cnt-") for k in h))
        with self.assertRaises(RuntimeError):  # FGB never borrows CNT's key
            ac.auth_headers("fgb", {"CNT_ARCHIVE_HMAC_SECRET": "c-fake"}, "{}")

    def test_hmac_secret_never_sent_as_archive_key(self):
        h, _ = self._capture("fgb", {"FGB_TRANSPORT_HEARTBEAT_SECRET": "h-fake"})
        self.assertNotIn("h-fake", h.values())
        h, _ = self._capture("fgb", {"FGB_ARCHIVE_API_KEY": "k-fake", "FGB_TRANSPORT_HEARTBEAT_SECRET": "h-fake"})
        self.assertNotIn("h-fake", h.values())

    def test_missing_credentials_fail_closed(self):
        for ch, env in (("fgb", {"ARCHIVE_URL": "https://example.invalid"}), ("cnt", {"CNT_ARCHIVE_URL": "https://example.invalid", "FGB_ARCHIVE_API_KEY": "k"})):
            e = Env(ch); s = e.run(None, DRY_RUN="false", CLEANUP_CONFIRM_DELETE="yes", **env)
            self.assertEqual(s["deleted_count"], 0); self.assertIn("not set", s["error"])
            self.assertTrue((e.scan / OLD).exists())

    def test_status_metrics_present(self):
        s = Env().run(ok_fetch([]))
        for k in ("last_run", "candidate_count", "deleted_count", "protected_count", "disk_free_mb"):
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main()
