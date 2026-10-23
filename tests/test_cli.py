import shutil
import tempfile
import unittest
from pathlib import Path

from bugbundle.cli import main

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_bundle"


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_demo_command(self):
        out = self.tmp / "report.html"
        rc = main(["demo", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("BugBundle report", out.read_text(encoding="utf-8"))

    def test_validate_ok_and_bad(self):
        self.assertEqual(main(["validate", str(FIXTURE)]), 0)
        self.assertEqual(main(["validate", str(self.tmp / "nope")]), 1)

    def test_view_command(self):
        out = self.tmp / "v.html"
        self.assertEqual(main(["view", str(FIXTURE), "--out", str(out)]), 0)
        self.assertTrue(out.is_file())

    def test_export_yes_then_import(self):
        bundle = self.tmp / "bundle"
        shutil.copytree(FIXTURE, bundle)
        archive = self.tmp / "share.zip"
        self.assertEqual(main(["export", str(bundle), "--out", str(archive), "--yes"]), 0)
        archive = self.tmp / "share.bugbundle.zip"  # export normalizes the name
        self.assertTrue(archive.is_file())
        self.assertEqual(main(["import", str(archive), "--out", str(self.tmp / "in")]), 0)
        self.assertTrue((self.tmp / "in" / "manifest.json").is_file())

    def test_capture_without_playwright_fails_gracefully(self):
        # Simulate playwright being absent even if it is installed locally.
        import sys
        from unittest import mock

        with mock.patch.dict(sys.modules, {"playwright": None, "playwright.sync_api": None}):
            rc = main(["capture", "http://localhost", "--out", str(self.tmp / "cap")])
        self.assertEqual(rc, 1)
        self.assertFalse((self.tmp / "cap").exists())

    def test_capture_unexpected_failure_is_clean_error(self):
        # e.g. playwright installed but browser binary missing: the CLI must
        # exit 1 with an error line, not crash with a traceback.
        from unittest import mock

        with mock.patch("bugbundle.capture.capture", side_effect=ValueError("boom")):
            rc = main(["capture", "http://localhost", "--out", str(self.tmp / "cap")])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
