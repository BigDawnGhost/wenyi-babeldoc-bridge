# wenyi-babeldoc-bridge

**English** | [简体中文](docs/zh/README.md)

An **AGPL-3.0-only HTTP service** that uses
[BabelDOC](https://github.com/funstory-ai/BabelDOC) to extract PDF paragraphs and
typeset translations back into the original layout.
[Wenyi](https://github.com/BigDawnGhost/wenyi) produces the translations; this
bridge only provides the external PDF engine.

## Use with Wenyi

- **Desktop:** install the optional, self-contained plugin through Wenyi Desktop.
  No separate Python installation is required. See the [Desktop guide](docs/desktop.md).
- **CLI or manual deployment:** install `wenyi-cli` and `wenyi-babeldoc-bridge`
  in one dedicated Python environment, then start the bridge as a separate HTTP
  process. See [installation and development](docs/installation.md).

BabelDOC is the layout engine. PDF2zh and PDF2zh Next are separate frontends,
not required dependencies of this bridge.

## Documentation

| Guide | Contents |
| --- | --- |
| [Installation and development](docs/installation.md) | Dependencies, shared environment, startup, caches and tests |
| [HTTP API and sessions](docs/api.md) | Extract/fillback contract, stable IDs, recovery and cleanup |
| [Desktop plugin](docs/desktop.md) | Four-platform builds, offline assets, runtime protocol and verification |
| [Publishing](docs/publishing.md) | Git-derived versions, verified Desktop releases and PyPI trusted publishing |

English guides live in `docs/`; Chinese guides live in `docs/zh/`.
The [online repository](https://github.com/BigDawnGhost/wenyi-babeldoc-bridge)
also provides these documents.

## License and process boundary

This repository is [AGPL-3.0-only](LICENSE). Wenyi's own code is MIT-licensed.
The projects communicate only over HTTP: do not import this bridge or BabelDOC
into `wenyi_core`, or copy this repository's code into Wenyi.

A shared Python environment does not merge processes or remove any component's
license obligations. See [third-party materials](THIRD_PARTY.md) for Desktop
dependency notices and corresponding-source distribution.
