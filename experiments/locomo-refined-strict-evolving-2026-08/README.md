# LoCoMo-Refined 全量终局实验 · 严格·演进模式

一次在 LoCoMo-Refined 全部 10 个 conversation、全部 1,382 道题上的完整评测，跑的是「严格·演进」协议：数据逐 session 到达、构建期不许回看未来、程序性演进（`evolve` + `challenge`）全程开启、执行期零人工干预。

**成绩：官方全量口径 LLM judge 76.34%，剔除烧题 76.30%。**

判分由数据集官方脚本原样执行：

```
./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined --concurrency 64
```

判官为官方指定的 `Qwen/Qwen3-14B`（经 OpenRouter 的 `qwen/qwen3-14b`，官方接受的别名）。

- 框架版本：`c132a270c985904528b87870f50bc8ef37757f58`
- 数据集：[mem-eval-suite/LoCoMo_refined](https://github.com/mem-eval-suite/LoCoMo_refined)（CC BY-NC 4.0）
- 执行日期：2026-08-06（UTC）

---

## 先读哪一份

| 文件 | 内容 |
|---|---|
| **[RUN-REPORT.md](RUN-REPORT.md)** | 主报告：双分数、分对话/分类别/分模态得分表、成本核算、冻结时间线、协议注记、演进史、十份契约的赌对赌错复盘、错题抽样、耗时与 token 合计 |
| [RUN-LOG.md](RUN-LOG.md) | 全程时间线，逐事件 |
| [FROZEN.md](FROZEN.md) | 两次冻结的 SHA-256 与烧题清单 |
| [results/analysis.md](results/analysis.md) | `analyze.py` 的原始输出 |

## 几个值得单看的结论

1. **失分重心不在记忆能力，在输出口径。** 错题抽样五道里三道事实正确、输在表述形态；47% 的错题属于「答得比金标长、多出未支撑项」（答案长度中位数 88 字符 vs 金标 22），8.6% 属于框架的时间条款与判官要求的正面冲突。
2. **演进机制本轮零产出。** 68 次按数据驱动触发的演进全部返回 `no_change`——契约的四族骨架第一天就定得足够宽，材料的后续演化都落在既有族内。这不是失败，是没有事情可做。
3. **质询机制本轮高产出。** 272 次覆盖质询触发了 252 次补偿编译（93%），说明首轮编译普遍存在覆盖缺口，且这些缺口确实为材料所支持。
4. **`people` 族严重偏瘦是最明确的一处建模失误。** 契约写了「第三方第一次有具体事实附着时就开页」，落地却只有 2–10 页；而最难的多跳题（category 1，60.56%）恰恰依赖第三方的串联。门槛写得够低，但没写成可机械判定的形式。

---

## 目录

```
scripts/          三个冻结脚本 + 其依赖与分析工具
contracts/        十份编译契约（各 conversation 一份）+ 引擎配置样例
results/          答案、判分、官方汇总、成本、分析报表
build-record/     逐 session 的构建记录、演进记录、全部运行日志
```

### scripts/

| 文件 | 作用 | 冻结 |
|---|---|:--:|
| `01-build.sh` | 构建：conversation 间 5 路并行、内部严格逐 session（转换 → ingest → compile 至队列归零 → 数据驱动演进） | ✅ |
| `02-answer.sh` | 答题：按 `conversation_idx` 路由到各自项目，`--style concise` | ✅ |
| `03-score.sh` | 判分：官方 scorer 原样调用 | ✅ |
| `to_material.py` | LoCoMo session → scaffold 对话材料，含逐字节往返核验 | ✅ |
| `answer_runner.py` | 单个 conversation 的串行答题，题面字段投影在此机械保证 | ✅ |
| `apply_env.py` | 凭据并入（值不打印、不回显） | — |
| `write-contracts.py` | 十份契约的落地脚本 | — |
| `lf.py` | Langfuse 探针与分环节成本聚合 | — |
| `analyze.py` | 阶段 C 的分数聚合与失分分析 | — |

三个冻结脚本全部支持断点续跑，执行前逐一核验哈希与 `FROZEN.md` 一致、无漂移。

### results/

| 文件 | 内容 |
|---|---|
| `predictions.jsonl` | 提交给官方 scorer 的预测，1,382 行，仅 `qa_id` + `predicted_answer` |
| `scores.jsonl` | 判分结果，**已剥离数据集字段**（`question` / `answer` / `evidence` / `evidence_messages` / `matched_answer`），保留 `qa_id`、我方作答、三项分数与 category 标签 |
| `summary-official.json` / `.md` | 官方 `summarize.py` 的原样输出 |
| `cost-by-operation.json` | Langfuse 按 operation 聚合的 token 与金额 |
| `analysis.md` | 双分数、各维度得分表、错题抽样 |

### build-record/

`progress/app-NN.csv` 是每个 session 落地后的库规模快照（claims / 正本 / sources / 耗时秒数），`evolve/app-NN.csv` 是每次演进触发的时刻与当时的增量，`logs/` 是十路构建与十路答题的完整原始日志。

---

## 关于数据边界

LoCoMo-Refined 以 CC BY-NC 4.0 发布。按本仓库的既定规矩（第三方数据集只 re-fetch、绝不 vendor），**本目录不包含数据集内容**：

- 不含转换后的会话材料（`material/`）
- 不含题面、金标、证据字段——`scores.jsonl` 是剥离版
- 不含各项目的 `data/` 运行时状态

`build-record/logs/` 里保留了编译任务打印的材料标题（形如 `Caroline & Melanie — session 3 of 19, 7:55 pm on 9 June, 2023`）——它是说话人名与 session 日期构成的元信息，不含任何对话内容，为的是让构建过程可核验。

要复现，需自行克隆数据集：

```bash
git clone --depth 1 https://github.com/mem-eval-suite/LoCoMo_refined
```

## 关于凭据

全程未经手：`apply_env.py` 从本机凭据文件读入、直接写进各项目 `.env`，值不打印、不回显，验证一律用 `grep -c`；判官的 key 由 `03-score.sh` 在进程内映射为 `EVALUATOR_API_KEY`，不落盘、不上命令行。本目录不含任何 `.env`。
