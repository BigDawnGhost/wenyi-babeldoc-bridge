# Wenyi BabelDOC Bridge repository guide for coding agents

本文件适用于整个仓库。开始修改前先阅读与任务直接相关的源码、测试和 README；若子目录以后出现更具体的 `AGENTS.md`，以更深层文件为准。

## 项目定位与许可证边界

`wenyi-babeldoc-bridge` 是独立的 **AGPL-3.0-only** HTTP 服务。它在隔离环境中调用 BabelDOC，把 PDF 抽取为稳定段落，接收 Wenyi 生成的译文，再使用同一份冻结 IL 快照回填排版。

- Wenyi 主仓是 MIT；两者只能通过 HTTP/JSON/multipart 协议通信。
- 不要让 Wenyi 主仓 import 本包、BabelDOC 或 pdf2zh，也不要把本仓 AGPL 代码复制进 Wenyi。
- Python 支持范围为 3.10–3.13；BabelDOC 固定在 `>=0.5.20,<0.6.0`，PyMuPDF 固定 `<1.25.3`。
- 包管理和命令执行优先使用 `uv`，BabelDOC 必须安装在本仓独立虚拟环境中。

## 目录地图

- `src/wenyi_babeldoc_bridge/server.py`：FastAPI 入口、上传文件、内存 session 注册表、错误映射和清理。
- `src/wenyi_babeldoc_bridge/pipeline.py`：BabelDOC 私有 IL 流程、段落抽取、译文注入、排版和 PDF 生成。
- `src/wenyi_babeldoc_bridge/schema.py`：`paragraphs.json` / `translations.json` 的纯数据模型、稳定 ID 与验证函数。
- `src/wenyi_babeldoc_bridge/smoke_client.py`：通过真实 HTTP 执行 extract → fillback → delete 的冒烟客户端。
- `src/wenyi_babeldoc_bridge/probe_extract.py`、`probe_fillback.py`：直接调用 BabelDOC 的人工探针，不是服务运行时入口。
- `src/wenyi_babeldoc_bridge/test_schema.py`：不依赖 BabelDOC 的轻量 schema 单测。
- `README.md`：安装、启动方式和对外 API 契约。

## 架构与状态不变量

- 正式调用路径保持 `Wenyi HTTP client → FastAPI server → pipeline → BabelDOC`；schema 层不得反向依赖 server 或 pipeline。
- `/extract` 创建 session，并持久化后续 `/fillback` 必须复用的原始 IL、修正后 PDF、MediaBox、段落索引、页面范围和版本信息。`session.json` 必须最后原子提交，只有完整快照可以跨进程恢复。
- session 恢复不得重新执行版面模型。反序列化内部 pickle 前必须校验路径、文件哈希、Python 和 BabelDOC 版本；不得加载上传文件或 session 根目录之外的 pickle。
- fillback 会修改 IL，因此每次请求必须从冻结快照加载新副本，不能复用上一次已经注入或排版的对象。失败重试必须保持幂等。
- `_SESSIONS` 的访问必须继续受 `_LOCK` 保护。失败的 extract 和显式 delete 都应清理对应 session 目录，不能删除共享临时根目录。
- 上传文件名必须先取 basename；运行数据只写入 session 专属目录，不要信任客户端提供的绝对路径。
- 段落 ID 固定为 `"{page}:{index}"`，其中 index 是原始页面 IL 中的段落位置。过滤不可翻译段落时不得重新编号，回填也必须使用相同原始位置。
- fillback 必须校验未知、缺失和空译文；不得静默跳过部分译文或把译文写到错误段落。
- 公式、placeholder、样式、box、layout/debug ID 和原始渲染顺序都属于回填身份信息。修改段落拆分或多行 TOC 处理时，要同时验证排版与 ID 映射。
- BabelDOC 的 `high_level` 和 IL 类属于易变接口。升级依赖时必须先验证 extract、fillback、页面范围和生成 PDF，不能只依赖 import 成功。
- 对外 schema 或 HTTP 字段变更必须同步更新 README、smoke client，以及 Wenyi 主仓中的纯 HTTP bridge 客户端和测试。

## 开发与验证

安装独立环境：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

本仓格式基线与 Wenyi 的 pre-commit 配置一致，固定使用 Ruff 0.12.7，并保持先 lint 修复、后格式化的顺序：

```bash
uvx --from ruff==0.12.7 ruff check --fix .
uvx --from ruff==0.12.7 ruff format .
uvx --from ruff==0.12.7 ruff check .
uvx --from ruff==0.12.7 ruff format --check .
```

轻量测试：

```bash
PYTHONPATH=src python -m unittest discover -s src/wenyi_babeldoc_bridge -p 'test_*.py'
```

真实 BabelDOC 验证需要独立环境和明确提供的 PDF；默认不要处理、读取或提交用户私有 PDF。涉及 IL、排版或页面选择时，使用公版或合成样例分别验证：

1. `/extract` 返回合法 schema 和稳定段落 ID；
2. 完整 translations 能回填，缺失/未知 ID 会失败；
3. 生成的单语 PDF 包含译文且页数、页面范围和基本版式合理；
4. `/delete` 能释放 session 和临时目录。

## 代码与交付风格

- 保持 Python 3.10 兼容，不使用更高版本才支持的语法。
- schema 校验优先写成不依赖 BabelDOC 的纯函数，并补快速确定性单测。
- 捕获宽泛异常仅限 BabelDOC 兼容降级或 HTTP 错误边界；新增时应保留清晰错误信息，避免伪装成功。
- 不提交虚拟环境、session、生成 PDF、真实书籍、缓存或调试产物。
- 工作区可能有用户改动；只暂存当前任务文件，不清理或覆盖无关内容。
- 提交前至少运行 Ruff check、Ruff format check、轻量测试和 `git diff --check`。只有用户明确要求时才提交或推送，提交信息使用 Conventional Commits。
