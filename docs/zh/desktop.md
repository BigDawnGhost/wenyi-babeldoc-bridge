# Desktop 插件

[English](../desktop.md) · [概览](README.md) · [发布](publishing.md)

Wenyi Desktop 可以按需下载独立、自带运行环境的插件，无需用户单独安装 Python。
AGPL 服务与 MIT 主程序保持进程隔离，只通过 HTTP 通信，不将 BabelDOC 安装或导入主程序。
Windows x64、Linux x64、macOS Apple Silicon 和 Intel 分别构建运行环境 ZIP，
模型和字体使用跨平台共享 ZIP。

## 构建环境与验证

**Desktop plugin** 工作流使用 Python 3.12 和 `desktop-constraints.txt`，
固定 BabelDOC 0.7.1 及兼容依赖接口。共享包约束 `pymupdf>=1.26.7,<2` 同样适用于 Desktop。
普通 HTTP 服务与 Desktop 使用同一个 bridge PyO3 扩展调用上游 Rust 流程；
源码构建需要 Rust/Cargo，用户安装冻结插件不需要。

工作流按 BabelDOC 内嵌 SHA3-256 校验下载资源，失败时尝试镜像。
各平台冻结后使用合成双页 PDF，通过真实 HTTP 验证鉴权、指定页面抽取、
无效/完整译文、短单元格及中文、回填文字、重启恢复、会话删除和父进程管道关闭退出。
运行时测试通过无效代理禁止外部网络访问，不使用私有 PDF 或真实 LLM。

Desktop 构建使用 `--excludes desktop-excludes.txt` 排除 RapidOCR 声明的 GUI 版
`opencv-python`：BabelDOC 已依赖 `opencv-python-headless`，提供相同的 `cv2` API，
但不携带 Qt。这是仅用于打包的显式替代；通用依赖检查器仍可能报告 RapidOCR
声明的 GUI 依赖缺失。

请使用全新隔离构建环境，不要在原环境内卸载互相覆盖的 OpenCV wheel。
构建器会在冻结前拒绝冲突的 OpenCV 发行包。Python 模块由导入分析与已有动态导入规则收集，
保留 BabelDOC CMap/IL 数据、ONNX 原生 provider、许可证、模型和字体。

每次构建生成 `<平台>-size.json`，记录压缩包大小、解压文件大小和各组件占比。
它是 CI 诊断产物，不改变 Desktop 安装协议。

## 本地构建

在本仓库根目录使用隔离环境执行：

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

## 离线资源与缓存复用

模型/字体压缩包的身份独立于 bridge 版本。
`desktop-models.json` 通过发行版本、大小和 SHA-256 固定已发布资源基线。
构建器先验证基线，再准备当前所需资源和许可说明，逐项比较文件名与字节。
全部一致时，将参考 ZIP 原样复制为新版文件名。

即使运行环境版本和资源文件名变化，Desktop 也能复用已验证、按哈希保存的下载缓存，
无需修改客户端协议。首次安装、缓存 ZIP 缺失或损坏，以及资源或许可说明真正变化时，
仍需要下载。

初始资源基线是 v0.1.2。只缓存了更早、哈希不同的 ZIP 时，可能仍需下载一次。
参考资源下载或校验失败会使构建失败，不会静默生成另一个压缩包。
内容变化时，新 ZIP 使用排序后的条目及固定时间戳和权限。
发布变化后的资源后，根据该发行版已验证的 `models` 描述更新 `desktop-models.json`
中的版本、大小和哈希；仅更新运行环境时不推进资源基线，不覆盖已发布资源。
构建端下载、向每个 Desktop 安装目录解压，与复用用户下载缓存是不同过程。

0.6 升级新增原生解析器的 CMap JSON 并更新许可说明，因此生成新模型包，
不能复用 0.5 的旧包。CMap 与字体、模型一样，在服务就绪前通过 SHA3-256 校验；
冻结服务处理 PDF 时必须无需联网。

## CI 与源码分发

`main` 是唯一集成主干。新工作从最新 `origin/main` 开短期分支，PR 直接提交到 `main`，
不经 `master`、`release/**` 或 `publish/**` 中转。
除非明确要求删除，否则保留历史分支与已发布标签；调整流程不等于迁移历史提交。

**Desktop plugin** 工作流在目标为 `main` 的 PR、`main` 推送、`v*` 标签和手动调度时运行。
使用 merge commit 合并 PR 前，必须确认当前提交的模型包和 Linux/Windows 运行包通过，
包括 HTTP 冒烟和对应源码打包。
PR 不运行 macOS，并跳过最终组装，不产生可发布的 `complete-plugin`；
PR 通过不代表 macOS 已验证。

main、标签和手动构建保留四平台及最终清单/源码组装。
不同于 Wenyi 的 main Rust 缓存预热，bridge 保留完整 main 构建以维持 main/标签发布校验。
所有包（包括冻结运行包）都通过 `setuptools-scm` 从 Git 标签生成版本。
正式发布需要独立授权及同一提交成功的 main/标签构建，
详见[发布指南](publishing.md#desktop-插件发布)。

运行包包含依赖许可、README、中英文指南和实际安装的依赖版本；模型包包含字体版权和完整许可。
每个平台另附 copyleft 依赖、MuPDF、Python 的对应源码 ZIP（安装 Shapely 时也包含 GEOS），
以及独立的 bridge 源码 ZIP。详见[第三方材料](../../THIRD_PARTY.md)。
升级依赖时仍须复查许可；打包不代替法律审查、操作系统签名或公证。

## 运行协议

清单包含 `protocol: 1`、稳定的 `version`、`models` 及 `platforms`。
平台键为 `windows-x86_64`、`linux-x86_64`、`macos-aarch64`、`macos-x86_64`。
每个资源提供 `name`、`size` 和 `sha256`。
Desktop 使用本仓库 `releases/download/v<version>/` 下的固定地址，
不接受任意下载 URL 或可执行路径。

清单与哈希通过官方发行仓库的 HTTPS 传输，而非独立插件签名。
这与 Wenyi 的签名应用更新器不同。

私有入口接受 `--data-dir` 和 `--cache-dir`。父进程在内存中提供 `WENYI_BABELDOC_TOKEN`，
并保持 stdin 管道打开。启动成功向 stdout 输出一行 JSON：
`{"protocol":1,"port":<port>,"pid":<pid>}`。
服务绑定操作系统分配的 `127.0.0.1` 端口，每个接口均要求 `Authorization: Bearer <token>`，
拒绝浏览器 Origin 和非本机 Host，在 stdin EOF 后退出。
日志写入 stderr，就绪消息不包含凭据。

会话使用指定的持久目录。模型与字体在就绪前校验，处理 PDF 时不再下载。
普通 `wenyi-babeldoc-bridge` 入口及 [HTTP 数据格式](api.md) 保持不变。
Desktop 固定已安装的运行环境版本，以满足冻结会话对 Python/BabelDOC 版本一致性的要求。
删除会话前先释放不可达的原生 PDF 句柄；文件仍被占用时返回 503，并保留会话供重试。
