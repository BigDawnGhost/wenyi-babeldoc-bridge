# 安装与开发

[English](../installation.md) · [概览](README.md) · [HTTP API](api.md)

## 依赖支持范围

bridge 支持 Python 3.10–3.13，使用 BabelDOC 0.6 原生解析入口：

- `babeldoc>=0.6.2,<0.7.0`
- `bitstring>=4.3.0,<5`
- `pymupdf<2`

普通安装与 Desktop 构建统一保持 PyMuPDF 1.x，以保留 Intel macOS wheel 和
Python 3.10 兼容性。只限制大版本，不锁定小版本，由 BabelDOC 与 Wenyi 共同解析。
不要单独强制升级 BabelDOC 或 PyMuPDF，也不要用 `--no-deps` 绕过依赖检查。
上游不维护 1.x 分支，这一兼容性选择不代表长期安全支持；更新依赖时仍须审查安全修复。

不需要安装 PDF2zh 或 PDF2zh Next，也不提供 PDF2zh 专属 extra。
共享环境不改变进程隔离或许可证边界。

## 与 Wenyi CLI 一起安装

默认将 `wenyi-cli` 和 `wenyi-babeldoc-bridge` 安装到同一个 **Wenyi 专用 Python 3.12
虚拟环境**。CLI 自动安装 `wenyi-core`，bridge 自动安装 BabelDOC 和 PDF 依赖。

```bash
uv venv .venv-wenyi --python 3.12
uv pip install --python .venv-wenyi/bin/python wenyi-cli wenyi-babeldoc-bridge
uv pip check --python .venv-wenyi/bin/python
```

这些索引安装命令要求包含共享环境集成及本文兼容约束的 CLI/Core 和 bridge 版本已经发布。
正式部署应固定实际验证过的版本；CLI/Core 与 bridge 的版本号独立，不要求相同。

Windows 对应使用环境内的 `Scripts/python.exe`、`Scripts/wenyi.exe` 和
`Scripts/wenyi-babeldoc-bridge.exe`，替代 `bin/` 下的路径。

不要复用插件的 `pdf2zh_next` 环境或 Wenyi 源码工作区的开发环境。
尤其不要在 Wenyi 源码工作区使用 `uv sync` 管理这套部署：未声明为工作区依赖的
bridge 可能被移除。PDF2zh 更新器不会管理这个环境，也不会自动启动 bridge。

先完成运行中的任务再升级，之后重新运行 `uv pip check` 和 PDF 冒烟。
旧会话要求兼容的 Python/BabelDOC 版本，详见[会话恢复](api.md#会话恢复)。

## 启动服务

显式使用专用环境的入口：

```bash
.venv-wenyi/bin/wenyi-babeldoc-bridge
# Alternatively:
.venv-wenyi/bin/python -m uvicorn \
  wenyi_babeldoc_bridge.server:app --host 127.0.0.1 --port 8765
```

**共用环境，不合并进程**：仍须单独启动 bridge，Wenyi 只通过 HTTP 调用，
不直接导入 bridge 或 BabelDOC。每个组件和依赖仍须遵守各自的许可证义务。

## 缓存与会话目录

字体和模型使用 BabelDOC 默认的 `~/.cache/babeldoc/`，与虚拟环境目录无关。
缺失或校验不匹配的资源仍会下载。通过 PyPI 安装只省去了从 GitHub 获取 Python
源码的步骤，不会将字体和模型打进 bridge 的 wheel。

`WENYI_BABELDOC_STATE_DIR` 只控制会话目录，不控制字体或模型缓存。
长时间翻译建议先指定专用的持久目录，再启动服务：

```bash
export WENYI_BABELDOC_STATE_DIR=/path/to/wenyi-babeldoc-sessions
.venv-wenyi/bin/wenyi-babeldoc-bridge
```

默认会话目录是系统临时目录下的 `wenyi-babeldoc-bridge/`。
它可以跨服务重启保留，但可能被操作系统清理。

## 源码开发

仅开发 bridge 时，在本仓库创建不含 Wenyi CLI 的隔离环境。
以下命令从仓库根目录执行：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

使用前面的启动命令时，将 `.venv-wenyi` 改为 `.venv`。

## 验证

安装并激活本服务的环境后，运行不下载模型的轻量测试：

```bash
PYTHONPATH=src python -m unittest discover -s src/wenyi_babeldoc_bridge -p 'test_*.py'
```

真实 BabelDOC 回归使用合成的两页 PDF，不调用翻译 API。
显式启用后可能下载缺失的字体和模型；它验证全文与第 2 页抽取、稳定 ID、
中文回填、错误译文拒绝、冻结 IL 复用、会话恢复和清理：

```bash
WENYI_BABELDOC_INTEGRATION=1 PYTHONPATH=src \
  python -m unittest wenyi_babeldoc_bridge.test_babeldoc_integration -v
```

冻结运行包构建及真实 HTTP 冒烟见 [Desktop 插件](desktop.md)。
