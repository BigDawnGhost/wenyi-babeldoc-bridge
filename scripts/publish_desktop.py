"""Publish a verified main build using the workflow's Python 3.12 interpreter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-aarch64")


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def verified_commit(run: dict, jobs: list[dict]) -> str:
    """Require the complete build, not a branch build or an old successful job."""
    commit = run.get("head_sha", "")
    names = [job["name"] for job in jobs]
    if (
        run.get("event") != "push"
        or run.get("head_branch") != "main"
        or run.get("path") != ".github/workflows/desktop-plugin.yml"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or len(jobs) != 6
        or not {"models", "assemble"} <= set(names)
        or any(
            sum(
                name.startswith("runtime (") and name.endswith(f", {target})")
                for name in names
            )
            != 1
            for target in PLATFORMS
        )
        or any(
            job["status"] != "completed"
            or job["conclusion"] != "success"
            or not job["steps"]
            or any(
                step["status"] != "completed" or step["conclusion"] != "success"
                for step in job["steps"]
            )
            for job in jobs
        )
    ):
        raise ValueError("Publication requires the complete successful main push build")
    return commit


def stable_version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Publication requires a stable three-part version")
    return tuple(map(int, value.split(".")))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_assets(directory: Path, version: str, commit: str) -> dict[str, dict]:
    manifest = json.loads(
        (directory / "desktop-plugin.json").read_text(encoding="utf-8")
    )
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
    source = f"wenyi-babeldoc-{version}-source.zip"
    with zipfile.ZipFile(directory / source) as archive:
        if archive.comment != commit.encode("ascii"):
            raise ValueError(
                "Bridge source archive is not from the selected main commit"
            )
    names = {"desktop-plugin.json", source}
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
        if result[item["name"]] != {
            "size": item["size"],
            "digest": f"sha256:{item['sha256']}",
        }:
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
    import tomllib

    repo = os.environ["GH_REPO"]
    run_id = os.environ["PLUGIN_BUILD_RUN"]
    if (
        repo != "BigDawnGhost/wenyi-babeldoc-bridge"
        or not run_id.isascii()
        or not run_id.isdecimal()
    ):
        raise ValueError("Select an official bridge build run")
    run = json.loads(gh("api", f"repos/{repo}/actions/runs/{run_id}"))
    jobs = json.loads(
        gh("api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
    )
    if jobs["total_count"] != len(jobs["jobs"]):
        raise ValueError("Build job list is incomplete")
    commit = verified_commit(run, jobs["jobs"])
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], check=True)
    version = tomllib.loads(git("show", f"{commit}:pyproject.toml"))["project"][
        "version"
    ]
    stable_version(version)
    tag = f"v{version}"
    print(f"Downloading verified main build {run_id} at {commit}", flush=True)
    directory = Path("build/verified-release") / run_id
    gh(
        "run",
        "download",
        run_id,
        "--repo",
        repo,
        "--name",
        "complete-plugin",
        "--dir",
        str(directory),
    )
    expected = verify_assets(directory, version, commit)
    pages = json.loads(
        gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100")
    )
    releases = [release for page in pages for release in page]
    release = next((item for item in releases if item["tag_name"] == tag), None)
    latest = json.loads(gh("api", f"repos/{repo}/releases/latest"))
    if release is None or release["draft"]:
        if stable_version(version) <= stable_version(
            latest["tag_name"].removeprefix("v")
        ):
            raise ValueError("Refusing to replace latest with a non-newer version")
    if release is None:
        notes = directory / "release-notes.md"
        notes.write_text(
            git("show", f"{commit}:.github/desktop-plugin-release.md"), encoding="utf-8"
        )
        release = json.loads(
            gh(
                "api",
                "--method",
                "POST",
                f"repos/{repo}/releases",
                "-f",
                f"tag_name={tag}",
                "-f",
                f"target_commitish={commit}",
                "-f",
                f"name=BabelDOC Desktop plugin {tag}",
                "-F",
                "draft=true",
                "-F",
                f"body=@{notes}",
            )
        )
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
        gh(
            "release",
            "upload",
            tag,
            "--repo",
            repo,
            *(str(directory / name) for name in missing),
        )
    for _ in range(12):
        release = json.loads(gh("api", endpoint, "-H", "Cache-Control: no-cache"))
        actual = {
            item["name"]: {"size": item["size"], "digest": item["digest"]}
            for item in release["assets"]
        }
        if actual == expected and all(
            item["state"] == "uploaded" for item in release["assets"]
        ):
            break
        time.sleep(5)
    else:
        raise ValueError("Uploaded asset set does not match the verified local files")
    if release["draft"]:
        print(f"All uploaded hashes verified; publishing {tag}", flush=True)
        gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest")
    latest = json.loads(gh("api", f"repos/{repo}/releases/latest"))
    if latest["tag_name"] != tag or latest["draft"] or latest["prerelease"]:
        raise ValueError("The verified release is not public/latest")
    print(latest["html_url"], flush=True)


if __name__ == "__main__":
    main()
