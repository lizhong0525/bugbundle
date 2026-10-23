import tempfile
import unittest
from pathlib import Path

from bugbundle.bundle import BundleError, load_bundle, write_bundle
from bugbundle.viewer import render_html, render_to_file

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_bundle"


class TestViewer(unittest.TestCase):
    def test_renders_all_sections(self):
        html = render_html(load_bundle(FIXTURE))
        self.assertIn("BugBundle report", html)
        self.assertIn("Steps (4)", html)
        self.assertIn("Network (3 requests, 2 failed)", html)
        self.assertIn("TypeError: Cannot read properties of null", html)
        # screenshots embedded as base64 data URIs
        self.assertIn("data:image/png;base64,", html)
        # review-before-sharing banner is part of every report
        self.assertIn("review before sharing", html.lower())

    def test_escapes_html_in_console(self):
        tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        root = write_bundle(
            tmp / "b",
            {"format": "bugbundle/1", "url": "http://x", "viewport": {}},
            [{"t": "t", "action": "click", "target": "<script>alert(1)</script>"}],
            [{"t": "t", "level": "error", "text": "<img src=x onerror=alert(1)>"}],
            [],
        )
        html = render_html(load_bundle(root))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)

    def test_empty_bundle_refuses_to_render(self):
        tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        root = write_bundle(
            tmp / "b", {"format": "bugbundle/1", "url": "http://x", "viewport": {}}, [], [], []
        )
        with self.assertRaises(BundleError):
            render_to_file(root, tmp / "out.html")

    def test_render_to_file_writes_html(self):
        tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        out = render_to_file(FIXTURE, tmp / "report.html")
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("<!doctype html>"))
        self.assertIn("dom snapshot", text.lower())


if __name__ == "__main__":
    unittest.main()
