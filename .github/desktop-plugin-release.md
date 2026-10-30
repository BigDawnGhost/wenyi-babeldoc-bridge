## English

The first self-contained BabelDOC plugin runtime for Wenyi Desktop. This provides the optional PDF layout-preserving service and offline assets; it is not a Wenyi Desktop application update.

### New features

- **Optional local plugin:** Compatible Wenyi Desktop builds can download and manage the independent runtime from Settings, without a separate Python installation. Native packages are provided for Windows x64, Linux x64, macOS Intel and Apple Silicon.
- **Offline assets:** The shared model archive includes layout/OCR models, fonts and tokenizer assets. Assets are verified before readiness; PDF processing does not download additional models.
- **Managed private service:** Desktop starts an authenticated loopback service and stops it on disable or app exit. Frozen PDF sessions support recovery after restart.
- **Integrity and source:** `desktop-plugin.json` includes sizes and SHA-256 hashes. Archives include dependency notices and font licenses; matching bridge and platform-specific dependency source archives are provided.

### Upgrade notes

- Requires a Wenyi Desktop version containing the plugin integration. Publishing this runtime does not add Settings controls to older applications.
- The plugin remains an independent AGPL-3.0-only service, communicating with the MIT application over HTTP. Third-party assets retain their own licenses; see `THIRD_PARTY.md`.
- Installed runtime versions stay pinned to preserve frozen-session compatibility; plugin upgrades are not automatic.
- Packages are not Windows code-signed or macOS notarized. Downloads use official GitHub HTTPS and archive hashes, not the separate application-updater signature scheme.

---

## 中文

首个自带运行环境的 Wenyi Desktop BabelDOC 插件发行版。本次提供可选的 PDF 保留版式服务和离线资源，**不是 Wenyi Desktop 主程序更新**。

### 新增功能

- **可选本地插件：** 包含插件集成功能的 Wenyi Desktop 可在设置中下载并管理独立运行环境，无需另外安装 Python。提供 Windows x64、Linux x64、macOS Intel 与 Apple Silicon 原生包。
- **离线资源：** 共享模型包包含版面/OCR 模型、字体与分词资源。服务就绪前校验资源，处理 PDF 时不再额外下载模型。
- **受管私有服务：** Desktop 启动带鉴权的本地服务，禁用插件或退出应用时停止。冻结的 PDF 会话支持重启后恢复。
- **完整性与源码：** `desktop-plugin.json` 包含大小与 SHA-256。资源附带依赖声明和字体许可证，并提供对应的 bridge 源码及各平台依赖源码包。

### 升级说明

- 需要使用已包含插件集成的 Wenyi Desktop 版本。仅发布本运行环境，不会为旧版应用增加设置入口。
- 插件仍是独立的 AGPL-3.0-only 服务，与 MIT 主程序只通过 HTTP 通信。第三方资源保留各自许可证，详见 `THIRD_PARTY.md`。
- 已安装的运行环境版本保持固定，以维持冻结会话兼容性；插件不会自动升级。
- 运行包未做 Windows 代码签名或 macOS 公证。下载使用官方 GitHub HTTPS 和压缩包哈希校验，区别于主程序更新器的独立签名机制。
