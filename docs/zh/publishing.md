# 发布到 PyPI

[English](../publishing.md) · [概览](README.md) · [Desktop 插件](desktop.md)

本仓库只发布 **`wenyi-babeldoc-bridge`**。BabelDOC 本身已由上游发布到 PyPI，
安装 bridge 时会自动解析兼容依赖，不需要从 GitHub 安装源码。
Wenyi CLI/Core 由各自的 MIT 主仓工作流发布，不与本仓合包。

## 一次性配置

1. 注册 PyPI 账号并开启双重验证。
2. 在 [GitHub 仓库环境设置](https://github.com/BigDawnGhost/wenyi-babeldoc-bridge/settings/environments)
   创建名为 **`pypi`** 的环境。不需要保存 PyPI Token 或仓库 Secret。
   如果希望发布后直接上传，不设置人工审批；如限制部署来源，要允许发布标签，例如 `v*`，
   不能只允许 `main` 分支。
3. 进入 [PyPI 账号发布设置](https://pypi.org/manage/account/publishing/)，
   为尚不存在的项目添加一个 GitHub **待定发布者（pending publisher）**：

| 字段 | 内容 |
| --- | --- |
| PyPI project name | `wenyi-babeldoc-bridge` |
| Owner | `BigDawnGhost` |
| Repository name | `wenyi-babeldoc-bridge` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

Workflow name 只填写文件名，不是显示名称或完整路径。首次成功上传时，PyPI 自动创建
项目并转换发布者，不需要先手动上传一遍；待定发布者本身不会预留包名。项目已存在且由你
管理时，在其 **Manage → Publishing** 配置同样的字段。

## 发布新版本

1. 完成适用验证，将要发布的改动和 `.github/workflows/publish-pypi.yml` 纳入已验证提交。
2. 本仓通过 `setuptools-scm` 从 Git 标签生成版本，不再维护固定的 `project.version`。
   例如标签 `v0.1.4` 生成包版本 `0.1.4`，`v0.2.0rc1` 生成 `0.2.0rc1`。
   这些只是示例，先确认新版本尚未发布；不要通过 SCM 环境变量覆盖版本。
3. 工作流合入 `main` 后，可到 **Actions → Publish bridge to PyPI → Run workflow**，
   填入已有标签进行预检，保持 `publish=false`；默认手动运行只构建和验证，不上传。
4. 为已验证提交创建新标签，在 **Releases → Draft a new release** 选择标签并发布。
   只推送标签或保存 Release 草稿不会上传。预发布版本也应在 GitHub 标记为预发布。
5. 确认 Actions 的 `build`、四个平台的 `wheels` 和 `publish` 全部成功。
   sdist 会单独重建和冒烟；ABI3 wheel 在对应平台构建、修复动态库依赖并测试后才上传。

### Desktop 插件发布

PR 仅验证模型包和 Linux/Windows 运行包（含 HTTP 冒烟与对应源码），不运行 macOS，
也不生成可发布的 `complete-plugin`；不能用 PR 通过代替完整发布验证。
Desktop 插件发布仍需四平台完整运行包。先等待 `main` 构建成功，在同一提交创建稳定标签，
再等待标签的 **Desktop plugin** 构建成功。手动运行 **Publish verified desktop plugin**，
`main_build_run` 填 main 推送构建 ID，`build_run` 填标签推送构建 ID。
发布器验证两次构建属于同一提交，并在草稿阶段完成资源校验后公开 Release。
它随后显式调度 PyPI 工作流（同一标签，`publish=true`），避免 `GITHUB_TOKEN` 创建
的 Release 不触发其他事件工作流而漏传 PyPI。无需额外 Token。

正式发布需要明确授权。合并后必须等待合并结果的 main 推送构建通过；
未合并分支或手动构建成功不能代替发布验证，无标签开发构建也不能重命名为稳定版。
在 `main` 上调度发布器；它检查两次运行的全部六个 job 和步骤、main 祖先关系及未移动的标签，
从对应提交读取发行说明，下载标签构建的 `complete-plugin`，创建草稿并上传全部资源。
逐项核验大小与 SHA-256 后才公开为 latest；开发版本、分支或手动构建、检查不完整、
非递增版本、发行版冲突和资源覆盖都会被拒绝。
构建工作流只读，不会随推送或 PR 自动发布。

### PyPI 验证与上传

`publish=true` 仅用于已公开 Release 的上传或失败恢复：工作流会验证对应 Release 存在、
不是草稿、标签一致，并执行全部版本及打包检查；它本身不创建 Release。
Desktop 发布不要先公开一个没有完整插件资源的稳定 Release。

构建会先核对标签、检出提交、工作区和 Git 派生版本，然后检查分发元数据，分别从 wheel 与
源码分发包安装到干净的 Python 3.12 环境。安装后验证版本、依赖、控制台入口和 `/health`，
并运行已安装包内的轻量回归。真实模型/PDF 集成回归默认跳过，不会触发字体或模型下载。

带标签的发布构建必须位于对应提交且工作区干净，不允许开发版本或本地版本后缀。
不指定标签的 PR/默认手动构建保留真实的开发版本，包括提交距离、哈希和脏工作区标识，
不会伪装为正式版本，也不会上传 PyPI。从 Git 检出构建时需要保留标签历史；
已构建的源码分发包携带版本，可以在没有 Git 仓库的环境重建。

服务启动后，Python 的 `wenyi_babeldoc_bridge.__version__` 与 API/OpenAPI 版本都读取
已安装包元数据，不在运行时调用 Git。未安装发行包、只通过 `PYTHONPATH=src` 运行的
源码探针显示 `0+unknown`，不冒充正式版本。

上传作业独立运行，只下载构建作业验证过的产物，并获得 OIDC 上传权限，不检出构建源码。
Fork 的 Release 不会执行本仓库的上传作业。

## 发布后安装

在一个 Wenyi 专用环境中同时安装 CLI 和 bridge；不复用 `pdf2zh_next` 环境：

```bash
uv venv .venv-wenyi --python 3.12
uv pip install --python .venv-wenyi/bin/python wenyi-cli "wenyi-babeldoc-bridge==0.1.5"
uv pip check --python .venv-wenyi/bin/python
.venv-wenyi/bin/wenyi --version
.venv-wenyi/bin/wenyi-babeldoc-bridge
```

将版本替换为实际发布版本，并在部署配置中固定已验证的 CLI 与 bridge 版本。
CLI 自动安装 `wenyi-core`，所以首次部署前 CLI/Core 和 bridge 都必须已发布到 PyPI；
它们的版本号独立，不要求相同。bridge 不再提供 `zotero` extra，也不安装 PDF2zh 前端。
Windows 对应使用 `Scripts/python.exe`、`Scripts/wenyi.exe` 和
`Scripts/wenyi-babeldoc-bridge.exe`。共用虚拟环境不改变独立 HTTP 进程或许可证边界；
不在 Wenyi 源码工作区的 `uv sync` 环境中管理这套部署。

PyPI 安装只消除了安装 Python 包时从 GitHub 拉源码的需求。BabelDOC 的字体和模型仍遵循
其资源下载与缓存机制，不会自动打进 bridge 的 wheel。
当前依赖兼容策略见[安装指南](installation.md)。

## 失败恢复

- **可信发布拒绝：**核对表格五项；尤其确认文件名和 `pypi` 环境一致。
- **等待环境审批：**批准部署，或调整环境审批及标签限制。
- **版本不一致：**确认检出的是发布标签对应的干净提交，保留 Git 标签历史，不设置 SCM
  版本覆盖变量；不要移动已发布标签，修复应使用新提交和新标签。
- **网络失败或部分上传：**点击 **Re-run failed jobs**；uv 通过显式 PyPI 检查地址跳过
  已存在且哈希一致的文件。
- **文件已存在但内容不同：**PyPI 不允许替换同版本文件，必须发布新版本。

官方参考：[PyPI 首次可信发布](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
与 [uv GitHub Actions 发布](https://docs.astral.sh/uv/guides/integration/github/#publishing-to-pypi)。
