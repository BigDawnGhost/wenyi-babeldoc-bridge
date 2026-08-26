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

段落 id：`"{page}:{index}"`（相对该 session 的 IL）。服务须保持运行直到 fillback 完成。

## 许可

AGPL-3.0-only。使用 BabelDOC 即须遵守其 AGPL 义务。
