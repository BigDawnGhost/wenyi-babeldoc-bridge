## English

This release adds protected mathematical objects and improves PDF link styling
and directory-row preservation. It updates the optional BabelDOC plugin and Python
package, not the Wenyi Desktop application itself.

### Improvements

- **Original mathematical objects:** New extraction groups confirmed formulas,
  mathematical-font glyphs and operators with adjacent variables. The bridge
  preserves their original glyphs, fonts and relative geometry; clients receive
  opaque identities and insertion points rather than lossy formula transcriptions.
- **Validated PDF fillback:** The `protected-objects-v1` capability requires complete,
  valid protected-object placements, including explicit order for coincident points.
  Ordinary styles, links and legacy unprotected formulas remain best effort.

### Fixes

- **Link appearance:** Precisely aligned links retain their original color and font
  when an overlapping body-style range is too broad. Links are not uniformly
  recolored blue.
- **Adjacent CJK prose:** Mathematical protection keeps neighboring Chinese,
  Japanese and Korean prose translatable even without intervening spaces.
- **Directories containing mathematics:** Row offsets follow the same clean-source
  mapping as annotations, preserving the original row boxes and order through
  fillback and session restoration.

### Upgrade notes

- Update Wenyi and the optional BabelDOC plugin together, then import the PDF into
  fresh state to enable protected objects and corrected extraction boundaries.
  Existing translation state and frozen sessions are not migrated in place.
- Desktop users update the plugin in Settings; Python users upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check` and
  restart the service. Publication does not upgrade an installed plugin.
- Recognition depends on native formula detection, mathematical character/font
  evidence and grouping boundaries. Check formula coverage and final layout.
  Synthetic PDF regressions do not establish real-model translation quality or
  pixel-identical preservation.
- BabelDOC remains pinned to 0.7.1. The service remains an independent AGPL-3.0-only
  process with protocol 1, Python 3.10–3.13 and PyMuPDF 1.x. Linux x64, Windows x64,
  macOS Intel and Apple Silicon retain separate runtimes and a shared model/font
  archive. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本版增加数学对象保护，并改进 PDF 链接样式和目录行保留。
发布范围是可选 BabelDOC 插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### 改进

- **原始数学对象：** 新抽取将确认的公式、数学字体字形及运算符与相邻变量组成完整对象。
  bridge 保留原字形、字体和相对几何；客户端只接收不透明身份和插入点，
  不接收有损的公式转写。
- **校验 PDF 回填：** `protected-objects-v1` 能力要求受保护对象的位置完整有效，
  同一插入点的对象须明确排序。普通样式、链接及旧会话中未受保护的公式仍采用尽力恢复。

### 问题修复

- **链接外观：** 正文样式范围过宽并与链接重叠时，精确对齐的链接仍保留原始颜色和字体，
  不将所有链接统一染蓝。
- **相邻中日韩正文：** 数学保护不再吞掉没有空格分隔的相邻中文、日文和韩文正文，
  这些文字仍可正常翻译。
- **含数学内容的目录：** 行偏移与标注采用同一份清理后原文映射，
  在回填和会话恢复后保留原始行框与顺序。

### 升级说明

- 同时更新文译和可选 BabelDOC 插件，再将 PDF 导入到新状态中，
  才能启用对象保护和修正后的抽取边界；已有译文状态及冻结会话不原地迁移。
- Desktop 用户在设置中更新插件；Python 用户在专用环境中升级
  `wenyi-babeldoc-bridge`，运行 `uv pip check` 后重启服务。
  发布本版不会自动升级已安装的插件。
- 识别覆盖率仍取决于原生公式检测、数学字符／字体证据及合并边界，
  需检查公式覆盖和最终版面。合成 PDF 回归不代表真实模型翻译质量评估，
  也不保证逐像素保留版面。
- BabelDOC 仍固定为 0.7.1；服务保持独立 AGPL-3.0-only 进程、protocol 1、
  Python 3.10–3.13 和 PyMuPDF 1.x。Linux x64、Windows x64、macOS Intel
  和 Apple Silicon 继续提供独立运行包及共用模型／字体包。
  运行包未做 Windows 代码签名或 macOS 公证。
