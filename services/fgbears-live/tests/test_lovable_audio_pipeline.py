#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "lovable-audio-pipeline.py"
spec = importlib.util.spec_from_file_location("fgb_audio_pipeline", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class ApprovalGateTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        mod.STATE_FILE = root / "state.json"
        mod.LOCK_FILE = root / "pipeline.lock"
        mod.ROOT = root / "incoming"
        mod.PREPARE_TOOL = root / "prepare.py"
        mod.PREPARE_TOOL.write_text("# test\n", encoding="utf-8")

    def tearDown(self):
        self.td.cleanup()

    def state(self):
        return json.loads(mod.STATE_FILE.read_text(encoding="utf-8"))

    def test_legacy_active_state_is_non_actionable(self):
        mod.fetch_contract = lambda: ("https://example.test/contract", {
            "revision": 41,
            "mode": "track",
            "enabled": True,
            "activeTrackId": "legacy",
            "activeTrackName": "Legacy",
            "assetUrl": "/asset",
        })
        self.assertEqual(mod.main(), 0)
        s = self.state()
        self.assertEqual(s["status"], "idle")
        self.assertEqual(s["observedRevision"], 41)
        self.assertNotIn("appliedRevision", s)

    def test_approved_revision_without_hash_is_non_actionable(self):
        mod.fetch_contract = lambda: ("https://example.test/contract", {
            "revision": 42,
            "approvalState": "approved",
            "approvedAt": "2026-09-15T22:00:00Z",
            "mode": "track",
            "enabled": True,
            "activeTrackId": "x",
            "activeTrackName": "Track",
            "assetUrl": "/asset",
        })
        self.assertEqual(mod.main(), 0)
        s = self.state()
        self.assertEqual(s["status"], "idle")
        self.assertIn("sourceSha256", s["message"])

    def test_failed_revision_is_not_retried(self):
        mod.STATE_FILE.write_text(json.dumps({"failedRevisions": [43]}), encoding="utf-8")
        mod.fetch_contract = lambda: ("https://example.test/contract", {
            "revision": 43,
            "approvalState": "approved",
            "approvedAt": "2026-09-15T22:00:00Z",
            "sourceSha256": "a" * 64,
            "mode": "track",
            "enabled": True,
            "activeTrackId": "x",
            "activeTrackName": "Track",
            "assetUrl": "/asset",
            "loop": True,
        })
        called = {"prepare": False}
        def bad_prepare(*args, **kwargs):
            called["prepare"] = True
            raise AssertionError("failed revision must not be prepared")
        mod.prepare_revision = bad_prepare
        self.assertEqual(mod.main(), 0)
        self.assertFalse(called["prepare"])


if __name__ == "__main__":
    unittest.main()
