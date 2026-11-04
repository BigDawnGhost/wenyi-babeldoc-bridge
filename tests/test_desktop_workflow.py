"""Keep tag versions and release authorization coherent across build workflows."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DesktopWorkflowTests(unittest.TestCase):
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
