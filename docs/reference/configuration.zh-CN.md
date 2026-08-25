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
| `MEDIA_S3_ENDPOINT_URL` | `http://localhost:19000` | 私有 S3 兼容 L0 图片存储（本地栈使用 RustFS） |
| `MEDIA_S3_ACCESS_KEY` / `_SECRET_KEY` | 开发值 | S3 凭据；脚手架项目生成彼此隔离的随机值 |
| `MEDIA_S3_BUCKET` / `_REGION` | `pneuma-media` / `us-east-1` | S3 bucket 与签名区域 |
| `MEDIA_MAX_IMAGE_BYTES` | `20971520` | 单张原图允许的最大字节数 |
| `CANONICAL_ROOT` | `./data/canonical` | 正本存储根（每用户一仓）；容器镜像里为 `/data/canonical` |
| `ENGINE_DIR` | （空） | 引擎目录：一个被版本化的单元，装着本部署的策略文件、编译契约、提示词覆盖与主人档案（见[架构 §11](../architecture.zh-CN.md#11-引擎目录)、[设计文档](../design/engine-console.zh-CN.md)）。空 = 本部署没有引擎目录：行为零变化，且 `/v1/engine/*` 返回 404。设上之后那四条路由就服务这个目录；下表里凡是被这个目录声明过的策略配置，只要进程环境不表态，就都从它解析 |

## 模型

| 配置 | 默认 | 含义 |
|---|---|---|
| `LLM_MODEL` | `openrouter:openai/gpt-5.6-luna` | 基础模型规格，也是所有角色的兜底 |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_ANSWER` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_CHALLENGE` / `_BRIEF` | 空 | 按角色覆盖；`answer` 只负责 fast 的最终答题，留空则借用 `recall` |
| `ANSWER_REASONING_EFFORT` | 空 | 只在 fast 最终答题调用中发送的推理强度；空则保持 provider 默认。生成项目明确写为 `high` |
| `LLM_TIMEOUT` | `600` | 秒；防挂死，不防慢 |
| `LLM_MAX_RETRIES` | `3` | 瞬时错误重试（langchain） |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<维度>`（确定性、零密钥）或 `openrouter:<模型>` |
| `COMPILE_IMAGE_MODE` | `auto` | `caption` = 只送带标签的 caption/OCR；`native` = 派生文本加真实图片块；`auto` = 读取编译模型 profile，未知则回落 `caption`。引擎键：`models.image_mode` |

模型规格三种形态：`scripted:<路径>`（本地回放、零密钥——且硬覆盖所有角色，scripted 运行完全确定）；`openrouter:<模型>`（需要 `OPENROUTER_API_KEY`）；以及 `init_chat_model` 认识的任意 provider 前缀（如 `anthropic:claude-sonnet-5`、`openai:gpt-5.6-luna`）。角色回退只有一跳：`answer → recall`、`live_context → recall`、`evolve → compile`、`challenge → compile`、`brief → compile`，然后是 `LLM_MODEL`。脚手架让检索规划/概览继续跑 standard Luna，只把最终答题送到显式 `high` effort 的 Luna Pro。

`native` 是一次明确断言：选中的模型和实际路由 provider 能接收 LangChain 图片 content block；不兼容就失败，不会悄悄把图片压成文本。`caption` 要求 importer 提供带标签的 `caption`/`ocr` 表示，也绝不声称编译模型看过原图。`auto` 会把直连 OpenAI 和 OpenRouter 上的 GPT-5.6 全系识别为原生图片模型，即使网关没有附 LangChain model profile；其他能力未知的 profile 保持保守的 `auto → caption`。

## L2 切块

| 配置 | 默认 | 含义 |
|---|---|---|
| `CHUNK_STRATEGY` | `semantic` | `semantic` = 一次编译角色调用同时返回主题/episode 边界和用于 L2 检索与派生回答上下文的有根据标题/描述（`scripted:` 模型下回落 `sentence`）；`sentence` / `recursive` = 机械切分，零 LLM 成本 |
| `SEMANTIC_OVERLAP` | `smart` | 只对 `semantic` 有意义。`smart` = 模型返回前闭后闭区间，转折块同时属于前后两段；`off` = 原来的零重叠切法 |
| `CHUNK_SIZE` | `768` | 语义边界检测后的 embedding 单元上限；按 token 计，CJK 约 1 token/字 |
| `CHUNK_OVERLAP` | `128` | token 计 |

**`SEMANTIC_OVERLAP`。** 转折句——那句既收束上一话题、又开启下一话题的话，那个既回答了上一问、又引出下一问的回应——本来就同时属于两段，而一刀切必须把它判给其中一段。`smart` 不再做这个取舍：每个 episode 对象末尾返回 `start`、`end` 前闭后闭坐标，相邻区间可以共享转折块。共享多少由模型逐个边界判断，不是固定步长。

**Episode 表示。** 同一份结构化响应里，每个语义段按「语义在前」的顺序返回 `title`、`description`，再返回 `start`/`end` 坐标（`off` 的 `end` 由下一个 start 推导，因此省略）。描述只跟随来源：具体人物、时间、地点、事件、决定、情绪、原因、计划与结果。已知来源发生日期只负责锚定相对时间；只有日历口径无歧义时才写精确周期端点。raw/caption 文本与 episode 标题/描述作为两套独立的 L2 表示分别做 embedding 和排序；episode point 还会保留标题/描述作为高密度的**派生 L2 内容**。普通 RRF 之后执行保序来源区间重叠抑制；纯 episode 命中与 raw/caption 或词法证据重叠时，保留精确证据区间，并让它至多继承 episode 的排名。fast recall 可以把最多 `RECALL_EPISODE_SUMMARY_CAP` 条高排名描述渲染进独立的 `派生 episode 摘要` 章节。每条都直说它是生成摘要而非逐字原文，并机械附上来源标题、发生时间、章节与精确 `source_id + block span`；任何精确细节冲突都以 raw/claim 证据为准。上下文组装不再扩张 semantic 区间，默认只合并真正重叠的区间；纯词法单块命中默认只向前扩一块。新 v3 manifest 无模型回放坐标与描述；只有边界的旧 manifest 会执行一次固定区间补描述，返回坐标必须逐一完全相等。

「段与段可以重叠」有一种退化读法：把每一段都写成全文，这样每一段都保证包含答案，L2 也就退化成源文的 N 份副本。挡住它的是闸门，不是提示词措辞：返回的每一份区间列表都必须端点真实且有序、起点严格递增、无缝隙覆盖整个窗口、相邻两段最多共享 **3** 块、段数不超过块数。违反任何一条即整份拒收，该窗口退回用模型自己报出的起点构造的零重叠切分——被拒掉的是重叠，不是切分。

`off` 保留原来的零重叠几何形状。产生 episode 表示的提示词是新的、有字节钉住的基线，因此旧的「只返回边界」测量会被明确退役，不会被当作 harness 未变的结果对比。

重叠会让一个块出现在两个 L2 chunk 里。这份重复完全在派生层：L0 不受影响，两个 chunk 通过同一套寻址方案指向同一批源块，而检索侧会抑制排名较低的重叠结果，所以经由两个 chunk 命中的转折块只会被读一次。chunk manifest 记录了产出这批区间的模式，因此翻转这个旋钮再跑 `rebuild_derived` 会真正重切，而不是回放旧布局。旧记录的坐标始终原样保留；一次性 v3 迁移只补它们缺失的派生描述。

## 演进与轮转

| 配置 | 默认 | 含义 |
|---|---|---|
| `EVOLVE_AUTO_TRIGGER` | `true` | 编译驱动的演进触发 |
| `EVOLVE_TRIGGER_TOPIC_DOCS` | `5` | 新文档阈值（与下一条同时满足） |
| `EVOLVE_TRIGGER_NEW_CLAIMS` | `30` | 新 claim 阈值 |
| `EVOLVE_DRAFT_TTL_HOURS` | `24` | 草稿存活时长 |
| `ROLLOVER_THRESHOLD_CHARS` | `40000` | 文档超过此字符数入队轮转；`0` 关闭 |
| `ROLLOVER_KEEP_RECENT_CHARS` | `12000` | 活动文档保留的近期尾部 |
| `RECALL_CLAIM_CANDIDATE_CAP` | `80` | 内容包含去重、可选重排与最终上下文裁剪之前的 claim 检索深度 |
| `RECALL_CLAIM_CAP` | `40` | 进入 fast 最终回答上下文的已编译 claim 数 |
| `RECALL_WINDOW_CANDIDATE_CAP` | `60` | 检索后保留的词法/raw/episode 融合源区间数 |
| `RECALL_EPISODE_SUMMARY_CAP` | `16` | 进入最终上下文、明确标为派生内容且元数据完整的 episode 摘要数 |
| `RECALL_WINDOW_CAP` | `6` | 进入最终上下文的精确逐字源窗口数 |
| `RECALL_EVIDENCE_STRATEGY` | `ranked` | 仅 fast 的上下文编排：`ranked` 保留固定检索头部；`select` 增加一次结构化 recall 模型调用，在断言、episode 摘要、raw 窗口和已知 canonical 文档之间选择受上限约束的组合。逐次覆盖字段：`evidence_strategy` |
| `RECALL_ANSWER_FORMAT` | `text` | 仅 fast 的回答线格式：`text` 是既有自由文本调用；`structured` 将回答类型、干净回答正文与精确引用分开，再只准入证据中出现过的精确区间。逐次覆盖字段：`answer_format` |
| `RECALL_SELECTION_REASONING_EFFORT` | （空） | `select` 调用的可选 provider 推理强度提示；留空不发送覆盖值 |
| `RECALL_PLAN_QUERIES` | `0` | `0` 关；N>0 = 一次规划调用派生至多 N 条额外检索查询，单次 RRF 融合成池 |
| `RECALL_RERANK_MODEL` | （空） | 空为关；`llm` = 召回模型 + reasoning effort `none` 做 LLM 重排；`llm:<spec>` 指定模型；裸模型名（如 `cohere/rerank-4-pro`）走 OpenRouter `/rerank` 端点 |
| `RECALL_RERANK_CANDIDATES` | `120` | 重排时每查询每路的检索深度；reranker 对完整去重并集打分（硬上限 1000） |
| `RECALL_ANSWER_STYLE` | `conversational` | fast/deep 回答的输出风格预设：`concise` = 只给所问的精确值/短语（判分器、脚本消费），`conversational` = 自然对话式回答，`detailed` = 自成一体的书面纪要。只管形态——红线/引用/诚实收尾与风格无关。recall 请求可逐次覆盖（`answer_style`） |

`select` 是质量／延迟取舍，不是另一份检索权威。选择器只返回候选下标和已知路径；框架会验证它们、并入一小段确定性的高排名安全头部，再把选中的 claim／episode 来源追到有上限的 L0 原文。超时、schema 或 provider 失败会回落 ranked 上下文，并通过 degraded telemetry 披露。因为这次调用串行位于检索与回答之间，把它设成部署默认前应单独测量 selector 延迟。`ranked + text` 仍是兼容且延迟最低的档位。

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

## 编译简报

| 配置 | 默认 | 含义 |
|---|---|---|
| `BRIEF_ENABLED` | `false` | 每次编译落地后，用一次模型调用把这次编译的机械 claim 事件叙述成一段简报，存在 job 行上、显示在 History 时间线（标注为派生） |
| `LLM_MODEL_BRIEF` | 空 | 叙述用的模型；留空借用编译角色 |

简报的输入只有机械记录——从 diff 推导出的 claim 事件加上各来源的出处句——从不包含编译对话本身，因此模型没有记录之外的东西可叙述。它是展示文案而非知识：不带引用、不写正本，生成失败只是没有简报，不会让任务失败。它的提示词（`compile.brief.system`、`compile.brief.task`）住在 prompt 目录里，与其他模型可见文案同一机制。

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
