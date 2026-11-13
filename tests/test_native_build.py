"""The native source build supplies locked zlib headers on Windows."""

import json
import os
import runpy
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class NativeBuildTests(unittest.TestCase):
    def run_build(self, platform, packages, build):
        class BaseBuild:
            def run(self):
                return build()

        setup = Mock()
        modules = {
            "setuptools": types.SimpleNamespace(setup=setup),
            "setuptools_rust.build": types.SimpleNamespace(build_rust=BaseBuild),
        }
        with (
            patch.dict("sys.modules", modules),
            patch("sys.platform", platform),
            patch(
                "subprocess.check_output",
                return_value=json.dumps({"packages": packages}),
            ) as cargo,
        ):
            runpy.run_path(str(ROOT / "setup.py"), run_name="__main__")
            setup.call_args.kwargs["cmdclass"]["build_rust"]().run()
        return cargo

    def test_windows_uses_locked_headers_and_restores_existing_include(self):
        with tempfile.TemporaryDirectory(prefix="native headers ") as directory:
            root = Path(directory)
            headers = root / "src/zlib"
            headers.mkdir(parents=True)
            for name in ("zlib.h", "zconf.h"):
                (headers / name).touch()
            packages = [{"name": "libz-sys", "manifest_path": str(root / "Cargo.toml")}]
            with patch.dict(os.environ, {"INCLUDE": "existing;compiler headers"}):
                cargo = self.run_build(
                    "win32",
                    packages,
                    lambda: self.assertEqual(
                        os.environ["INCLUDE"], f"{headers};existing;compiler headers"
                    ),
                )
                self.assertEqual(os.environ["INCLUDE"], "existing;compiler headers")
            self.assertIn("--locked", cargo.call_args.args[0])

    def test_windows_rejects_missing_headers_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Mock()
            with self.assertRaisesRegex(RuntimeError, "zlib headers"):
                self.run_build(
                    "win32",
                    [
                        {
                            "name": "libz-sys",
                            "manifest_path": str(Path(directory) / "Cargo.toml"),
                        }
                    ],
                    build,
                )
            build.assert_not_called()

    def test_other_platforms_do_not_change_the_build_environment(self):
        build = Mock()
        cargo = self.run_build("linux", [], build)
        build.assert_called_once_with()
        cargo.assert_not_called()
