# Desktop plugin

[简体中文](zh/desktop.md) · [Overview](../README.md) · [Publishing](publishing.md)

Wenyi Desktop can download this service as a separate, self-contained plugin.
It remains an AGPL process; the MIT application uses HTTP only and does not
install or import BabelDOC. Users do not need a separate Python installation.
Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtime ZIPs,
while all platforms share a model/font ZIP.

## Build environment and verification

The **Desktop plugin** workflow builds with Python 3.12 and
`desktop-constraints.txt` (BabelDOC 0.7.1 and compatible dependency APIs).
The shared `pymupdf>=1.26.7,<2` requirement also applies to these builds.
Both HTTP and Desktop use the same bridge-owned PyO3 extension over upstream
Rust stages. Source builds require Rust/Cargo; frozen plugins do not.

The workflow downloads assets using BabelDOC's embedded SHA3-256 hashes, with
mirror fallback, then freezes each runtime and tests a synthetic two-page PDF
through real HTTP: authentication, selected-page extraction, invalid/complete
translations, short cells and Chinese text, fillback text, restart recovery,
session deletion and owner-pipe shutdown. Runtime tests disable outbound network
access via an unusable proxy. No user PDF or LLM is used.

Desktop builds use `--excludes desktop-excludes.txt` to omit RapidOCR's GUI
`opencv-python` dependency: BabelDOC already requires `opencv-python-headless`,
which supplies the same `cv2` API without Qt. This is an explicit packaging-only
substitution; a generic dependency checker can still report RapidOCR's declared
GUI requirement as missing.

Use a fresh isolated build environment rather than uninstalling overlapping
OpenCV wheels in place. The builder rejects conflicting OpenCV distributions
before freezing. Python modules are selected by import analysis and the existing
dynamic-import rules; BabelDOC CMaps/IL data, native ONNX providers, licenses,
models and fonts are kept.

Each build emits `<platform>-size.json` with compressed archive size, unpacked
file size and per-component totals. These are CI diagnostics, not changes to the
Desktop installation protocol.

## Local build

Run from this repository's root in an isolated environment:

```bash
uv venv .venv --python 3.12 --seed
uv pip install --python .venv -c desktop-constraints.txt \
  --excludes desktop-excludes.txt . pyinstaller fonttools==4.60.1
VERSION=$(uv run --no-project --python .venv python -c \
  'from importlib.metadata import version; print(version("wenyi-babeldoc-bridge"))')
uv run --no-project --python .venv python scripts/build_desktop.py models --version "$VERSION"
uv run --no-project --python .venv python scripts/build_desktop.py runtime --version "$VERSION"
# On Windows, append .exe to the executable path:
uv run --no-project --python .venv python scripts/smoke_desktop.py \
  dist/wenyi-babeldoc-plugin/wenyi-babeldoc-plugin "dist/wenyi-babeldoc-$VERSION-models.zip"
```

## Offline assets and cache reuse

Model/font archive identity is independent of the bridge version.
`desktop-models.json` pins a published reference archive by release, size and
SHA-256. The builder verifies it, prepares the currently required resources and
license notices, then compares every member's name and bytes. If all contents
match, it copies the reference ZIP unchanged under the new release's filename.

Desktop can reuse its verified, hash-addressed download cache even when the
runtime version and asset filename change; no client protocol change is required.
New installations, missing/corrupted cached ZIPs, or genuinely changed resources
or notices still require a download.

The initial reference is v0.1.2. An installation that only cached an older,
differently hashed ZIP may still need one download. Reference download or checksum
failures fail the build rather than silently generating another archive.
Changed contents produce a ZIP with sorted entries and fixed timestamps/permissions.
After publishing changed resources, update `desktop-models.json` from that
release's verified `models` descriptor, using its release, size and hash.
Do not advance this reference for runtime-only releases or overwrite published assets.
Build-side downloads and extraction into each Desktop installation remain separate
from reusing the user's download cache.

The 0.6 upgrade adds native-parser CMap JSON assets and updates license notices,
so it produces a new model archive rather than reusing the 0.5 archive.
All CMaps are SHA3-256 verified before readiness, like fonts and models;
the frozen service must work without network access during PDF processing.

## CI and source distribution

`main` is the only integration branch. Start short-lived branches from the latest
`origin/main` and open PRs directly against `main`, not `master`, `release/**` or
`publish/**`. Keep historical branches and published tags unless their removal is
explicitly requested; changing the flow does not migrate their commits.

The **Desktop plugin** workflow runs on PRs targeting `main`, pushes to `main`,
`v*` tags and manual dispatches. Before merging a PR with a merge commit, require
the models and Linux/Windows runtime jobs to pass for its current revision,
including HTTP smoke tests and corresponding-source packaging.
PRs do not run macOS and skip final assembly; they never produce a publishable
`complete-plugin`. PR success is not macOS validation.

Main, tag and manual builds retain all four platforms and final manifest/source
assembly. Unlike Wenyi's Rust-cache warm-up on main, the bridge retains complete
main builds for its main/tag publication gate. All package versions, including
frozen runtimes, come from Git tags through `setuptools-scm`.
Publication requires separate authorization and successful main/tag builds of
the same commit; see the [publishing guide](publishing.md#desktop-plugin-release).

Runtime ZIPs include dependency notices, README, the bilingual guides and exact
installed requirements. Model ZIPs include font copyrights and full licenses.
Each platform has a corresponding source ZIP for copyleft dependencies, MuPDF
and Python (plus GEOS when Shapely is installed), alongside the separate bridge
source ZIP. See [third-party materials](../THIRD_PARTY.md).
Review licenses when upgrading dependencies; packaging does not replace legal
review or OS signing/notarization.

## Runtime protocol

The manifest has `protocol: 1`, a stable `version`, `platforms` keyed by
`windows-x86_64`, `linux-x86_64`, `macos-aarch64`, `macos-x86_64`, and `models`.
Each asset has `name`, `size` and `sha256`. Desktop constructs URLs under this
repository's `releases/download/v<version>/`; arbitrary download URLs or executable
paths are not accepted.

The manifest and hashes are authenticated by HTTPS to the official release
repository, not a separate plugin signature. This differs from Wenyi's signed
application updater.

The private executable accepts `--data-dir` and `--cache-dir`. Its parent supplies
`WENYI_BABELDOC_TOKEN` in memory and holds stdin open. On successful startup it
writes one JSON line to stdout: `{"protocol":1,"port":<port>,"pid":<pid>}`.
It binds an OS-assigned `127.0.0.1` port, requires `Authorization: Bearer <token>`
on every endpoint, rejects browser origins and foreign Host headers, and exits
on stdin EOF. Logs use stderr; credentials never appear in the readiness message.

Sessions use the supplied persistent data directory. Models/fonts are verified
before readiness and are not downloaded during PDF processing.
The ordinary `wenyi-babeldoc-bridge` entry point and [HTTP schema](api.md) are
unchanged. Desktop pins installed runtime versions because frozen sessions
require matching Python/BabelDOC versions.
Session deletion first releases unreachable native PDF handles; if files remain
busy, it returns 503 and keeps the session for a retry.
