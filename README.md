# wenyi-babeldoc-bridge

**AGPL-3.0** HTTP 服务：用 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 做 PDF 抽段与回填排版。

供 [Wenyi](https://github.com/BigDawnGhost/Wenyi) 以 **外部引擎** 方式调用（HTTP only）。  
Wenyi 主仓保持 MIT，**不要**把本仓库代码 import 进 `trans_novel`。

## 与 pdf2zh 的关系

- **BabelDOC**：版式内核  
- **pdf2zh_next**：官方用户前端（整本翻译黑盒）  
- **本桥**：只暴露 `extract` / `fillback`，翻译由 Wenyi 完成  

## 安装（独立 venv）

```bash
cd wenyi-babeldoc-bridge
uv venv .venv --python 3.12
uv pip install -e .
```

## 启动

```bash
uv run wenyi-babeldoc-bridge
# 或
uv run uvicorn wenyi_babeldoc_bridge.server:app --host 127.0.0.1 --port 8765
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 探活 |
| POST | `/extract` | `multipart`：`file`=PDF，可选 `pages` → `session_id` + `paragraphs` |
| POST | `/fillback` | JSON：`{session_id, translations:{id:text}}` → mono PDF |
| GET/DELETE | `/session/{id}` | 查看 / 释放会话 |

段落 id：`"{page}:{index}"`（相对该 session 的 IL）。`/extract` 完成后，bridge 会把
未修改的 BabelDOC IL、修正后的输入 PDF、MediaBox 数据和依赖版本原子保存为 session
快照。服务重启后可按原 `session_id` 懒加载，不会重新执行版面识别；每次 `/fillback`
也从原始 IL 快照开始，因此失败后可以安全重试。

提取保留所有非空原文，包括短词、单字符、纯数值，以及恰好为 `table` / `title` 等
版面角色名称的真实文本。不按长度或文字内容过滤；仅按 IL 的 `debug_info` 属性排除
调试叠加标签，段落 id 仍使用原始 IL 索引，回填与提取采用相同规则。
更新并重启 bridge 后，需要重新提取此前受过滤影响的 PDF；旧会话不自动迁移或补齐遗漏段落。

session 默认保存在系统临时目录的 `wenyi-babeldoc-bridge/` 下。它可以跨进程重启，但
可能被系统清理；长时间翻译建议使用持久目录启动：

```bash
export WENYI_BABELDOC_STATE_DIR=/path/to/wenyi-babeldoc-sessions
uv run wenyi-babeldoc-bridge
```

恢复要求 Python、BabelDOC 版本与快照一致，且所有快照文件校验通过。完成回填后调用
`DELETE /session/{id}` 释放 PDF、IL 和其它 session 文件。

回填 PDF 默认不绘制 BabelDOC 的版面定位框，也不输出 ``plain text`` / ``title`` /
``figure_caption`` 这类版面角色标签。诊断排版时可以：

```bash
export WENYI_BABELDOC_DEBUG=1
```

## 许可

AGPL-3.0-only。使用 BabelDOC 即须遵守其 AGPL 义务。
