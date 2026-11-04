"""Version-source contracts for package builds and source-only probes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import tomllib
import unittest
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

from setuptools_scm import get_version

ROOT = Path(__file__).resolve().parents[1]


class PackageVersionTests(unittest.TestCase):
    def test_hatch_uses_git_instead_of_a_static_version(self):
        with (ROOT / "pyproject.toml").open("rb") as source:
            config = tomllib.load(source)
        self.assertNotIn("version", config["project"])
        self.assertEqual(config["project"]["dynamic"], ["version"])
        self.assertIn("hatch-vcs", config["build-system"]["requires"])
        self.assertEqual(config["tool"]["hatch"]["version"]["source"], "vcs")

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
