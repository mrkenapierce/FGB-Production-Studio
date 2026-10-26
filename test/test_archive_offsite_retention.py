"""Unit tests for FGB confirmed archive cleanup and offsite source safety."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "ops" / "transport-ovh" / "archive-uploader.py"
spec = importlib.util.spec_from_file_location("fgb_archive_uploader", SOURCE)
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


class ConfirmedMediaRetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for d in ("state", "hourly", "final", "offsite"):
            (self.root / d).mkdir()
        self.source = self.root / "hourly" / "live-20261025-010000--0500.ts"
        self.mp4 = self.root / "final" / "20261025T010000m0500.mp4"
        self.state = self.root / "state" / "hourly-20261025T010000m0500.json"
        self.source.write_bytes(b"source raw capture preserved")
        self.mp4.write_bytes(b"confirmed mp4 upload copy")
        self.record = {"confirmed": True, "confirmed_epoch": time.time() - 100000,
                       "video_id": "cBzqZwkfQ4o",
                       "source": str(self.source), "mp4": str(self.mp4)}
        self.state.write_text(json.dumps(self.record))
        self.old = os.environ.get("FGB_OFFSITE_REQUIRED")
        self.addCleanup(self.restore)

    def restore(self):
        if self.old is None:
            os.environ.pop("FGB_OFFSITE_REQUIRED", None)
        else:
            os.environ["FGB_OFFSITE_REQUIRED"] = self.old

    def test_requires_offsite_proof_for_raw_capture(self):
        os.environ["FGB_OFFSITE_REQUIRED"] = "1"
        uploader.cleanup_confirmed(self.root, 24)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.mp4.exists())
        self.assertFalse(json.loads(self.state.read_text()).get("media_removed"))

    def test_verified_offsite_receipt_allows_cleanup(self):
        os.environ["FGB_OFFSITE_REQUIRED"] = "1"
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        (self.root / "offsite" / (self.source.name + ".sha256")).write_text(digest + " source today\n")
        uploader.cleanup_confirmed(self.root, 24)
        self.assertFalse(self.source.exists())
        self.assertFalse(self.mp4.exists())
        self.assertTrue(json.loads(self.state.read_text()).get("media_removed"))

    def test_invalid_offsite_checksum_blocks_raw_deletion(self):
        os.environ["FGB_OFFSITE_REQUIRED"] = "1"
        (self.root / "offsite" / (self.source.name + ".sha256")).write_text("f" * 64 + " source\n")
        uploader.cleanup_confirmed(self.root, 24)
        self.assertTrue(self.source.exists())

    def test_unconfirmed_upload_never_deleted(self):
        os.environ["FGB_OFFSITE_REQUIRED"] = "0"
        self.record["confirmed"] = False
        self.state.write_text(json.dumps(self.record))
        uploader.cleanup_confirmed(self.root, 24)
        self.assertTrue(self.source.exists())
        self.assertTrue(self.mp4.exists())

    def test_default_retention_after_youtube_confirmation(self):
        os.environ["FGB_OFFSITE_REQUIRED"] = "0"
        uploader.cleanup_confirmed(self.root, 24)
        self.assertFalse(self.source.exists())
        self.assertFalse(self.mp4.exists())


if __name__ == "__main__":
    unittest.main()
