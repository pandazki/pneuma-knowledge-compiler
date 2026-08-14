# 高质量上下文选择

[English](quality-context-selection.md) | **简体中文**

状态：已接受的实现契约。

## 1. 目标

fast recall 目前把各条独立排序的证据面直接截成固定头部。这是延迟最低的路径，但一个问题有时需要在
canonical claim、高密度 episode 描述、逐字源窗口之间做一个小型联结，偶尔还需要一份完整 canonical
文档。框架需要一条可选的质量路径：在答题调用前，由 recall 模型组合这些证据；同时不创造新权威，
也不隐藏新增的串行延迟。

这是通用知识库能力。实现中不得出现数据集、类别、话题、题目句式或评分器特判。

## 2. 公共契约

fast recall 新增两个彼此独立的请求／部署选择：

- `evidence_strategy`：`ranked` 或 `select`。`ranked` 是既有固定头部路径并保持默认；
  `select` 会在所有证据面与 canonical 鸟瞰上增加一次结构化 recall-model 调用。
- `answer_format`：`text` 或 `structured`。`text` 是既有自由文本回答并保持默认；
  `structured` 分开返回答案类型、纯答案正文和来源标记，再由程序机械重建普通的带引用答案。

逐请求值覆盖部署设置。字段仅对 `mode=fast` 合法；`rag`、`deep` 收到非空值时必须拒绝，不能假装
已经执行。

部署设置：

- `PNEUMA_KNOWLEDGE_RECALL_EVIDENCE_STRATEGY`
- `PNEUMA_KNOWLEDGE_RECALL_ANSWER_FORMAT`
- `PNEUMA_KNOWLEDGE_RECALL_SELECTION_REASONING_EFFORT`（空表示沿用供应商默认）

既有候选上限与最终上限仍是唯一证据预算旋钮。要采用已测质量形状的部署，可用 80 条 claim 候选、
60 个来源候选，以及 16 条 claim、10 条 episode 摘要、10 个逐字窗口的最终上限。这些是运行档位，
不是隐藏的 benchmark 规则。

## 3. 选择行为

`select` 在宽召回之后、来源组装之前运行：

1. selector 看到编号后的 claim、episode 摘要和 raw window 候选；有 canonical 鸟瞰时也会看到它。
   问题放在最后。
2. schema 只含候选下标与已知文档路径；selector 绝不作答。
3. 未知路径、越界下标、重复值、超上限值由程序机械丢弃。
4. 最终裁剪前合并确定性安全头：最多 8 条 claim、4 条 episode 摘要、4 个 raw window，均来自原
   检索顺序。选择可以改善组合，但不能抹掉最强的已排序证据。
5. 模型某一面选空时回退到该面的安全头。超时、供应商错误或 schema 错误时，整体回退普通 ranked
   头部，并记录 `evidence_selection_degraded`。
6. 所选 claim 的引用和 episode 区间会回跳 L0，与独立命中的窗口去重，并在有界的依据展开预算内
   准入。派生文本继续明确标注；L0 字节仍是权威。
7. 只有调用方明确请求了相应模态时，才从所选逐字窗口读取原始媒体；选择机制不会让媒体变成无条件
   上下文。

selector operation 为 `recall.fast.evidence_select`；其 usage 计入返回的 token 总量。候选数、入选数、
策略与降级原因作为不含来源正文的响应遥测返回。

## 4. 结构化回答行为

结构化 schema 包含：

- `answer_kind`：`fact`、`list`、`time`、`duration`、`yes_no`、`inference` 或 `no_record`；
- `answer`：遵循所请求回答风格的用户可见正文，不带引用标记或过程说明；
- `citations`：从已呈现证据逐字复制的完整 `[cite: sNN ¶a-b]` 标记。

只有 handle 与精确块区间都在别名化证据中出现过的引用才能准入；未知或擅自扩大的引用由程序机械
丢弃。有效标记按返回顺序追加到 `answer`，保持现有 API／UI 引用契约。供应商或 schema 失败时，
回退既有 text 调用并记录 `answer_format_degraded`，不得悄悄伪装成结构化成功。

structured 与 text 的 SystemMessage 都必须逐字节稳定；问题、`as_of`、快照与证据继续只放
HumanMessage。

## 5. 兼容与失败契约

- `ranked + text` 是默认值，必须保持逐字节兼容。
- 不增加中间件或权威层；选择结果只是一次查询的瞬时状态。
- 每条入选 claim／summary／window 保留 `source_id + block span` 依据；租户过滤继续由 adapter 注入。
- 附加 selector 失败不能让回答失败，但降级必须可见。
- 为所选依据读取来源时，L0 缺失不得被吞掉；这是违反不变式，沿既有请求错误路径上报。
- 新增 selector 是串行调用，延迟与成本必须和答题调用分开报告。

## 6. 验收示例

1. 使用默认值时，回答 prompt 与输出和改动前一致。
2. 当所需 claim、episode、raw span 没有同时落在固定头部时，一份合法结构化选择会将它们准入、
   合并安全头，并且绝不突破配置的最终上限。
3. 非法 selector 下标与路径绝不会进入存储读取或回答 prompt。
4. selector 超时会返回 ranked 回答，并带 `evidence_selection_degraded="timeout"`。
5. structured 引用只能指向确实呈现给回答模型的精确区间。
6. caption-only 调用不读取原图；调用方请求且窗口入选的图片仍走既有 digest 校验后的 L0 媒体往返。
7. Langfuse 会在同一 trace context 下收到分开的 selector 与 answer observation。

