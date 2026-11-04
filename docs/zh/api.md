# HTTP API 与会话

[English](../api.md) · [概览](README.md) · [安装](installation.md)

## 接口

| 方法 | 路径 | 契约 |
| --- | --- | --- |
| GET | `/health` | 探活 |
| POST | `/extract` | Multipart：`file` 为 PDF，可选 `pages`；返回 `session_id` 和 `paragraphs` |
| POST | `/fillback` | JSON `{session_id, translations: {id: text}}`；返回单语 PDF |
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
