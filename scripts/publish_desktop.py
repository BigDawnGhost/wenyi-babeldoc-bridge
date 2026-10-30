"""Publish an explicitly pinned, successful build; never overwrite release assets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-aarch64")


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_assets(directory: Path, version: str) -> dict[str, dict]:
    manifest_path = directory / "desktop-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest["protocol"] != 1
        or manifest["version"] != version
        or set(manifest["platforms"]) != set(PLATFORMS)
        or any(
            manifest["platforms"][target]["name"]
            != f"wenyi-babeldoc-{version}-{target}.zip"
            for target in PLATFORMS
        )
    ):
        raise ValueError("Release manifest identity mismatch")
    names = {"desktop-plugin.json", f"wenyi-babeldoc-{version}-source.zip"}
    for target in PLATFORMS:
        names.add(f"wenyi-babeldoc-{version}-{target}-sources.zip")
    assets = [*manifest["platforms"].values(), manifest["models"]]
    expected_names = {
        *(f"wenyi-babeldoc-{version}-{target}.zip" for target in PLATFORMS),
        f"wenyi-babeldoc-{version}-models.zip",
    }
    if {item["name"] for item in assets} != expected_names:
        raise ValueError("Unexpected downloadable assets")
    names.update(expected_names)
    result = {}
    for name in sorted(names):
        path = directory / name
        result[name] = {"size": path.stat().st_size, "digest": f"sha256:{sha256(path)}"}
        if name.endswith("-sources.zip"):
            with zipfile.ZipFile(path) as archive:
                if not {"SOURCES.json", "requirements.txt", "THIRD_PARTY.md"} <= set(
                    archive.namelist()
                ):
                    raise ValueError("Missing corresponding source materials")
    for item in assets:
        actual = result[item["name"]]
        if actual != {"size": item["size"], "digest": f"sha256:{item['sha256']}"}:
            raise ValueError(f"Manifest checksum mismatch: {item['name']}")
    checksums = directory / "SHA256SUMS"
    checksums.write_text(
        "".join(
            f"{value['digest'].removeprefix('sha256:')}  {name}\n"
            for name, value in result.items()
        ),
        encoding="utf-8",
    )
    result[checksums.name] = {
        "size": checksums.stat().st_size,
        "digest": f"sha256:{sha256(checksums)}",
    }
    return result


def main() -> None:
    repo = os.environ["GH_REPO"]
    version = os.environ["PLUGIN_VERSION"]
    run_id = os.environ["PLUGIN_BUILD_RUN"]
    commit = os.environ["PLUGIN_BUILD_SHA"]
    tag = f"v{version}"
    run = json.loads(gh("run", "view", run_id, "--json", "headSha,status,conclusion"))
    if run != {"headSha": commit, "status": "completed", "conclusion": "success"}:
        raise ValueError("Publication requires the exact successful build")
    print(f"Downloading verified build {run_id} at {commit}", flush=True)
    directory = Path("build/verified-release")
    gh("run", "download", run_id, "--name", "complete-plugin", "--dir", str(directory))
    expected = verify_assets(directory, version)
    releases_path = f"repos/{repo}/releases?per_page=100"
    releases = json.loads(gh("api", releases_path))
    release = next((item for item in releases if item["tag_name"] == tag), None)
    if release is None:
        gh(
            "release",
            "create",
            tag,
            "--target",
            commit,
            "--title",
            f"BabelDOC Desktop plugin {tag}",
            "--draft",
            "--notes-file",
            ".github/desktop-plugin-release.md",
        )
        releases = json.loads(gh("api", releases_path))
        release = next(item for item in releases if item["tag_name"] == tag)
    # The tag lookup only guarantees published releases; use the ID for drafts.
    endpoint = f"repos/{repo}/releases/{release['id']}"
    if release["target_commitish"] != commit or release["prerelease"]:
        raise ValueError("Existing release points to a different candidate")
    existing = {asset["name"]: asset for asset in release["assets"]}
    for name, asset in existing.items():
        if name not in expected or any(
            asset[field] != expected[name][field] for field in ("size", "digest")
        ):
            raise ValueError(f"Refusing to overwrite a different release asset: {name}")
    missing = sorted(set(expected) - set(existing))
    if missing:
        if not release["draft"]:
            raise ValueError("Refusing to modify an already published release")
        print(f"Uploading {len(missing)} assets to draft {tag}", flush=True)
        gh("release", "upload", tag, *(str(directory / name) for name in missing))
    release = json.loads(gh("api", endpoint))
    actual = {
        item["name"]: {"size": item["size"], "digest": item["digest"]}
        for item in release["assets"]
    }
    if actual != expected:
        raise ValueError("Uploaded asset set does not match the verified local files")
    if release["draft"]:
        print(f"All uploaded hashes verified; publishing {tag}", flush=True)
        gh("release", "edit", tag, "--draft=false", "--latest")
    latest = json.loads(gh("api", f"repos/{repo}/releases/latest"))
    if latest["tag_name"] != tag or latest["draft"]:
        raise ValueError("The verified release is not public/latest")
    print(latest["html_url"], flush=True)


if __name__ == "__main__":
    main()
