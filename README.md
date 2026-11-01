# wenyi-babeldoc-bridge

An independent **AGPL-3.0-only** HTTP service for
[Wenyi](https://github.com/BigDawnGhost/Wenyi).
[BabelDOC](https://github.com/funstory-ai/BabelDOC) extracts PDF paragraphs and
typesets translations supplied by Wenyi.

Wenyi remains MIT-licensed. Run the bridge in a separate process and environment,
and communicate over HTTP only; do not import the bridge or BabelDOC into Wenyi.

## Quick start

Requires Python 3.10–3.13 and [uv](https://docs.astral.sh/uv/).
Use an isolated environment; Python 3.12 is recommended.

```bash
cd wenyi-babeldoc-bridge
uv venv .venv --python 3.12
uv pip install --python .venv -e .
uv run --no-project --python .venv wenyi-babeldoc-bridge
```

The standalone service listens on `http://127.0.0.1:8765`. It has no authentication;
keep it on loopback or behind an authenticated proxy. To configure the listener:

```bash
uv run --no-project --python .venv uvicorn wenyi_babeldoc_bridge.server:app \
  --host 127.0.0.1 --port 8765
```

## HTTP API

| Method | Endpoint | Request / response |
| --- | --- | --- |
| GET | `/health` | Service status and session counts |
| POST | `/extract` | Multipart `file` (PDF), optional `pages`; returns a session ID and paragraph document |
| POST | `/fillback` | JSON `session_id` and `translations`; returns a monolingual PDF |
| GET | `/session/{session_id}` | Session metadata and paragraph document |
| DELETE | `/session/{session_id}` | Remove the session and its files |

Read extracted units from `paragraphs.paragraphs` in the `/extract` response.
Send their IDs and translated text to `/fillback`:

```json
{
  "session_id": "<session_id>",
  "translations": {
    "0:0": "Translated paragraph."
  }
}
```

Replace the example with the returned session ID and **every** extracted paragraph
ID. Missing or unknown IDs and blank translations return HTTP 400; missing sessions
return HTTP 404.

### Paragraph identity

IDs use `"{page}:{index}"` from the session's original BabelDOC intermediate
representation (IL). Filtering never renumbers paragraphs.

Extraction keeps all nonblank text, including short words, single characters,
numbers and real text such as `table` or `title`. Only debug overlays marked by
IL `debug_info` metadata are excluded. Extraction and fillback use the same rule.
Re-extract PDFs affected by older filtering behavior; existing sessions do not
gain previously omitted paragraphs.

## Sessions and diagnostics

Extraction saves a frozen IL snapshot, the corrected input PDF, MediaBox data,
paragraph index, page selection and dependency versions. The session manifest is
committed atomically after the snapshot is complete.

Sessions reload by ID after a restart without repeating layout analysis. Recovery
requires matching Python major/minor and BabelDOC versions, valid file paths and
matching file hashes. Each fillback loads a fresh copy of the frozen IL, so failed
or repeated requests do not reuse a partially modified document.

By default, sessions live in `wenyi-babeldoc-bridge/` under the system temporary
directory, which the OS may clear. For long-running translations, set a persistent
directory before starting the service:

```bash
export WENYI_BABELDOC_STATE_DIR=/path/to/wenyi-babeldoc-sessions
uv run --no-project --python .venv wenyi-babeldoc-bridge
```

Call `DELETE /session/{session_id}` when finished. Deletion releases unreachable
native PDF handles first; if files remain busy, it returns HTTP 503 and keeps the
loaded session available for a deletion retry.

Output PDFs omit layout boxes and debug role labels by default. To diagnose
typesetting, set this before starting the service:

```bash
export WENYI_BABELDOC_DEBUG=1
```

## Desktop plugin

Wenyi Desktop can download this service as a separate, self-contained plugin.
No user-installed Python is required. Windows x64, Linux x64, macOS Apple Silicon
and macOS Intel have separate runtime ZIPs and share one model/font ZIP.
The plugin remains an independent AGPL process using the same HTTP API.

### Runtime protocol

- The private executable accepts `--data-dir` and `--cache-dir`.
- Its parent supplies `WENYI_BABELDOC_TOKEN` in memory and holds stdin open.
  The process exits on stdin EOF.
- It binds an OS-assigned `127.0.0.1` port and requires
  `Authorization: Bearer <token>` on every endpoint. Browser origins and foreign
  Host headers are rejected.
- Readiness is one stdout line: `{"protocol":1,"port":<port>,"pid":<pid>}`.
  Logs go to stderr; credentials never appear in the readiness message.
- Models and fonts are verified before readiness, not downloaded during PDF
  processing. Sessions use the supplied persistent data directory.

Desktop pins installed runtime versions to preserve Python/BabelDOC compatibility
with frozen sessions. The standalone entry point is unchanged.

### Release manifest

`desktop-plugin.json` contains `protocol: 1`, a stable `version`, `models`, and
`platforms` keyed by `windows-x86_64`, `linux-x86_64`, `macos-aarch64` and
`macos-x86_64`. Each asset has `name`, `size` and `sha256`.

Desktop constructs download URLs under this repository's
`releases/download/v<version>/`; the manifest supplies no arbitrary URLs or
executable paths. Trust comes from HTTPS to the official release repository and
hash verification, not a separate plugin signature. This differs from Wenyi's
signed application updater. Plugin packages are not Windows code-signed or macOS
notarized.

### Local build

Use a fresh Python 3.12 environment with the pinned dependencies in
`desktop-constraints.txt` (including BabelDOC 0.5.20). Run these commands in a
POSIX-compatible shell; on Windows, append `.exe` to the smoke-test executable:

```bash
uv venv .venv --python 3.12 --seed
uv pip install --python .venv -c desktop-constraints.txt \
  --excludes desktop-excludes.txt . pyinstaller fonttools==4.60.1
VERSION=$(uv run --no-project --python .venv python -c \
  'from importlib.metadata import version; print(version("wenyi-babeldoc-bridge"))')
uv run --no-project --python .venv python scripts/build_desktop.py models --version "$VERSION"
uv run --no-project --python .venv python scripts/build_desktop.py runtime --version "$VERSION"
uv run --no-project --python .venv python scripts/smoke_desktop.py \
  dist/wenyi-babeldoc-plugin/wenyi-babeldoc-plugin "dist/wenyi-babeldoc-$VERSION-models.zip"
```

`desktop-excludes.txt` replaces RapidOCR's declared GUI `opencv-python` dependency
with BabelDOC's `opencv-python-headless`, which supplies `cv2` without Qt. This is a
packaging-only substitution; generic dependency checks may still report the GUI
requirement as missing. The builder rejects overlapping OpenCV distributions.
Do not repair an existing environment by uninstalling overlapping wheels in place.

Import analysis and explicit dynamic-import rules select Python modules while
preserving BabelDOC CMaps/IL data, native ONNX providers, licenses, models and fonts.
Each build emits `<platform>-size.json` with archive, unpacked and per-component
sizes for diagnostics; these reports are not part of the installation protocol.

### Model and font cache

`desktop-models.json` pins a published reference ZIP by release, size and SHA-256.
The builder verifies it, prepares resources using BabelDOC's embedded SHA3-256
hashes with mirror fallback, and compares every resource and license notice.

- Identical contents reuse the reference ZIP bytes under the new release filename,
  preserving the hash so Desktop can reuse its verified download cache.
- Changed contents produce a new ZIP with sorted entries and fixed timestamps and
  permissions. Reference download or checksum failures fail the build.
- New installations, missing or corrupt caches, and older differently hashed ZIPs
  still need a download. Build downloads and per-installation extraction are unchanged.

After publishing changed resources, update the reference from that release's
verified `models` descriptor. Do not advance it for runtime-only releases or
overwrite published assets.

## Development and releases

`main` is the default and only integration branch. Start short-lived branches from
the latest `origin/main` and open pull requests against `main`.
See [AGENTS.md](AGENTS.md) for the code map, invariants and validation commands.

The [Desktop plugin](.github/workflows/desktop-plugin.yml) workflow runs on PRs to
`main`, pushes to `main`, and manual diagnostic runs. It tests synthetic two-page
PDFs over real HTTP on all four platforms: authentication, page selection,
invalid/complete translations, short cells and Chinese text, fillback text,
restart recovery, session deletion and owner-pipe shutdown. Runtime smoke tests
use an unusable proxy to prevent external downloads; no private PDFs or LLMs are used.

1. Before merging, require the complete workflow to pass for the current PR
   revision: models, all four runtimes with HTTP smoke tests, and final
   manifest/source assembly. Use a merge commit.
2. After merging, wait for the resulting `main` push build to pass again.
   A branch or manual build is not a release candidate.
3. With explicit publication approval, run
   [Publish verified desktop plugin](.github/workflows/publish-desktop-plugin.yml)
   manually on `main`. Set `build_run` to that successful push run's numeric ID.

The publisher checks all six jobs and their steps, confirms the build commit is in
`main` history, and reads the version and release notes from that exact commit.
It transfers `complete-plugin` on a GitHub runner, creates a draft stable
`v<version>` release matching `pyproject.toml`, uploads all ZIPs and
`desktop-plugin.json`, and verifies every asset's size and SHA-256 before publishing
as latest. It rejects incomplete checks, non-newer versions, conflicting releases
and asset replacement. Existing tags and assets are never overwritten.

The build workflow is read-only and never publishes. Only the manually invoked
publisher has release-write permission, so Desktop cannot discover a partially
uploaded stable release.

## License

The bridge is licensed under [AGPL-3.0-only](LICENSE). Third-party components retain
their own licenses.

Runtime ZIPs include dependency notices, this README and exact installed
requirements. The model ZIP includes font copyrights and full license texts.
Each platform has a corresponding source ZIP for copyleft dependencies, MuPDF,
GEOS and Python, alongside a separate bridge source ZIP.
See [THIRD_PARTY.md](THIRD_PARTY.md) for details. Review licenses when upgrading
dependencies; packaging does not replace legal review or OS signing/notarization.
