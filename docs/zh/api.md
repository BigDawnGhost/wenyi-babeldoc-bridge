# HTTP API 与会话

[English](../api.md) · [概览](README.md) · [安装](installation.md)

## 接口

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| GET | `/health` | 探活 |
| POST | `/extract` | Multipart：`file` 为 PDF，可选 `pages`；返回 `session_id` 和 `paragraphs` |
| POST | `/fillback` | JSON `{session_id, translations: {id: text}, annotations?: {id: alignment}, rows?: {id: ranges}}`；返回单语 PDF |
| GET / DELETE | `/session/{id}` | 查看或释放会话 |

Wenyi 生成译文，本桥使用 BabelDOC 抽取段落并回填，不运行整本翻译前端。
Desktop 插件在相同 HTTP 契约外增加私有鉴权边界，详见[运行协议](desktop.md#运行协议)。

## 段落身份

段落 ID 为 `"{page}:{index}"`，其中 `index` 是页面 IL 中原始段落的位置。
过滤时不得重新编号，抽取和回填使用相同的身份规则。

抽取保留所有非空原文，包括短词、单字符、纯数值，以及恰好为 `table` 或 `title`
等版面类别名称的真实文本。仅按 IL 的 `debug_info` 属性排除调试叠加标签，
不按长度或文字内容过滤。

更新并重启此前过滤过这类文本的 bridge 后，需要重新提取受影响的 PDF。
旧会话不会自动迁移或补齐遗漏段落。

## 目录行结构

`/health` 声明 `toc-rows-v1`。具有对齐编号、点引导线和页码，且能够可靠识别为同级目录项
的段落包含非空 `rows` 列表。每行记录半开区间 `source_start` / `source_end`，
以及原始 PDF 坐标 `box: [x, y, x2, y2]`。
边界在样式合并视觉行之前保存；正文自然折行仍为软边界，不能可靠识别的版面保持普通段落。

行是原始段落 ID 下的子单元，不插入新编号的段落。
客户端逐条翻译，保留标注身份，并将标注偏移转换到各行内。
跨行样式／链接范围拆成独立标注 ID，仍指向同一原始组成部分或链接；
公式跨行时不将该段归类为独立目录行。

对于每个结构化段落，`/fillback` 必须提供 `rows[id]`，条目数量与提取结果相同。
每项包含在 `translations[id]` 中的 `target_start` / `target_end`。
范围必须有序、非空，并覆盖全部非空白文字。
例如两条译文可使用 `[{"target_start": 0, "target_end": 18},
{"target_start": 19, "target_end": 35}]`。
条目边界由这些范围明确指定，不根据译文换行猜测；单项内部换行不会产生额外条目。
缺失、格式错误或引用未知段落的行范围返回 HTTP 400。

回填逐行应用标注，在各自保存的区域排版，保留父段落 ID 和主渲染顺序。
各行字形在 PDF 文本流中连续排列，以支持搜索和复制。
行结构随会话恢复，缺少行结构的旧会话保持旧行为。
需要同时更新文译与 bridge，再提取到新的状态目录才能启用该契约。

## 行内标注对齐

`/health` 在 `capabilities` 中声明 `annotation-alignment-v1` 和 `annotation-best-effort-v1`。
依赖逐项忽略失败标注的客户端必须检查后者。
每个提取段落包含 `annotations` 列表。每项包含稳定的 `id`、
`kind`（`formula`、`style` 或 `link`）、`mode: "range"`，以及在该段精确
`source` 中的半开区间 `source_start` / `source_end`。
偏移按 Unicode 码点计数，不是 UTF-8 字节或 UTF-16 代码单元。
`composition_index` 指向冻结的公式或样式组成部分；
`link_id` 指向段落文档 `links` 列表中的记录。
客户端不得更改这些身份，也不应重新生成所引用的 IL。
原文偏移在 BabelDOC 合并样式和公式前记录；不连续的样式或链接范围使用独立标注项。

正文中的小字号角标从待翻译 `source` 中移除，使用 `mode: "point"` 和相等的起止偏移表示。
原角标 IL 及其附带的 `link_ids` 仍保存在会话中。
存在 `original_source` 时，该字段记录原段落 Unicode，供快照校验使用。
独立成段的角标仍保留非空原文，使用范围对齐。

Wenyi 在段落翻译完成后复用现有标注对齐器。
`/fillback` 可选的 `annotations` 对象以段落 ID 为键：

```json
{
  "0:3": {
    "target_digest": "精确译文按 UTF-8 编码后的 SHA-256 十六进制摘要",
    "placements": [
      {
        "id": "formula:1",
        "mode": "range",
        "target_start": 8,
        "target_end": 13,
        "status": "aligned"
      }
    ]
  }
}
```

回填保留提交的译文，逐项应用有效标注；同段其他项失败不影响正常项。
有效位置须具有匹配的摘要、`status: "aligned"`、合法偏移和模式。
缺失、重复、未解决或无效的项会被忽略，未知标注 ID 不参与回填。
摘要缺失或过期时，该段所有位置失效，但不替换译文正文。
公式范围重叠或不同样式范围冲突时，仅忽略参与冲突的项。
原样回填原文可直接使用原文位置，无需对齐请求。

文字及所有标注位置均未变化时，回填直接保留冻结段落的原始字形、字体、字号、坐标和旋转，
不重新生成 Unicode 文本或重排；该段链接根据未变化的字形恢复。
独立页码和旋转标识同样适用，不依赖版面类别过滤。
显式移动或失败的标注仍走正常标注回填逻辑；结构化目录行还须保持原文行边界，才能原样保留。

成功项将已定位的译文范围替换为原公式 IL，在已对齐的点插入原角标 IL，并恢复样式。
失败项保留提交的正文，不猜位置添加原对象、样式或链接，也不根据译文重新生成数学内容。
提交的位置与译文一同写入 `translations.json`。
未知段落 ID，以及缺失、未知或空白译文仍返回 HTTP 400；
这些属于无效请求，不是标注对齐失败。

bridge 在 BabelDOC 清理注释前保存网址和内部页码链接（包括已解析的命名目标），
再根据实际排版字形重建可点击矩形，每行一个矩形。纯图片链接保留原矩形。
内部跳转保留原目标页坐标，并映射到导出页码；目标页未导出时省略该链接。
其他动作类型不予重建。可见字形序列不匹配时忽略该段的文字链接，
不把链接挂到无关文字上，其他段落不受影响。
单项没有可用字形时仅忽略该项。排版在行边界删除空格不会使映射失效。

每次成功回填都通过响应头 `X-Wenyi-PDF-Annotation-Stats` 返回紧凑 JSON 摘要，
并在会话目录写入 `annotation_stats.json`。
文件包含逐项段落／标注 ID、种类、位置校验状态及跳过原因，不复制段落文本。
摘要统计 `total`、`aligned`、`applied`、`skipped`、
`alignment_pass_rate`、`application_rate`，
并按 `by_kind`、`reasons`、`translated`、`source_identity` 分组。
比率为小数，分母为零时为 `null`。
`aligned` 表示通过位置校验，不代表模型选择的语义位置已经被证明正确；
`applied` 还排除冲突及链接字形映射失败。
原文恒等位置单独统计，避免抬高译文对齐通过率。
统计仅描述本次请求，不累计重试次数；文译将摘要写入 CLI 日志。

旧项目需要同时更新客户端和 bridge，并从原始 PDF 重新提取才能启用。
没有标注元数据的旧会话保持原来的纯文本回填行为；恢复不会重新提取来补齐元数据。

## 会话恢复

`/extract` 完成后，bridge 将未修改的 BabelDOC IL、修正后的输入 PDF、
MediaBox、段落索引、页面选择和依赖版本保存为会话快照。
`session.json` 最后提交，只有完整快照可以恢复。

服务重启后可以按原 `session_id` 懒加载，不重新执行版面识别。
每次 `/fillback` 都从冻结 IL 加载新的副本，重试不会复用上次注入或排版后修改过的对象。
未知、缺失或空白译文会被拒绝，不会静默跳过。

恢复要求 Python、BabelDOC 版本与快照一致，且所有快照文件校验通过。
BabelDOC 0.5 快照不会自动迁移到 0.6 原生解析器，也不会绕过版本检查加载 pickle。
请在原环境中完成旧任务，或在新环境中从原始 PDF 重新 `/extract`。

需要将会话保存在系统临时目录之外时，参见[缓存与会话目录](installation.md#缓存与会话目录)。

## 清理

回填完成后调用 `DELETE /session/{id}`，释放 PDF、IL 和其他会话文件。
删除前先释放不可达的原生 PDF 文件句柄。
如果文件仍被占用，返回 503 并保留已加载会话，待占用解除后重试；
不会在文件尚未清理时报告成功。

## 版式诊断

默认回填不绘制 BabelDOC 的版面定位框，也不输出 `plain text`、`title`、
`figure_caption` 等调试类别标签。诊断排版时，在启动服务前启用：

```bash
export WENYI_BABELDOC_DEBUG=1
```
