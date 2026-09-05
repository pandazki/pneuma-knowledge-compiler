# 任务书 — LoCoMo-Refined 全量重跑（2026-09-05，最新 main，执行者 GPT-6，第二次尝试）

你是本次实验的唯一执行者：一个在空目录里工作的自治 agent。目标：把
pneuma-knowledge-compiler **当前 main**（commit `c58efd5`，取全 sha 记录）当作一个陌生
开发者拿到的产品，在 LoCoMo-Refined 全部 10 个 conversation、全部 1,382 道题上走一次完整的
「严格·演进」评测，并留下一个可以被逐文件复查的现场和一份实验报告。

同协议同判官的既往线：2026-08-06（框架 `c132a27`）**76.34%**；2026-09-03（框架 `0646268`，
执行者 GPT-5.6）**78.15%**。那两次运行的报告、契约、冻结记录**都没有给你**——它们含数据集的
答案值，而且你的实验设计必须是你自己的。`reference/prev-run/` 里只有 2026-08 那次的五个协议
脚本，**协议参考，不是命令**：路径、app.py 的 CLI 面、引擎配置面都变了，照抄会坏。

## 0. 红线（先读，违反任何一条即实验作废）

1. **这台机器上有别人的生产容器。** 你只允许 `docker` 操作**你自己创建的**、名字带你项目
   前缀的容器/卷/网络。禁止 `docker system prune`、`docker stop/rm` 任何你没创建的东西，
   禁止碰名字含 `yize`、`opc-example`、`pneuma-knowledge-compiler`、`omne-engram`、
   `univpn`、`lcr2609` 的任何容器或卷（最后一个是上一轮实验留下的卷，不是你的）。端口由
   scaffold 随机分配，不要手工挑端口。
2. **凭据不过眼。** `secrets/.env` 已备好（含 `OPENROUTER_API_KEY` 与仓库当前的模型配置）。
   用脚本把它并入各项目 `.env`；值不打印、不回显、不写日志，验证一律 `grep -c`。现场 git
   仓库里不得出现任何 `.env` 或密钥（`.gitignore` 先行）。
3. **主仓库只读。** 框架源码用
   `git -C /Users/pandazki/Codes/pneuma-knowledge-compiler worktree add <本目录>/repo c58efd5 --detach`
   取出，此后不得对主仓库做任何写操作，也不得改 worktree 里的框架代码。**不得检出或读取
   主仓库的任何 `exp/*` 分支或 `experiments/` 目录**——那里是既往实验，读了就是泄漏。发现
   框架 bug 就如实记录并绕行，不修。
4. **GPT 系模型经 OpenRouter 必须钉官方 provider**：每个项目 `.env` 追加
   `PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai`（框架默认 `allow_fallbacks=false`）。
5. **预算**：构建+答题合计软顶 $50、硬顶 $60（判官另计，约 $1–2）。OpenRouter 当前单价
   （USD / 百万 token，input / output）：`openai/gpt-5.6-luna` 0.20 / 1.20；
   `openai/gpt-6-astra` 10 / 50（`:batch` 半价）。上一轮构建+答题共约 1.25 亿 token——
   照此规模，用 gpt-6 系做编译或答题会超预算 20 倍以上，这是算术不是禁令：模型角色怎么配
   是你的判断，但必须在预算内，且在冻结前把估算写进 RUN-LOG。构建过半时自查一次累计花费
   与外推，若外推超软顶，写明并给出处置。
6. **数据集 CC BY-NC 4.0**：现场仓库不得含数据集内容——不含 material/、不含题面金标证据
   字段；判分文件要剥离 `question`/`answer`/`evidence`/`evidence_messages`/`matched_answer`
   后再入库（保留 qa_id、你的作答、分数、category 标签）；构建日志里 dataset-derived 的
   会话标签要脱敏。
7. **诚实**：一切偏差、事故、重跑、观察错误都写进 RUN-LOG，如实。跑砸了就报告跑砸了。

## 1. 防火墙协议（无泄漏的机制保证）

数据集：`git clone --depth 1 https://github.com/mem-eval-suite/LoCoMo_refined data`。

**第一次冻结之前，你允许读的数据集内容，全部清单：**
- `data/public/manifest.json` 与 `conversations.jsonl` 的**结构字段**（conversation 数、
  session 数、speaker 名、日期跨度、多模态计数）；
- **每个 conversation 的第一个 session 全文**——这是唯一的原文阅读窗口，为写契约用，
  读了哪些在 RUN-LOG 记录。

**结构字段的提取必须是白名单投影**：写一个只输出你点名的字段（session 数、speaker 名、date_time、message 计数、多模态计数）的脚本，逐字段取值，绝不用「整条记录排除某几个字段」的写法——上一次尝试正是这样把整段会话文本带进了输出而作废。任何 conversation 的文本字段，除十个首 session 之外，不得进入任何工具输出、日志或你的上下文；一旦发生，实验作废，如实记录并停止。写好投影脚本后，先用一个带诱饵全文字段的合成对象测试它只输出白名单字段，再让它碰真实语料。

**第一次冻结之前禁止读**：`questions.jsonl` 的任何字节、官方 `README.md`、`src/`、
`scripts/`、提交模板。**永远禁止读**（人和你的上下文都不许碰）：`questions.jsonl` 的
`answer`、`evidence`、`evidence_messages`、`category` 字段——答题脚本对题库做机械字段
投影（只取 `qa_id`、`conversation_idx`、`question`），这个投影是保证，不是自觉。

**冻结规程**（两段式）：
- **FREEZE#1**：全部契约 + 构建脚本及其依赖（材料转换器在内）定稿，SHA-256 写进
  `FROZEN.md`，此后不得改动；改动=重冻结并保留旧哈希、说明原因。
- **考纲阶段**（只能在 FREEZE#1 之后）：通读官方 README、判官提示词、评测脚本、提交
  模板，用于写答题与判分脚本。官方文档若直接给出了某些题的答案值，把 qa_id 与出处记进
  `FROZEN.md` 的**烧题清单**（只记 qa_id，不复制答案值），最终报双分数。
- **应试姿态属于这一阶段，且只属于这一阶段。** 读完判官之后，你可以为**答题侧**冻结一条
  应试 doctrine——例如证据弱但非零时给出承诺的单值、只在真正无据时弃答、答案粒度贴合
  问法——前提是它只通过框架现有的旋钮与风格面实现（答题风格、证据策略、格式、推理力度、
  后处理），**一个字不改框架**，是通用的、不面向具体题目/话题/类别，并随 FREEZE#2 入档。
  框架"宁弃答不编造"的品格不是你能改的东西；它在考试上的代价如实记进报告。
- **FREEZE#2**：答题脚本 + 判分脚本 + 应试 doctrine + 烧题清单，哈希入 `FROZEN.md`。
- **阶段 B（执行）零人工干预**：三个脚本各自跑完，不改契约、不改库、不改脚本、不依据
  中间产出调整任何东西。执行前逐一核验冻结哈希。
- 分数落地前，你不读任何题面之外的判分中间产物；分数落地后防火墙解除，进入分析。

**材料转换必须带往返核验**：每个 session 渲染成材料文件后，用生成项目 `app.py` 里**真实
的解析函数**（逐字提取，不重写）解析回来，(speaker, text) 序列必须与源 JSON 逐字节一致，
不一致就硬失败。全部 272 个 session 先演练一遍再冻结。

**答题以无痕访客身份进行**：测量不是使用。用 `visitor_class: silent`（scaffold 的
`./app.py ask` 默认即是；若你换用 HTTP 面，显式带 `silent`），不许在访问账本上留下评测
的痕迹。

**答题从一开始就并发**：答题是只读的、无痕的，题与题之间没有任何依赖，没有什么可串行的。
冻结的答题脚本应当跨项目并行、且**库内也并行**，全局在飞上限由 provider 限流决定（上一轮
32 路稳定、无 429），带退避与幂等续跑。

## 2. 框架的现状（事实清单，用不用是你的判断）

**下面只是事实，不是暗示**；每一项用或不用、怎么配，都是你的实验设计，报告里要写清你赌了
什么、为什么：

- **索引组件** `PNEUMA_KNOWLEDGE_COMPONENTS`：`people`（人物页投影：第三方身份归拢、
  出场索引）、`time`（主体日历：带时区的时间线索引与相对时间解析）、`attention`（访问
  账本的面——评测全程 silent，它必然无事可做）。
- **正本概览头**：每页四槽概览，`overview_budget_chars` / `overview_required_after_claims`。
- **`supersede_claim`**：「世界变了」与「我记错了」分开。
- **归档（archive）**：把一份文档或来源从所有默认检索里退下但不删除（main 刚合入）。
- **答题证据策略** `evidence_strategy: select | ranked | all`，以及 `plan_queries`、
  `claim_cap`、`window_cap`、`answer_format`、`answer_reasoning_effort`。
- **质询（challenge）**：编译后盲问覆盖审计 + 补偿编译，`PNEUMA_KNOWLEDGE_CHALLENGE_*`。
- **演进（evolve）**：`evolve step --policy adopt-clean` 程序化采纳。
- **语义切分** `PNEUMA_KNOWLEDGE_CHUNK_STRATEGY=semantic`。
- **engine.yaml `pricing:`**：给每个模型角色声明单价，成本核算优先用框架自己的账；答题侧
  从 `ask` 自报的 token 统计聚合。
- 模型角色面：`compile`/`recall`/`answer`/`deep`/`live_*`/`embedding` 可分角色配置。

读这些的权威文档（全部可读，都在 repo/ 里）：`scaffold/AGENT-GUIDE.md`、
`docs/guides/compile-contract.md`、`docs/guides/recall-strategies.md`、
`docs/design/index-components.md`、`docs/reference/configuration.md`、`examples/opc/`
（一个完整的参考工程；**只读其 README 与 engine/ 目录形态**，不读 build-record/eval 下的
任何评估产物——那是另一个语料的评估集，与你无关）。

## 3. 你的自主权（实验设计属于你）

- **契约/schema**：十份契约怎么写、族怎么定、口径怎么立——你的判断。允许的信息只有
  第 1 节列的结构字段与十个首 session。
- **超参与模型角色**：检索预算、证据策略、切分、演进阈值、质询轮数、并发池、每个角色用
  哪个模型（预算内）。
- **拓扑**：这台机器 16 CPU / 31 GiB，已有 24 个别人的容器在跑；一个 scaffold 项目一栈
  6 个容器。分批起停、缩小池子、或别的安排，自行权衡并写明理由。
- **答题风格与应试 doctrine**属于考纲阶段的决定，冻结#1 前不定。

## 4. 判分（不可协商）

官方 scorer 原样调用：`./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined
--concurrency 64`，判官 `qwen/qwen3-14b`（OpenRouter，官方接受的别名），key 进程内映射、
不落盘不上命令行。报**双分数**：官方全量 + 剔除烧题。predictions 装配时核验 1,382 行、
与官方题库 qa_id 一一对齐、无缺无重。

## 5. 交付物（现场 = 本目录的一个 git 仓库）

本目录 `git init`，从任务书落地起小步提交（冻结点必须各是一个干净提交）。结构：

```
TASKBOOK.md          本文件（不改）
README.md            现场导读：跑了什么、成绩、先读哪份、怎么复现
RUN-LOG.md           全程时间线（UTC），逐事件，含一切事故与披露
FROZEN.md            两次冻结的哈希、应试 doctrine、烧题清单
RUN-REPORT.md        主报告（下详）
contracts/           十份契约 + 引擎配置样例
scripts/             冻结脚本 + 辅助工具
results/             predictions.jsonl（qa_id+作答）、剥离版判分、官方汇总原样、成本
build-record/        逐 session 进度 csv、演进/质询记录、脱敏后的构建与答题日志
reference/prev-run/  （已备好，不改）
repo/                框架 worktree（git 仓库里只记 commit sha，不入库）
data/ material/ app-*/ secrets/ logs/   一律 .gitignore
```

**RUN-REPORT.md 必须包含**：双分数与官方榜参照；分 conversation / 分 category / 分模态
得分表（category 标签从判分产物读，判分后才接触）；与两条既往线（76.34%、78.15%）的对比
——同协议同判官，框架版本、执行者模型与你的实验设计是变量，逐项写明差异，并诚实说明哪些
能归因、哪些不能（单线无消融、判官噪音约 ±1pp，2–3pp 以内不主张差异）；成本核算（分环节
token 与金额、口径写明）与耗时表；演进/质询的触发与产出统计；错题抽样分析（判分后）；
「赌对/赌错」复盘；结论。

语言：报告与 RUN-LOG 用中文（技术名词保留英文），代码与脚本注释用英文。

## 6. 执行方式

全程自治，别问人。长活（构建/答题/判分）用 nohup 落盘日志后台跑，你轮询文件系统状态；
你的会话可能被打断（上一轮就遇到过上游服务中断），编排者会 resume——所以一切要可断点
续跑，RUN-LOG 与状态文件是接续的依据。阶段边界（冻结、起跑、跑完、分数落地）在 stdout
打一行明确标记。跑完阶段 C 后，最后一行输出 `EXPERIMENT COMPLETE: <官方全量分数>`。
