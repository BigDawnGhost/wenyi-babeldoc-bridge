# 选页标注

计数对象是页面上看得见的完整目录项，每项包含编号（若有）、完整标题及单独的印刷目标页码
（若有）。页眉、页脚、`Contents` 标题、点线及续行不是独立条目。`internal_links` 统计实际页面上
指向同文档的链接注释，不是书签数，也不一定等于条目数。负例的 `toc_entries: 0` 只表示不应产生
目录条目，不要求特定的非目录段落或表格序列化形式。

## `uk-treasury-guidance.pdf` — 物理第 3 页

- **28 项，28 个 `/GoTo` 内链**。无点线；页码形成单独一列，链接矩形在数字上而不是标题上。
- `Chapter 1 Overview: Introduction to sustainability reporting` 和 `Concepts, principles and foundations`
  都标 `6`、都跳到物理第 6 页，但落点不同，必须分为两项。
- `Annex C List of abbreviations`（`43`）与 `Annex D` 必须分开；后者的标题跨三行：
  `Differences in the reporting requirements between Annual` /
  `Reports and Accounts and the Greening Government` / `Commitments`。三行只算一项，`45` 和链接在末行。
- 原件有一处页码和内链不一致：`Emissions accounting standards and guidance` 印 `14`，对应标题确实在物理
  第 14 页，但源 `/GoTo` 落在物理第 13 页。比对时分别保留印刷值 `14` 和原链接目标 `13`，
  不要把原件差异算成识别或回填错误。

## `nist-fips180.pdf` — 物理第 7、4 页

- **第 7 页（印刷页脚 `2`）：19 项，0 个链接。** 目录续页，点线到右侧页码列。
  `APPENDIX A: ADDITIONAL INFORMATION`、`A.1 SECURITY OF THE SECURE HASH ALGORITHMS`、
  `A.2 IMPLEMENTATION NOTES` 和 `A.3 OBJECT IDENTIFIERS` 是四项，虽然都印 `28`。
  其后 `APPENDIX B: REFERENCES` 印 `29`，也不能并入 A.3。
- **第 4 页（印刷页脚 `iv`）：编号正文负例，0 个目录项、0 个链接。**
  `2. Category of Standard` 与 `3. Explanation` 是正文编号项，后者首段从 `This Standard specifies`
  换行至 `numbers (bits).`；不要把首段的换行、句内的 `1)` / `2)`，或后面的
  `4. Approving Authority` 误判成目录项。

## `nasa-sti.pdf` — 物理第 9 页

- **40 项，0 个链接**（印刷页脚 `vii`）。点线和右侧页码列；层级深且很多相邻条目共用印刷页码。
- 第一项 `SECTION I OVERVIEW OF NASA SCIENTIFIC AND TECHNICAL INFORMATION` 在下一行续为
  `(STI) PUBLICATIONS: ELEMENTS AND FORMAT`；页码 `1` 在续行。合为一项，与随后同标 `1` 的
  `1.1 NASA STI Report Series`、`1.1.1 Purpose` 分开。

## `rfc9000.pdf` — 物理第 3 页

- **30 项，60 个内链**。目录续页，无点线、无目标页码列；右下的 `Page 3` 是页脚，不能赋给条目。
  这一页每项的编号和标题分别各有一个 `/Link` 注释；`/Dest` 为命名目标，两块区域仍只算一项。
- `5.2.1. Client Packet Handling` 与 `5.2.2. Server Packet Handling` 分开；四个链接都解析到物理
  第 30 页，但两项的落点不同。没有可回填的印刷目标页码。仅用于只读抽取。

## `census-p25-1144.pdf` — 物理第 4 页

- **数值表格负例，0 个目录项、0 个链接。** 顶部 `Table 1. Population by Age Group: Projections 2020 to 2060`
  有正文标签、点线和多列右对齐数字，底部是三栏正文（不是多栏目录）。
- `Total population` 行的 `403.7` 属于 `2060` 列，`24.9` 属于 `Percent` 列；下一行 `Under 18 years`
  的 `79.8` 和 `8.4` 也分别属于这两列。两行都不能识别为目录项，尾部数值不是目标页码。

## 核验范围

五个文件均用 Poppler 26.11.0 打开；对全部六个选页运行 `pdftotext -layout`，并查看
`pdftoppm` 渲染以确认点线、列、换行和负例。用 PyMuPDF 1.26.7 读选页的 `Page.get_links()`、
链接矩形和 `Document.xref_get_key()`（`A/S` 或 `Dest`）；抽查标注中的同页不同落点、
数字列和页码错配。四个正例页的计数分别对照可见条目、页面链接或右侧纯数字列复核，
不拿 PDF 书签或识别器的输出当真值。未逐条核对所有内链的实际标题，也没有审阅未标注页。
只读取和渲染，不触发链接或运行嵌入内容。

本组覆盖长标题换行和多栏正文负例，不覆盖真正的多栏目录、扫描件或非拉丁文字目录。数值表格
负例有点线，但没有内链；不覆盖「左栏文字有内链、右栏是对齐数值」的复合负例。
没有运行 Bridge 抽取、识别算法比较或回填基线。
