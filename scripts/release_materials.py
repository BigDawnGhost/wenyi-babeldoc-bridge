"""Preserve third-party notices and corresponding source alongside native releases."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import sys
import zipfile
from importlib.metadata import distribution, distributions
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def requires_source(license_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:agpl|gpl|lgpl|mpl)(?:\b|v\d)|mozilla public",
            license_text,
            re.IGNORECASE,
        )
    )


def license_files(dist):
    for file in dist.files or []:
        if ".." not in file.parts and any(
            word in file.name.lower() for word in ("license", "copying", "notice")
        ):
            path = Path(dist.locate_file(file))
            if path.is_file():
                yield file, path


def runtime_notices(directory: Path) -> None:
    """Keep wheel notices, including notices for their vendored native libraries."""
    catalog = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        catalog[name] = {
            "version": dist.version,
            "project_urls": dist.metadata.get_all("Project-URL", []),
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License", ""),
        }
        for relative, source in license_files(dist):
            destination = directory / "third-party-licenses" / name / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    (directory / "third-party-packages.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copyfile(ROOT / "THIRD_PARTY.md", directory / "THIRD_PARTY.md")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        response = client.get(
            f"https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE"
        )
        response.raise_for_status()
        (directory / "PYTHON-LICENSE.txt").write_bytes(response.content)


def model_notices(bundle: zipfile.ZipFile, cache: Path, files: list[dict]) -> None:
    from fontTools.ttLib import TTFont

    notices = []
    for item in files:
        with TTFont(cache / "fonts" / item["name"]) as font:
            names = font["name"]
            notices.append(
                f"## {item['name']}\n\n"
                + "\n\n".join(
                    names.getDebugName(key) or "" for key in (0, 13, 14)
                ).strip()
            )
    bundle.writestr("licenses/FONT-COPYRIGHTS.md", "\n\n".join(notices) + "\n")
    bundle.write(ROOT / "THIRD_PARTY.md", "licenses/THIRD_PARTY.md")
    urls = {
        "OFL-1.1.txt": (
            "https://raw.githubusercontent.com/fontworks-fonts/Klee/"
            "8b0532731b63ad8a445ca341d8d7d941079b83ab/OFL.txt"
        ),
        "Apache-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    }
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name, url in urls.items():
            response = client.get(url)
            response.raise_for_status()
            bundle.writestr(f"licenses/{name}", response.content)
    tokenizer_licenses = list(license_files(distribution("tiktoken")))
    if not tokenizer_licenses:
        raise RuntimeError("The tokenizer distribution is missing its license")
    for relative, source in tokenizer_licenses:
        bundle.write(source, f"licenses/tiktoken/{relative}")


def sources(release: str, target: str) -> None:
    """Publish unmodified copyleft sources, not just links to upstream projects."""
    import pymupdf
    import shapely

    catalog = {}
    output = ROOT / "dist" / f"wenyi-babeldoc-{release}-{target}-sources.zip"
    with (
        httpx.Client(follow_redirects=True, timeout=120) as client,
        zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle,
    ):

        def add(url: str, name: str, expected: str | None = None) -> None:
            print(f"Archiving corresponding source: {name}", flush=True)
            digest = hashlib.sha256()
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with bundle.open(name, "w") as stream:
                    for chunk in response.iter_bytes(1024 * 1024):
                        digest.update(chunk)
                        stream.write(chunk)
            actual = digest.hexdigest()
            if expected and actual != expected:
                raise ValueError(f"Source checksum mismatch: {name}")
            catalog[name] = {"url": url, "sha256": actual}
            print(f"Verified source: {name}", flush=True)

        for dist in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
            name = dist.metadata["Name"]
            if name.lower() == "wenyi-babeldoc-bridge":
                continue  # The exact repository archive is a separate release asset.
            license_text = " ".join(
                [
                    dist.metadata.get("License", ""),
                    dist.metadata.get("License-Expression", ""),
                    *dist.metadata.get_all("Classifier", []),
                ]
            ).lower()
            if not requires_source(license_text):
                continue
            response = client.get(f"https://pypi.org/pypi/{name}/{dist.version}/json")
            response.raise_for_status()
            archives = [
                entry
                for entry in response.json()["urls"]
                if entry["packagetype"] == "sdist"
            ]
            if len(archives) != 1:
                raise RuntimeError(f"Review corresponding sources for {name}")
            entry = archives[0]
            add(entry["url"], entry["filename"], entry["digests"]["sha256"])
        # Native libraries bundled in wheels have their own corresponding sources.
        geos = shapely.geos_version_string
        add(
            f"https://download.osgeo.org/geos/geos-{geos}.tar.bz2",
            f"geos-{geos}.tar.bz2",
        )
        mupdf = pymupdf.mupdf_version
        add(
            f"https://mupdf.com/downloads/archive/mupdf-{mupdf}-source.tar.gz",
            f"mupdf-{mupdf}-source.tar.gz",
        )
        python = platform.python_version()
        add(
            f"https://www.python.org/ftp/python/{python}/Python-{python}.tar.xz",
            f"Python-{python}.tar.xz",
        )
        bundle.writestr("SOURCES.json", json.dumps(catalog, indent=2) + "\n")
        bundle.write(ROOT / "THIRD_PARTY.md", "THIRD_PARTY.md")
        bundle.write(
            ROOT / "dist/wenyi-babeldoc-plugin/requirements.txt", "requirements.txt"
        )


if __name__ == "__main__":
    sources(sys.argv[1], sys.argv[2])
