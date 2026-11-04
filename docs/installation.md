# Installation and development

[简体中文](zh/installation.md) · [Overview](../README.md) · [HTTP API](api.md)

## Supported dependencies

The bridge supports Python 3.10–3.13 and uses BabelDOC's native 0.6 parser:

- `babeldoc>=0.6.2,<0.7.0`
- `bitstring>=4.3.0,<5`
- `pymupdf<2`

Both standard installs and Desktop builds stay on PyMuPDF 1.x to retain Intel
macOS wheels and Python 3.10 compatibility. This caps the major version only;
minor versions are resolved jointly with BabelDOC and Wenyi. Do not upgrade
BabelDOC or PyMuPDF independently or bypass dependency checks with `--no-deps`.
Upstream does not maintain a 1.x branch, so this compatibility choice is not a
long-term security-support guarantee; review security fixes when updating dependencies.

Neither PDF2zh frontend is required, and there is no PDF2zh-specific installation
extra. Sharing an environment does not change process or license boundaries.

## Install with Wenyi CLI

By default, install `wenyi-cli` and `wenyi-babeldoc-bridge` together in one
dedicated Python 3.12 environment. The CLI installs `wenyi-core` automatically;
the bridge installs BabelDOC and its PDF dependencies.

```bash
uv venv .venv-wenyi --python 3.12
uv pip install --python .venv-wenyi/bin/python wenyi-cli wenyi-babeldoc-bridge
uv pip check --python .venv-wenyi/bin/python
```

These index commands require published CLI/Core and bridge versions containing
the shared-environment integration and documented compatibility constraints.
Pin versions actually verified for production. CLI/Core and bridge versions are
independent and do not need to match.

On Windows, use `Scripts/python.exe`, `Scripts/wenyi.exe`, and
`Scripts/wenyi-babeldoc-bridge.exe` instead of `bin/`.

Do not reuse the plugin's `pdf2zh_next` environment or the Wenyi source workspace's
development environment. In particular, do not manage this deployment with
`uv sync` in the Wenyi workspace: it can remove a bridge that is not a workspace
dependency. The PDF2zh updater does not manage this environment or start the bridge.

Finish running tasks before upgrading. Afterwards, run `uv pip check` and a PDF
smoke test again. Existing sessions require compatible Python/BabelDOC versions;
see [session recovery](api.md#session-recovery).

## Start the service

Use the dedicated environment's entry point explicitly:

```bash
.venv-wenyi/bin/wenyi-babeldoc-bridge
# Alternatively:
.venv-wenyi/bin/python -m uvicorn \
  wenyi_babeldoc_bridge.server:app --host 127.0.0.1 --port 8765
```

The environment is shared, not the process: start the bridge separately and let
Wenyi call it over HTTP. Do not import bridge/BabelDOC modules into Wenyi.
Each component and dependency retains its own license obligations.

## Caches and sessions

Fonts and models use BabelDOC's default `~/.cache/babeldoc/`, independently of the
virtual environment. Missing or checksum-mismatched resources are downloaded.
Installing the bridge from PyPI avoids fetching its Python source from GitHub,
but does not bundle fonts or models into the wheel.

`WENYI_BABELDOC_STATE_DIR` controls session storage, not font/model caches.
For persistent sessions, choose a dedicated directory before starting the service:

```bash
export WENYI_BABELDOC_STATE_DIR=/path/to/wenyi-babeldoc-sessions
.venv-wenyi/bin/wenyi-babeldoc-bridge
```

The default session directory is `wenyi-babeldoc-bridge/` under the system
temporary directory. It survives service restarts but may be cleared by the OS.

## Develop from source

When developing only the bridge, create an isolated environment in this repository,
without installing Wenyi CLI. Run these commands from the repository root:

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

Use `.venv` instead of `.venv-wenyi` in the startup commands above.

## Validation

After installing and activating the service environment, run the lightweight
tests without downloading models:

```bash
PYTHONPATH=src python -m unittest discover -s src/wenyi_babeldoc_bridge -p 'test_*.py'
```

The opt-in BabelDOC regression uses a synthetic two-page PDF and no translation
API. It may download missing fonts/models. It verifies full-document and page-2
extraction, stable IDs, Chinese fillback, invalid translations, frozen IL reuse,
session recovery and cleanup:

```bash
WENYI_BABELDOC_INTEGRATION=1 PYTHONPATH=src \
  python -m unittest wenyi_babeldoc_bridge.test_babeldoc_integration -v
```

For frozen-runtime builds and real HTTP smoke tests, see the
[Desktop guide](desktop.md).
