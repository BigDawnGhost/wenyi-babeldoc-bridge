"""Build offline assets from BabelDOC's embedded hashes, with mirror fallback."""

from __future__ import annotations

import asyncio
import hashlib
import os
import zipfile
from pathlib import Path

import httpx


async def prepare_assets(cache: Path, output: Path) -> None:
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

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        await asyncio.gather(
            *[
                fetch(client, group, item)
                for group, items in files.items()
                for item in items
            ]
        )
    temporary = output.with_suffix(".part")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
        for group, items in files.items():
            for item in items:
                path = cache / group / item["name"]
                if not verify_file(path, item["sha3_256"]):
                    raise ValueError("Asset changed before packaging")
                bundle.write(path, f"{group}/{item['name']}")
    os.replace(temporary, output)
