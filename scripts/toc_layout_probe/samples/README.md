# 目录版式探针：公开 PDF 样本

这是一组独立于识别算法的真实文档。下载只在手动执行时发生；普通测试和 CI 不读取样本缓存，也不因此联网。
[清单](manifest.json)固定了官方 PDF、发布记录、许可依据、文件字节数、SHA-256、总页数及选页。
[选页标注](annotations.md)给出可比对的条目边界和版面证据。所有物理页码从 PDF 第一页开始按 1 计数，
不是页脚、PDF 页标签，也不是目录中印刷的目标页码。

## 手动获取

在 Bridge 根目录运行（Python 3.10+；联网下载需要 `curl` 8.4+）：

```sh
python3 scripts/toc_layout_probe/samples/fetch_samples.py
python3 scripts/toc_layout_probe/samples/fetch_samples.py --verify-only
```

第一条命令复用已通过校验的文件，缺失或失配时才下载。只从清单中指定的 HTTPS 出版方地址获取，
最多跟随三次同主机 HTTPS 重定向；每次请求的连接/总时限为 7/30 秒，单文件上限 8 MiB。
每个文件先写入 `.cache/` 内的临时目录，只有 HTTP 200、大小和 SHA-256 均匹配才替换缓存文件。
任一文件失败时退出状态非零；其他已校验文件仍可复用。若出版方重发文件导致哈希变化，先核对版本、
许可和标注再更新清单，不要接受未经核实的新哈希。第二条命令只读本地缓存，不启动 `curl`；
它校验文件身份，不重复版面检查。

原始 PDF 只保存在本目录的 git-ignored `.cache/` 中，不随 Git 工作树变更同步。
这里只缓存原件；会话、渲染图和回填结果放在临时目录。样本不是仓库许可证的一部分。
英国财政部样本的归属：HM Treasury, *Sustainability Reporting Guidance 2025-26*,
© Crown copyright 2025. Contains public sector information licensed under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
不把许可扩展到第三方材料、标志或背书。RFC 9000 的用例仅做只读抽取，不生成修改后的 PDF；
如需回填试验，可改用英国财政部的样本。
