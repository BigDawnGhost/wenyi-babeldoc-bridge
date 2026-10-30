"""Offline checks for the publication gate; no GitHub writes or real archives."""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "publish_desktop",
    Path(__file__).resolve().parents[2] / "scripts/publish_desktop.py",
)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def fixture(self, directory):
        def asset(target):
            path = directory / f"wenyi-babeldoc-0.1.0-{target}.zip"
            path.write_bytes(b"synthetic archive")
            return {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": publisher.sha256(path),
            }

        manifest = {
            "protocol": 1,
            "version": "0.1.0",
            "platforms": {target: asset(target) for target in publisher.PLATFORMS},
            "models": asset("models"),
        }
        asset("source")
        for target in publisher.PLATFORMS:
            path = directory / f"wenyi-babeldoc-0.1.0-{target}-sources.zip"
            with zipfile.ZipFile(path, "w") as archive:
                for name in ("SOURCES.json", "requirements.txt", "THIRD_PARTY.md"):
                    archive.writestr(name, "synthetic source record")
        (directory / "desktop-plugin.json").write_text(json.dumps(manifest))
        return manifest

    def test_complete_assets_are_hashed_and_missing_sources_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            assets = publisher.verify_assets(directory, "0.1.0")
            self.assertEqual(len(assets), 12)
            self.assertIn("SHA256SUMS", assets)
            (directory / "wenyi-babeldoc-0.1.0-linux-x86_64-sources.zip").unlink()
            with self.assertRaises(FileNotFoundError):
                publisher.verify_assets(directory, "0.1.0")

    def test_tampered_downloads_and_swapped_platforms_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = self.fixture(directory)
            (directory / manifest["models"]["name"]).write_bytes(b"changed archive")
            with self.assertRaisesRegex(ValueError, "checksum"):
                publisher.verify_assets(directory, "0.1.0")
            manifest = self.fixture(directory)
            platforms = manifest["platforms"]
            platforms["windows-x86_64"], platforms["linux-x86_64"] = (
                platforms["linux-x86_64"],
                platforms["windows-x86_64"],
            )
            (directory / "desktop-plugin.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "identity"):
                publisher.verify_assets(directory, "0.1.0")
