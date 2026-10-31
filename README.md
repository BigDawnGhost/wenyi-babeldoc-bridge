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
删除前释放不可达的原生 PDF 文件句柄；如果文件仍被占用，返回 503 并保留已加载会话，
可在占用解除后重试，不会把清理失败报告为成功。

回填 PDF 默认不绘制 BabelDOC 的版面定位框，也不输出 ``plain text`` / ``title`` /
``figure_caption`` 这类版面角色标签。诊断排版时可以：

```bash
export WENYI_BABELDOC_DEBUG=1
```

## Desktop optional plugin / 桌面端可选插件

### English

Wenyi Desktop can download this service as a separate, self-contained plugin.
It remains an AGPL process; the MIT application uses HTTP only and does not
install or import BabelDOC. Windows x64, Linux x64, macOS Apple Silicon and Intel
have separate runtime ZIPs, while all platforms share a model/font ZIP.

The **Desktop plugin** workflow builds with Python 3.12 and
`desktop-constraints.txt` (BabelDOC 0.5.20 and compatible dependency APIs).
It downloads assets using BabelDOC's embedded SHA3-256 hashes, with mirror
fallback, then freezes each runtime and tests a synthetic two-page PDF through
real HTTP: authentication, selected-page extract, invalid/complete translations,
fillback text, session deletion and owner-pipe shutdown. Runtime tests disable
outbound network access via an unusable proxy. No user PDF or LLM is used.

Push a `release/**` branch or run the workflow manually to produce CI artifacts.
Only after all platforms pass, download that run's `complete-plugin` artifact and
create a **draft** stable `v<version>` release at the tested commit, matching
`pyproject.toml`. Upload all ZIPs and `desktop-plugin.json`, verify the complete
asset set, then publish the draft as latest. Never overwrite existing assets.
This separates validation from publication so Desktop cannot discover an empty or
partially uploaded stable release. The workflow has read-only repository access
and never publishes automatically.
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
uv pip install --python .venv -c desktop-constraints.txt . pyinstaller fonttools==4.60.1
uv run --no-project --python .venv python scripts/build_desktop.py models --version 0.1.1
uv run --no-project --python .venv python scripts/build_desktop.py runtime --version 0.1.1
# On Windows, append .exe to the executable path:
uv run --no-project --python .venv python scripts/smoke_desktop.py \
  dist/wenyi-babeldoc-plugin/wenyi-babeldoc-plugin dist/wenyi-babeldoc-0.1.1-models.zip
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

**Desktop plugin** 工作流使用 Python 3.12 和 `desktop-constraints.txt` 中的兼容约束。
模型/字体按 BabelDOC 内嵌 SHA3-256 校验，下载失败时尝试其他镜像。
各平台冻结后使用合成双页 PDF，通过真实 HTTP 验证鉴权、指定页面抽取、缺失/未知译文拒绝、
完整回填文字、删除会话及父进程管道关闭退出；运行时通过无效代理禁止外部下载，
不使用私有 PDF 或真实 LLM。

推送 `release/**` 分支或手动运行工作流，只生成 CI artifacts。
四平台全部通过后，下载该次运行的 `complete-plugin`，在已验证的提交上创建与
`pyproject.toml` 版本匹配的稳定 `v<version>` **草稿**发行版。
上传全部 ZIP 和 `desktop-plugin.json` 并检查完整性，最后公开草稿并设为最新版。
不覆盖已有资源；验证与公开发布分离，避免 Desktop 发现空的或尚未上传完整的稳定版。
工作流只拥有仓库读取权限，不自动发布。清单 protocol 为 1，包含版本、四个平台及模型包；
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
