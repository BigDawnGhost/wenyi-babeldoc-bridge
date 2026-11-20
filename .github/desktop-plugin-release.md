## English

This update to the optional BabelDOC plugin and Python package keeps PDF fillback downloads independent and changes how the bridge restores frozen sessions. It is not an update to Wenyi Desktop itself.

### Improvements

- **Session recovery:** The bridge checks the compressed snapshot before decoding it. The first fillback after a restart uses the graph already decoded during recovery; subsequent requests still load a fresh copy. The snapshot format is unchanged.
- **Diagnostics on demand:** The full `styles_and_formulas.json` dump is now generated only with `WENYI_BABELDOC_DEBUG=1`. Normal extraction, fillback and recovery do not need it.

### Fixes

- **Independent PDF downloads:** Each `/fillback` response delivers the PDF generated for that request, even if another render finishes before the client reads the first response. Renders on the same session run one at a time, but downloads can overlap. Temporary render files are cleaned up when delivery finishes, fails or is cancelled.
- **Cleanup during fillback:** Deleting a session while a render or download is active returns HTTP 503 without removing the session. Retry after the download finishes.

### Upgrade notes

- Desktop users can update the plugin in Settings. Python users should upgrade `wenyi-babeldoc-bridge` in their dedicated environment, run `uv pip check`, and restart the service.
- Run only one bridge process (one worker) per state directory. For annotation statistics for a specific download, use that response's `X-Wenyi-PDF-Annotation-Stats` header; later renders replace the session's diagnostic file.

---

## 中文

本次更新面向可选 BabelDOC 插件和 Python 包，使 PDF 回填下载相互独立，并调整冻结会话的恢复方式，不包含 Wenyi Desktop 主程序更新。

### 改进

- **会话恢复：** Bridge 在解码前校验压缩快照。服务重启后的首次回填会使用恢复时已解码的文档结构，后续请求仍各自加载新副本。快照格式不变。
- **按需生成诊断：** 现在仅在设置 `WENYI_BABELDOC_DEBUG=1` 时生成完整的 `styles_and_formulas.json`。正常抽取、回填和恢复均不需要此文件。

### 问题修复

- **独立下载 PDF：** 每次 `/fillback` 都返回该请求生成的 PDF，即使客户端还没读取第一次响应、后一次回填就已完成，也不会收到后一次的结果。同一会话逐个执行回填，但下载可以重叠。下载完成、失败或取消时会清理临时文件。
- **回填期间的清理：** 会话正在回填或下载时，删除请求会返回 HTTP 503，不会删除会话。请在下载结束后重试。

### 升级说明

- Desktop 用户可在设置中更新插件。Python 用户请在专用环境中升级 `wenyi-babeldoc-bridge`，运行 `uv pip check`，然后重启服务。
- 每个状态目录只运行一个 Bridge 进程（一个 worker）。如需查看某次下载的注释统计，请读取对应响应的 `X-Wenyi-PDF-Annotation-Stats` 响应头；后续回填会覆盖会话的诊断文件。
