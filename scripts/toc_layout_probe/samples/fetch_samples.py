"""Opt in to fetching, or offline verification of, pinned public PDF samples."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

SAMPLES = Path(__file__).resolve().parent
MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3


def matches(path: Path, size: int, sha256: str) -> bool:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == sha256


def download(url: str, output: Path) -> None:
    publisher = urlsplit(url).netloc
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != publisher
            or not parsed.hostname
        ):
            raise ValueError(f"expected HTTPS on the publisher host, got {url}")
        result = subprocess.run(
            [
                "curl",
                "-q",
                "--globoff",
                "--proto",
                "=https",
                "--fail",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "7",
                "--max-time",
                "30",
                "--max-filesize",
                str(MAX_BYTES),
                "--output",
                str(output),
                "--write-out",
                "%{http_code}\n%{redirect_url}",
                "--url",
                url,
            ],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        status, _, redirect = result.stdout.partition("\n")
        if status == "200":
            return
        if status not in {"301", "302", "303", "307", "308"} or not redirect:
            raise ValueError(
                f"expected a complete PDF response, got HTTP {status} from {url}"
            )
        url = redirect
    raise ValueError(f"too many redirects from {publisher}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check the existing cache without networking.",
    )
    args = parser.parse_args()

    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    cache = SAMPLES / ".cache"
    if cache.is_symlink():
        parser.exit(1, f"Refusing a symlinked cache: {cache}\n")

    failed = False
    for sample in manifest:
        name, size, sha256 = sample["file"], sample["bytes"], sample["sha256"]
        target = cache / name
        try:
            if matches(target, size, sha256):
                print(f"Verified cached {name}")
                continue
            if args.verify_only:
                raise ValueError(
                    "missing or wrong size/SHA-256; run again without --verify-only"
                )
            cache.mkdir(exist_ok=True)
            with TemporaryDirectory(dir=cache, prefix=".download-") as temp:
                candidate = Path(temp) / name
                download(sample["url"], candidate)
                if not matches(candidate, size, sha256):
                    raise ValueError("download does not match the pinned size/SHA-256")
                candidate.replace(target)
            print(f"Downloaded and verified {name}")
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"{name}: {exc}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
