## English

This update to the optional BabelDOC plugin and Python package addresses PDF text splitting and formula placement during translation. It is not an update to Wenyi Desktop itself.

### Fixes

- **Paragraphs and captions:** Repair clipped words and overlapping caption detections, and prevent an inline accent assigned to the wrong text box from splitting a paragraph into overlapping translations. A word already covered by another prose box is not pulled into a neighboring column.
- **Inline mathematics:** Keep confirmed variable runs, scripts, and comma-separated sets together; retain wide accents identified by the PDF's font encoding and original fraction rules drawn as solid inline masks. Transparent masks are not treated as division.
- **Chart legends and formula-only pages:** Preserve the original glyphs in recognized math legend entries. A document or page selection with only protected formulas can be rendered without translations, including after session recovery.

### Upgrade notes

- Desktop users can update the plugin in Settings. Python users should upgrade `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`, and restart the service.
- Re-extract the original PDF to use the new layout and formula grouping. Re-exporting from an existing frozen session does not rerun extraction.

---

## 中文

本次更新面向可选 BabelDOC 插件和 Python 包，修复 PDF 翻译中的文字切分与公式排版问题，不包含 Wenyi Desktop 主程序更新。

### 问题修复

- **正文与图注：** 补齐被版面框截断的单词，合并重叠的图注检测框，避免行内重音被分到错误文本框后导致段落切分、译文叠印。已被其他正文框完整覆盖的单词不会被吸入相邻栏。
- **行内公式：** 将已确认的连续变量、上下标和逗号分隔的数学集合保留为整体；保留 PDF 字体编码所识别的宽重音，以及以实心行内蒙版绘制的原始分数线。透明蒙版不会被当作除法。
- **图例与纯公式页：** 识别出的数学图例保留原始字形。选中的页面或文档如果只有受保护的公式，无需译文即可回填，恢复会话后也适用。

### 升级说明

- Desktop 用户可在设置中更新插件。Python 用户请在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check`，然后重启服务。
- 要使用新版的版面和公式分组规则，请重新提取原 PDF。使用旧的冻结会话重新导出不会重新提取。
