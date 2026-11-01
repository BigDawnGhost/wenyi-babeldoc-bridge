"""Build offline assets from BabelDOC's embedded hashes, with mirror fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx

REPOSITORY = "https://github.com/BigDawnGhost/wenyi-babeldoc-bridge"
BLOCK_SIZE = 1024 * 1024
MAX_ARCHIVE = 2 * 1024**3
MAX_UNPACKED = 6 * 1024**3


def read_reference(path: Path) -> dict:
    """Pin an immutable official archive independently of the bridge version."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("release"), str)
        or not re.fullmatch(
            r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value["release"]
        )
        or not isinstance(value.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
        or type(value.get("size")) is not int
        or not 0 < value["size"] <= MAX_ARCHIVE
    ):
        raise ValueError("Invalid model archive reference")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


async def require_https(request: httpx.Request) -> None:
    if request.url.scheme != "https":
        raise ValueError("Model asset downloads require HTTPS, including redirects")


async def download_reference(
    client: httpx.AsyncClient, reference: dict, directory: Path
) -> Path:
    """Fail closed rather than silently changing the archive hash on an outage."""
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"{reference['sha256']}.zip"
    if (
        archive.is_file()
        and archive.stat().st_size == reference["size"]
        and await asyncio.to_thread(_sha256, archive) == reference["sha256"]
    ):
        return archive
    release = reference["release"]
    url = (
        f"{REPOSITORY}/releases/download/v{release}/wenyi-babeldoc-{release}-models.zip"
    )
    temporary = archive.with_suffix(".part")
    digest = hashlib.sha256()
    count = 0
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                async for block in response.aiter_bytes(BLOCK_SIZE):
                    count += len(block)
                    if count > reference["size"]:
                        raise ValueError("Model reference exceeds its declared size")
                    stream.write(block)
                    digest.update(block)
        if count != reference["size"] or digest.hexdigest() != reference["sha256"]:
            raise ValueError("Model reference checksum mismatch")
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def _members(bundle: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Accept only the regular, unambiguous members Desktop can install."""
    entries = bundle.infolist()
    if len(entries) > 100_000 or sum(item.file_size for item in entries) > MAX_UNPACKED:
        raise ValueError("Model archive is too large")
    result = {}
    names = set()
    for item in entries:
        name = item.filename
        path = PurePosixPath(name)
        if (
            not name
            or item.orig_filename != name
            or str(path) != name
            or not path.parts
            or path.is_absolute()
            or any(
                part in {"", ".", ".."}
                or "\\" in part
                or ":" in part
                or part.endswith((".", " "))
                for part in path.parts
            )
            or item.is_dir()
            or item.flag_bits & 1
            or stat.S_IFMT(item.external_attr >> 16) not in {0, stat.S_IFREG}
            or name.casefold() in names
        ):
            raise ValueError(f"Invalid model archive member: {name}")
        names.add(name.casefold())
        result[name] = item
    return result


def _same_contents(
    candidate: zipfile.ZipFile,
    reference: zipfile.ZipFile,
    current: dict[str, zipfile.ZipInfo],
    previous: dict[str, zipfile.ZipInfo],
) -> bool:
    if current.keys() != previous.keys():
        return False
    for name, item in current.items():
        if item.file_size != previous[name].file_size:
            return False
        with candidate.open(item) as left, reference.open(previous[name]) as right:
            while True:
                block = left.read(BLOCK_SIZE)
                if block != right.read(BLOCK_SIZE):
                    return False
                if not block:
                    break
    return True


def publish_archive(candidate: Path, reference: Path, output: Path) -> bool:
    """Reuse identical payloads byte-for-byte; canonicalize genuinely new assets."""
    if output.resolve() in {candidate.resolve(), reference.resolve()}:
        raise ValueError("Model output must not overwrite an archive input")
    with (
        zipfile.ZipFile(candidate) as current,
        zipfile.ZipFile(reference) as previous,
        tempfile.TemporaryDirectory(
            prefix=".model-archive-", dir=output.parent
        ) as stage,
    ):
        current_members, previous_members = _members(current), _members(previous)
        reused = _same_contents(current, previous, current_members, previous_members)
        temporary = Path(stage) / "models.zip"
        if reused:
            shutil.copyfile(reference, temporary)
        else:
            with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
                for name, item in sorted(current_members.items()):
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.file_size = item.file_size
                    with current.open(item) as source, bundle.open(info, "w") as target:
                        shutil.copyfileobj(source, target, BLOCK_SIZE)
        if temporary.stat().st_size > MAX_ARCHIVE:
            raise ValueError("Model archive exceeds the Desktop download limit")
        os.replace(temporary, output)
    return reused


async def prepare_assets(cache: Path, output: Path, *, reference: dict) -> None:
    from babeldoc.assets.assets import generate_all_assets_file_list, verify_file
    from babeldoc.assets.embedding_assets_metadata import (
        DOC_LAYOUT_ONNX_MODEL_URL,
        FONT_URL_BY_UPSTREAM,
        TABLE_DETECTION_RAPIDOCR_MODEL_URL,
    )

    files = generate_all_assets_file_list()
    semaphore = asyncio.Semaphore(3)

    async def fetch(client, group, item):
        name, checksum = item["name"], item["sha3_256"]
        destination = cache / group / name
        if verify_file(destination, checksum):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        if group == "fonts":
            urls = [
                FONT_URL_BY_UPSTREAM[key](name)
                for key in ("github", "huggingface", "modelscope")
            ]
        elif group == "models":
            sources = (
                DOC_LAYOUT_ONNX_MODEL_URL
                if name.startswith("doclayout_")
                else TABLE_DETECTION_RAPIDOCR_MODEL_URL
            )
            urls = [
                sources[key]
                for key in ("huggingface", "modelscope", "hf-mirror")
                if key in sources
            ]
        else:
            url = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
            if name != hashlib.sha1(url.encode()).hexdigest():
                raise ValueError(
                    "Unrecognized tokenizer asset; update the build adapter"
                )
            urls = [url]
        temporary = destination.with_suffix(".part")
        async with semaphore:
            for url in urls:
                try:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with temporary.open("wb") as stream:
                            async for chunk in response.aiter_bytes(256 * 1024):
                                stream.write(chunk)
                    if not verify_file(temporary, checksum):
                        raise ValueError("Asset checksum mismatch")
                    os.replace(temporary, destination)
                    print(f"Verified {group}/{name}", flush=True)
                    return
                except (httpx.HTTPError, ValueError):
                    temporary.unlink(missing_ok=True)
            raise RuntimeError(f"All mirrors failed for {group}/{name}")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=60,
        event_hooks={"request": [require_https]},
    ) as client:
        baseline = await download_reference(
            client, reference, cache.parent / "model-archives"
        )
        await asyncio.gather(
            *[
                fetch(client, group, item)
                for group, items in files.items()
                for item in items
            ]
        )
    with tempfile.TemporaryDirectory(
        prefix=".model-assets-", dir=output.parent
    ) as stage:
        candidate = Path(stage) / "candidate.zip"
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as bundle:
            from release_materials import model_notices

            model_notices(bundle, cache, files["fonts"])
            for group, items in files.items():
                for item in items:
                    path = cache / group / item["name"]
                    if not verify_file(path, item["sha3_256"]):
                        raise ValueError("Asset changed before packaging")
                    bundle.write(path, f"{group}/{item['name']}")
        reused = publish_archive(candidate, baseline, output)
    print(
        f"Reused model/font archive from v{reference['release']} without repacking."
        if reused
        else "Model/font files or notices changed; built a new canonical archive.",
        flush=True,
    )
