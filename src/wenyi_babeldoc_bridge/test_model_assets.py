"""Model archives retain their identity across runtime-only releases."""

import asyncio
import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

spec = importlib.util.spec_from_file_location(
    "model_assets", Path(__file__).resolve().parents[2] / "scripts/model_assets.py"
)
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)

FILES = {
    "models/layout.onnx": b"synthetic weights",
    "fonts/font.ttf": b"synthetic font",
    "licenses/LICENSE": b"synthetic license",
}


def archive(path, files, *, year=2020, compression=zipfile.ZIP_STORED):
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, (year, 1, 1, 0, 0, 0))
            info.compress_type = compression
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, content)


def reference(content):
    return {
        "release": "0.1.2",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


class ModelArchiveTests(unittest.TestCase):
    def test_unchanged_payload_reuses_legacy_bytes_despite_zip_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate, output = (
                root / name for name in ("old", "new", "out")
            )
            archive(baseline, FILES)
            archive(
                candidate,
                dict(reversed(list(FILES.items()))),
                year=2026,
                compression=zipfile.ZIP_DEFLATED,
            )
            previous = baseline.read_bytes()
            self.assertNotEqual(candidate.read_bytes(), previous)
            self.assertTrue(assets.publish_archive(candidate, baseline, output))
            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(baseline.read_bytes(), previous)

    def test_changed_resources_and_notices_generate_a_new_complete_archive(self):
        changes = [
            {**FILES, name: b"x" * len(content)} for name, content in FILES.items()
        ]
        changes += [
            {**FILES, "fonts/another.ttf": b"another font"},
            {name: value for name, value in FILES.items() if name != "fonts/font.ttf"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate, output = (
                root / name for name in ("old", "new", "out")
            )
            archive(baseline, FILES)
            for files in changes:
                with self.subTest(files=sorted(files)):
                    archive(candidate, files)
                    self.assertFalse(
                        assets.publish_archive(candidate, baseline, output)
                    )
                    self.assertNotEqual(output.read_bytes(), baseline.read_bytes())
                    with zipfile.ZipFile(output) as bundle:
                        self.assertEqual(bundle.namelist(), sorted(files))
                        for name, content in files.items():
                            self.assertEqual(bundle.read(name), content)

    def test_new_archive_is_stable_across_names_timestamps_and_entry_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate = root / "baseline.zip", root / "candidate.zip"
            archive(baseline, FILES)
            files = {**FILES, "models/layout.onnx": b"new synthetic weights"}
            results = []
            for version, year in (("0.1.3", 2025), ("0.1.4", 2026)):
                files = dict(reversed(list(files.items())))
                archive(candidate, files, year=year)
                output = root / f"wenyi-babeldoc-{version}-models.zip"
                self.assertFalse(assets.publish_archive(candidate, baseline, output))
                results.append(output.read_bytes())
                with zipfile.ZipFile(output) as bundle:
                    for item in bundle.infolist():
                        self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                        self.assertEqual(item.create_system, 3)
                        self.assertEqual(item.external_attr >> 16, stat.S_IFREG | 0o644)
            self.assertEqual(*results)

    def test_invalid_reference_cannot_replace_a_completed_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate, output = (
                root / name for name in ("old", "new", "out")
            )
            archive(candidate, FILES)
            output.write_bytes(b"previous completed output")
            baseline.write_bytes(b"not a zip")
            with self.assertRaises(zipfile.BadZipFile):
                assets.publish_archive(candidate, baseline, output)
            self.assertEqual(output.read_bytes(), b"previous completed output")
            self.assertEqual(
                sorted(path.name for path in root.iterdir()), ["new", "old", "out"]
            )

    def test_reference_rejects_duplicate_alias_and_link_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline, candidate, output = (
                root / name for name in ("old", "new", "out")
            )
            archive(candidate, FILES)
            for extra, mode in (
                ("fonts/font.ttf", stat.S_IFREG | 0o644),
                ("fonts/FONT.ttf", stat.S_IFREG | 0o644),
                ("../outside", stat.S_IFREG | 0o644),
                ("fonts/link.ttf", stat.S_IFLNK | 0o777),
            ):
                with self.subTest(extra=extra):
                    archive(baseline, FILES)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        with zipfile.ZipFile(baseline, "a") as bundle:
                            item = zipfile.ZipInfo(extra)
                            item.external_attr = mode << 16
                            bundle.writestr(item, b"synthetic")
                    with self.assertRaises(ValueError):
                        assets.publish_archive(candidate, baseline, output)
                    self.assertFalse(output.exists())

    def test_reference_file_pins_an_official_release_size_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reference.json"
            value = reference(b"synthetic archive")
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(assets.read_reference(path), value)
            for key, bad in (
                ("release", "../outside"),
                ("release", "0.1"),
                ("release", "01.1.2"),
                ("release", "0.1.2-beta"),
                ("sha256", "invalid"),
                ("size", True),
                ("size", 0),
                ("size", 2 * 1024**3 + 1),
            ):
                with self.subTest(key=key, value=bad):
                    path.write_text(json.dumps({**value, key: bad}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        assets.read_reference(path)
            for bad in ([], None):
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    assets.read_reference(path)

    def test_reference_download_reuses_only_a_verified_cache(self):
        async def run():
            content = b"synthetic reference archive"
            item = reference(content)
            requests = []

            def handler(request):
                requests.append(str(request.url))
                return httpx.Response(200, content=content)

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                async with httpx.AsyncClient(
                    transport=httpx.MockTransport(handler)
                ) as client:
                    path = await assets.download_reference(client, item, root)
                    self.assertEqual(path.read_bytes(), content)
                    self.assertEqual(path.name, f"{item['sha256']}.zip")
                    self.assertEqual(
                        await assets.download_reference(client, item, root), path
                    )
                    self.assertEqual(len(requests), 1)
                    path.write_bytes(b"x" * len(content))
                    await assets.download_reference(client, item, root)
                    self.assertEqual(path.read_bytes(), content)
                    self.assertEqual(len(requests), 2)
                self.assertTrue(
                    requests[0].endswith(
                        "/releases/download/v0.1.2/wenyi-babeldoc-0.1.2-models.zip"
                    )
                )
                self.assertFalse(list(root.glob("*.part")))

        asyncio.run(run())

    def test_bad_or_unavailable_reference_download_fails_without_partial_files(self):
        async def run():
            content = b"synthetic reference archive"
            item = reference(content)
            responses = [
                (200, b"x" * len(content)),
                (200, content + b"oversized"),
                (200, b"short"),
                (503, b"unavailable"),
            ]
            for status, body in responses:
                with self.subTest(status=status, body=body):
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        async with httpx.AsyncClient(
                            transport=httpx.MockTransport(
                                lambda _: httpx.Response(status, content=body)
                            )
                        ) as client:
                            with self.assertRaises((ValueError, httpx.HTTPStatusError)):
                                await assets.download_reference(client, item, root)
                        self.assertFalse(list(root.iterdir()))

        asyncio.run(run())

    def test_reference_redirect_cannot_downgrade_to_http(self):
        async def run():
            requests = []

            def handler(request):
                requests.append(str(request.url))
                return httpx.Response(
                    302, headers={"Location": "http://insecure.test/file"}
                )

            with tempfile.TemporaryDirectory() as temporary:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    event_hooks={"request": [assets.require_https]},
                    transport=httpx.MockTransport(handler),
                ) as client:
                    with self.assertRaisesRegex(ValueError, "HTTPS"):
                        await assets.download_reference(
                            client, reference(b"synthetic"), Path(temporary)
                        )
                self.assertEqual(len(requests), 1)

        asyncio.run(run())

    def test_preparation_reuses_complete_assets_and_does_not_hide_failures(self):
        async def run():
            for failure in (None, "reference", "notices"):
                with (
                    self.subTest(failure=failure),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    root = Path(temporary)
                    baseline, output, cache = (
                        root / "baseline",
                        root / "output",
                        root / "cache",
                    )
                    archive(baseline, FILES)
                    output.write_bytes(b"previous completed output")
                    files = {"fonts": [], "models": []}
                    for name, content in FILES.items():
                        group, filename = name.split("/")
                        if group == "licenses":
                            continue
                        path = cache / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                        files[group].append(
                            {
                                "name": filename,
                                "sha3_256": hashlib.sha3_256(content).hexdigest(),
                            }
                        )

                    def verify_file(path, digest):
                        return hashlib.sha3_256(path.read_bytes()).hexdigest() == digest

                    def notices(bundle, _cache, _fonts):
                        if failure == "notices":
                            raise RuntimeError("synthetic notices failure")
                        bundle.writestr("licenses/LICENSE", FILES["licenses/LICENSE"])

                    modules = {
                        "babeldoc": ModuleType("babeldoc"),
                        "babeldoc.assets": ModuleType("babeldoc.assets"),
                        "babeldoc.assets.assets": SimpleNamespace(
                            generate_all_assets_file_list=lambda: files,
                            verify_file=verify_file,
                        ),
                        "babeldoc.assets.embedding_assets_metadata": SimpleNamespace(
                            DOC_LAYOUT_ONNX_MODEL_URL={},
                            FONT_URL_BY_UPSTREAM={},
                            TABLE_DETECTION_RAPIDOCR_MODEL_URL={},
                        ),
                        "release_materials": SimpleNamespace(model_notices=notices),
                    }
                    download = AsyncMock(
                        return_value=baseline,
                        side_effect=(
                            RuntimeError("synthetic reference failure")
                            if failure == "reference"
                            else None
                        ),
                    )
                    with (
                        patch.dict(sys.modules, modules),
                        patch.object(assets, "download_reference", download),
                    ):
                        operation = assets.prepare_assets(
                            cache, output, reference=reference(baseline.read_bytes())
                        )
                        if failure:
                            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                                await operation
                            self.assertEqual(
                                output.read_bytes(), b"previous completed output"
                            )
                        else:
                            await operation
                            self.assertEqual(output.read_bytes(), baseline.read_bytes())
                    self.assertFalse(list(root.glob(".model-*")))

        asyncio.run(run())
