"""Native build customization shared by wheel and source installations."""

import json
import os
import subprocess
import sys
from pathlib import Path

from setuptools import setup
from setuptools_rust.build import build_rust


class BuildRust(build_rust):
    def run(self):
        if sys.platform != "win32":
            return super().run()

        # freetype-sys 0.23's bundled libpng names a nonexistent zlib include
        # directory. Use the headers from the exact locked libz-sys dependency,
        # not an unrelated system installation or an arbitrary Cargo cache entry.
        metadata = json.loads(
            subprocess.check_output(
                [
                    os.environ.get("CARGO", "cargo"),
                    "metadata",
                    "--locked",
                    "--format-version",
                    "1",
                    "--manifest-path",
                    str(Path(__file__).parent / "rust/Cargo.toml"),
                ],
                text=True,
            )
        )
        roots = {
            Path(package["manifest_path"]).parent / "src/zlib"
            for package in metadata["packages"]
            if package["name"] == "libz-sys"
        }
        if len(roots) != 1:
            raise RuntimeError("Cannot identify the locked zlib headers")
        headers = roots.pop()
        if not all((headers / name).is_file() for name in ("zlib.h", "zconf.h")):
            raise RuntimeError(f"Missing locked zlib headers in {headers}")

        # MSVC's INCLUDE is a semicolon-separated path list, including paths
        # with spaces. cc-rs preserves it when adding the Visual Studio paths.
        previous = os.environ.get("INCLUDE")
        os.environ["INCLUDE"] = str(headers) + (f";{previous}" if previous else "")
        try:
            return super().run()
        finally:
            if previous is None:
                os.environ.pop("INCLUDE", None)
            else:
                os.environ["INCLUDE"] = previous


setup(cmdclass={"build_rust": BuildRust})
