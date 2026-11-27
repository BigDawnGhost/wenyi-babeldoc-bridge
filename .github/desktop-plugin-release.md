## English

This update to the optional BabelDOC plugin and Python package preserves printed page numbers when translating a PDF's table of contents. It does not update the Wenyi Desktop application.

### Fixes

- **Contents entries:** In a recognized front-of-book contents section, titles can be translated independently, including wrapped titles. The printed decimal page numbers stay at their original positions. A link on a number keeps its original destination if that page is included in the output; the bridge does not recalculate printed numbers from links.
- **Scope:** The repair requires a contents heading and a consistent page-number column supported by dot leaders or links on the same row. It stops when the contents section ends. A missing page-number column or an ambiguous two-column layout uses the existing extraction path.

### Upgrade notes

- Desktop users can update the plugin in Settings. Python users should upgrade `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`, and restart the service.
- Re-extract the original PDF to apply this repair. Re-exporting an existing frozen session does not change its paragraph boundaries. No change to the HTTP client is required.

---

## 中文

本次更新面向可选 BabelDOC 插件和 Python 包，修复翻译 PDF 目录时印刷页码随标题移动的问题，不包含 Wenyi Desktop 主程序更新。

### 问题修复

- **目录条目：** 在确认的书前目录中，标题可逐条翻译，跨行标题也能作为一项处理。印刷的十进制页码保留在原位置。页码上原有的链接在目标页包含于输出时仍指向原落点；不会根据链接重算印刷页码。
- **适用范围：** 需要有目录标题、对齐的页码列，以及点引导线或本行链接作为佐证。目录结束后不再套用这条规则。没有页码列或双栏归属不明确时，沿用原抽取逻辑。

### 升级说明

- Desktop 用户可在设置中更新插件。Python 用户请在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check`，然后重启服务。
- 要启用修正，请重新提取原 PDF。重新导出旧会话不会改变段落边界，无需修改 HTTP 客户端。
