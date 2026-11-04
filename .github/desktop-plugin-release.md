## English

This update moves the independent BabelDOC bridge and optional Wenyi Desktop
plugin to BabelDOC 0.6. It is not a Wenyi Desktop application update.

### Improvements

- **Reuse model/font downloads:** Unchanged resources and license notices retain the exact ZIP bytes and SHA-256 from v0.1.2. Desktop can reuse its verified download cache even when the plugin version and asset filename change; no client protocol update is required.
- **Unified parser:** Desktop pins BabelDOC 0.6.2 and uses the same native PDF
  parser as ordinary and Zotero bridge installations. Synthetic PDF regressions
  cover extraction, stable IDs, translated fillback and session recovery.
- **Validate before reuse:** Builds compare every resource and notice, fail if
  the reference archive cannot be verified, and create a new archive only when
  contents change.

### Development and documentation

- **Main-based integration:** Pull requests target `main` and validate models plus Linux/Windows runtimes with HTTP smoke tests. macOS and final assembly run on main, tags and manual builds, not PRs. Publication still requires complete main and tag builds at the same commit.
- **Git-tag versions and PyPI:** Package and API versions come from Git tags.
  Stable Desktop publication verifies both the main build and a tag build at the
  same commit; public releases upload the Python distribution through Trusted Publishing.
- **Cache regression checks:** Tests cover unchanged archives, changed models/fonts/licenses, invalid reference downloads and stable packaging across runtime versions.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings. Publishing this release does not automatically upgrade an installed plugin.
- Finish BabelDOC 0.5 sessions in the old environment or re-extract the original
  PDF with 0.6. Frozen sessions are not migrated across BabelDOC versions.
- Keep the downloaded model ZIP cache to avoid downloading it again. New installations, missing or corrupted cached ZIPs, and older differently hashed caches still require a download. Per-installation extraction remains unchanged; this does not reduce the model/font package itself.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtime packages and share the same model/font package.
- The runtime remains an independent AGPL-3.0-only service using protocol 1. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本次将独立 bridge 与 Wenyi Desktop 可选插件统一升级到 BabelDOC 0.6，
**不是 Wenyi Desktop 主程序更新**。

### 改进

- **复用模型与字体下载：** 资源及许可证未变化时，保留 v0.1.2 资源包的原始 ZIP 字节与 SHA-256。即使插件版本号和资源文件名变化，Desktop 仍能复用已校验的下载缓存，无需升级客户端协议。
- **统一解析器：** Desktop 固定 BabelDOC 0.6.2，与普通及 Zotero bridge 安装共用原生
  PDF 解析入口。合成 PDF 回归覆盖提取、稳定 ID、译文回填和会话恢复。
- **验证后才复用：** 构建时逐项比较资源与许可内容，基线压缩包无法验证时明确失败，
  只有内容变化才生成新包。

### 开发与文档

- **统一合入 main：** PR 直接提交到 `main`，验证模型包、Linux/Windows 运行包与 HTTP 冒烟；macOS 和最终组装仅在 main、标签及手动构建运行。发布仍要求同一提交的完整 main 和标签构建。
- **Git 标签版本与 PyPI：** 包和 API 版本来自 Git 标签。Desktop 稳定版发布同时验证
  同一提交的 main 和标签构建；公开 Release 通过可信发布上传 Python 分发包。
- **缓存回归检查：** 覆盖资源包未变化、模型/字体/许可证变化、基线下载异常，以及跨运行环境版本的稳定打包。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
- 在旧环境完成 BabelDOC 0.5 的会话，或在 0.6 环境重新提取原 PDF；冻结快照不跨版本迁移。
- 保留已下载的模型 ZIP 缓存才能避免重复下载。首次安装、缓存缺失或损坏、仅有更早且哈希不同的缓存时，仍需下载。各安装目录的解压方式不变，本优化不缩减模型/字体包本身。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
- 运行环境仍是独立的 AGPL-3.0-only 服务，沿用 protocol 1。运行包未做 Windows 代码签名或 macOS 公证。
