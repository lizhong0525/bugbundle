import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from bugbundle.bundle import (
    BundleError,
    export_bundle,
    import_bundle,
    load_bundle,
    validate_bundle,
    write_bundle,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_bundle"


class TestFixtureBundle(unittest.TestCase):
    def test_fixture_validates_clean(self):
        self.assertEqual(validate_bundle(FIXTURE), [])

    def test_fixture_loads_and_is_redacted(self):
        b = load_bundle(FIXTURE)
        self.assertEqual(b.manifest["format"], "bugbundle/1")
        self.assertEqual(len(b.steps), 4)
        blob = json.dumps(b.console) + json.dumps(b.network) + json.dumps(b.manifest)
        self.assertNotIn("alice@example.com", blob)
        self.assertNotIn("sekrit123", blob)
        self.assertIn("[REDACTED]", blob)
        self.assertFalse(b.manifest["passwords_recorded"])
        self.assertEqual(len(b.screenshots), 2)

    def test_fixture_dom_snapshot_redacted(self):
        b = load_bundle(FIXTURE)
        self.assertIsNotNone(b.dom_snapshot)
        self.assertNotIn("hunter2", b.dom_snapshot)
        self.assertIn("[REDACTED REGION: #account-panel]", b.dom_snapshot)


class TestExportImportRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _copy_fixture(self) -> Path:
        dst = self.tmp / "bundle"
        shutil.copytree(FIXTURE, dst)
        return dst

    def test_export_requires_confirmation(self):
        bundle = self._copy_fixture()
        with self.assertRaises(BundleError):
            export_bundle(bundle, self.tmp / "out.zip", confirm=False)

    def test_round_trip_preserves_all_artifacts(self):
        bundle = self._copy_fixture()
        out_zip = export_bundle(bundle, self.tmp / "out.zip", confirm=True)
        self.assertTrue(out_zip.is_file())
        self.assertEqual(out_zip.suffix, ".zip")

        before = load_bundle(bundle)
        imported_root = import_bundle(out_zip, self.tmp / "imported")
        after = load_bundle(imported_root)

        self.assertEqual(before.manifest, after.manifest)
        self.assertEqual(before.steps, after.steps)
        self.assertEqual(before.console, after.console)
        self.assertEqual(before.network, after.network)
        self.assertEqual(before.dom_snapshot, after.dom_snapshot)
        self.assertEqual(
            [p.name for p in before.screenshots], [p.name for p in after.screenshots]
        )
        for p in before.screenshots:
            self.assertEqual(
                p.read_bytes(), (imported_root / "screenshots" / p.name).read_bytes()
            )

    def test_import_rejects_path_traversal(self):
        evil = self.tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"format": "bugbundle/1"}))
            zf.writestr("steps.json", "[]")
            zf.writestr("console.json", "[]")
            zf.writestr("network.json", "[]")
            zf.writestr("../../escape.txt", "pwned")
        with self.assertRaises(BundleError):
            import_bundle(evil, self.tmp / "evil-out")

    def test_import_rejects_non_zip(self):
        junk = self.tmp / "junk.zip"
        junk.write_bytes(b"this is not a zip")
        with self.assertRaises(BundleError):
            import_bundle(junk, self.tmp / "junk-out")

    def test_import_rejects_archive_without_manifest(self):
        nope = self.tmp / "nope.zip"
        with zipfile.ZipFile(nope, "w") as zf:
            zf.writestr("readme.txt", "hello")
        with self.assertRaises(BundleError):
            import_bundle(nope, self.tmp / "nope-out")


class TestValidationFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bugbundle-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_missing_directory(self):
        with self.assertRaises(BundleError):
            validate_bundle(self.tmp / "does-not-exist")

    def test_missing_required_file(self):
        (self.tmp / "manifest.json").write_text(json.dumps({"format": "bugbundle/1"}))
        with self.assertRaises(BundleError) as ctx:
            validate_bundle(self.tmp)
        self.assertIn("steps.json", str(ctx.exception))

    def test_malformed_json(self):
        (self.tmp / "manifest.json").write_text("{not json")
        with self.assertRaises(BundleError) as ctx:
            validate_bundle(self.tmp)
        self.assertIn("Malformed JSON", str(ctx.exception))

    def test_wrong_format_version(self):
        write_bundle(self.tmp / "b", {"format": "bugbundle/99"}, [], [], [])
        with self.assertRaises(BundleError) as ctx:
            validate_bundle(self.tmp / "b")
        self.assertIn("Unsupported bundle format", str(ctx.exception))

    def test_wrong_json_type(self):
        (self.tmp / "manifest.json").write_text('["not", "an", "object"]')
        with self.assertRaises(BundleError):
            validate_bundle(self.tmp)

    def test_write_refuses_existing_dir(self):
        write_bundle(self.tmp / "b", {}, [], [], [])
        with self.assertRaises(BundleError):
            write_bundle(self.tmp / "b", {}, [], [], [])

    def test_missing_screenshot_warns_not_fails(self):
        root = write_bundle(
            self.tmp / "b",
            {"format": "bugbundle/1", "url": "http://x", "viewport": {}},
            [{"t": "t", "action": "click", "target": "a", "screenshot": "gone.png"}],
            [],
            [],
        )
        warnings = validate_bundle(root)
        self.assertTrue(any("gone.png" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
