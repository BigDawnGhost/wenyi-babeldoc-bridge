# Publishing to PyPI

[简体中文](zh/publishing.md) · [Overview](../README.md) · [Desktop plugin](desktop.md)

This repository publishes only **`wenyi-babeldoc-bridge`**. Upstream already
publishes BabelDOC to PyPI; installing the bridge resolves compatible dependencies
without installing their source from GitHub.
Wenyi CLI/Core are published by the separate MIT repository, not bundled here.

## One-time setup

1. Register a PyPI account and enable two-factor authentication.
2. In the [GitHub repository environment settings](https://github.com/BigDawnGhost/wenyi-babeldoc-bridge/settings/environments),
   create an environment named **`pypi`**. No PyPI token or repository secret is
   required. To upload directly after release publication, do not require manual
   approval. Deployment restrictions must allow release tags such as `v*`,
   not only the `main` branch.
3. In [PyPI account publishing settings](https://pypi.org/manage/account/publishing/),
   add a GitHub **pending publisher** for the project if it does not exist yet:

| Field | Value |
| --- | --- |
| PyPI project name | `wenyi-babeldoc-bridge` |
| Owner | `BigDawnGhost` |
| Repository name | `wenyi-babeldoc-bridge` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

Workflow name is the filename, not its display name or full path.
The first successful upload creates the project and converts the publisher;
no preliminary manual upload is needed. A pending publisher does not reserve
the package name. If you already own the project, configure the same fields
under **Manage → Publishing**.

## Publish a new version

1. Complete the applicable validation and include the release changes and
   `.github/workflows/publish-pypi.yml` in the verified commit.
2. Package versions come from Git tags through `hatch-vcs`, not a fixed
   `project.version`. For example, `v0.1.4` produces `0.1.4`, and `v0.2.0rc1`
   produces `0.2.0rc1`. These are examples: check that the chosen version has not
   been published. Do not override the version with SCM environment variables.
3. Once the workflow is on `main`, use **Actions → Publish bridge to PyPI →
   Run workflow**, select an existing tag and leave `publish=false` for a preflight.
   Manual runs build and validate without uploading by default.
4. Create a new tag for the verified commit, then select and publish it through
   **Releases → Draft a new release**. Pushing a tag or saving a draft does not
   upload to PyPI. Mark prereleases as prereleases on GitHub too.
5. Confirm that both the Actions `build` and `publish` jobs succeeded.

### Desktop plugin release

PRs validate only the model pack and Linux/Windows runtimes, including HTTP smoke
tests and corresponding sources. They do not run macOS or produce a publishable
`complete-plugin`; PR success cannot substitute for complete release validation.

Desktop releases require all four runtime platforms. Wait for the main build to
pass, create a stable tag at that same commit, then wait for the tag's
**Desktop plugin** build to pass. Dispatch **Publish verified desktop plugin**
with `main_build_run` set to the main push run ID and `build_run` set to the tag
push run ID. The publisher verifies that both builds belong to the same commit,
checks uploaded assets while the release is still a draft, then makes it public.

It explicitly dispatches the PyPI workflow with the same tag and `publish=true`:
releases created by `GITHUB_TOKEN` do not trigger other release-event workflows.
No extra token is needed.

Publication requires explicit authorization. After merging, wait for the main
push build of the merge result; an unmerged branch or manual build is not release
validation. An untagged development build cannot be relabeled as stable.
Run the publisher on `main`. It checks all six jobs and their steps in both runs,
main ancestry and the unchanged tag, and reads release notes from that commit.
It downloads the tag build's `complete-plugin`, creates a draft and uploads all
assets, verifying every size and SHA-256 before publishing as latest.
It rejects development versions, branch/manual builds, incomplete checks,
non-newer versions, conflicting releases and asset replacement.
Build workflows are read-only and never publish automatically on a push or PR.

### PyPI validation and upload

`publish=true` uploads or retries an upload for an already public release.
The workflow verifies the matching release exists, is not a draft and has the
expected tag, then runs all version and packaging checks. It does not create a release.
Do not publish a stable Desktop release before its complete plugin assets are ready.

The build checks the tag, checkout, worktree and Git-derived version, validates
distribution metadata, and installs the wheel and source distribution separately
into clean Python 3.12 environments. It checks the installed version, dependencies,
console entry point and `/health`, then runs the installed lightweight tests.
Real model/PDF integration tests are skipped by default; fonts/models are not downloaded.

Tagged releases must use the matching clean commit, with no development or local
version suffix. Untagged PR/default manual builds keep their real development
version, including commit distance, hash and dirty-state marker; they are neither
relabeled as releases nor uploaded to PyPI.
Git checkouts need tag history. Built source distributions carry their version
and can be rebuilt without a Git repository.

At runtime, `wenyi_babeldoc_bridge.__version__` and the API/OpenAPI versions read
installed package metadata, not Git. Uninstalled source probes using
`PYTHONPATH=src` report `0+unknown`, not a release version.

The upload job is isolated: it only downloads verified build artifacts and
receives OIDC upload permission, without checking out source code.
Fork releases do not run this repository's upload job.

## Install a published release

Install CLI and bridge together in a dedicated Wenyi environment,
not an existing `pdf2zh_next` environment:

```bash
uv venv .venv-wenyi --python 3.12
uv pip install --python .venv-wenyi/bin/python wenyi-cli "wenyi-babeldoc-bridge==0.1.5"
uv pip check --python .venv-wenyi/bin/python
.venv-wenyi/bin/wenyi --version
.venv-wenyi/bin/wenyi-babeldoc-bridge
```

Replace the example version with the actual release and pin verified CLI and
bridge versions in your deployment. CLI automatically installs `wenyi-core`,
so CLI/Core and bridge must all be published before initial deployment.
Their versions are independent and do not need to match.
The bridge has no `zotero` extra and does not install either PDF2zh frontend.
On Windows, use `Scripts/python.exe`, `Scripts/wenyi.exe`, and
`Scripts/wenyi-babeldoc-bridge.exe`. Sharing the environment does not merge HTTP
processes or license obligations; do not manage it with the Wenyi workspace's `uv sync`.

PyPI installation only avoids fetching Python package source from GitHub.
BabelDOC fonts and models still use its asset download/cache mechanism and
are not bundled into the bridge wheel. See [installation](installation.md) for
the current dependency compatibility policy.

## Recovery

- **Trusted publishing rejected:** check all five table fields, especially the
  workflow filename and `pypi` environment.
- **Waiting for environment approval:** approve deployment or adjust environment
  approval and tag restrictions.
- **Version mismatch:** use the clean commit matching the release tag, retain tag
  history and remove SCM version overrides. Do not move published tags; use a
  new commit and tag for fixes.
- **Network failure or partial upload:** select **Re-run failed jobs**.
  uv uses an explicit PyPI check URL to skip existing files with matching hashes.
- **Existing filename with different contents:** PyPI does not allow replacing
  a version's files; publish a new version.

References: [PyPI first-time trusted publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [uv GitHub Actions publishing](https://docs.astral.sh/uv/guides/integration/github/#publishing-to-pypi).
