# OPC 84d v2 · 最终评估摘要

日期：2026-07-29

## 最终运行

真实模型导入完整执行了 28 个连续批次：

- 84 个自然日、104 个已验收 source contract、190 个标准化 L0 来源；
- 380/380 个任务成功，失败任务为 0；
- 生成 28 份 canonical 文档、1,262 条 claim、185 个知识快照；
- canonical、Postgres、Meilisearch 与 Qdrant 的 claim 数量均为 1,262。

结构化引用覆盖 1,262/1,262 条 claim，正文中没有残留 citation marker；
1,753/1,753 个 locator 可以回放到原始来源。语义引用支持率为
1,235/1,262（97.86%），精确重复 claim 组为 0，负向噪音控制泄漏为 0/5。

## 评估边界

当前检索评估只覆盖 HEAD。带 `as_of` 的用例不能视为历史快照检索基准，
后续实验需要先冻结人工复核的 claim/block witness 与 hard negatives，再报告
Recall@1/3/5/15 和 MRR。这个限制不影响本轮对导入完整性、索引一致性和引用
可回放性的验收结论。

## 最终证据

- [真实运行](opc-84d-v2-run.json)
- [结构化评估](opc-84d-v2-evaluation.json)
- [语料与质检说明](../opc-84d-v2/README.md)
