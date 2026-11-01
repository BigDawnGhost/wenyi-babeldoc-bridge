"""Publication accepts only complete main builds and verified immutable assets."""

import copy
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "publish_desktop",
    Path(__file__).resolve().parents[2] / "scripts/publish_desktop.py",
)
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
COMMIT = "a" * 40


def successful_build():
    run = {
        "head_sha": COMMIT,
        "head_branch": "main",
        "event": "push",
        "path": ".github/workflows/desktop-plugin.yml",
        "status": "completed",
        "conclusion": "success",
    }
    names = ["models", "assemble"] + [
        f"runtime (runner, {target})" for target in publisher.PLATFORMS
    ]
    jobs = [
        {
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "steps": [{"status": "completed", "conclusion": "success"}],
        }
        for name in names
    ]
    return run, jobs


def release_assets(directory):
    def descriptor(name):
        path = directory / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("synthetic.txt", "synthetic payload")
        return {
            "name": name,
            "size": path.stat().st_size,
            "sha256": publisher.sha256(path),
        }

    manifest = {
        "protocol": 1,
        "version": "0.1.3",
        "platforms": {
            target: descriptor(f"wenyi-babeldoc-0.1.3-{target}.zip")
            for target in publisher.PLATFORMS
        },
        "models": descriptor("wenyi-babeldoc-0.1.3-models.zip"),
    }
    (directory / "desktop-plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with zipfile.ZipFile(directory / "wenyi-babeldoc-0.1.3-source.zip", "w") as archive:
        archive.comment = COMMIT.encode("ascii")
    for target in publisher.PLATFORMS:
        with zipfile.ZipFile(
            directory / f"wenyi-babeldoc-0.1.3-{target}-sources.zip", "w"
        ) as archive:
            for name in ("SOURCES.json", "requirements.txt", "THIRD_PARTY.md"):
                archive.writestr(name, "synthetic source notice")
    return manifest


class PublicationTests(unittest.TestCase):
    def test_complete_main_build_is_accepted(self):
        run, jobs = successful_build()
        self.assertEqual(publisher.verified_commit(run, jobs), COMMIT)

    def test_other_branches_events_and_incomplete_runs_are_rejected(self):
        run, jobs = successful_build()
        for key, value in (
            ("head_branch", "release/example"),
            ("event", "pull_request"),
            ("event", "workflow_dispatch"),
            ("path", ".github/workflows/other.yml"),
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("head_sha", "HEAD"),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                publisher.verified_commit({**run, key: value}, jobs)

    def test_missing_failed_skipped_or_duplicated_jobs_are_rejected(self):
        run, jobs = successful_build()
        candidates = [jobs[:-1], [*jobs[:-1], jobs[0]]]
        for key, value in (
            ("conclusion", "failure"),
            ("status", "in_progress"),
            ("steps", []),
        ):
            changed = copy.deepcopy(jobs)
            changed[0][key] = value
            candidates.append(changed)
        changed = copy.deepcopy(jobs)
        changed[0]["steps"][0]["conclusion"] = "skipped"
        candidates.append(changed)
        for candidate in candidates:
            with self.subTest(jobs=candidate), self.assertRaises(ValueError):
                publisher.verified_commit(run, candidate)

    def test_stable_versions_compare_numerically(self):
        self.assertGreater(
            publisher.stable_version("0.1.10"), publisher.stable_version("0.1.9")
        )
        for value in ("01.2.3", "0.1.3-beta", "0.1", "../outside"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                publisher.stable_version(value)

    def test_complete_assets_generate_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            release_assets(directory)
            expected = publisher.verify_assets(directory, "0.1.3", COMMIT)
            self.assertEqual(len(expected), 12)
            self.assertIn("SHA256SUMS", expected)
            self.assertEqual(
                len((directory / "SHA256SUMS").read_text().splitlines()), 11
            )

    def test_wrong_source_or_corrupted_asset_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = release_assets(directory)
            with self.assertRaisesRegex(ValueError, "selected main commit"):
                publisher.verify_assets(directory, "0.1.3", "b" * 40)
            models = directory / manifest["models"]["name"]
            models.write_bytes(b"x" * models.stat().st_size)
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                publisher.verify_assets(directory, "0.1.3", COMMIT)
