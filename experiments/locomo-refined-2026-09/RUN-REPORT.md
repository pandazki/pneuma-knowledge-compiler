# LoCoMo-Refined 2026-09 全量重跑报告

## 摘要

本次实验在 pneuma-knowledge-compiler `0646268bea1ed51f546112461d01519892975326`
上完成 LoCoMo-Refined 全部 10 个 conversation、272 个 session、1,382 道题的严格演进评测。
官方 `refined` 判官的全量 LLM score 是 **78.147612%**（1,080/1,382）；剔除官方 README
直接披露答案值的两道烧题后是 **78.115942%**（1,078/1,380）。全量结果比 2026-08 同数据、
同判官口径的 76.34% 高 **1.807612 个百分点**，但仍比官方 README 所列 MemoraX AI
82.65% 低 **4.502388 个百分点**。

这是一个完整但非因果识别的系统测量。框架版本、合同、材料表示、检索/回答策略和并发均与
上次运行同时变化，而且没有消融或重复种子；因此 1.81pp 的变化只能归于整套配置，不能归于
某个单独功能。

## 成绩

| 口径 | 题数 | LLM score | F1 | BLEU | 对 2026-08 | 对官方 SOTA |
|---|---:|---:|---:|---:|---:|---:|
| 官方全量 | 1,382 | **78.147612%** | 43.260796% | 34.016827% | +1.807612pp | -4.502388pp |
| 剔除烧题 | 1,380 | **78.115942%** | 43.295025% | 34.046060% | +1.775942pp | -4.534058pp |

官方全量是最终主分。去烧题的 F1/BLEU 是 Phase C 从脱敏逐题分数重新聚合的辅助值；冻结评分
器正式输出的双分主指标是 LLM score。两道烧题均被判对，所以剔除后主分下降 0.031670pp。

### 分 conversation

conversation 使用官方 `conversation_idx`，不在报告中复制数据集正文。

| conversation | 题数 | LLM score | F1 | BLEU |
|---:|---:|---:|---:|---:|
| 0 | 138 | 75.362319% | 37.802861% | 29.142409% |
| 1 | 72 | 70.833333% | 41.058434% | 32.489410% |
| 2 | 136 | 80.882353% | 47.707511% | 37.578480% |
| 3 | 179 | **83.798883%** | 48.085569% | 38.505962% |
| 4 | 162 | 75.308642% | 45.471168% | 36.856382% |
| 5 | 114 | 77.192982% | 40.144393% | 30.858061% |
| 6 | 137 | 81.021898% | **48.815315%** | **39.261625%** |
| 7 | 165 | 75.757576% | 39.494132% | 29.830371% |
| 8 | 135 | 79.259259% | 39.556871% | 30.535807% |
| 9 | 144 | 77.777778% | 41.879737% | 32.884610% |

主分跨度为 70.83%–83.80%，说明总体均值不能代表每个独立库的稳定性。最低的 conversation 1
与最高的 conversation 3 相差 12.97pp；只有 3 个 conversation 超过 80%。

### 分 category

| category | 题数 | LLM score | F1 | BLEU |
|---:|---:|---:|---:|---:|
| 1 | 213 | **57.746479%** | 31.289338% | 23.919189% |
| 2 | 299 | 73.913043% | 45.339620% | 35.263018% |
| 3 | 68 | 72.058824% | 26.580947% | 19.410386% |
| 4 | 802 | **85.660848%** | 47.079477% | 37.472468% |

category 1 是最清楚的短板：比总体低 20.40pp，也比 category 4 低 27.91pp。category 3 的
LLM score 尚可，但 lexical 指标最低，提示答案表达与参考措辞可能存在较大差异；这不能仅凭
F1/BLEU 判定为事实错误。

### 分模态可用性

| 官方模态标签 | 题数 | LLM score | F1 | BLEU |
|---|---:|---:|---:|---:|
| text only | 861 | **81.765389%** | 44.836839% | 35.373405% |
| multimodal available | 521 | **72.168906%** | 40.656241% | 31.774959% |

两组主分相差 9.60pp。这里的 `multimodal available` 是官方题目标签，不代表本系统实际读取了
原图：本次 `image_mode=caption`，只把 URL、caption 与 query 作为有明确来源等级的文本材料，
不下载、不启用 native vision。因此该落差更合理地解释为“当前 caption-only 路径在这些题上
不足”，而不是视觉模型性能。

## 实验设计

### 隔离与材料

- 每个 conversation 使用一个独立 scaffold 项目、tenant、合同和持久卷，共 10 个知识库；
  conversation 内严格按 session 顺序 ingest、compile、drain-to-zero。
- 同时只运行 2 个项目，避免在已有生产容器的宿主上额外拉起 10 套栈。每次 Docker 操作前
  都校验精确的 `pneuma-lcr2609-NN-` compose 前缀，teardown 保留卷。
- 5,882 条 source message 的 `(speaker, text)` 经生成项目中真实 parser 逐字节往返校验；
  272/272 session 预演通过。两个内部空行案例由生成项目 parser 的确定性兼容补丁保留，框架
  worktree 未修改。
- media URL、caption、query 以 message ordinal 放进已核验的 `Context` turn，不改 source
  tuple。caption 是派生观察，query/URL 只作上下文线索，合同禁止把它们自动当成所有权或事实。

### 合同与引擎

十份合同共享六族 `people/`、`companions/`、`threads/`、`events/`、`places/`、`objects/`，
但各自只用冻结前允许读取的首 session 定义初始方向。合同强调精确姓名、计数、日期、相对时间
锚点、负事实、说话者归属，以及 proposal/plan/outcome 的区分；状态改变用
`supersede_claim`，原记录当时就错才用 `edit_claim`。

固定引擎面如下：

- 模型角色：compile/recall/answer/deep/live 均为 `openai/gpt-5.6-luna`，embedding 为
  `openai/text-embedding-3-small`；OpenRouter provider 固定 `openai`。
- components：启用 `people,time`；不用 `attention`，因为答题是 `visitor_class=silent`。
- intake：`semantic` + `smart` overlap；overview 预算 2,400 chars，6 claims 后要求概览。
- recall 候选/最终上限：claim 100/48、window 100/10、episode summary 20；component 路径开启，
  component budget 8,000 chars，`plan_queries=0`。
- challenge：1 round、最多 6 问、8,192 output tokens、开启 compensation。
- evolve：`adopt-clean`；至少新增 80 claims 且经过 6 sessions 才触发，每个 conversation 末尾
  再强制一次。
- 答题阶段覆盖 sample default，固定 `concise + select + structured`、high reasoning；不启用
  original-image retrieval。入榜答案只机械去掉 citation marker。

## 与 2026-08 运行的差异

| 变量 | 2026-08 | 本次 | 可解释范围 |
|---|---|---|---|
| framework | `c132a270` | `0646268` | 新版本整体影响可存在；无版本消融，不能拆分 |
| 项目拓扑 | 10 个独立库 | 10 个独立库 | 隔离原则保持 |
| build / answer pool | 5 / 5 | 2 / 2 | 主要影响资源压力与耗时；不主张带来分数提升 |
| evolve 触发 | 50 claims + 4 sessions | 80 claims + 6 sessions | 轮数 68 降至 44；两次运行都全为 no-change |
| challenge | 1 round；252/272 补偿 | 1 round；244/272 补偿 | 覆盖审计都大量生效；本次少 8 个补偿，不能映射到分数 |
| 材料往返 | media 行并入解析后的 message text | source tuple 保持逐字节；media 独立进 Context | 本次语义边界更严格，但没有对照组 |
| components / semantic chunk / overview | 脱敏参考协议未给出旧 engine 配置 | `people,time`；semantic/smart；2,400/6 | 只能披露本次值，不能假定旧值 |
| 合同 | 上次报告与合同未提供 | 十合同、六族、显式状态/时间/媒体口径 | 合同同时变化，不能单独归因 |
| 答题 doctrine | 参考脚本刻意 redacted | concise/select/structured，原题不改 | 不能与旧风格做单变量比较 |

唯一坚实的跨运行结论是：在同一数据集与同一 refined judge 口径下，本次“框架 + 实验设计”
组合比上次高 1.81pp。把提升具体归因给 `people`、`time`、`select`、challenge 或合同都会超过
证据所能支持的范围。

## 构建、演进与质询

| 项目 | 结果 |
|---|---:|
| conversation / session 完成 | 10/10；272/272 |
| 最终 canonical claims | 3,400 |
| compile job events | 1,064 |
| indexed / done job events | 272 / 272 |
| 初始 + 补偿 claim-producing jobs | 272 + 244 = 516 |
| claim-producing job 的 gross `+claims` | 7,309 |
| gate rejection | 4，均自动重试恢复 |
| challenge audit / compensation | 272 / 244（89.71%） |
| challenge degraded | 1（输出长度上限）；构建继续且最终成功 |
| evolve | 44（34 阈值、10 强制） |
| evolve 结果 | 44/44 `no draft produced` |
| fatal marker | 0 |

`gross +claims` 是各编译作业报告的新增写入总和，不能等同最终去重后的 canonical claim 数。
44 个 evolve 间隔覆盖的最终累计 claims 为 3,400，但 evolve 本身没有产出 draft，也没有证据
表明其改变了结构。这一选择在本次评测里增加了调用/检查，却没有可观察的结构收益。

challenge 则不同：244/272 session 触发一次补偿编译，说明覆盖审计实际改变了构建路径。它是否
提高准确率仍未知，因为没有关闭 challenge 的对照组。4 个 compensation job 首次被 gate 拒绝
后都由既定重试路径恢复；没有人为挑选或改写结果。

## 成本

成本是 token 记账估算，不是 OpenRouter 账单。语言模型按 Luna input $0.20/M、output
$1.20/M 计算；为保守起见，所有 input 都按 full price，未应用 cache read/write 折扣。CLI 日志
没有 embedding token 汇总，所以 embedding 未计入；因此“保守的语言模型计价”和“仍缺少
embedding”两个方向同时存在。判官必须另计，且官方 scorer 没有输出聚合 token/账单值，故不
伪造精确金额。

| 环节 | input tokens | output tokens | total tokens | 估算 USD |
|---|---:|---:|---:|---:|
| build | 64,745,033 | 2,076,272 | 66,821,305 | $15.440533 |
| answer | 59,403,205 | 429,686 | 59,832,891 | $12.396264 |
| build + answer | 124,148,238 | 2,505,958 | 126,654,196 | **$27.836797** |
| official judge | 未暴露 | 未暴露 | 未暴露 | 协议估计 $1–2，非实测 |

因此可报告的 all-in 区间是 $28.836797–$29.836797，但只有 build + answer 的 $27.836797
来自本次 token 记录。半程（136/272）实测 $7.550627，外推 $15.101254；最终 build + answer
远低于 $50 soft ceiling 与 $60 hard ceiling。

## 耗时

| 阶段（UTC） | 起止 | wall time | 备注 |
|---|---|---:|---|
| 准备与两次冻结 | 06:19:20–06:46:45 | 27m25s | 含 272-session 全量往返演练与测试 |
| build | 06:46:45–12:29:51 | 5h43m06s | 两项目并行；逐 session 工时合计 10h55m06s |
| answer | 12:34:09–15:26:24 | 2h52m15s | wall time 包含 websocket 404 中断与恢复 |
| official scoring | 15:27:33–15:40:03 | 12m30s | concurrency 64 |

从任务开始到官方分数落地共 9h20m43s。Phase C 文档与最终审计不计入模型管线耗时。

## 错题抽样分析

官方判官给出 1,080 个 1 分和 302 个 0 分，且 1,382 条评分记录均 `success=true`、没有缺失
prediction 或 evaluator error。Phase C 用固定盐 `phase-c-sample-v1:`，在八个
`category × modality` 层内按 `sha256(salt + qa_id)` 排序，各取前两道判错题，共 16 道。
该抽样可由 `scripts/phase_c_analysis.py` 重建。

防泄漏约束仍然适用：分析者只看允许的题面与自身预测，从未查看金标。官方脱敏产物中的
`llm_reason` 也只给出判官标签而非解释。因此下表是“预测表面的可疑失分面”，不是用金标确认
过的根因；报告不复制题面或答案值。

| 可疑失分面 | 抽样 qa_id | 表面现象 |
|---|---|---|
| 保留/拒答代替精确值 | `conv-26#q0059`、`conv-47#q0027`、`conv-48#q0066`、`conv-47#q0136` | 用“记录未确认/未说明”或否定式收尾；若检索有弱证据，select 可能过度保守 |
| 多候选、列表或附加项膨胀 | `conv-41#q0006`、`conv-26#q0028`、`conv-48#q0077`、`conv-49#q0039`、`conv-26#q0134` | 给出多个候选、长列表或额外限定；增加 unsupported addition 风险 |
| 时间粒度或过度精确 | `conv-49#q0052`、`conv-42#q0006`、`conv-26#q0009` | 同时给计划/事件时间、补出具体日期或近似换算；可能偏离问题要求的粒度 |
| 因果/情绪的重构性扩写 | `conv-48#q0021`、`conv-48#q0116`、`conv-44#q0093`、`conv-41#q0125` | 把多段经历合成为理由、意义或当前状态；简洁题上容易加入未要求推断 |

定量表面信号与抽样一致：判错预测平均 110.35 chars、中位 101；判对预测平均 76.76 chars、
中位 59。预先定义的“记录/上下文未说明或未确认”正则命中判错 53/302（17.55%），判对
30/1,080（2.78%）。长度与保留措辞都只是相关指标，但它们提示下一轮应优先测试更强的
“单值优先、禁止候选扩张、仅在真正无证据时 abstain”回答后处理。

按 category × modality 的判错率进一步显示 multimodal 落差并非均匀：category 1 的
multimodal-available 为 44.85%（61/136），text-only 为 37.66%（29/77）；category 4 则分别
为 17.19%（38/221）和 13.25%（77/581）。最优先的改进区是 category 1，而不是对所有答案
统一增加更多上下文。

## 赌对、赌错与下一步

### 赌对或至少得到正向证据

- 两项目并发守住了宿主资源与容器边界，所有 272 session、1,382 answer、1,382 score 完整，
  没有 fatal 或硬预算停止。
- source tuple 逐字节往返和 media 分层避免了转换器静默改写；这是一项可证明的正确性收益，
  即使不能直接换算成分数。
- `concise + select + structured` 在无人工介入下达到 78.15%，相对上一全量线提高 1.81pp；
  至少说明整套设计是可行的。
- challenge 在 89.71% 的 session 上发现并补偿记录缺口，确实不是空开关。

### 赌错或证据不足

- evolve 44 次全部 no-change。提高触发阈值减少了 24 轮，但仍没有结构产出；对这类已写得较宽
  的合同，继续执行 evolve 没有观测收益。
- caption-only 在 multimodal-available 题上落后 9.60pp。保守处理图片避免幻觉，但也失去原图
  细节；这是当前最大且可定位的能力缺口之一。
- “concise”没有阻止答案膨胀：判错答案反而更长，样本中多候选、理由拼接和时间补充明显。
  select 选证据后仍需要更严格的 semantic answer constraint。
- `people,time`、宽六族合同和 8,000-char component budget 可能扩大候选面；目前没有关闭组件、
  缩窄合同或切换 evidence strategy 的消融，不能说这些配置提升了分数。

### 下一轮最有信息量的实验

1. 保持同一冻结知识库，做 answer-only 2×2：`select`/`ranked` × 当前 doctrine/严格单值 doctrine，
   重点观测 category 1、答案长度和 hedge 命中率。
2. 对 521 道 multimodal-available 题做 caption-only 与受控 original-image retrieval 对照；其余
   配置不变，避免把视觉收益和合同变化混在一起。
3. 关闭 evolve 复跑 build 成本对照；鉴于本次 44/44 no-change，预期质量不变但耗时/调用减少。
4. 单独关闭 `people`、`time` 或降低 component budget，按 conversation 分层比较，确认组件究竟
   提升检索还是引入干扰。

## 事故、完整性与结论

主要执行事故是 answer 后期的上游 websocket 404。会话与其承载的 runner 在 1,345/1,382 时
一起死亡；磁盘状态完整，旧 PID 已失效。恢复时先重验两组冻结哈希与 framework HEAD，再启动
同一个冻结脚本；qa_id 去重只补齐 37 题。这是基础设施中断，不是实验干预。另有首次后台启动
被短命 shell 回收、外置 framework venv 起初少 workspace package、一次 challenge 长度降级、
4 次 gate rejection，以及监控误把全局成本快照相加的观察错误；均已逐项写入 `RUN-LOG.md`。

最终结论：本次全量、无人工 Phase-B 干预的系统分数为 **78.147612%**。它显著超过自己的
2026-08 线，但未达到 82.65% 官方 SOTA。最值得继续的不是再扩充泛化记忆，而是收紧回答的
精确性/单值约束并补上真实多模态对照；同时移除在本合同上 44/44 无产出的 evolve 路径。
