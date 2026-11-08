## English

This release adds aligned PDF formula, marker, style and hyperlink preservation
to the independent BabelDOC bridge. It includes the optional plugin and Python
package, not an update to the Wenyi Desktop application itself.

### PDF annotations

- **Original inline objects:** Restore frozen formula and corner/citation-marker
  objects and mixed styles at the target offsets supplied by Wenyi's shared
  annotation aligner, without regenerating mathematical content.
- **Clickable translated text:** Capture URI, internal page and resolved named
  links before BabelDOC clears annotations, then rebuild their clickable areas
  from the actual typeset glyphs. Internal destinations follow selected output
  pages; links to omitted destination pages are omitted.
- **Independent best-effort fillback:** Keep successful items even when another
  item in the same paragraph fails. Missing, stale, invalid or fallback positions
  omit only the affected annotations; formula/style conflicts omit their
  participants. Annotation failures do not block export or replace translated
  paragraphs with source text. Fillback itself makes no translation-model calls.
- **Diagnostics:** Advertise `annotation-best-effort-v1`, return per-request
  validation/application statistics, and save per-item skip reasons in
  `annotation_stats.json`. The compatible Wenyi client records the summary in
  its diagnostic log.

### Extraction and recovery

- Preserve original glyph offsets before style regrouping and split discontinuous
  style/link runs, keeping stable paragraph and composition identities.
- Select linked glyphs by their centers so tall citation-link rectangles do not
  accidentally include words on neighboring lines.
- Load fresh frozen IL for every fillback. Regression tests cover partial failure
  within one paragraph, formulas/markers, page selection, retries, recovery,
  deletion and cropped/rotated link geometry.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings; publication does
  not automatically upgrade an installed plugin. Python users can upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`,
  and restart the service.
- New annotation preservation requires an annotation-capable Wenyi build.
  Older text-only projects need fresh extraction to acquire annotation metadata;
  existing sessions are not silently migrated or supplemented. Keep translation
  state and session backups, and retain matching Python/BabelDOC versions for
  frozen-session recovery.
- Placement-validation and application rates are not semantic accuracy scores.
  A model can mark an overly broad formula range as aligned, including in date
  fields. BabelDOC's formula recognition, fixed paragraph boxes and font scaling
  still limit fidelity; this release does not claim those quality issues are solved.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtimes
  and share the model/font archive. The service remains AGPL-3.0-only with
  protocol 1 and PyMuPDF 1.x; packages are not Windows code-signed or macOS notarized.

---

## 中文

本版为独立 BabelDOC bridge 增加 PDF 公式、角标、样式及超链接的对齐回填。
发布范围包含可选插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### PDF 标注

- **恢复原始行内对象：** 按文译共用对齐器提供的译文位置，恢复冻结的公式、
  引用角标对象及混合样式，不重新生成数学内容。
- **译文链接可点击：** 在 BabelDOC 清理注释前保存网址、内部页码和已解析命名目标，
  再按排版后的实际字形重建点击区域。内部跳转映射到选定输出页；目标页未导出时省略链接。
- **同段逐项回填：** 同段中一项失败不影响其他成功项。位置缺失、过期、无效或处于
  回退状态时，仅忽略相关标注；公式／样式冲突时忽略参与冲突的项。
  标注失败不会阻止导出，也不会把已译段落替换回原文。回填本身不调用翻译模型。
- **诊断统计：** 声明 `annotation-best-effort-v1` 能力，返回本次回填的位置校验
  通过率和应用统计，并在 `annotation_stats.json` 中记录逐项跳过原因。
  兼容的文译客户端会将摘要写入诊断日志。

### 提取与恢复

- 在样式重分组前保存原始字形偏移，拆开不连续的样式／链接范围，保留稳定的段落和组成身份。
- 按字形中心判断链接范围，避免过高的文献链接矩形误选相邻行文字。
- 每次回填重新加载冻结 IL。回归测试覆盖同段部分失败、公式／角标、页面选择、
  重试、恢复、删除，以及裁切／旋转页面的链接几何。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
  Python 用户可在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check` 后重启服务。
- 新标注保留能力需要支持 PDF 标注对齐的文译版本。旧的纯文本项目需重新提取以补齐
  标注元数据；不会静默迁移或补写现有会话。保留译文状态和会话备份；
  冻结会话恢复仍要求匹配的 Python/BabelDOC 版本。
- 位置校验通过率和应用率不代表语义正确率。模型仍可能把过宽的公式范围标成成功，
  日期栏就是一种情况。BabelDOC 的公式识别、固定段落框和字体缩放仍会限制保真度，
  本版不宣称这些质量问题已经解决。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
  服务仍采用 AGPL-3.0-only、protocol 1 和 PyMuPDF 1.x；
  运行包未做 Windows 代码签名或 macOS 公证。
