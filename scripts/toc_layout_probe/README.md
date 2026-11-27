# TOC layout probe

## 验证当前 Bridge

`check_labels.py` 在[已标注的公开样本](samples/annotations.md)上运行实际抽取、会话恢复和回填；
不访问网络或调用翻译服务。开发环境需要有当前源码对应的原生扩展，并预先缓存模型和字体。
下载样本是单独的可选步骤：

```bash
python3 scripts/toc_layout_probe/samples/fetch_samples.py
PYTHONPATH=src python scripts/toc_layout_probe/check_labels.py --require-all
# 可选：在同一轮验证中加入经授权的 GRH 文件，只检查物理第 1–3 页。
PYTHONPATH=src python scripts/toc_layout_probe/check_labels.py --require-all --paper "$PDF"
```

探针在临时目录创建和恢复会话，以确定性中文短句替换普通段落，按原 PDF 的独立页码列核对
完整标题和输出数字字形的位置（坐标取到 0.1 pt）。RFC 9000 只跑抽取，不生成修改版。
`--require-all` 还对负例和无页码列页运行一次仅关闭本次目录修正的抽取，比较客户端
可见的完整段落（不比较随机 `debug_id`）；不一致即失败。对照旧版时不要设置
`PYTHONPATH`，用发行 wheel 运行 `check_labels.py` 并去掉 `--require-all`。

不要将私有 PDF、会话或渲染结果存入仓库。
