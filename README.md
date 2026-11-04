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

Zotero 集成直接使用插件已有的 `pdf2zh_next` Python 环境，不另外维护一套
固定版本。`.[zotero]` 安装选项与插件 `server/config/venv.json.example`
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

Zotero 部署始终显式使用共享环境的入口；不在 bridge 仓库中通过 `uv run`
另建项目环境：

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

## 许可

AGPL-3.0-only。使用 BabelDOC 即须遵守其 AGPL 义务。
