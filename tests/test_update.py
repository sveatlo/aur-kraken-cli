import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "update", Path(__file__).resolve().parents[1] / "scripts/update.py"
)
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for package in update.ARTIFACTS:
            destination = self.root / "packages" / package
            destination.mkdir(parents=True)
            (destination / "PKGBUILD").write_text(
                (update.ROOT / "packages" / package / "PKGBUILD").read_text()
            )
            (destination / ".SRCINFO").write_text("original metadata\n")
        self.root_patch = patch.object(update, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def recipe(self, package="kraken-cli"):
        return self.root / "packages" / package / "PKGBUILD"

    def test_latest_release_authenticates_when_token_is_available(self):
        def respond(request, timeout):
            self.assertEqual(
                request.full_url,
                "https://api.github.com/repos/krakenfx/kraken-cli/releases/latest",
            )
            if request.get_header("Authorization") != "Bearer test-token":
                raise urllib.error.HTTPError(
                    request.full_url, 403, "rate limit exceeded", {}, None
                )
            return io.BytesIO(b'{"draft": false, "prerelease": false, "tag_name": "v0.5.1"}')

        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), patch.object(
            update.urllib.request, "urlopen", side_effect=respond
        ):
            self.assertEqual(update.latest_version(), "0.5.1")

    def test_latest_release_works_without_token_for_local_use(self):
        def respond(request, timeout):
            self.assertIsNone(request.get_header("Authorization"))
            return io.BytesIO(b'{"draft": false, "prerelease": false, "tag_name": "v0.5.1"}')

        with patch.dict(os.environ, {}, clear=True), patch.object(
            update.urllib.request, "urlopen", side_effect=respond
        ):
            self.assertEqual(update.latest_version(), "0.5.1")

    def test_artifact_download_does_not_receive_api_token(self):
        def respond(request, timeout):
            self.assertIsNone(request.get_header("Authorization"))
            return io.BytesIO(b"artifact")

        destination = self.root / "source.tar.gz"
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), patch.object(
            update.urllib.request, "urlopen", side_effect=respond
        ):
            update.download(
                "https://github.com/krakenfx/kraken-cli/releases/download/v0.5.1/source.tar.gz",
                destination,
            )
        self.assertEqual(destination.read_bytes(), b"artifact")

    def test_rejects_unsafe_or_unstable_versions(self):
        for version in ["../main", "1.2.3-rc1", "1.2", "v1.2.3", "1.2.3\nx"]:
            with self.subTest(version=version), self.assertRaises(ValueError):
                update.validate_version(version)

    def test_resets_release_only_for_new_version(self):
        original = self.recipe().read_text().replace("pkgrel=1", "pkgrel=7")
        same = update.render_recipe(original, "0.5.1", {})
        changed = update.render_recipe(original, "0.5.2", {"sha256sums": "a" * 64})
        self.assertIn("pkgrel=7\n", same)
        self.assertIn("pkgver=0.5.2\npkgrel=1\n", changed)
        self.assertIn("sha256sums=('" + "a" * 64 + "')", changed)

    def test_refuses_downgrade_and_duplicate_fields(self):
        original = self.recipe().read_text()
        with self.assertRaises(ValueError):
            update.render_recipe(original, "0.5.0", {})
        with self.assertRaises(ValueError):
            update.render_recipe(original + "pkgver=0.5.1\n", "0.5.2", {})

    def test_signature_failure_leaves_both_recipes_unchanged(self):
        before = {package: self.recipe(package).read_text() for package in update.ARTIFACTS}
        with patch.object(update, "verified_hash", side_effect=["a" * 64, RuntimeError("bad signature")]):
            with self.assertRaisesRegex(RuntimeError, "bad signature"):
                update.update("0.5.2", list(update.ARTIFACTS))
        for package, original in before.items():
            self.assertEqual(self.recipe(package).read_text(), original)

    def test_metadata_failure_rolls_back_recipes(self):
        before = self.recipe().read_text()
        with patch.object(update, "verified_hash", return_value="a" * 64), patch.object(
            update.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, "makepkg")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                update.update("0.5.2", ["kraken-cli"])
        self.assertEqual(self.recipe().read_text(), before)
        self.assertEqual((self.recipe().parent / ".SRCINFO").read_text(), "original metadata\n")

    def test_verify_only_rejects_checksum_mismatch(self):
        before = self.recipe().read_text()
        with patch.object(update, "verified_hash", return_value="b" * 64):
            with self.assertRaisesRegex(ValueError, "differs from signed release"):
                update.update("0.5.1", ["kraken-cli"], verify_only=True)
        self.assertEqual(self.recipe().read_text(), before)

    def test_verifies_signature_before_hashing(self):
        def download(url, destination):
            destination.write_bytes(b"artifact")

        with patch.object(update, "download", side_effect=download), patch.object(
            update.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "minisign")
        ) as verify:
            with self.assertRaises(subprocess.CalledProcessError):
                update.verified_hash("0.5.1", "source.tar.gz", self.root)
        self.assertIn(update.PUBLIC_KEY, verify.call_args.args[0])
        self.assertTrue(verify.call_args.kwargs["check"])

    def test_success_updates_both_recipes_and_metadata(self):
        with patch.object(update, "verified_hash", return_value="c" * 64), patch.object(
            update.subprocess, "check_output", return_value="new metadata\n"
        ):
            update.update("0.5.2", list(update.ARTIFACTS))
        for package in update.ARTIFACTS:
            self.assertIn("pkgver=0.5.2", self.recipe(package).read_text())
            self.assertEqual((self.recipe(package).parent / ".SRCINFO").read_text(), "new metadata\n")


if __name__ == "__main__":
    unittest.main()
