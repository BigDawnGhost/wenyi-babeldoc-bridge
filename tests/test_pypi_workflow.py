"""Offline contracts for the PyPI release workflow (Python 3.12 CI tooling)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow():
    with (ROOT / ".github/workflows/publish-pypi.yml").open() as source:
        return yaml.load(source, Loader=yaml.BaseLoader)


class PyPIWorkflowTests(unittest.TestCase):
    def run_identity(
        self,
        tag="",
        version="0.1.0",
        *,
        dirty=False,
        wrong_checkout=False,
        overrides=None,
    ):
        step = next(
            item
            for item in workflow()["jobs"]["build"]["steps"]
            if item.get("id") == "version"
        )
        code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            previous = Path.cwd()
            try:
                os.chdir(root)
                with (
                    patch.dict(
                        os.environ,
                        {
                            "RELEASE_TAG": tag,
                            "GITHUB_OUTPUT": str(output),
                            **(overrides or {}),
                        },
                    ),
                    patch("setuptools_scm.get_version", return_value=version),
                    patch(
                        "subprocess.check_output",
                        side_effect=[
                            "tagged\n",
                            "other\n" if wrong_checkout else "tagged\n",
                            " M pyproject.toml\n" if dirty else "",
                        ],
                    ),
                ):
                    exec(compile(code, "workflow-version", "exec"), {})
            finally:
                os.chdir(previous)
            return output.read_text()

    def test_matching_release_and_manual_build(self):
        self.assertEqual(self.run_identity("v0.1.0"), "python=0.1.0\n")
        self.assertEqual(self.run_identity(), "python=0.1.0\n")
        self.assertEqual(
            self.run_identity("v0.2.0rc1", "0.2.0rc1"), "python=0.2.0rc1\n"
        )

    def test_manual_build_preserves_development_version(self):
        version = "0.1.4.dev2+g123abc"
        self.assertEqual(self.run_identity(version=version), f"python={version}\n")

    def test_rejects_wrong_version_development_and_local_versions(self):
        for tag, version in (
            ("v0.2.0", "0.1.0"),
            ("v0.1.0", "0.1.0.dev1"),
            ("v0.1.0", "0.1.0+local"),
            ("--invalid", "0.1.0"),
        ):
            with self.subTest(tag=tag, version=version), self.assertRaises(SystemExit):
                self.run_identity(tag, version)

    def test_rejects_scm_version_overrides(self):
        for key in (
            "SETUPTOOLS_SCM_PRETEND_VERSION",
            "SETUPTOOLS_SCM_PRETEND_VERSION_FOR_WENYI_BABELDOC_BRIDGE",
            "HATCH_VCS_PRETEND_VERSION",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(SystemExit, "override"):
                self.run_identity("v0.1.0", overrides={key: "0.1.0"})

    def test_rejects_wrong_checkout_and_dirty_release(self):
        with self.assertRaisesRegex(SystemExit, "checkout"):
            self.run_identity("v0.1.0", wrong_checkout=True)
        with self.assertRaisesRegex(SystemExit, "clean"):
            self.run_identity("v0.1.0", dirty=True)

    def test_requested_upload_requires_the_matching_public_release(self):
        import json

        step = next(
            item
            for item in workflow()["jobs"]["build"]["steps"]
            if item.get("name") == "Verify public release before upload"
        )
        self.assertEqual(step["if"], "github.event_name == 'release' || inputs.publish")
        code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        environment = {"RELEASE_TAG": "v0.1.4", "GH_REPO": "owner/repo"}
        with (
            patch.dict(os.environ, environment),
            patch("subprocess.check_output") as lookup,
        ):
            lookup.return_value = json.dumps({"tag_name": "v0.1.4", "draft": False})
            exec(compile(code, "workflow-public-release", "exec"), {})
            lookup.assert_called_once_with(
                ["gh", "api", "repos/owner/repo/releases/tags/v0.1.4"], text=True
            )
            for release in (
                {"tag_name": "v0.1.4", "draft": True},
                {"tag_name": "v0.1.3", "draft": False},
            ):
                lookup.return_value = json.dumps(release)
                with self.assertRaisesRegex(SystemExit, "public GitHub release"):
                    exec(compile(code, "workflow-public-release", "exec"), {})
            with patch.dict(os.environ, {"RELEASE_TAG": ""}):
                with self.assertRaisesRegex(SystemExit, "explicit release tag"):
                    exec(compile(code, "workflow-public-release", "exec"), {})

    def test_upload_is_release_only_and_uses_isolated_oidc_job(self):
        document = workflow()
        self.assertEqual(document["on"]["release"]["types"], ["published"])
        self.assertEqual(document["on"]["pull_request"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", document["on"])
        self.assertEqual(
            document["on"]["workflow_dispatch"]["inputs"]["publish"]["default"], "false"
        )
        self.assertNotIn("push", document["on"])
        self.assertEqual(document["permissions"], {"contents": "read"})
        self.assertEqual(document["concurrency"]["cancel-in-progress"], "false")
        build, publish = document["jobs"]["build"], document["jobs"]["publish"]
        self.assertNotIn("id-token", build.get("permissions", {}))
        self.assertEqual(publish["needs"], "build")
        self.assertEqual(
            publish["if"],
            "(github.event_name == 'release' || "
            "(github.event_name == 'workflow_dispatch' && inputs.publish)) && "
            "github.repository == 'BigDawnGhost/wenyi-babeldoc-bridge'",
        )
        self.assertEqual(publish["environment"]["name"], "pypi")
        self.assertEqual(publish["permissions"], {"id-token": "write"})
        self.assertFalse(
            any(
                "actions/checkout@" in step.get("uses", "") for step in publish["steps"]
            )
        )
        commands = "\n".join(step.get("run", "") for step in build["steps"])
        self.assertIn("--with hatch-vcs", commands)
        self.assertIn('Version(get_version(root="."))', commands)
        self.assertNotIn("tomllib", commands)
        self.assertIn("uv build --no-sources --out-dir dist/pypi", commands)
        self.assertIn("for extension in whl tar.gz", commands)
        self.assertIn('client.get("/health")', commands)
        self.assertIn("server.app.version != installed.version", commands)
        self.assertIn("suite.countTestCases() == 0", commands)
        self.assertIn("loadTestsFromNames", commands)
        self.assertIn('"test_session_cleanup"', commands)
        self.assertNotIn('"test_desktop_package"', commands)
        self.assertIn("uv pip check", commands)
        self.assertNotIn("uv publish", commands)
        upload = next(
            step["run"]
            for step in publish["steps"]
            if "uv publish" in step.get("run", "")
        )
        self.assertIn("--trusted-publishing always", upload)
        self.assertIn("--check-url https://pypi.org/simple/", upload)
        self.assertNotIn("secrets.", str(document))
        producer = next(
            step
            for step in build["steps"]
            if "actions/upload-artifact@" in step.get("uses", "")
        )
        consumer = next(
            step
            for step in publish["steps"]
            if "actions/download-artifact@" in step.get("uses", "")
        )
        self.assertEqual(producer["with"]["name"], consumer["with"]["name"])


if __name__ == "__main__":
    unittest.main()
