# wenyi-babeldoc-bridge

[English](../../README.md) | **简体中文**

独立的 **AGPL-3.0-only HTTP 服务**，使用
[BabelDOC](https://github.com/funstory-ai/BabelDOC) 抽取 PDF 段落，并将译文回填到原有版式。
[Wenyi](https://github.com/BigDawnGhost/wenyi) 负责生成译文，本桥只提供外部 PDF 引擎。

## 配合 Wenyi 使用

- **Desktop：**通过 Wenyi Desktop 安装可选的自包含插件，无需单独安装 Python。
  详见 [Desktop 插件](desktop.md)。
- **CLI 或手动部署：**将 `wenyi-cli` 和 `wenyi-babeldoc-bridge` 安装到同一个专用
  Python 环境，再单独启动 bridge 的 HTTP 进程。详见[安装与开发](installation.md)。

BabelDOC 是版式内核；PDF2zh 和 PDF2zh Next 是独立前端，不是本桥必需的依赖。

## 文档

| 指南 | 内容 |
| --- | --- |
| [安装与开发](installation.md) | 依赖约束、专用共享环境、启动、缓存与测试 |
| [HTTP API 与会话](api.md) | 抽取/回填契约、稳定 ID、恢复与清理 |
| [Desktop 插件](desktop.md) | 四平台构建、离线资源、运行协议与验证 |
| [发布指南](publishing.md) | Git 派生版本、已验证的 Desktop 发行版与 PyPI 可信发布 |

英文文档放在 `docs/`，中文文档放在 `docs/zh/`。
[在线仓库](https://github.com/BigDawnGhost/wenyi-babeldoc-bridge)也提供这些文档。

## 许可与进程边界

本仓库采用 [AGPL-3.0-only](../../LICENSE)，Wenyi 自有代码采用 MIT。
两者只通过 HTTP 通信：不要将本桥或 BabelDOC import 进 `wenyi_core`，
也不要将本仓库代码复制到 Wenyi。

共享 Python 环境不会合并进程，也不会免除任何组件的许可证义务。
Desktop 的依赖许可与对应源码分发说明见[第三方材料](../../THIRD_PARTY.md)。
