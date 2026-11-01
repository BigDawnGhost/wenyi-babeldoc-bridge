## English

This patch reduces the runtime packaging overhead of the optional BabelDOC plugin for Wenyi Desktop. It is not a Wenyi Desktop application update.

### Improvements

- **Leaner runtimes:** Use headless OpenCV instead of installing overlapping GUI and headless packages, and stop collecting unused BabelDOC and ONNX Runtime tooling. Required PDF resources, native inference libraries and license notices are retained.
- **Unchanged models and fonts:** This is a runtime packaging change, not a model or font reduction. BabelDOC remains at 0.5.20; extraction, translation and layout behavior are not intentionally changed.

### Development and documentation

- **Packaging regression checks:** The build rejects conflicting OpenCV packages, reports per-component archive sizes, and exercises Chinese text alongside short labels, PDF fillback and restart recovery with synthetic PDFs.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings. Publishing this release does not automatically upgrade an installed plugin.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtime packages and share the same model/font package. Runtime size reductions vary by platform; the model/font download is not reduced.
- The runtime remains an independent AGPL-3.0-only service using protocol 1. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本补丁精简 Wenyi Desktop 可选 BabelDOC 插件的运行环境打包体积，**不是 Wenyi Desktop 主程序更新**。

### 改进

- **运行包瘦身：** 仅使用 headless OpenCV，不再同时安装相互覆盖的 GUI 与 headless 包，并停止全量收集未使用的 BabelDOC 和 ONNX Runtime 工具模块。保留必要的 PDF 资源、原生推理库和许可证。
- **模型与字体不变：** 本次仅调整运行环境打包，不裁剪模型或字体。BabelDOC 仍为 0.5.20，不主动改变提取、翻译或排版行为。

### 开发与文档

- **打包回归检查：** 构建前拒绝冲突的 OpenCV 包，输出各组件体积报告，并使用合成 PDF 验证中文、短文本、PDF 回填与重启恢复。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。运行包缩减幅度因平台而异，模型/字体下载量不变。
- 运行环境仍是独立的 AGPL-3.0-only 服务，沿用 protocol 1。运行包未做 Windows 代码签名或 macOS 公证。
