"""The distributable ZIP contains regular files, including framework aliases."""

import importlib.util
import os
import stat
import tempfile
import unittest
import zipfile
from importlib.metadata import PackagePath
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "build_desktop", Path(__file__).resolve().parents[2] / "scripts/build_desktop.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

notice_spec = importlib.util.spec_from_file_location(
    "release_materials",
    Path(__file__).resolve().parents[2] / "scripts/release_materials.py",
)
materials = importlib.util.module_from_spec(notice_spec)
notice_spec.loader.exec_module(materials)


class RuntimeArchiveTests(unittest.TestCase):
    def test_license_files_preserve_native_notices_but_reject_parent_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = [
                PackagePath("example.dist-info/licenses/LICENSE"),
                PackagePath("example.libs/NOTICE.txt"),
                PackagePath("example/__init__.py"),
                PackagePath("../COPYING"),
            ]
            for file in files[:3]:
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic notice", encoding="utf-8")
            dist = SimpleNamespace(files=files, locate_file=lambda file: root / file)
            self.assertEqual(
                [relative for relative, _ in materials.license_files(dist)], files[:2]
            )

    @unittest.skipIf(os.name == "nt", "Creating symlinks requires Windows privileges")
    def test_materializes_internal_framework_directory_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            version = root / "Framework/Versions/A"
            version.mkdir(parents=True)
            (version / "library").write_bytes(b"synthetic binary")
            (version / "library").chmod(0o755)
            (version.parent / "Current").symlink_to("A", target_is_directory=True)
            (root / "Framework/library").symlink_to("Versions/Current/library")
            output = Path(temporary) / "runtime.zip"
            builder.write_runtime_zip(root, output)
            with zipfile.ZipFile(output) as bundle:
                for name in (
                    "Framework/Versions/A/library",
                    "Framework/Versions/Current/library",
                    "Framework/library",
                ):
                    self.assertEqual(bundle.read(name), b"synthetic binary")
                    mode = bundle.getinfo(name).external_attr >> 16
                    self.assertTrue(stat.S_ISREG(mode))
                    self.assertTrue(mode & 0o111)

    @unittest.skipIf(os.name == "nt", "Creating symlinks requires Windows privileges")
    def test_rejects_external_and_cyclic_directory_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            root.mkdir()
            link = root / "alias"
            output = Path(temporary) / "runtime.zip"
            for destination in (root, root.parent):
                link.symlink_to(destination, target_is_directory=True)
                with self.assertRaises(ValueError):
                    builder.write_runtime_zip(root, output)
                link.unlink()
