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
from unittest.mock import patch

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
    def test_runtime_collects_data_without_collecting_unused_python_modules(self):
        with patch.object(builder.sys, "platform", "linux"):
            command = builder.runtime_command()
        self.assertNotIn("--collect-all", command)
        self.assertIn("--collect-data", command)
        self.assertEqual(command[command.index("--collect-data") + 1], "babeldoc")
        for module in (
            "bitstring",
            "scipy._external.array_api_compat",
            "uvicorn",
            "tiktoken_ext",
        ):
            index = command.index(module)
            self.assertEqual(command[index - 1], "--collect-submodules")
        self.assertNotIn("--recursive-copy-metadata", command)
        for name in ("wenyi-babeldoc-bridge", "babeldoc"):
            index = command.index(name, command.index("tiktoken_ext"))
            self.assertEqual(command[index - 1], "--copy-metadata")

    def test_runtime_requires_only_the_headless_opencv_distribution(self):
        installed = {"babeldoc": "0.5.20", "opencv-python-headless": "4.12.0.88"}

        def version(name):
            if name not in installed:
                raise builder.PackageNotFoundError(name)
            return installed[name]

        with patch.object(builder, "version", side_effect=version):
            builder.validate_runtime_environment()
            for conflicting in (
                "opencv-python",
                "opencv-contrib-python",
                "opencv-contrib-python-headless",
            ):
                with self.subTest(conflicting=conflicting):
                    installed[conflicting] = "4.12.0.88"
                    with self.assertRaisesRegex(RuntimeError, "fresh.*environment"):
                        builder.validate_runtime_environment()
                    del installed[conflicting]
            del installed["opencv-python-headless"]
            with self.assertRaisesRegex(RuntimeError, "opencv-python-headless"):
                builder.validate_runtime_environment()
            installed["babeldoc"] = "0.5.21"
            with self.assertRaisesRegex(RuntimeError, "BabelDOC 0.5.20"):
                builder.validate_runtime_environment()

    def test_size_report_counts_installed_files_and_groups_internal_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("_internal/example/a", b"a" * 100)
                bundle.writestr("_internal/example/b", b"b" * 200)
                bundle.writestr("_internal/library.so", b"c" * 50)
                bundle.writestr("plugin", b"d" * 25)
                bundle.writestr("empty/", b"")
            report = builder.runtime_size_report(path)
            self.assertEqual(report["archive_bytes"], path.stat().st_size)
            self.assertEqual(report["unpacked_bytes"], 375)
            self.assertEqual(report["file_count"], 4)
            self.assertEqual(report["components"]["example"]["unpacked_bytes"], 300)
            self.assertEqual(report["components"]["example"]["file_count"], 2)
            self.assertEqual(report["components"]["library.so"]["unpacked_bytes"], 50)
            with zipfile.ZipFile(path) as bundle:
                compressed = sum(
                    item.compress_size
                    for item in bundle.infolist()
                    if not item.is_dir()
                )
            self.assertEqual(
                sum(row["compressed_bytes"] for row in report["components"].values()),
                compressed,
            )

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
