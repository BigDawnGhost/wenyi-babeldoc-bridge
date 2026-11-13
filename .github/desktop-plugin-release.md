## English

This release fixes rotated sidebar preservation in the independent BabelDOC
bridge. It includes the optional plugin and Python package, not an update to
the Wenyi Desktop application itself.

### Rotated text preservation

- **Skip before translation:** Paragraphs marked `vertical=True` by BabelDOC
  are no longer sent for translation. Their original glyphs, fonts, sizes,
  coordinates, rotation and links are preserved without reflow, regardless of
  layout class.
- **Protect existing sessions:** Previously extracted rotated paragraphs also
  retain their frozen glyphs and links, even when saved translations reorder
  their text or annotation placements are stale. Paragraph IDs and frozen
  snapshots remain unchanged across repeated exports and session recovery.
- **Replace the text-equality shortcut:** Preservation now follows BabelDOC's
  vertical flag rather than requiring translation text and annotation positions
  to match the extracted source. Nonvertical paragraphs use normal text and
  annotation fillback, including when their text is unchanged.

### Upgrade notes

- Update the optional BabelDOC plugin from Desktop Settings; publication does
  not automatically upgrade an installed plugin. Python users can upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`,
  and restart the service.
- Export the PDF again after updating to apply the protection to an existing
  compatible session. Previously generated PDFs are not rewritten automatically.
  Keep translation state and session backups; frozen-session recovery still
  requires matching Python/BabelDOC versions.
- Protection depends on BabelDOC's `vertical` flag; it does not add a separate
  rotation detector or translate vertical text.
- Windows x64, Linux x64, macOS Apple Silicon and Intel have separate runtimes
  and share the model/font archive. The service remains AGPL-3.0-only with
  protocol 1 and PyMuPDF 1.x; packages are not Windows code-signed or macOS notarized.

---

## 中文

本版修复独立 BabelDOC bridge 中旋转侧栏文字的保留问题。
发布范围包含可选插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### 旋转文字保护

- **翻译前跳过：** BabelDOC 标记为 `vertical=True` 的段落不再送往翻译器。
  不论版面类别，均直接保留原始字形、字体、字号、坐标、旋转及链接，不重新排版。
- **已有会话同样受保护：** 即使已保存的译文调整了侧栏文字顺序，或标注位置已经过期，
  仍保留冻结快照中的字形和链接。重复导出及会话恢复不会改变段落 ID 和冻结快照。
- **取代文字相等判断：** 保护依据改为 BabelDOC 的竖排标记，不再要求译文及标注位置
  与抽取原文完全相同。非竖排段落统一走正常文字／标注回填，即使文字未发生变化。

### 升级说明

- 在 Desktop 设置中更新可选 BabelDOC 插件。发布本版不会自动升级已安装的插件。
  Python 用户可在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check` 后重启服务。
- 更新后重新导出 PDF，即可将保护应用于已有的兼容会话。已经生成的 PDF 不会自动改写。
  保留译文状态和会话备份；冻结会话恢复仍要求匹配的 Python/BabelDOC 版本。
- 保护依赖 BabelDOC 的 `vertical` 标记，不增加独立的旋转检测，也不提供竖排文字翻译。
- Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别提供运行包，共用模型/字体包。
  服务仍采用 AGPL-3.0-only、protocol 1 和 PyMuPDF 1.x；
  运行包未做 Windows 代码签名或 macOS 公证。
