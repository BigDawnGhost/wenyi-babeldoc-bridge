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
    def test_windows_collects_every_wheels_dlls_and_load_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("numpy", "hyperscan"):
                directory = root / f"{name}.libs"
                directory.mkdir()
                (directory / "native.dll").write_bytes(b"synthetic DLL")
                (directory / ".load-order").write_text("native.dll", encoding="utf-8")
            options = builder.windows_dll_options(root)
            for name in ("numpy", "hyperscan"):
                directory = root / f"{name}.libs"
                self.assertIn(f"{directory / 'native.dll'}:{name}.libs", options)
                self.assertIn(f"{directory / '.load-order'}:{name}.libs", options)
            self.assertEqual(options.count("--add-binary"), 2)
            self.assertEqual(options.count("--add-data"), 2)

    def test_source_selection_uses_license_names_not_substrings(self):
        for text in ("AGPL-3.0", "GPLv2 with exception", "MPL-2.0", "LGPL-2.1"):
            self.assertTrue(materials.requires_source(text))
        for text in ("MIT: example", "BSD: implied warranty", "Apache-2.0"):
            self.assertFalse(materials.requires_source(text))

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
