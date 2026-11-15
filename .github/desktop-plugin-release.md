## English

This release keeps detached mathematical accents and scripts with their expressions
and preserves non-translatable numeric paragraphs. It updates the optional BabelDOC
plugin and Python package, not the Wenyi Desktop application itself.

### Improvements

- **Explicit best-effort omission:** Updated clients can explicitly omit an
  unresolved protected object when best-effort export is requested. Strict
  validation remains the default; incomplete placements are not silently accepted.

### Fixes

- **Detached mathematical marks:** New extraction conservatively joins overhead
  accents to a unique mathematical base and small scripts in all four corners
  inside mathematical sequences. Expressions move as protected objects while
  retaining original glyphs, fonts and relative geometry. Ambiguity, prose,
  spatial gaps and drawing-context boundaries stop reassignment or expansion.
- **Duplicate or displaced scripts:** A page-level script transferred into a
  protected expression is no longer drawn separately. Detached accent runs and
  inferred wide spaces no longer incorrectly bind distant expressions together.
- **Numeric paragraphs:** Numeric-only, separator-only and vertical paragraphs
  remain in the original PDF instead of becoming translation inputs. The same
  selection rule applies when restoring frozen sessions.

### Upgrade notes

- Update Wenyi and the optional BabelDOC plugin together, then import the PDF into
  fresh state to enable repaired mathematical grouping and extraction boundaries.
  Existing translation state and frozen sessions are not migrated in place.
- Desktop users update the plugin in Settings; Python users upgrade
  `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check` and
  restart the service. Publication does not upgrade an installed plugin.
- Recognition depends on native formula detection, mathematical character/font
  evidence and grouping boundaries. Check formula coverage and final layout;
  explicitly omitted objects can remove mathematical meaning.
  Synthetic PDF regressions do not establish real-model translation quality or
  pixel-identical preservation.
- BabelDOC remains pinned to 0.7.1. The service remains an independent AGPL-3.0-only
  process with protocol 1, Python 3.10–3.13 and PyMuPDF 1.x. Linux x64, Windows x64,
  macOS Intel and Apple Silicon retain separate runtimes and a shared model/font
  archive. Packages are not Windows code-signed or macOS notarized.

---

## 中文

本版修正游离数学重音与角标的归属，并保留不应翻译的数字段落。
发布范围是可选 BabelDOC 插件和 Python 包，**不是 Wenyi Desktop 主程序更新**。

### 改进

- **显式尽力省略：** 更新后的客户端可在请求尽力导出时，显式省略无法定位的受保护对象。
  默认仍执行严格校验，不会静默接受缺少对象定位的请求。

### 问题修复

- **游离数学符号：** 新抽取保守地将正上方重音绑定到唯一的数学基字，
  并归并数学序列内部左上、左下、右上、右下的小号角标。
  表达式作为保护对象一起移动，保留原字形、字体和相对几何。
  遇到歧义、正文、空间间隔或绘制上下文边界时停止归属或扩展。
- **重复或错位角标：** 从页面级转入保护表达式的角标不再单独绘制；
  游离重音组和推断出的宽空格不再将远处表达式错误绑定在一起。
- **数字段落：** 纯数字、纯分隔符及竖排段落保留在原 PDF 中，不再成为翻译输入；
  恢复冻结会话时也使用同一筛选规则。

### 升级说明

- 同时更新文译和可选 BabelDOC 插件，再将 PDF 导入到新状态中，
  才能启用修正后的数学分组和抽取边界；已有译文状态及冻结会话不原地迁移。
- Desktop 用户在设置中更新插件；Python 用户在专用环境中升级
  `wenyi-babeldoc-bridge`，运行 `uv pip check` 后重启服务。
  发布本版不会自动升级已安装的插件。
- 识别覆盖率仍取决于原生公式检测、数学字符／字体证据及合并边界，
  需检查公式覆盖和最终版面；显式省略对象可能损失数学含义。
  合成 PDF 回归不代表真实模型翻译质量评估，
  也不保证逐像素保留版面。
- BabelDOC 仍固定为 0.7.1；服务保持独立 AGPL-3.0-only 进程、protocol 1、
  Python 3.10–3.13 和 PyMuPDF 1.x。Linux x64、Windows x64、macOS Intel
  和 Apple Silicon 继续提供独立运行包及共用模型／字体包。
  运行包未做 Windows 代码签名或 macOS 公证。
