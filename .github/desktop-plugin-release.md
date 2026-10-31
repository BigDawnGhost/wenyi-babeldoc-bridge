## English

This patch fixes missing short PDF text in the optional BabelDOC plugin for Wenyi Desktop. It is not a Wenyi Desktop application update.

### Fixes

- **Short table labels:** Preserve text such as `Cis man`, `Gender`, and `Percent`, along with single-character and numeric cells. The bridge no longer discards paragraphs based on their length or content.
- **Debug labels:** Exclude layout debug overlays using IL metadata rather than matching words, so genuine text such as `table` and `title` remains available for translation.

### Upgrade notes

- Re-extract affected PDFs after installing the updated runtime. Previously omitted paragraphs are not automatically added to existing sessions.
- Existing Desktop plugin installations remain pinned; publishing this release does not automatically upgrade them.
- The runtime remains an independent AGPL-3.0-only service using the existing protocol 1. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本补丁修复 Wenyi Desktop 可选 BabelDOC 插件遗漏 PDF 短文本的问题，**不是 Wenyi Desktop 主程序更新**。

### 问题修复

- **短表格标签：** 保留 `Cis man`、`Gender`、`Percent` 等短文本，以及单字符和纯数值单元格。bridge 不再按段落长度或文字内容过滤。
- **调试标签：** 根据 IL 元数据排除版面调试叠加标签，不再按单词匹配，因此真实的 `table`、`title` 等文本仍可进入翻译。

### 升级说明

- 安装新版运行环境后，请重新提取受影响的 PDF。旧会话不会自动补入此前遗漏的段落。
- Desktop 已安装的插件版本仍保持固定；发布本版不会使其自动升级。
- 运行环境仍是独立的 AGPL-3.0-only 服务，沿用 protocol 1。运行包未做 Windows 代码签名或 macOS 公证。
