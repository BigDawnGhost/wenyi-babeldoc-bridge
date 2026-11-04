"""Keep tag versions and release authorization coherent across build workflows."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DesktopWorkflowTests(unittest.TestCase):
    def runtime_matrix(self, event, ref):
        document = yaml.load(
            (ROOT / ".github/workflows/desktop-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        jobs = document["jobs"]
        self.assertEqual(jobs["runtime"]["needs"], "models")
        self.assertEqual(
            jobs["runtime"]["strategy"]["matrix"],
            "${{ fromJSON(needs.models.outputs.matrix) }}",
        )
        self.assertEqual(
            jobs["models"]["outputs"]["matrix"], "${{ steps.platforms.outputs.matrix }}"
        )
        step = next(
            item for item in jobs["models"]["steps"] if item.get("id") == "platforms"
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            subprocess.run(
                ["bash", "-e", "-c", step["run"]],
                env={
                    **os.environ,
                    "GITHUB_EVENT_NAME": event,
                    "GITHUB_REF": ref,
                    "GITHUB_OUTPUT": str(output),
                },
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(output.read_text().removeprefix("matrix="))

    def test_pr_builds_only_linux_windows_and_skips_complete_assembly(self):
        matrix = self.runtime_matrix("pull_request", "refs/pull/7/merge")
        self.assertEqual(
            matrix["include"],
            [
                {"runner": "ubuntu-22.04", "target": "linux-x86_64"},
                {"runner": "windows-2022", "target": "windows-x86_64"},
            ],
        )
        document = yaml.load(
            (ROOT / ".github/workflows/desktop-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(
            document["jobs"]["assemble"]["if"], "github.event_name != 'pull_request'"
        )
        self.assertEqual(document["jobs"]["assemble"]["needs"], ["runtime", "models"])

    def test_main_tag_and_manual_builds_keep_all_four_platforms(self):
        for event, ref in (
            ("push", "refs/heads/main"),
            ("push", "refs/tags/v0.1.4"),
            ("workflow_dispatch", "refs/heads/example"),
        ):
            with self.subTest(event=event, ref=ref):
                matrix = self.runtime_matrix(event, ref)
                self.assertEqual(
                    matrix["include"],
                    [
                        {"runner": "ubuntu-22.04", "target": "linux-x86_64"},
                        {"runner": "windows-2022", "target": "windows-x86_64"},
                        {"runner": "macos-15-intel", "target": "macos-x86_64"},
                        {"runner": "macos-15", "target": "macos-aarch64"},
                    ],
                )

    def test_every_desktop_job_has_git_tags_available(self):
        document = yaml.load(
            (ROOT / ".github/workflows/desktop-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(document["on"]["push"]["tags"], ["v*"])
        self.assertEqual(document["on"]["push"]["branches"], ["main"])
        self.assertEqual(document["permissions"], {"contents": "read"})
        for job in document["jobs"].values():
            checkout = next(
                item
                for item in job["steps"]
                if "actions/checkout@" in item.get("uses", "")
            )
            self.assertEqual(checkout["with"]["fetch-depth"], "0")

    def test_manual_publication_requires_main_and_tag_builds(self):
        document = yaml.load(
            (ROOT / ".github/workflows/publish-desktop-plugin.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(set(document["on"]), {"workflow_dispatch"})
        inputs = document["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"build_run", "main_build_run"})
        self.assertTrue(all(item["required"] == "true" for item in inputs.values()))
        self.assertEqual(document["permissions"]["actions"], "write")
        self.assertEqual(
            document["jobs"]["publish"]["if"], "github.ref == 'refs/heads/main'"
        )
        step = document["jobs"]["publish"]["steps"][-1]
        self.assertEqual(
            step["env"]["PLUGIN_MAIN_BUILD_RUN"], "${{ inputs.main_build_run }}"
        )
