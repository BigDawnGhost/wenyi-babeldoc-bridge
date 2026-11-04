# wenyi-babeldoc-bridge

**AGPL-3.0** HTTP 服务：用 [BabelDOC](https://github.com/funstory-ai/BabelDOC) 做 PDF 抽段与回填排版。

供 [Wenyi](https://github.com/BigDawnGhost/Wenyi) 以 **外部引擎** 方式调用（HTTP only）。  
Wenyi 主仓保持 MIT，**不要**把本仓库代码 import 进 `trans_novel`。

## 与 pdf2zh 的关系

- **BabelDOC**：版式内核  
- **pdf2zh_next**：官方用户前端（整本翻译黑盒）  
- **本桥**：只暴露 `extract` / `fillback`，翻译由 Wenyi 完成  

## PyPI 发布

`.github/workflows/publish-pypi.yml` 在发布 GitHub Release 后自动构建、验证并上传
`wenyi-babeldoc-bridge`；首次需要在 PyPI 配置可信发布者。
包版本通过 `hatch-vcs` 从 Git 标签生成，不手动修改 `project.version`。
运行时 API/OpenAPI 版本读取已安装包的元数据。
具体字段、版本规则与恢复方法见[发布指南](docs/publishing.md)。
PyPI 版本发布后，可从索引安装，不必克隆本仓；下面的 `-e` 命令用于源码开发。

## 安装（跟随 Zotero PDF2zh 的环境）

Zotero 集成可以与插件已有的 `pdf2zh_next` Python 环境共装；这是可选部署方式，
不要求 Wenyi CLI 共用环境。`.[zotero]` 安装选项与插件 `server/config/venv.json.example`
使用同一规则：

- Python 开发基线为 3.12；本服务支持 3.10–3.13；
- `pdf2zh-next>=2.9.0,<3.0.0`；
- `bitstring>=4.3.0,<5`，避免 5.x 移除 `BitStream` 导致 BabelDOC 导入失败；
- BabelDOC、PyMuPDF 的实际版本由这一组包共同解析，不单独强制升级或锁定 PyMuPDF。

bridge 保留 `babeldoc>=0.6.2,<0.7.0` 的接口兼容范围，抽取使用其原生 PDF
解析入口，再转换为后续段落处理和回填共用的 IL。测试时的具体版本号不是额外的部署锁。

先在 Zotero PDF2zh 的 `server` 目录查看现有环境；尚未创建时先使用插件的更新入口：

```bash
python manage_packages.py status --engine pdf2zh_next
# 尚未创建环境时：
python update_packages.py
```

再从本 bridge 仓库根目录执行，`--python` 使用上述 status 输出的解释器路径：

```bash
uv pip install --python /path/to/zotero-pdf2zh-next-venv/bin/python -e '.[zotero]'
uv pip check --python /path/to/zotero-pdf2zh-next-venv/bin/python
/path/to/zotero-pdf2zh-next-venv/bin/wenyi-babeldoc-bridge
```

Windows 对应使用环境内的 `Scripts/python.exe` 和
`Scripts/wenyi-babeldoc-bridge.exe`。安装会按上述范围升级旧版 BabelDOC；
请先完成旧版运行中的任务。不要把 bridge 安装进 Wenyi 主仓环境，也不要在 Wenyi
中 import BabelDOC；共用 PDF2zh_next 环境不改变 HTTP/进程隔离边界。

以后仍使用 Zotero 插件的 `update_packages.py` 更新共享环境；不要分别强制升级
BabelDOC 或 PyMuPDF，也不要用 `--no-deps` 绕过检查。更新后重新执行上述
`.[zotero]` 安装及 `uv pip check`，确认 bridge 的接口兼容范围仍被满足；
现有插件的更新器不会代替 bridge 做这项检查。在同一环境安装 bridge
不等于 Server 会自动启动它，仍需单独运行 bridge 服务。

字体和模型仍使用 BabelDOC 默认的 `~/.cache/babeldoc/`，与虚拟环境目录无关。
同一系统用户启动的 PDF2zh_next 和 bridge 会复用哈希匹配的资源，不需要复制到
各自环境。新增或校验不匹配的资源仍会下载；不同用户或容器需要另外配置共享缓存。
`WENYI_BABELDOC_STATE_DIR` 只控制会话目录，不控制字体或模型缓存。

### 独立开发调试

不接 Zotero 时，可以在本仓库单独创建开发环境；这不是 Zotero 部署的另一套版本基线：

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .
```

## 启动

选择共装时，显式使用共享环境的入口；不在 bridge 仓库中通过 `uv run`
另建项目环境。独立部署则使用前文 `.venv` 的对应入口：

```bash
/path/to/zotero-pdf2zh-next-venv/bin/wenyi-babeldoc-bridge
# 或
/path/to/zotero-pdf2zh-next-venv/bin/python -m uvicorn \
  wenyi_babeldoc_bridge.server:app --host 127.0.0.1 --port 8765
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
/path/to/zotero-pdf2zh-next-venv/bin/wenyi-babeldoc-bridge
```

恢复要求 Python、BabelDOC 版本与快照一致，且所有快照文件校验通过。完成回填后调用
`DELETE /session/{id}` 释放 PDF、IL 和其它 session 文件。
删除前释放不可达的原生 PDF 文件句柄；如果文件仍被占用，返回 503 并保留已加载会话，
可在占用解除后重试，不会把清理失败报告为成功。

升级到 BabelDOC 0.6 后，旧版 0.5 创建的 session 快照不会自动迁移，也不会绕过版本检查
加载 pickle。请在旧环境中完成旧任务，或在新环境中从原始 PDF 重新 `/extract`。

回填 PDF 默认不绘制 BabelDOC 的版面定位框，也不输出 ``plain text`` / ``title`` /
``figure_caption`` 这类版面角色标签。诊断排版时可以：

```bash
export WENYI_BABELDOC_DEBUG=1
```

## 验证

安装并激活本服务的环境后，运行不下载模型的轻量测试：

```bash
PYTHONPATH=src python -m unittest discover -s src/wenyi_babeldoc_bridge -p 'test_*.py'
```

真实 BabelDOC 回归使用合成的两页 PDF，不调用翻译 API。显式启用后可能下载缺失的
字体和模型；它验证全文与第 2 页抽取、稳定 ID、中文回填、错误译文拒绝、
冻结 IL 复用、session 恢复和清理：

```bash
WENYI_BABELDOC_INTEGRATION=1 PYTHONPATH=src \
  python -m unittest wenyi_babeldoc_bridge.test_babeldoc_integration -v
```

## Desktop optional plugin / 桌面端可选插件

### English

Wenyi Desktop can download this service as a separate, self-contained plugin.
It remains an AGPL process; the MIT application uses HTTP only and does not
install or import BabelDOC. Windows x64, Linux x64, macOS Apple Silicon and Intel
have separate runtime ZIPs, while all platforms share a model/font ZIP.

The **Desktop plugin** workflow builds with Python 3.12 and
`desktop-constraints.txt` (BabelDOC 0.6.2 and compatible dependency APIs).
It downloads assets using BabelDOC's embedded SHA3-256 hashes, with mirror
fallback, then freezes each runtime and tests a synthetic two-page PDF through
real HTTP: authentication, selected-page extract, invalid/complete translations,
short cells and Chinese text, fillback text, restart recovery, session deletion
and owner-pipe shutdown. Runtime tests disable outbound network access via an
unusable proxy. No user PDF or LLM is used.

Desktop builds use `--excludes desktop-excludes.txt` to omit RapidOCR's GUI
`opencv-python` dependency: BabelDOC already requires `opencv-python-headless`,
which supplies the same `cv2` image-processing API without Qt. This is an explicit
packaging-only substitution; a generic dependency checker can still report
RapidOCR's declared GUI requirement as missing. Use a fresh isolated build
environment rather than uninstalling overlapping OpenCV wheels in place.
The builder rejects conflicting OpenCV distributions before freezing. Python
modules are selected by import analysis and the existing dynamic-import rules;
BabelDOC CMaps/IL data, native ONNX providers, licenses, models and fonts are kept.
Each build emits `<platform>-size.json` with compressed archive size, unpacked
file size and per-component totals. These reports are CI diagnostics, not changes
to the Desktop installation protocol.

Model/font archive identity is independent of the bridge version.
`desktop-models.json` pins a published reference archive by release, size and
SHA-256. The builder verifies that archive, prepares the currently required
resources and license notices, then compares every member's name and bytes.
If all contents match, it copies the reference ZIP unchanged under the new
release's filename. Desktop can reuse its verified, hash-addressed download
cache even though the runtime version and asset filename changed; no client
protocol change is required. New installations, missing/corrupted cached ZIPs,
or genuinely changed resources/notices still require a download.

The initial reference is v0.1.2. An installation that only cached an older,
differently hashed ZIP may still need one download. Reference download or
checksum failures fail the build instead of silently generating a different
archive. Changed contents produce a new ZIP with sorted entries and fixed
timestamps/permissions. After publishing changed resources, update
`desktop-models.json` from that release's verified `models` descriptor, using its
release, size and hash; do not advance this reference for runtime-only releases
or overwrite published assets. Build-side downloads and extraction into each
Desktop installation remain separate from reusing the user's download cache.

`main` is the only integration branch. Start short-lived branches from the latest
`origin/main` and open pull requests directly against `main`; do not route new work
through `master`, `release/**` or `publish/**`. The **Desktop plugin** workflow runs
for pull requests targeting `main`, pushes to `main`, and `v*` tags, and can also be run
manually for diagnostics. Before merging a PR with a merge commit, require the
complete workflow to pass for its current revision: models, all four runtime
platforms with HTTP smoke tests, and final manifest/source artifact assembly.
Keep historical branches and published tags unless their removal is explicitly
requested; changing the development flow does not migrate their commits.

Versions come from Git tags through `hatch-vcs`, including in frozen runtimes.
After merging, wait for the workflow on the resulting `main` commit to pass again.
When publication is explicitly authorized, create a new stable `v<version>` tag at
that tested commit and wait for its complete **Desktop plugin** build. An untagged
main build retains a development version; it cannot be relabeled as a stable
release. A successful build on an unmerged branch is not a release candidate.

Run **Publish verified desktop plugin** manually on `main`, with `build_run` set
to the successful **tag push** run's numeric ID and `main_build_run` set to the
successful **main push** run for the same commit. The publisher checks all six
jobs and their steps in both runs, checks main ancestry and the unchanged tag,
and reads release notes from that exact commit. It downloads the tag build's
`complete-plugin`, creates a **draft** release, and verifies every uploaded asset's
size and SHA-256 before publishing it as latest. It rejects development, branch
and manual builds, incomplete checks, non-newer versions, conflicting releases
and asset replacement. Build workflows are read-only and never publish on a push
or PR. Publication remains a separate explicitly authorized action.

The manual publisher then dispatches **Publish bridge to PyPI** with the same tag
and `publish=true`: releases created by `GITHUB_TOKEN` do not trigger other
release-event workflows. That workflow verifies the matching release is public
before uploading. Ordinary manual PyPI validation defaults to `publish=false`.
No PyPI token is stored; only the isolated PyPI upload job receives OIDC permission.

The manifest has `protocol: 1`, a stable `version`, `platforms`
keyed by `windows-x86_64`, `linux-x86_64`, `macos-aarch64`, `macos-x86_64`, and
`models`. Each asset contains `name`, `size` and `sha256`. Desktop constructs URLs
under this repository's `releases/download/v<version>/`; there are no arbitrary
download URLs or executable paths in the manifest.

The manifest and hashes are authenticated by HTTPS to the official release
repository, not a separate plugin signature. This is distinct from Wenyi's signed
application updater. Runtime ZIPs include dependency notices, README and exact
installed requirements; the model ZIP includes font copyrights and full licenses.
Each platform also has a corresponding source ZIP for copyleft dependencies,
MuPDF, GEOS and Python, alongside the separate bridge repository source ZIP.
See [THIRD_PARTY.md](THIRD_PARTY.md). Review licenses again when upgrading
dependencies; packaging does not replace legal review or OS signing/notarization.

For a local build in this repository's isolated environment:

```bash
uv venv .venv --python 3.12 --seed
uv pip install --python .venv -c desktop-constraints.txt \
  --excludes desktop-excludes.txt . pyinstaller fonttools==4.60.1
VERSION=$(uv run --no-project --python .venv python -c \
  'from importlib.metadata import version; print(version("wenyi-babeldoc-bridge"))')
uv run --no-project --python .venv python scripts/build_desktop.py models --version "$VERSION"
uv run --no-project --python .venv python scripts/build_desktop.py runtime --version "$VERSION"
# On Windows, append .exe to the executable path:
uv run --no-project --python .venv python scripts/smoke_desktop.py \
  dist/wenyi-babeldoc-plugin/wenyi-babeldoc-plugin "dist/wenyi-babeldoc-$VERSION-models.zip"
```

The private executable accepts `--data-dir` and `--cache-dir`. Its parent supplies
`WENYI_BABELDOC_TOKEN` in memory, and holds stdin open. On successful startup it
writes one JSON line to stdout: `{"protocol":1,"port":<port>,"pid":<pid>}`.
It binds an OS-assigned `127.0.0.1` port, requires `Authorization: Bearer <token>`
on every HTTP endpoint, rejects browser origins and foreign Host headers, and
exits on stdin EOF. Logs use stderr; credentials are never sent in the readiness
message. Sessions use the supplied persistent data directory; models/fonts are
verified before readiness and are not downloaded during PDF processing.
The normal `wenyi-babeldoc-bridge` entry point and existing public HTTP schema are
unchanged. Desktop keeps installed runtime versions pinned because frozen sessions
require matching Python/BabelDOC versions.
Session deletion first releases unreachable native PDF file handles. If files are
still busy, it returns 503 and retains the loaded session for a deletion retry,
rather than reporting successful cleanup.

### 中文

Wenyi Desktop 可以按需下载独立、自带运行环境的插件，不要求用户安装 Python。
AGPL 服务与 MIT 主程序保持进程隔离，只通过 HTTP 通信。
Windows x64、Linux x64、macOS Apple Silicon/Intel 分别构建运行环境 ZIP，
模型和字体使用跨平台共享 ZIP。

**Desktop plugin** 工作流使用 Python 3.12，固定 BabelDOC 0.6.2，
与普通 HTTP 服务及 Zotero 集成都使用 0.6 原生解析入口，不保留 0.5 分支。
其他兼容约束见 `desktop-constraints.txt`。
模型/字体按 BabelDOC 内嵌 SHA3-256 校验，下载失败时尝试其他镜像。
各平台冻结后使用合成双页 PDF，通过真实 HTTP 验证鉴权、指定页面抽取、缺失/未知译文拒绝、
短单元格及中文、完整回填文字、重启恢复、删除会话及父进程管道关闭退出；运行时通过无效代理禁止外部下载，
不使用私有 PDF 或真实 LLM。

Desktop 构建使用 `--excludes desktop-excludes.txt` 排除 RapidOCR 声明的 GUI 版
`opencv-python`：BabelDOC 已依赖 `opencv-python-headless`，提供相同的 `cv2`
图像处理 API，但不携带 Qt。这是仅用于打包的显式替代，通用依赖检查器仍可能报告
RapidOCR 声明的 GUI 依赖缺失。请使用全新隔离构建环境，不要在原环境内卸载互相覆盖的
OpenCV wheel；构建器会在冻结前拒绝冲突的 OpenCV 发行包。
Python 模块由导入分析与已有动态导入规则收集，保留 BabelDOC CMap/IL 数据、ONNX
原生 provider、许可证、模型和字体。每次构建生成 `<平台>-size.json`，记录压缩包大小、
解压文件大小和各组件占比；它是 CI 诊断产物，不改变 Desktop 安装协议。

模型/字体压缩包的身份独立于 bridge 版本。`desktop-models.json` 通过发行版本、大小和
SHA-256 固定一份已发布的资源基线。构建器先验证基线，再准备当前所需资源与许可证，
逐项比较文件名和文件内容；全部一致时，将原 ZIP 字节不变地复制到新版资源文件名下。
因此即使运行环境版本和下载文件名变化，Desktop 也能复用按哈希保存并校验的下载缓存，
无需修改客户端协议。首次安装、本地压缩包缓存缺失或损坏、资源或许可内容确实变化时，
仍需要下载。

初始资源基线为 v0.1.2；只缓存了更早、哈希不同的 ZIP 的安装仍可能需要下载一次。
基线下载或校验失败会让构建明确失败，不会静默生成另一个哈希的包。内容变化时，
生成按名称排序、固定时间戳和权限的新 ZIP。新资源发布后，应根据已验证发行清单的
`models` 描述更新 `desktop-models.json` 中的发行版本、大小和哈希；
仅更新运行环境时不推进资源基线，也不覆盖已发布资源。
构建端下载及 Desktop 各安装目录的解压仍独立执行，本优化针对用户的重复下载。

`main` 是唯一集成主干。新工作从最新 `origin/main` 开短期分支，PR 直接提交到 `main`，
不再经 `master`、`release/**` 或 `publish/**` 中转。**Desktop plugin** 工作流在目标为
`main` 的 PR、`main` 推送和 `v*` 标签推送时执行，也可手动运行用于诊断。使用 merge commit 合并前，
必须确认当前 PR 提交的完整工作流通过：模型包、四平台运行包与 HTTP 冒烟，
以及最终清单和源码产物组装。除非明确要求删除，否则保留历史分支与已发布标签；
调整开发流程不等于迁移这些分支上的提交。

所有包（包括冻结运行包）都通过 `hatch-vcs` 从 Git 标签生成版本。
合并后，等待 `main` 上合并结果的工作流再次通过。得到明确发布授权后，
在该提交创建新的稳定 `v<version>` 标签，并等待标签的完整 **Desktop plugin** 构建通过。
无标签的主干构建保留真实开发版本，不能重命名为稳定版；未合并分支也不能作为发行版来源。

在 `main` 上手动运行 **Publish verified desktop plugin**：
`build_run` 填成功的**标签推送构建**数字 ID，`main_build_run` 填同一提交成功的
**main 推送构建**数字 ID。发布器检查两次运行的全部六个 job 及其步骤，确认提交属于
`main`、标签未移动，并从该提交读取发布说明。它下载标签构建的 `complete-plugin`，
创建**草稿**并上传全部资源，逐项核验大小与 SHA-256 后才公开为 latest。
它拒绝开发版本、分支或手动构建、检查不完整、非递增版本、发行版冲突及资源覆盖。
构建工作流只读，不会随推送或 PR 自动发布；正式发布仍需明确授权。

发布器随后使用同一标签和 `publish=true` 显式调度 **Publish bridge to PyPI**，
因为 `GITHUB_TOKEN` 创建的 Release 不会触发其他 Release 事件工作流。
PyPI 工作流先检查匹配的 Release 已公开，再上传；普通手动预检默认 `publish=false`。
不保存 PyPI Token，只有隔离的上传作业获得 OIDC 权限。

清单 protocol 为 1，包含版本、四个平台及模型包；
每个资源提供文件名、大小和 SHA-256，不接受任意下载 URL 或可执行路径。
Desktop 使用固定官方仓库的 HTTPS 发行版及哈希校验，而非独立的插件签名，
与 Wenyi 的签名应用更新器不同。

运行包附带依赖许可证、README、实际依赖版本；模型包包含字体版权及完整许可文本。
每个平台另附对应的 copyleft 依赖、MuPDF、GEOS 和 Python 源码包，以及独立的 bridge
仓库源码 ZIP，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
升级依赖时仍需复查许可；该流程不代替法律审查、操作系统签名或公证。
本地构建命令见上方英文段。

私有入口通过 `--data-dir`、`--cache-dir` 指定会话及资源目录，由父进程提供
仅内存使用的 `WENYI_BABELDOC_TOKEN`，保持 stdin 管道打开。
启动成功输出包含 protocol、随机本地端口、PID 的一行 JSON，不输出令牌。
所有请求需要 Bearer 鉴权，拒绝浏览器 Origin 和非本机 Host；stdin EOF 后退出。
模型/字体就绪前校验，处理 PDF 时不再下载。普通 bridge 入口及现有 HTTP 数据格式保持不变。
Desktop 固定已安装的运行环境版本，避免破坏要求相同 Python/BabelDOC 版本的会话恢复。

## 许可

AGPL-3.0-only。使用 BabelDOC 即须遵守其 AGPL 义务。
