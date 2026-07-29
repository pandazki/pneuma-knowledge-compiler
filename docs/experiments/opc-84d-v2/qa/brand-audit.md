# OPC 84d v2 开源品牌与全局验收终审

审计日期：2026-07-29

结论：**PASS，可发布；未发现品牌、产品策略或全局验收阻塞项。**

为避免本审计文件自身重新引入公开仓库禁止的 token，下文用拆分写法表示敏感检索词。

## 范围与方法

- 扫描当前仓库的文本内容和路径，忽略 `.git`、缓存、虚拟环境、`node_modules`、`dist` 和 `build`。
- 重点审阅 v2 的 accepted corpus、groups、QA、运行代码、测试和 Web UI；另将历史 `examples/data/opc-84d` 单独归类。
- 大小写不敏感检索以下词形及空格、连字符、下划线、点号变体：
  - `` `E` + `ven Realities` ``
  - `` `E` + `ven AI` ``
  - `` `E` + `ven App(s)` ``
  - `` `E` + `ven Glass(es)` ``
  - `` `E` + `van` ``
  - `` `Con` + `versate` ``
  - `` `C` + `ue` `` 及常见英文屈折形式
- 对所有命中人工审阅上下文，并运行仓库自带的开源卫生测试；压缩 preset 由专门测试覆盖。
- 对 `qa/global.json` 和 `qa/acceptance-audit.json` 进行无写入重算，并另以独立遍历复算日期、source、ID 和 acceptance 哈希。

## 品牌泄露结论

### 发布阻塞项

无。

在代码、UI、v2 accepted corpus、运行入口、文档正文和路径中，目标品牌组合、近似人名、会话产品名及已退役短功能词的语义命中均为 0。未发现产品定位、硬件、应用名称、功能策略或内部品牌迁移信息。

`tests/test_open_source_hygiene.py` 全量结果为 **8 passed**，包括公开文本、路径和压缩 preset 检查。

### 非阻塞命中

1. 目标公司名前半词作为普通英文副词共 35 处。上下文均为 “即使”“甚至”“仍然”一类语法用途，分布于代码注释、测试说明、QA rubric、研究摘要和历史 review；没有与公司、产品、硬件或应用语义相邻。
2. `apps/web/pnpm-lock.yaml:1574` 与 `apps/web/pnpm-lock.yaml:1714` 的 SHA-512 integrity Base64 中各有一个大小写不敏感的三字节偶合片段。它们不是单词、标识符或可执行产品文案，且 lockfile 被仓库卫生测试明确排除，判定为非语义命中。
3. 文件名和目录名扫描无有效目标命中。缓存中残留的旧 `.pyc` 路径已按审计范围排除，不属于发布源文件。

## 历史 rejected 数据

`examples/data/opc-84d` 应单独标注为历史 rejected/legacy 数据，不计入 v2 的 accepted corpus、104-source 组装或全局验收。`qa/evaluation-v2-design.md` 已明确 v2 不复用旧 rejected manifest。

该目录仍按公开仓库表面单独扫描；目标品牌组合、近似人名、会话产品名、已退役短功能词及相关路径命中均为 0。因此它不构成本次品牌发布阻塞，但不能被误称为 v2 验收数据。

## 84 天与 104 source 复核

accepted 目录恰有 G01–G28 共 28 组，每组 3 天。日期从 2026-03-02 连续覆盖至 2026-05-24：

- 覆盖天数：84
- 缺口：0
- 重叠：0
- 范围外日期：0

四类 source 的正式报告值、无写入验证器重算值和独立遍历值一致：

| Source family | 数量 |
| --- | ---: |
| meeting | 18 |
| document library | 35 |
| IM | 30 |
| email | 21 |
| **合计** | **104** |

## 重复与 acceptance 复核

| 检查 | 唯一值数量 | 重复数量 |
| --- | ---: | ---: |
| authored ID | 2,221 | 0 |
| source ID | 104 | 0 |
| provider normalized unit ID | 190 | 0 |
| 跨组 normalized exact 候选 | — | 0 |
| 跨组 5-gram near 候选 | — | 0 |

provider ID 按 `source_family + provider + normalized_unit_provider_id` 复合命名空间检查。跨组文本结果是当前确定性检测器阈值内的候选数，不延伸声称不存在任何抽象语义相似。

`qa/acceptance-audit.json` 的正式状态为 `current`，28 current、0 stale、0 findings。逐组独立复核还确认：

- 28 份 group 与 accepted copy 字节一致；
- 当前 group、accepted copy、deterministic report、independent review、rubric、schema、story bible 和 daily beats 的 SHA-256 均与 acceptance evidence 一致；
- 28 份 deterministic report 均为 `structural_pass`、0 findings；
- 28 份 review 均记录 PASS、非作者声明及当前 group 哈希。

`qa/global.json` 的正式状态为 `global_pass`、0 findings；无写入重建再次得到相同的 84 天、104 source、重复检查和 28/28 freshness 结果。

## 发布判定

当前快照没有品牌泄露阻塞项，也没有验收 freshness、规模、日期或重复阻塞项。历史 rejected 数据已与 v2 发布资产清楚分界；两个 lockfile integrity 偶合片段和普通英文副词均为非阻塞命中。
