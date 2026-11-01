## English

This patch avoids downloading unchanged models and fonts again when updating the optional BabelDOC plugin for Wenyi Desktop. It is not a Wenyi Desktop application update.

### Improvements

- **Reuse model/font downloads:** Unchanged resources and license notices retain the exact ZIP bytes and SHA-256 from v0.1.2. Desktop can reuse its verified download cache even when the plugin version and asset filename change; no client protocol update is required.
- **Validate before reuse:** Builds compare every resource and notice, fail if the reference archive cannot be verified, and create a new archive only when contents change. BabelDOC remains at 0.5.20; extraction, translation and layout behavior are not intentionally changed.

### Development and documentation

- **Main-based integration:** Pull requests now target `main` and run the complete four-platform plugin workflow before merging. Releases use a separately verified build of the merged `main` commit.
- **Cache regression checks:** Tests cover unchanged archives, changed models/fonts/licenses, invalid reference downloads and stable packaging across runtime versions.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings. Publishing this release does not automatically upgrade an installed plugin.
- Keep the downloaded model ZIP cache to avoid downloading it again. New installations, missing or corrupted cached ZIPs, and older differently hashed caches still require a download. Per-installation extraction remains unchanged; this does not reduce the model/font package itself.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtime packages and share the same model/font package.
- The runtime remains an independent AGPL-3.0-only service using protocol 1. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本补丁避免更新 Wenyi Desktop 可选 BabelDOC 插件时重复下载未变化的模型与字体，**不是 Wenyi Desktop 主程序更新**。

### 改进

- **复用模型与字体下载：** 资源及许可证未变化时，保留 v0.1.2 资源包的原始 ZIP 字节与 SHA-256。即使插件版本号和资源文件名变化，Desktop 仍能复用已校验的下载缓存，无需升级客户端协议。
- **验证后才复用：** 构建时逐项比较资源与许可内容，基线压缩包无法验证时明确失败，只有内容变化才生成新包。BabelDOC 仍为 0.5.20，不主动改变提取、翻译或排版行为。

### 开发与文档

- **统一合入 main：** PR 直接提交到 `main`，合并前运行完整四平台插件工作流；发行版使用合并后 `main` 提交单独验证的构建产物。
- **缓存回归检查：** 覆盖资源包未变化、模型/字体/许可证变化、基线下载异常，以及跨运行环境版本的稳定打包。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
- 保留已下载的模型 ZIP 缓存才能避免重复下载。首次安装、缓存缺失或损坏、仅有更早且哈希不同的缓存时，仍需下载。各安装目录的解压方式不变，本优化不缩减模型/字体包本身。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
- 运行环境仍是独立的 AGPL-3.0-only 服务，沿用 protocol 1。运行包未做 Windows 代码签名或 macOS 公证。
