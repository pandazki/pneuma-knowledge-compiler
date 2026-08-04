# 配置

[English](configuration.md) | **简体中文**

框架的全部配置都是带 `PNEUMA_KNOWLEDGE_` 前缀的环境变量（读取本地 `.env`；未知键忽略）。下表省略前缀。起步可以拷贝 [`.env.example`](../../.env.example)。

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
| `CHUNK_SIZE` | `768` | token 计；CJK 约 1 token/字 |
| `CHUNK_OVERLAP` | `128` | token 计 |

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

## 编译后覆盖挑战

| 配置 | 默认 | 含义 |
|---|---|---|
| `CHALLENGE_ENABLED` | `false` | 每次编译落地后跑一轮覆盖审计：对材料盲出题、探针查 claim 面、反思判缺口 |
| `CHALLENGE_MAX_ROUNDS` | `2` | 每次审计的出题/反思轮数（任一阶段自认无题即提前结束） |
| `CHALLENGE_MAX_QUESTIONS` | `6` | 每轮出题上限 |
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
