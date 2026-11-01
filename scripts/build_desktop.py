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
import sysconfig
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

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


def runtime_size_report(path: Path) -> dict:
    """Measure the ZIP as installed, including materialized library aliases."""
    components: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(path) as bundle:
        for item in bundle.infolist():
            if item.is_dir():
                continue
            parts = PurePosixPath(item.filename).parts
            name = parts[1] if parts[0] == "_internal" else parts[0]
            row = components.setdefault(
                name, {"file_count": 0, "unpacked_bytes": 0, "compressed_bytes": 0}
            )
            row["file_count"] += 1
            row["unpacked_bytes"] += item.file_size
            row["compressed_bytes"] += item.compress_size
    return {
        "archive": path.name,
        "archive_bytes": path.stat().st_size,
        "unpacked_bytes": sum(row["unpacked_bytes"] for row in components.values()),
        "file_count": sum(row["file_count"] for row in components.values()),
        "components": dict(
            sorted(
                components.items(),
                key=lambda item: (-item[1]["compressed_bytes"], item[0]),
            )
        ),
    }


def windows_dll_options(site_packages: Path) -> list[str]:
    """Preserve delvewheel libraries and load order, independent of import order."""
    options = []
    for directory in sorted(site_packages.glob("*.libs")):
        for source in sorted(directory.rglob("*")):
            if source.is_file():
                relative = source.relative_to(site_packages)
                kind = (
                    "--add-binary" if source.suffix.lower() == ".dll" else "--add-data"
                )
                options.extend([kind, f"{source}:{relative.parent.as_posix()}"])
    return options


def validate_runtime_environment() -> None:
    if version("babeldoc") != "0.5.20":
        raise RuntimeError("Desktop protocol 1 requires the tested BabelDOC 0.5.20")
    for name in (
        "opencv-python",
        "opencv-contrib-python",
        "opencv-contrib-python-headless",
    ):
        try:
            version(name)
        except PackageNotFoundError:
            continue
        raise RuntimeError(
            f"{name} overlaps opencv-python-headless. Use a fresh Desktop build "
            "environment with --excludes desktop-excludes.txt."
        )
    try:
        version("opencv-python-headless")
    except PackageNotFoundError:
        raise RuntimeError("Desktop builds require opencv-python-headless") from None


def runtime_command() -> list[str]:
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
        # Keep BabelDOC's CMaps and IL resources, but let import analysis select
        # Python modules. ONNX Runtime's standard hook collects native providers;
        # collecting all its tools/transformers/quantizers is not needed to infer.
        "--collect-data",
        "babeldoc",
        "--collect-submodules",
        "bitstring",
        "--collect-submodules",
        "scipy._external.array_api_compat",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "tiktoken_ext",
        # Preserve explicit version identities without traversing RapidOCR's
        # replaced GUI dependency. Dependency hooks retain their own metadata.
        "--copy-metadata",
        "wenyi-babeldoc-bridge",
        "--copy-metadata",
        "babeldoc",
        str(ROOT / "scripts/desktop_entry.py"),
    ]
    if sys.platform == "win32":
        # Some upstream hooks assume INSTALLER="pip", but this build uses uv.
        # Worker imports differ from server imports: preserve every wheel's DLL set.
        command.extend(windows_dll_options(Path(sysconfig.get_path("platlib"))))
    return command


def runtime(release: str) -> None:
    validate_runtime_environment()
    subprocess.run(runtime_command(), check=True)
    directory = DIST / "wenyi-babeldoc-plugin"
    shutil.copy(ROOT / "LICENSE", directory / "LICENSE")
    shutil.copy(ROOT / "README.md", directory / "README.md")
    (directory / "requirements.txt").write_text(
        subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True),
        encoding="utf-8",
    )
    from release_materials import runtime_notices

    runtime_notices(directory)
    system = {"win32": "windows", "darwin": "macos", "linux": "linux"}[sys.platform]
    arch = {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64"}[
        platform.machine()
    ]
    target = f"{system}-{arch}"
    path = DIST / f"wenyi-babeldoc-{release}-{target}.zip"
    write_runtime_zip(directory, path)
    report = runtime_size_report(path)
    (DIST / f"{target}-size.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Runtime ZIP: {report['archive_bytes'] / 1024**2:.2f} MiB; "
        f"unpacked: {report['unpacked_bytes'] / 1024**2:.2f} MiB. "
        f"Component sizes: {target}-size.json",
        flush=True,
    )
    (DIST / f"{target}.json").write_text(
        json.dumps({"target": target, "version": release, "asset": descriptor(path)}),
        encoding="utf-8",
    )


def models(release: str) -> None:
    from model_assets import prepare_assets, read_reference

    path = DIST / f"wenyi-babeldoc-{release}-models.zip"
    reference = read_reference(ROOT / "desktop-models.json")
    asyncio.run(
        prepare_assets(ROOT / "build" / "asset-cache", path, reference=reference)
    )
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
