# 任务书 — LoCoMo-Refined 全量重跑（2026-09，最新 main）

你是本次实验的唯一执行者：一个在空目录里工作的自治 agent。目标：把
pneuma-knowledge-compiler **当前 main**（commit `0646268bea1ed51f546112461d01519892975326`）
当作一个陌生开发者拿到的产品，在 LoCoMo-Refined 全部 10 个 conversation、全部 1,382 道题上
走一次完整的「严格·演进」评测，并留下一个可以被逐文件复查的现场和一份实验报告。

上一次全量运行（2026-08-06，框架 `c132a27`，同判官同口径）得分 **76.34%**。那次运行的五个
协议脚本放在 `reference/prev-run/` 供你参考——它们是**协议参考，不是命令**：路径、app.py
的 CLI 面、引擎配置面都变了，照抄会坏。上次的报告和冻结记录**没有**给你，因为它们含有
数据集的答案值；协议本身在本文档里完整陈述。

## 0. 红线（先读，违反任何一条即实验作废）

1. **这台机器上有别人的生产容器。** 你只允许 `docker` 操作**你自己创建的**、名字带你项目
   前缀的容器/卷/网络。禁止 `docker system prune`、`docker stop/rm` 任何你没创建的东西，
   禁止碰名字含 `yize`、`opc-example`、`pneuma-knowledge-compiler`、`omne-engram`、
   `univpn` 的任何容器。端口由 scaffold 随机分配，不要手工挑端口。
2. **凭据不过眼。** `secrets/.env` 已备好（含 `OPENROUTER_API_KEY` 与模型配置）。用脚本把
   它并入各项目 `.env`；值不打印、不回显、不写日志，验证一律 `grep -c`。现场 git 仓库里
   不得出现任何 `.env` 或密钥（`.gitignore` 先行）。
3. **主仓库只读。** 框架源码用
   `git -C /Users/pandazki/Codes/pneuma-knowledge-compiler worktree add <本目录>/repo 0646268 --detach`
   取出，此后不得对主仓库做任何写操作，也不得改 worktree 里的框架代码。发现框架 bug 就
   如实记录并绕行，不修。
4. **GPT 系模型经 OpenRouter 必须钉官方 provider**：每个项目 `.env` 追加
   `PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai`（框架默认 `allow_fallbacks=false`）。
   这是本仓库的既定规矩，不是超参。
5. **预算**：构建+答题合计软顶 $50、硬顶 $60（判官另计，约 $1–2）。构建过半时自查一次
   累计花费与外推，若外推超软顶，在 RUN-LOG 写明并给出你的处置（降并发/照跑到硬顶即停）。
6. **数据集 CC BY-NC 4.0**：现场仓库不得含数据集内容——不含 material/、不含题面金标证据
   字段；results 里的判分文件要剥离 `question`/`answer`/`evidence`/`evidence_messages`/
   `matched_answer` 字段后再入库（保留 qa_id、你的作答、分数、category 标签）。
7. **诚实**：一切偏差、事故、重跑、观察错误都写进 RUN-LOG，如实。跑砸了就报告跑砸了。

## 1. 防火墙协议（无泄漏的机制保证）

数据集：`git clone --depth 1 https://github.com/mem-eval-suite/LoCoMo_refined data`。

**第一次冻结之前，你允许读的数据集内容，全部清单：**
- `data/public/manifest.json` 与 `conversations.jsonl` 的**结构字段**（conversation 数、
  session 数、speaker 名、日期跨度、多模态计数）；
- **每个 conversation 的第一个 session 全文**——这是唯一的原文阅读窗口，为写契约用，
  读了哪些在 RUN-LOG 记录。

**第一次冻结之前禁止读**：`questions.jsonl` 的任何字节、官方 `README.md`、`src/`、
`scripts/`、提交模板。**永远禁止读**（人和你的上下文都不许碰）：`questions.jsonl` 的
`answer`、`evidence`、`evidence_messages`、`category` 字段——答题脚本对题库做机械字段
投影（只取 `qa_id`、`conversation_idx`、`question`），这个投影是保证，不是自觉。

**冻结规程**（照上次的两段式）：
- **FREEZE#1**：全部契约 + 构建脚本及其依赖（材料转换器在内）定稿，SHA-256 写进
  `FROZEN.md`，此后不得改动；改动=重冻结并保留旧哈希、说明原因。
- **考纲阶段**（只能在 FREEZE#1 之后）：通读官方 README、判官提示词、评测脚本、提交
  模板，用于写答题与判分脚本。官方文档若直接给出了某些题的答案值（上次 README 的格式
  示例就烧了两题），把 qa_id 与出处记进 `FROZEN.md` 的**烧题清单**，最终报双分数。
- **FREEZE#2**：答题脚本 + 判分脚本 + 烧题清单，哈希入 `FROZEN.md`。
- **阶段 B（执行）零人工干预**：三个脚本各自跑完，不改契约、不改库、不改脚本、不依据
  中间产出调整任何东西。执行前逐一核验冻结哈希。
- 分数落地前，你不读任何题面之外的判分中间产物；分数落地后防火墙解除，进入分析。

**材料转换必须带往返核验**：每个 session 渲染成材料文件后，用生成项目 `app.py` 里**真实
的解析函数**（逐字提取，不重写）解析回来，(speaker, text) 序列必须与源 JSON 逐字节一致，
不一致就硬失败。全部 272 个 session 先演练一遍再冻结。

**答题以无痕访客身份进行**：测量不是使用。用 `visitor_class: silent`（scaffold 的
`./app.py ask` 默认即是；若你换用 HTTP 面，显式带 `silent`），不许在访问账本上留下评测
的痕迹。

## 2. 框架的现状（事实清单，用不用是你的判断）

main 相对上次运行（c132a27）多了一批能力。**下面只是事实，不是暗示**；每一项用或不用、
怎么配，都是你的实验设计，报告里要写清你赌了什么、为什么：

- **索引组件** `PNEUMA_KNOWLEDGE_COMPONENTS`：`people`（人物页投影：第三方身份归拢、
  出场索引）、`time`（主体日历：带时区的时间线索引与相对时间解析）、`attention`（访问
  账本的面——评测全程 silent，它必然无事可做）。
- **正本概览头**：每页四槽概览（definition/summary/introduction/connections），
  `overview_budget_chars` / `overview_required_after_claims` 可调。
- **`supersede_claim`**：「世界变了」与「我记错了」分开；LoCoMo 的状态随 session 演化，
  这与它直接相关。
- **答题证据策略** `evidence_strategy: select | ranked | all`：框架自己的测量默认是
  `select`（多一次串行选择调用，换来一个被挑选过的证据集）；`ranked` 在小语料上 RRF
  分数平坦。`plan_queries`、`claim_cap`、`window_cap`、`answer_reasoning_effort` 同面。
- **质询（challenge）**：编译后盲问覆盖审计 + 补偿编译，`PNEUMA_KNOWLEDGE_CHALLENGE_*`。
  上次开 1 轮，252/272 次触发了补偿编译，是实际起作用的机制。
- **演进（evolve）**：`evolve step --policy adopt-clean` 程序化采纳。上次 68 轮全部
  no_change——契约骨架定得宽就没事可做。
- **语义切分** `PNEUMA_KNOWLEDGE_CHUNK_STRATEGY=semantic`（边界记录在 manifest、重建
  确定）。
- **engine.yaml `pricing:`**：给每个模型角色声明单价，编译作业与咨询就带金额；评测是
  silent 不留咨询行，答题侧成本从 `ask` 自报的 token 统计聚合。把 pricing 声明上，报告
  的成本核算优先用框架自己的账。
- 模型角色面：`compile`/`recall`/`answer`/`deep`/`live_*`/`embedding` 可分角色配置。
  `secrets/.env` 里是仓库当前的默认配置（全角色 gpt-5.6-luna + text-embedding-3-small），
  沿用或改配是你的判断（预算红线内）。

读这些的权威文档（全部可读，都在 repo/ 里）：`scaffold/AGENT-GUIDE.md`、
`docs/guides/compile-contract.md`、`docs/guides/recall-strategies.md`、
`docs/design/index-components.md`、`docs/reference/configuration.md`、
`examples/opc/`（一个完整的参考工程，含 engine 目录形态与 build-record 的样子）。

## 3. 你的自主权（实验设计属于你）

- **契约/schema**：十份契约怎么写、族怎么定、口径怎么立——你的判断。允许的信息只有
  第 1 节列的结构字段与十个首 session。
- **超参**：检索预算、证据策略、切分、演进阈值、质询轮数、并发池、模型角色分配。
- **拓扑**：上次是 10 个独立 scaffold 项目（每个一栈 6 容器，共 60 容器）。这台机器
  16 CPU / 31 GiB，已有 24 个别人的容器在跑。10 栈并发大概率过重——按分批起停、缩小
  池子、或单栈多租户（框架 I1 隔离）自行权衡；写明你的选择与理由。
- **答题风格**（concise/conversational/detailed）属于考纲阶段的决定，冻结前不定。

## 4. 判分（不可协商）

官方 scorer 原样调用：`./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined
--concurrency 64`，判官 `qwen/qwen3-14b`（OpenRouter，官方接受的别名），key 进程内映射、
不落盘不上命令行。报**双分数**：官方全量 + 剔除烧题。predictions 装配时核验 1,382 行、
与官方题库 qa_id 一一对齐、无缺无重。

## 5. 交付物（现场 = 本目录的一个 git 仓库）

本目录 `git init`，从任务书落地起小步提交（冻结点必须各是一个干净提交）。结构照上次：

```
TASKBOOK.md          本文件（不改）
README.md            现场导读：跑了什么、成绩、先读哪份、怎么复现
RUN-LOG.md           全程时间线（UTC），逐事件，含一切事故与披露
FROZEN.md            两次冻结的哈希与烧题清单
RUN-REPORT.md        主报告（下详）
contracts/           十份契约 + 引擎配置样例
scripts/             冻结脚本 + 辅助工具
results/             predictions.jsonl（qa_id+作答）、剥离版判分、官方汇总原样、成本
build-record/        逐 session 进度 csv、演进/质询记录、构建与答题日志
reference/prev-run/  （已备好，不改）
repo/                框架 worktree（git 仓库里只记 commit sha，不入库）
data/ material/ app-*/ secrets/   一律 .gitignore
```

**RUN-REPORT.md 必须包含**：双分数与官方榜参照；分 conversation / 分 category / 分模态
得分表（category 标签从判分产物读，判分后才接触）；与 2026-08 线（76.34%）的对比——同
协议同判官，框架版本与你的实验设计是变量，逐项写明差异（组件、策略、契约设计、超参），
并诚实说明哪些提升/回退能归因、哪些不能；成本核算（分环节 token 与金额、口径写明）与
耗时表；演进/质询的触发与产出统计；错题抽样分析（判分后）；「赌对/赌错」复盘；结论。

语言：报告与 RUN-LOG 用中文（技术名词保留英文），代码与脚本注释用英文。

## 6. 执行方式

全程自治，别问人。长活（构建/答题/判分）用 nohup 落盘日志后台跑，你轮询文件系统状态；
你的会话可能被打断，编排者会 resume——所以一切要可断点续跑，RUN-LOG 与状态文件是接续的
依据。阶段边界（冻结、起跑、跑完、分数落地）在 stdout 打一行明确标记。跑完阶段 C 后，
最后一行输出 `EXPERIMENT COMPLETE: <官方全量分数>`。
