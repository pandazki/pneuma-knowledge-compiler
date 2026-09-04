# LoCoMo-Refined 严格演进全量重跑（2026-09）

实验已完成：pneuma-knowledge-compiler `0646268bea1ed51f546112461d01519892975326`
在 LoCoMo-Refined 10 个 conversation、272 个 session、1,382 道题上的官方全量 LLM score
为 **78.147612%**；剔除两道 README 烧题后为 **78.115942%**。全量 F1 为 43.260796%，
BLEU 为 34.016827%。

相对 2026-08 同判官全量线 76.34%，本次提高 1.807612pp；相对官方 README 所列 82.65%
SOTA，仍低 4.502388pp。build + answer 的保守 token 计价为 **$27.836797**，官方判官另计且
没有可用的精确账单值。

> 追加测量：maintainer 指定的 2026-09-04 capability-guidance answer+score line 得到官方全量
> **77.206946%**，较原记录 -0.940666pp；原报告与根级结果未改。完整归因边界、分项对账、
> 成本和耗时见 [`REPORT-ADDENDUM.md`](REPORT-ADDENDUM.md)。

## 从哪里开始

- [`RUN-REPORT.md`](RUN-REPORT.md)：成绩切片、实验变量、成本/耗时、错题抽样、归因边界与复盘。
- [`REPORT-ADDENDUM.md`](REPORT-ADDENDUM.md)：capability-guidance 追加测量及与原运行的逐项对账。
- [`RUN-LOG.md`](RUN-LOG.md)：UTC 全程时间线、所有事故与恢复记录。
- [`FROZEN.md`](FROZEN.md)：FREEZE#1/FREEZE#2 哈希和烧题清单。
- [`results/score-summary.json`](results/score-summary.json)：官方全量与去烧题主分。
- [`results/official-summary.json`](results/official-summary.json)：官方聚合摘要原样副本。
- [`results/predictions-scored-sanitized.jsonl`](results/predictions-scored-sanitized.jsonl)：白名单脱敏逐题结果。
- [`results/analysis-summary.json`](results/analysis-summary.json)：可复现 Phase C 聚合与固定抽样 ID。
- [`results/cost.json`](results/cost.json)：token、价格假设、阶段成本与判官未知项。

`results/predictions.jsonl` 只含 `qa_id` 与本系统预测。原始 gold-bearing scored 文件、数据集、
material、十个运行项目、runtime 环境和 `.env` 都被 git 忽略；本仓库不分发数据集内容或凭据。

## 固定设计

- 十个 conversation 各用一个独立 scaffold 项目，最多两个并行；session 严格顺序构建。
- 十份首 session 派生合同，六族 filing model；source `(speaker, text)` 逐字节往返，272/272
  session 通过真实 parser 校验。
- `people,time` components，semantic/smart chunking，caption-only media，challenge 一轮并补偿，
  evolve 为 80 claims + 6 sessions 阈值与每库一次强制收尾。
- 答题为 silent visitor，`concise + select + structured`，不启用 original-image retrieval。
- 官方 scorer 原样运行 `llm f1 bleu`、`refined` judge、concurrency 64；判官
  `qwen/qwen3-14b`。

具体配置见 [`contracts/`](contracts/) 与 [`scripts/PROTOCOL.md`](scripts/PROTOCOL.md)。

## 核验与复现

当前现场的只读核验：

```bash
python3 scripts/freeze_guard.py verify --phase 1
python3 scripts/freeze_guard.py verify --phase 2
python3 -m unittest discover -s tests -v
python3 scripts/phase_c_analysis.py \
  --scored results/predictions-scored-sanitized.jsonl \
  --official-summary results/official-summary.json \
  --out results/analysis-summary.json
```

在已按 `TASKBOOK.md` 准备好 ignored `repo/`、`data/`、`secrets/.env` 与十个项目后，冻结的
Phase B 入口依次为：

```bash
./scripts/01-build.sh
./scripts/02-answer.sh
./scripts/03-score.sh
```

三者都有状态文件并支持恢复。第二阶段按已完成 `qa_id` 跳过答案；2026-09-03 的 websocket
404 中断正是用该机制从 1,345/1,382 恢复并只补齐剩余 37 题。完整前置条件、安全边界和官方
命令以 [`TASKBOOK.md`](TASKBOOK.md) 为准。

LoCoMo-Refined 数据集采用 CC BY-NC 4.0；本现场只记录协议与不含禁用金标字段的实验产物。
