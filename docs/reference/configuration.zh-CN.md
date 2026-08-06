# 配置

[English](configuration.md) | **简体中文**

框架的全部配置都是带 `PNEUMA_KNOWLEDGE_` 前缀的环境变量（读取本地 `.env`；未知键忽略）。下表省略前缀。起步可以拷贝 [`.env.example`](../../.env.example)。

环境变量与默认值之间可以插入一层：**引擎目录**（`ENGINE_DIR`，见[架构 §11](../architecture.zh-CN.md#11-引擎目录)）。优先级是**进程 env > 引擎文件 > 框架默认**，并且在 settings 装配处被机械执行：引擎文件的值只在 `os.environ` 未表态的键上被交给 `Settings`。两个值得知道的推论：环境变量存在但为空，仍然算环境层的一次表态；而来自 `.env` **文件**的值不是进程 env，因此排在引擎文件**之下**。`ENGINE_DIR` 不设（默认）就表示这一层根本不存在，每一项配置的解析与这个概念出现之前完全一致。

## 必填

| 配置 | 含义 |
|---|---|
| `USER_SCHEMA_BASE_VERSION` | 本部署通过 `register_skill_base` 注册的编译契约版本。刻意不给默认值：框架不带领域契约，部署必须声明自己的——留空会在第一次编译时大声失败。 |

## 存储与中间件

| 配置 | 默认 | 含义 |
|---|---|---|
| `PG_DSN` | `postgresql://pneuma_knowledge:pneuma_knowledge@localhost:15432/pneuma_knowledge` | Postgres（L0、任务队列、投影、各注册表） |
| `QDRANT_URL` | `http://localhost:16333` | 向量库 |
| `QDRANT_COLLECTION` | `pneuma_knowledge_chunks` | 单 collection；向量维度建库时锁定——换嵌入模型要换 collection 名 |
| `MEILI_URL` | `http://localhost:17700` | 词法索引 |
| `MEILI_KEY` | `masterKey_change_me` | 生产必须改 |
| `CANONICAL_ROOT` | `./data/canonical` | 正本存储根（每用户一仓）；容器镜像里为 `/data/canonical` |
| `ENGINE_DIR` | （空） | 引擎目录：一个被版本化的单元，装着本部署的策略文件、编译契约、提示词覆盖与主人档案（见[架构 §11](../architecture.zh-CN.md#11-引擎目录)、[设计文档](../design/engine-console.zh-CN.md)）。空 = 本部署没有引擎目录：行为零变化，且 `/v1/engine/*` 返回 404。设上之后那四条路由就服务这个目录；下表里凡是被这个目录声明过的策略配置，只要进程环境不表态，就都从它解析 |

## 模型

| 配置 | 默认 | 含义 |
|---|---|---|
| `LLM_MODEL` | `openai:gpt-4o-mini` | 基础模型规格，也是所有角色的兜底 |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_CHALLENGE` | 空 | 按角色覆盖 |
| `LLM_TIMEOUT` | `600` | 秒；防挂死，不防慢 |
| `LLM_MAX_RETRIES` | `3` | 瞬时错误重试（langchain） |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<维度>`（确定性、零密钥）或 `openrouter:<模型>` |

模型规格三种形态：`scripted:<路径>`（本地回放、零密钥——且硬覆盖所有角色，scripted 运行完全确定）；`openrouter:<模型>`（需要 `OPENROUTER_API_KEY`）；以及 `init_chat_model` 认识的任意 provider 前缀（如 `anthropic:claude-sonnet-5`、`openai:gpt-4o-mini`）。角色回退只有一跳：`live_context → recall`、`evolve → compile`、`challenge → compile`，然后是 `LLM_MODEL`。

## L2 切块

| 配置 | 默认 | 含义 |
|---|---|---|
| `CHUNK_STRATEGY` | `semantic` | `semantic` = LLM 主题/情节边界检测（用编译角色模型；`scripted:` 模型下自动回落 `sentence`）；`sentence` / `recursive` = 机械切分，零 LLM 成本 |
| `SEMANTIC_OVERLAP` | `smart` | 只对 `semantic` 有意义。`smart` = 模型返回前闭后闭区间，转折块同时属于前后两段；`off` = 原来的零重叠切法 |
| `CHUNK_SIZE` | `768` | token 计；CJK 约 1 token/字 |
| `CHUNK_OVERLAP` | `128` | token 计 |

**`SEMANTIC_OVERLAP`。** 转折句——那句既收束上一话题、又开启下一话题的话，那个既回答了上一问、又引出下一问的回应——本来就同时属于两段，而一刀切必须把它判给其中一段。`smart` 不再做这个取舍：模型返回 `[起, 止]` 数对而不是起始编号，相邻两段可以共享转折块。共享多少由模型逐个边界判断，不是固定步长。

「段与段可以重叠」有一种退化读法：把每一段都写成全文，这样每一段都保证包含答案，L2 也就退化成源文的 N 份副本。挡住它的是闸门，不是提示词措辞：返回的每一份区间列表都必须端点真实且有序、起点严格递增、无缝隙覆盖整个窗口、相邻两段最多共享 **3** 块、段数不超过块数。违反任何一条即整份拒收，该窗口退回用模型自己报出的起点构造的零重叠切分——被拒掉的是重叠，不是切分。

`off` 是此前全部语义切分测量所用的口径，它的请求字节有测试逐字节钉住，因此它仍然是与 `smart` 做同 harness A/B 的基线。`smart` 作为出厂默认是基于设计判断，**尚未**在同一 harness 上与 `off` 对比测量。

重叠会让一个块出现在两个 L2 chunk 里。这份重复完全在派生层：L0 不受影响，两个 chunk 通过同一套寻址方案指向同一批源块，而检索侧本来就会把重叠窗口合并成一段，所以经由两个 chunk 命中的转折块只会被读一次。chunk manifest 记录了产出这批区间的模式，因此翻转这个旋钮再跑 `rebuild_derived` 会真正重切，而不是回放旧布局；模式概念出现之前写下的记录则原样回放。

## 演进与轮转

| 配置 | 默认 | 含义 |
|---|---|---|
| `EVOLVE_AUTO_TRIGGER` | `true` | 编译驱动的演进触发 |
| `EVOLVE_TRIGGER_TOPIC_DOCS` | `5` | 新文档阈值（与下一条同时满足） |
| `EVOLVE_TRIGGER_NEW_CLAIMS` | `30` | 新 claim 阈值 |
| `EVOLVE_DRAFT_TTL_HOURS` | `24` | 草稿存活时长 |
| `ROLLOVER_THRESHOLD_CHARS` | `40000` | 文档超过此字符数入队轮转；`0` 关闭 |
| `ROLLOVER_KEEP_RECENT_CHARS` | `12000` | 活动文档保留的近期尾部 |
| `RECALL_CLAIM_CAP` | `64` | fast recall 每问的 claim 预算（release 默认，处于实测 40–80 甜区内；不计 token 成本时 80 为实测最优） |
| `RECALL_WINDOW_CAP` | `8` | fast recall 每问的原文窗口预算 |
| `RECALL_PLAN_QUERIES` | `0` | `0` 关；N>0 = 一次规划调用派生至多 N 条额外检索查询，单次 RRF 融合成池 |
| `RECALL_RERANK_MODEL` | （空） | 空为关（默认：实测对 claim 级检索无增益）；`llm` = 召回模型 + reasoning effort `none` 做 LLM 重排（默认 provider）；`llm:<spec>` 指定模型；裸模型名（如 `cohere/rerank-4-pro`）走 OpenRouter `/rerank` 端点 |
| `RECALL_RERANK_CANDIDATES` | `120` | 重排时每查询每路的检索深度；reranker 对完整去重并集打分（硬上限 1000） |
| `RECALL_ANSWER_STYLE` | `conversational` | fast/deep 回答的输出风格预设：`concise` = 只给所问的精确值/短语（判分器、脚本消费），`conversational` = 自然对话式回答，`detailed` = 自成一体的书面纪要。只管形态——红线/引用/诚实收尾与风格无关。recall 请求可逐次覆盖（`answer_style`） |

## 提示词语言

| 配置 | 默认 | 含义 |
|---|---|---|
| `PROMPT_LANGUAGE` | `en` | **框架自身**提示词文案用哪种语言：`en` = 英文目录，`zh` = 核心自带的中文语言包（`prompts.lang_zh.chinese_overlay()`，目录里每个键都有译文、插槽完全一致）。它作为一层 overlay 铺在**部署自己的 overlay 之下**，所以手写的文案永远盖过语言包。`en` 一条 overlay 都不注册，因此与语言包之前的行为逐字节相同 |

它只改模型读到的文案，别的都不改——不改策略、不改机制、不改插槽契约。特别地，它**不**决定文库用什么语言写：那取决于知识主体自己声明的语言（`compile.owner_env.write_language`）。

**英文是基线。** 本仓库公布的每一项测量都是在英文目录上做的。中文包的用途是可读性与贴合中文材料域，跑分等价性未经验证。见[引擎控制台设计](../design/engine-console.zh-CN.md#语言包)。

## 编译后覆盖挑战

| 配置 | 默认 | 含义 |
|---|---|---|
| `CHALLENGE_ENABLED` | `false` | 每次编译落地后跑一轮覆盖审计：对材料盲出题、探针查 claim 面、反思判缺口 |
| `CHALLENGE_MAX_ROUNDS` | `2` | 每次审计的出题/反思轮数（任一阶段自认无题即提前结束） |
| `CHALLENGE_MAX_QUESTIONS` | `6` | 每轮出题上限 |
| `CHALLENGE_MAX_OUTPUT_TOKENS` | `32768` | 审计结构化调用的完成预算——失控生成会便宜地早失败，而不是跑满供应商上限（实测出现过 65,536 token）；`0` = 供应商默认 |
| `CHALLENGE_COMPENSATE` | `true` | 确认的缺口入队一次补偿编译（写入照常过引用闸门） |
| `LLM_MODEL_CHALLENGE` | 空 | 出题与反思用的模型；留空借用编译角色 |

审计的判断力可扩展：它的三段提示词——`compile.challenge.questions_system`、`compile.challenge.reflect_system`、`compile.challenge.compensation_preamble`——都住在 prompt 目录里，启动时用 `override_prompts` 整体替换即可，与其他模型可见文案同一机制。

## 行为开关

| 配置 | 默认 | 含义 |
|---|---|---|
| `DEFAULT_TIMEZONE` | `UTC` | 画像未声明时区时统计"日历天"用的兜底时区 |
| `USER_SCHEMA_PACKS` | `true` | 每用户 schema pack 组合 |
| `USER_SCHEMA_MATRIX_PATH` | 未设 | 部署自带的 pack matrix JSON；未设用内置 |
| `CONTEXT_STREAM_RENDER_ROLES` | `true` | 摄入时渲染 owner/participant 标签 |
| `CONTEXT_STREAM_COMPILE_GUIDANCE` | `true` | 编译时注入按类型的指引 |
| `BRIEFING_CITATION_ALIAS` | `true` | briefing 里把真实 source id 别名成 `sNN` 句柄 |
| `CORS_ALLOW_ORIGIN_REGEX` | `https?://(localhost\|127\.0\.0\.1)(:\d+)?` | 设为空串完全关闭 CORS |

## 无前缀（直读）

| 变量 | 含义 |
|---|---|
| `OPENROUTER_API_KEY` | `openrouter:` 的对话与嵌入规格共用 |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | 追踪；缺任意一个整体降级为空操作 |

## 仅脚本与 compose 读取（服务不读）

| 变量 | 默认 | 使用方 |
|---|---|---|
| `PNEUMA_KNOWLEDGE_API_HOST` / `_API_PORT` | `127.0.0.1` / `18000` | `scripts/dev-api.sh` |
| `PNEUMA_KNOWLEDGE_PG_PASSWORD` / `_MEILI_KEY` | `pneuma_knowledge` / — | `infra/docker-compose.yml` |
