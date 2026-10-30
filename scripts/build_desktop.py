"""Build a native plugin runtime or platform-independent offline model archive.

Run in an isolated Python 3.12 environment with BabelDOC 0.5.20 and PyInstaller.
The release workflow assembles all four runtime descriptors and one asset pack.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def descriptor(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def write_runtime_zip(directory: Path, path: Path) -> None:
    """Materialize internal file/directory links without following cycles or escapes."""
    root = directory.resolve()

    def files(current: Path, ancestors: frozenset[Path]):
        resolved = current.resolve()
        if resolved in ancestors or (resolved != root and root not in resolved.parents):
            raise ValueError("Runtime contains a cyclic or external link")
        if current.is_dir():
            for child in sorted(current.iterdir()):
                yield from files(child, ancestors | {resolved})
        elif current.is_file():
            yield current
        else:
            raise ValueError("Runtime contains a non-regular entry")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for file in files(directory, frozenset()):
            bundle.write(file, file.relative_to(directory).as_posix())


def runtime(release: str) -> None:
    if version("babeldoc") != "0.5.20":
        raise RuntimeError("Desktop protocol 1 requires the tested BabelDOC 0.5.20")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "wenyi-babeldoc-plugin",
        "--distpath",
        str(DIST),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        "--collect-all",
        "babeldoc",
        "--collect-all",
        "onnxruntime",
        "--collect-submodules",
        "bitstring",
        "--collect-submodules",
        "scipy._external.array_api_compat",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "tiktoken_ext",
        "--copy-metadata",
        "wenyi-babeldoc-bridge",
        "--recursive-copy-metadata",
        "babeldoc",
        str(ROOT / "scripts/desktop_entry.py"),
    ]
    if sys.platform == "win32":
        # PyInstaller 6.16's NumPy hook only collects delvewheel DLLs when
        # INSTALLER is "pip"; our isolated build uses uv instead.
        from PyInstaller.utils.hooks import collect_delvewheel_libs_directory

        data, binaries = collect_delvewheel_libs_directory("numpy")
        for option, entries in (("--add-data", data), ("--add-binary", binaries)):
            for source, destination in entries:
                command.extend([option, f"{source}:{destination}"])
    subprocess.run(command, check=True)
    directory = DIST / "wenyi-babeldoc-plugin"
    shutil.copy(ROOT / "LICENSE", directory / "LICENSE")
    shutil.copy(ROOT / "README.md", directory / "README.md")
    (directory / "requirements.txt").write_text(
        subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True),
        encoding="utf-8",
    )
    system = {"win32": "windows", "darwin": "macos", "linux": "linux"}[sys.platform]
    arch = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64"}[
        platform.machine()
    ]
    target = f"{system}-{arch}"
    path = DIST / f"wenyi-babeldoc-{release}-{target}.zip"
    write_runtime_zip(directory, path)
    (DIST / f"{target}.json").write_text(
        json.dumps({"target": target, "version": release, "asset": descriptor(path)}),
        encoding="utf-8",
    )


def models(release: str) -> None:
    from model_assets import prepare_assets

    path = DIST / f"wenyi-babeldoc-{release}-models.zip"
    asyncio.run(prepare_assets(ROOT / "build" / "asset-cache", path))
    (DIST / "models.json").write_text(
        json.dumps({"version": release, "asset": descriptor(path)}), encoding="utf-8"
    )


def manifest(release: str) -> None:
    platforms = {}
    for target in ("windows-x86_64", "linux-x86_64", "macos-x86_64", "macos-aarch64"):
        value = json.loads((DIST / f"{target}.json").read_text())
        if value["version"] != release or value["target"] != target:
            raise ValueError("Runtime identity mismatch")
        if descriptor(DIST / value["asset"]["name"]) != value["asset"]:
            raise ValueError("Runtime checksum mismatch")
        platforms[target] = value["asset"]
    assets = json.loads((DIST / "models.json").read_text())
    if (
        assets["version"] != release
        or descriptor(DIST / assets["asset"]["name"]) != assets["asset"]
    ):
        raise ValueError("Model identity mismatch")
    (DIST / "desktop-plugin.json").write_text(
        json.dumps(
            {
                "protocol": 1,
                "version": release,
                "platforms": platforms,
                "models": assets["asset"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("runtime", "models", "manifest"))
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if args.version != version("wenyi-babeldoc-bridge"):
        parser.error("Release version must match the installed bridge package")
    DIST.mkdir(exist_ok=True)
    {"runtime": runtime, "models": models, "manifest": manifest}[args.kind](
        args.version
    )


if __name__ == "__main__":
    main()
