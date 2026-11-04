## English

This maintenance release restores complete Desktop plugin packaging and keeps
the independent BabelDOC bridge on PyMuPDF 1.x. It includes the optional plugin
and Python package, not an update to the Wenyi Desktop application itself.

### Fixes

- **Intel macOS builds:** Standard installations and Desktop builds now require
  `pymupdf<2`, avoiding the PyMuPDF 2.x source-build failure on Intel Macs.
  Compatible 1.x minor versions remain resolver-selected; Desktop still pins
  BabelDOC 0.6.2, while ordinary installations support BabelDOC 0.6.

### Development and documentation

- **Separate language guides:** English installation, API, Desktop and publishing
  guides live in `docs/`, with matching Chinese guides in `docs/zh/`.
  READMEs provide concise introductions and navigation.
- **Bundled documentation:** Runtime ZIPs include both language sets so their
  README links continue to work. Regression tests cover documentation packaging
  and the PyMuPDF major-version boundary.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings; publication does
  not automatically upgrade an installed plugin. Python users can upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment and run `uv pip check`.
- v0.1.4 was Python/source-only. Desktop users upgrading from v0.1.3 or earlier
  move to BabelDOC 0.6: finish 0.5 sessions in the old environment or re-extract
  the original PDF. Frozen sessions are not migrated across BabelDOC versions.
  The updated model/font archive includes native-parser CMaps and needs a new
  download when the matching verified archive is not already cached.
- PyMuPDF 1.x is a compatibility choice, not a long-term security-support
  guarantee; upstream does not maintain a separate 1.x branch.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtimes
  and share the model/font archive. The service remains AGPL-3.0-only with
  protocol 1; packages are not Windows code-signed or macOS notarized.

---

## 中文

本次维护版本恢复完整 Desktop 插件打包，并将独立 BabelDOC bridge 保持在 PyMuPDF 1.x。
发布范围包含可选插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### 问题修复

- **Intel macOS 构建：** 普通安装与 Desktop 构建统一要求 `pymupdf<2`，
  避免 Intel Mac 上 PyMuPDF 2.x 的源码构建失败。兼容的 1.x 小版本仍由依赖解析选择；
  Desktop 继续固定 BabelDOC 0.6.2，普通安装支持 BabelDOC 0.6。

### 开发与文档

- **中英文分离：** 英文安装、API、Desktop 和发布指南放在 `docs/`，
  对应中文指南放在 `docs/zh/`；README 只保留简介与导航。
- **随包提供文档：** 运行包包含两种语言的文档，避免 README 链接失效。
  回归测试覆盖文档打包和 PyMuPDF 大版本约束。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
  Python 用户可在专用环境中升级 `wenyi-babeldoc-bridge`，再运行 `uv pip check`。
- v0.1.4 仅发布了 Python/源码。从 v0.1.3 或更早版本升级的 Desktop 用户将切换到
  BabelDOC 0.6：请在旧环境完成 0.5 会话，或重新提取原 PDF；冻结快照不跨版本迁移。
  新模型/字体包包含原生解析器的 CMap；没有缓存匹配且已验证的资源包时，需要重新下载。
- 保留 PyMuPDF 1.x 是兼容性选择，不代表长期安全支持；上游不维护独立的 1.x 分支。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
  服务仍采用 AGPL-3.0-only 和 protocol 1；运行包未做 Windows 代码签名或 macOS 公证。
