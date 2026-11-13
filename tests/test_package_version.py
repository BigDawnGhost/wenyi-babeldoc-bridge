"""Version-source contracts for package builds and source-only probes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import tomllib
import unittest
import zipfile
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from setuptools_scm import get_version

ROOT = Path(__file__).resolve().parents[1]


class PackageVersionTests(unittest.TestCase):
    def test_native_package_uses_git_instead_of_a_static_version(self):
        with (ROOT / "pyproject.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertNotIn("version", config["project"])
        self.assertEqual(config["project"]["dynamic"], ["version"])
        self.assertIn("setuptools-scm>=8", config["build-system"]["requires"])
        self.assertIn("setuptools_scm", config["tool"])
        extension = config["tool"]["setuptools-rust"]["ext-modules"][0]
        self.assertEqual(extension["target"], "wenyi_babeldoc_bridge._native")
        self.assertTrue(extension["py-limited-api"])

    def test_bridge_does_not_install_pdf2zh_frontends(self):
        from packaging.requirements import Requirement

        with (ROOT / "pyproject.toml").open("rb") as source:
            config = tomllib.load(source)
        extras = config["project"].get("optional-dependencies", {})
        self.assertNotIn("zotero", extras)
        dependencies = [
            *config["project"]["dependencies"],
            *(item for requirements in extras.values() for item in requirements),
        ]
        names = {
            Requirement(item).name.lower().replace("_", "-") for item in dependencies
        }
        self.assertTrue(names.isdisjoint({"pdf2zh", "pdf2zh-next"}))

    def test_desktop_and_http_use_the_same_babeldoc_generation(self):
        from packaging.requirements import Requirement

        with (ROOT / "pyproject.toml").open("rb") as source:
            config = tomllib.load(source)
        dependency = next(
            Requirement(item)
            for item in config["project"]["dependencies"]
            if Requirement(item).name == "babeldoc"
        )
        constraints = (ROOT / "desktop-constraints.txt").read_text().splitlines()
        pin = next(item for item in constraints if item.startswith("babeldoc=="))
        self.assertEqual(pin, "babeldoc==0.7.1")
        self.assertIn("0.7.1", dependency.specifier)
        self.assertNotIn("0.7.2", dependency.specifier)
        self.assertNotIn("0.5.20", dependency.specifier)

    def test_pymupdf_stays_on_1x_without_a_minor_pin(self):
        from packaging.requirements import Requirement

        with (ROOT / "pyproject.toml").open("rb") as source:
            config = tomllib.load(source)
        dependency = next(
            Requirement(item)
            for item in config["project"]["dependencies"]
            if Requirement(item).name == "pymupdf"
        )
        self.assertIsNone(dependency.marker)
        for version in ("1.26.7", "1.28.2", "1.99.0"):
            with self.subTest(allowed=version):
                self.assertIn(version, dependency.specifier)
        for version in ("1.26.6", "2.0", "2.1", "3.0"):
            with self.subTest(rejected=version):
                self.assertNotIn(version, dependency.specifier)

    def test_scm_tracks_tags_commits_and_dirty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {**os.environ, "GIT_EDITOR": "true"}

            def git(*arguments):
                return subprocess.check_output(
                    ["git", "-C", str(root), *arguments],
                    env=environment,
                    stderr=subprocess.STDOUT,
                    text=True,
                )

            git("init")
            git("config", "user.name", "Packaging Test")
            git("config", "user.email", "packaging@example.invalid")
            source = root / "source"
            source.write_text("initial")
            git("add", "source")
            git("-c", "core.hooksPath=/dev/null", "commit", "-m", "initial")
            git("tag", "v1.2.3")
            self.assertEqual(get_version(root=str(root)), "1.2.3")
            source.write_text("next")
            self.assertIn("dev", get_version(root=str(root)))
            git("add", "source")
            git("-c", "core.hooksPath=/dev/null", "commit", "-m", "next")
            self.assertIn("dev", get_version(root=str(root)))
            git("tag", "v1.2.4rc1")
            self.assertEqual(get_version(root=str(root)), "1.2.4rc1")

    def test_git_source_archive_preserves_its_tag_version_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            repository.mkdir()
            environment = {**os.environ, "GIT_EDITOR": "true"}

            def git(*arguments):
                return subprocess.check_output(
                    ["git", "-C", str(repository), *arguments],
                    env=environment,
                    stderr=subprocess.STDOUT,
                )

            for name in (".git_archival.txt", ".gitattributes"):
                (repository / name).write_bytes((ROOT / name).read_bytes())
            git("init")
            git("config", "user.name", "Packaging Test")
            git("config", "user.email", "packaging@example.invalid")
            git("add", ".")
            git("commit", "-m", "archive fixture")
            git("tag", "v7.8.9")
            for development in (False, True):
                if development:
                    git("commit", "--allow-empty", "-m", "development fixture")
                archive = root / "source.zip"
                archive.write_bytes(git("archive", "--format=zip", "HEAD"))
                unpacked = root / f"unpacked-{development}"
                with zipfile.ZipFile(archive) as source:
                    source.extractall(unpacked)
                self.assertFalse((unpacked / ".git").exists())
                self.assertEqual(
                    get_version(root=str(unpacked)), get_version(root=str(repository))
                )

    def load_package(self, metadata_version):
        path = ROOT / "src/wenyi_babeldoc_bridge/__init__.py"
        spec = importlib.util.spec_from_file_location("bridge_version_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch("importlib.metadata.version") as lookup:
            if isinstance(metadata_version, Exception):
                lookup.side_effect = metadata_version
            else:
                lookup.return_value = metadata_version
            spec.loader.exec_module(module)
            lookup.assert_called_once_with("wenyi-babeldoc-bridge")
        return module

    def test_runtime_version_comes_from_installed_metadata(self):
        self.assertEqual(self.load_package("1.2.3").__version__, "1.2.3")

    def test_uninstalled_source_probe_has_an_explicit_unknown_version(self):
        self.assertEqual(
            self.load_package(PackageNotFoundError()).__version__, "0+unknown"
        )


if __name__ == "__main__":
    unittest.main()
