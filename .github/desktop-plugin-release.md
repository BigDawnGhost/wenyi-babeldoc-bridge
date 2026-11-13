## English

This release upgrades the independent bridge to **BabelDOC 0.7.1** and introduces
precompiled Python wheels. It includes the optional plugin and Python package,
not an update to the Wenyi Desktop application itself.

### Native engine and Python wheels

- **Pinned Rust stages:** PDF parsing, paragraph/style analysis, typesetting and
  writing use the Rust crates from the exact BabelDOC 0.7.1 revision through a
  bridge-owned PyO3 extension. HTTP, annotation and directory-row policies remain
  in Python; Wenyi still communicates with this separate AGPL process over HTTP.
- **Precompiled installation:** Platform wheels target Linux x64, Windows x64,
  macOS Intel and Apple Silicon with the CPython 3.10 stable ABI. Supported
  Python versions remain 3.10–3.13. Installing a matching wheel does not require
  Rust; source builds require Rust/Cargo and a C/C++ toolchain.
- **Restart-safe snapshots:** Compressed native graph checkpoints preserve
  shared objects, lazy graphics-state history and the parser's page-object map.
  Each fillback loads a fresh graph, and recovery does not reload the layout model.
- **Preserved integration behavior:** Stable paragraph IDs, selected-page exports,
  aligned formulas/styles/links, directory rows and protected vertical glyphs
  continue through the production pipeline. The HTTP schema and Desktop protocol
  remain unchanged.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings; publication does
  not automatically upgrade an installed plugin. Python users can upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`,
  and restart the service.
- **BabelDOC 0.5/0.6 sessions are incompatible with the new snapshot format.**
  Keep existing translation state and session backups. Finish old tasks in their
  original environment, or extract the original PDF again with the new bridge.
  Old pickle/JSON snapshots are rejected, not loaded or automatically migrated.
- The bridge wheel does not contain a Python interpreter, fonts or models.
  Desktop runtimes are self-contained and use a separate shared model/font ZIP.
  Python installations resolve dependencies normally and use BabelDOC's asset cache.
- Validation uses synthetic PDFs and local roundtrip checks, including CJK text,
  formulas/links, directory rows, vertical glyphs and restart recovery. It does
  not establish real-model translation quality or pixel-identical preservation.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtimes
  and share the model/font archive. The service remains AGPL-3.0-only with
  protocol 1 and PyMuPDF 1.x; packages are not Windows code-signed or macOS notarized.

---

## 中文

本版将独立 bridge 升级到 **BabelDOC 0.7.1**，并提供 Python 预编译 wheel。
发布范围包含可选插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### 原生引擎与 Python wheel

- **固定版本的 Rust 流程：** 通过 bridge 自有的 PyO3 扩展调用 BabelDOC 0.7.1
  准确提交中的 Rust crate，负责 PDF 解析、段落/样式分析、排版和写出。
  HTTP、注释和目录行策略仍由 Python 负责；Wenyi 仍仅通过 HTTP 访问独立 AGPL 进程。
- **预编译安装：** Linux x64、Windows x64、macOS Intel 和 Apple Silicon wheel
  使用 CPython 3.10 稳定 ABI，支持 Python 3.10–3.13。安装匹配的 wheel 不需要 Rust；
  从源码构建需要 Rust/Cargo 和 C/C++ 工具链。
- **可恢复的原生快照：** 压缩图快照保留共享对象、惰性图形状态历史和解析器页面对象映射。
  每次回填加载全新副本，恢复会话时不重新加载版面模型。
- **保留集成行为：** 生产路径继续支持稳定段落 ID、选页导出、公式/样式/链接对齐、
  目录行和竖排字形保护；HTTP schema 与 Desktop protocol 保持不变。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
  Python 用户可在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check` 后重启服务。
- **BabelDOC 0.5/0.6 会话与新快照格式不兼容。** 保留已有译文状态及会话备份；
  在原环境完成旧任务，或使用新 bridge 重新抽取原始 PDF。
  旧 pickle/JSON 快照会被拒绝，不会加载或自动迁移。
- bridge wheel 不包含 Python 解释器、字体或模型。Desktop 运行包自带运行环境，
  另配共用模型/字体 ZIP；Python 安装按常规解析依赖并使用 BabelDOC 资源缓存。
- 验证使用合成 PDF 和本地回填检查，覆盖中文、公式/链接、目录行、竖排和重启恢复。
  这些验证不代表真实模型翻译质量评估，也不保证逐像素保留版面。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
  服务仍采用 AGPL-3.0-only、protocol 1 和 PyMuPDF 1.x；
  运行包未做 Windows 代码签名或 macOS 公证。
