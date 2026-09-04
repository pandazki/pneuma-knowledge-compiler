# 2026-09-04 capability-guidance 复测附录

## 结论

maintainer 指定的 post-protocol answer+score line 已在原十个持久知识库上完成。新框架 HEAD
为 `212a8fe46da3a8e6f29d36ed82dd7cb38b39736a`，官方全量 LLM score 为
**77.206946%**（1,067/1,382），比原运行记录的 **78.147612%**（1,080/1,382）低
**0.940666 个百分点**。与此同时，全量 F1 从 43.260796% 升至 **45.890598%**，BLEU
从 34.016827% 升至 **36.777350%**。

因此这条线没有提高主指标，但产生了更短、lexical overlap 更高的回答，并改善了 category 1、
category 3 和 `multimodal_available` 的 LLM score。原 `RUN-REPORT.md` 及根级 `results/`
产物均保持不变；本文件是披露的追加测量，不回写原报告表格。

## 成绩对账

| 口径 | 题数 | 原 LLM | 新 LLM | Δ LLM | 原 F1 | 新 F1 | Δ F1 | 原 BLEU | 新 BLEU | Δ BLEU |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 官方全量 | 1,382 | 78.147612% | **77.206946%** | **-0.940666pp** | 43.260796% | **45.890598%** | +2.629802pp | 34.016827% | **36.777350%** | +2.760523pp |

剔除两道既有烧题后的 LLM score 是 77.173913%（1,065/1,380），原值为 78.115942%
（1,078/1,380），变化为 -0.942029pp。两道烧题在两次运行中均判对，所以全量与去烧题
结论一致。

### 分 category

| category | 题数 | 原 LLM | 新 LLM | Δ LLM | 原 F1 | 新 F1 | Δ F1 | 原 BLEU | 新 BLEU | Δ BLEU |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 213 | 57.746479% | **61.032864%** | **+3.286385pp** | 31.289338% | 36.053970% | +4.764632pp | 23.919189% | 28.161079% | +4.241890pp |
| 2 | 299 | 73.913043% | **71.906355%** | **-2.006688pp** | 45.339620% | 49.402953% | +4.063333pp | 35.263018% | 40.261595% | +4.998577pp |
| 3 | 68 | 72.058824% | **75.000000%** | **+2.941176pp** | 26.580947% | 29.356160% | +2.775213pp | 19.410386% | 22.483041% | +3.072655pp |
| 4 | 802 | 85.660848% | **83.665835%** | **-1.995013pp** | 47.079477% | 48.595522% | +1.516045pp | 37.472468% | 38.978709% | +1.506241pp |

主分净下降集中在题量最大的 category 4（27 题错转对、43 题对转错，净 -16）和 category 2
（15/21，净 -6）；category 1 净 +7，category 3 净 +2。四类的 F1/BLEU 则全部提高，说明
lexical 改善与 refined 判官的 inclusion/non-contradiction 判断并不等价。

### 分模态可用性

| 官方模态标签 | 题数 | 原 LLM | 新 LLM | Δ LLM | 原 F1 | 新 F1 | Δ F1 | 原 BLEU | 新 BLEU | Δ BLEU |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| text only | 861 | 81.765389% | **79.442509%** | **-2.322880pp** | 44.836839% | 47.789656% | +2.952817pp | 35.373405% | 38.350979% | +2.977574pp |
| multimodal available | 521 | 72.168906% | **73.512476%** | **+1.343570pp** | 40.656241% | 42.752231% | +2.095990pp | 31.774959% | 34.176785% | +2.401826pp |

`text_only` 为 40 题错转对、60 题对转错，净 -20；`multimodal_available` 为 33/26，净
+7。本 line 仍未启用 original-image retrieval，故后者只代表原有 caption/query 文本进入新的
fast-lane whole-document 选择路径后的 bundled 结果，不能解释为视觉能力提升。

## 回答变化与判官波动

两轮按 qa_id 配对后，962/1,382 条预测文本改变，420 条逐字相同。整体判分迁移为：

| 原判分 → 新判分 | 题数 |
|---|---:|
| 0 → 0 | 229 |
| 0 → 1 | 73 |
| 1 → 0 | 86 |
| 1 → 1 | 994 |

逐字相同的 420 条中仍有 8 条发生判分翻转（5 条 0→1、3 条 1→0），直接显示单次 judge
调用存在运行间波动；这部分净贡献为 +2，不能解释总体净 -13。文本改变的 962 条自身净贡献
为 -15。这里的拆分只是观测对账，不把某一题的翻转当成确定性因果标签。

预测平均长度由 84.099132 降到 72.001447 chars（-12.097685，约 -14.39%），中位数由 68
降到 58。新一轮判对答案平均 65.20 chars，判错答案平均 95.04 chars；预定义的“record/context
未说明”表面正则在新一轮命中 75 条，原轮为 83 条。这些信号与 concise coherence 方向一致，
但 whole-document glance 同时改变了证据面，不能把缩短或 lexical 增益单独归因给 style clause。

## 处理变量与归因边界

framework 从原运行 `0646268bea1ed51f546112461d01519892975326` 前进到
`212a8fe46da3a8e6f29d36ed82dd7cb38b39736a`，严格恰好四个 commit：

| commit | 内容 | 本 line 是否走到该路径 |
|---|---|---|
| `34fafd1` | scaffold 让 deep lane 可达并写入指导 | 否；仍未使用 `--deep` |
| `3318f6b` | message 内空行可往返 | 未重新 ingest/compile；原库不变 |
| `890739f` | concise 要求“给值”与“记录缺值”二选一 | 是 |
| `212a8fe` | canonical documents 传入 `fast_recall`，启用 library glance/whole-document selection | 是 |

十份 `app-NN/app.py` 在回答前同步为 branch template 的逐字节副本，SHA-256 为
`67f43f2ef0d71dba9d6499071b134b5b44ad60449a4ad6d2c938cb27fd5e1f92`。因此本 line 的
回答语义处理变量是 **fast-lane canonical-document glance + concise coherence clause**；这两个
框架变化在同一条测量线内同时启用，**不能彼此分离归因**。

并发也按 maintainer 指令改变：十个项目同时回答，项目内 worker 为 `4,4,3,3,3,3,3,3,3,3`，
总 in-flight 上限 32。并发的设计目的为吞吐量，不应被解释为质量功能；但它改变了请求调度，且
本次没有重复种子，所以仍属于整条线的运行条件。能够严格保持不变的是十个已编译知识库、
question projection（SHA-256 `42bcc322da30d8ca9cf9862c9b9be8471c023f74ab6fb902b55a1d995c0b6410`）、
原题、`concise/select/structured` flags、silent visitor、judge、metrics 与冻结 scorer wrapper。

综上，主分 -0.940666pp 只能归于“两个 fast-lane 框架变化 + 并发/运行随机性”的 bundle；不能
宣称 library glance 或 coherence clause 单独提高/降低了分数。若要分离，至少需要同一冻结库上
做 2×2 answer-only 消融，并给每个 cell 多次重复评分。

## 成本与耗时

answer-side 仍按 Luna input $0.20/M、output $1.20/M 且所有 input full price 保守计价，不应用
cache discount。官方 judge 未暴露聚合 token 或账单值，因此不伪造精确成本。

| answer line | input tokens | output tokens | total tokens | 估算 USD |
|---|---:|---:|---:|---:|
| 原运行 | 59,403,205 | 429,686 | 59,832,891 | $12.396264 |
| capability-guidance | 62,523,153 | 421,898 | 62,945,051 | **$13.010908** |
| 变化 | +3,119,948 (+5.25%) | -7,788 (-1.81%) | +3,112,160 (+5.20%) | **+$0.614644 (+4.96%)** |

$13.010908 低于本 line 的 $50 answer-side soft ceiling；全程没有 429、timeout、invalid-output retry
或 final failure。

| 阶段（UTC） | 起止 | wall time |
|---|---|---:|
| branch/env/protocol 准备 | 03:09:43–03:15:04 | 5m21s |
| fresh answer | 03:15:04–03:29:20 | **14m16s** |
| answer 后核验/score 装配 | 03:29:20–03:30:11 | 51s |
| official scoring | 03:30:11–03:35:30 | 5m19s |
| scoped teardown | 03:35:30–03:36:49 | 1m19s |
| line 开始至 teardown | 03:09:43–03:36:49 | **27m06s** |

原 answer wall time 为 2h52m15s，新 answer 表观快 12.07×、wall 降 91.72%。这个比值同时混入
了原运行的 websocket 404 中断/恢复以及“原先两项目、项目内串行”到“十项目、总 32 asks”的
变化，只是运营吞吐对账，不是隔离后的并发 benchmark。

## 完整性与产物

- fresh answers 只写 `outputs/answers-2026-09-04/`，没有 resume 或改写原 `outputs/answers/`。
- 新结果只写 [`results/2026-09-04-capability-guidance/`](results/2026-09-04-capability-guidance/)；
  raw gold-bearing scored 文件仍在 ignored 目录，未被人工打开或提交。
- 新 sanitized scored 为 1,382 条唯一记录，全部 evaluator success，禁用 gold 字段递归计数为 0。
- 五个原运行产物受 SHA-256 guard 保护；`RUN-REPORT.md` 和原报告表格没有编辑。
- 评分后只撤下 `pneuma-lcr2609-*` 专属容器/网络，owned running count 为 0；未使用 `-v`，卷保留。
- 可复核聚合见 [`comparison.json`](results/2026-09-04-capability-guidance/comparison.json)、
  [`analysis-summary.json`](results/2026-09-04-capability-guidance/analysis-summary.json)、
  [`cost.json`](results/2026-09-04-capability-guidance/cost.json) 与 [`RUN-LOG.md`](RUN-LOG.md)。

最终结论：capability-guidance bundled line 的官方全量主分为 **77.206946%**。它没有复现或超过
原 78.147612% 主分，但以约 4.96% 更高的 answer-side 成本，得到显著更短且 F1/BLEU 更高的
答案；主分的收益/损失因 category 与 modality 明显异质。
