# Desktop plugin release notes

This patch avoids downloading unchanged models and fonts again when updating the optional BabelDOC plugin for Wenyi Desktop. It is not a Wenyi Desktop application update.

## Improvements

- **Reuse model/font downloads:** Unchanged resources and license notices retain the exact ZIP bytes and SHA-256 from v0.1.2. Desktop can reuse its verified download cache even when the plugin version and asset filename change; no client protocol update is required.
- **Validate before reuse:** Builds compare every resource and notice, fail if the reference archive cannot be verified, and create a new archive only when contents change. BabelDOC remains at 0.5.20; extraction, translation and layout behavior are not intentionally changed.

## Development and documentation

- **Main-based integration:** Pull requests now target `main` and run the complete four-platform plugin workflow before merging. Releases use a separately verified build of the merged `main` commit.
- **Cache regression checks:** Tests cover unchanged archives, changed models/fonts/licenses, invalid reference downloads and stable packaging across runtime versions.

## Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings. Publishing this release does not automatically upgrade an installed plugin.
- Keep the downloaded model ZIP cache to avoid downloading it again. New installations, missing or corrupted cached ZIPs, and older differently hashed caches still require a download. Per-installation extraction remains unchanged; this does not reduce the model/font package itself.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtime packages and share the same model/font package.
- The runtime remains an independent AGPL-3.0-only service using protocol 1. Packages are not Windows code-signed or macOS notarized.
