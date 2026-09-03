# 可观测性 —— Langfuse 追踪

[English](observability.md) | **简体中文**

框架里的每一次模型调用都可以追踪到 Langfuse，而 `pneuma-knowledge-core` 从不导入任何追踪库。core 的调用点只接受 langchain 的 `callbacks` + `trace_metadata`；服务侧在 [`wiring.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/wiring.py) 里构建 Langfuse `CallbackHandler` 并注入。没配置时，整套东西是逐字节的 no-op。

## 怎么开启

三个**不带前缀**的变量（与 `OPENROUTER_API_KEY` 同一约定，好让 Langfuse 项目自己的变量名原样可用），写在 `.env` 或进程环境里：

| 变量 | 含义 |
|---|---|
| `LANGFUSE_SECRET_KEY` | 项目 secret key |
| `LANGFUSE_PUBLIC_KEY` | 项目 public key |
| `LANGFUSE_BASE_URL` | Langfuse 主机（如 `http://localhost:3000`） |

scaffold 项目会把这三个变量同时传给 API 与 worker 容器。若自托管 Langfuse 绑定在 Docker 主机上，可保留面向宿主机的原值，并设置 `PNEUMA_APP_LANGFUSE_BASE_URL_CONTAINER=http://host.docker.internal:<端口>`。若该 Langfuse 还用 `localhost` 签发媒体上传 URL，再设置 `PNEUMA_APP_LANGFUSE_LOCALHOST_GATEWAY=host-gateway`；这个显式开关让容器无需改写凭据或签名 URL，就能上传 trace 中的图片附件。

`build_langfuse_handler(settings)` 只有三个都非空才返回 handler，否则返回 `None`。缺一个按**关闭**处理，而不是报错：`llm_call_config` 给出 `callbacks: []`，每个 core 调用点跑得和追踪不存在时一模一样，`flush_traces()` 也不会打开任何连接。这三个值永不打印、永不回显。

「配了一半」和「配好了」在 span 缺失之前无法区分——任何付费管线都应把这三个变量当作全有或全无。

追踪与模型无关：零密钥的 `scripted:` / fake 聊天模型走 langchain 标准的 `BaseChatModel` 路径，注入的回调在它们身上和在真实 provider 上一样会触发——**为了让追踪成立，模型侧没有改过一行代码**，scripted 回放同样产出真实 span。（嵌入调用不带回调；只有聊天模型与 agent 运行被追踪。）

## 被追踪的 operation 全表

`llm_call_config(ctx, operation=…, user_id=…, extra=…)` 打的是 `operation` 这个 metadata 键；core 打的是 langchain 运行上的 `run_name`。一个 operation 内含多种不同调用时，两者会不一致。

| `operation` | `run_name` | 何时触发 | 每次调用的 span 数 |
|---|---|---|---|
| `compile` | `compile` | worker 的 `compile` job（challenge 的补偿编译也走这里） | 工具循环每一轮一次——一个 job 是 N 条 trace，靠 session 串起来 |
| `compile.challenge` | `compile.challenge.questions`、`compile.challenge.reflect` | `challenge` job：`CHALLENGE_ENABLED` 时每次编译提交后入队 | 每审计轮两次（最多 `CHALLENGE_MAX_ROUNDS` 轮） |
| `compile.groom` | `compile.groom.overview` | `groom` job：文档超过 `ROLLOVER_THRESHOLD_CHARS` | 一次（概览重写） |
| `chunk.semantic` | `chunk.semantic` | `CHUNK_STRATEGY=semantic` 下的 `index` job，且仅首次入库或内容/模型真变了——manifest 回放不调模型 | 每个 block 窗口一次 |
| `evolve.propose` | `evolve.propose` | `evolve` job 的 phase 1 | 一次结构化调用 |
| `evolve.reorganize` | `evolve` | `evolve` job 的 phase 2（与 propose 同一个 job） | 工具循环每一轮一次 |
| `recall.fast` | `recall.fast`、`recall.fast.plan`、`recall.fast.select`、`recall.fast.evidence_select` | `POST /v1/users/{user_id}/recall` 且 `mode=fast` | 一次作答调用（`recall.fast`），外加每个真正跑起来的模型步骤各一个 span：`RECALL_PLAN_QUERIES` 大于零时是 `plan`，`ranked` 从概览里整页挑选时是 `select`，`evidence_strategy: select` 编排证据时是 `evidence_select` |
| `recall.deep` | `recall.deep` | `POST /v1/users/{user_id}/recall` 的 `mode=deep`，以及 `POST …/recall/stream` | 每次提问一条根 chain run；agent 每一轮是其下的嵌套 span |
| `briefing.ask` | `briefing.ask` | `POST /v1/users/{user_id}/briefings/{briefing_id}/ask` | 形状同 deep：根 chain run + 每轮一个嵌套 span |
| `profile.generate` | `profile.generate` | `POST /v1/profile/generate` | 一次结构化调用 |
| `live_context.evaluate` | `recall.suggestion` | 每一次 Live Context 评估（`…/live-context/ws` 与 `…/live-context/stream`） | 每次评估一次结构化调用 |
| `live_context.expand` | `live_context.expand` | Live Context 的 `want_more`（卡片展开） | 一次调用 |

评测 harness 专用、不出现在服务路径上的 operation：`bench.answer.upstream`、`bench.answer.full_context`、`bench.answer.budget_matched`、`bench.answer.<arm>`、`bench.judge.<arm>`、`bench.judge2.<arm>`。harness 同时复用 `recall.fast` 与 `profile.generate`。

目前未被追踪的：`skill.derive`（derive-pack 推理）虽然接受 `callbacks`/`trace_metadata`，但 `skills.skill_for_user` 调 `packs_for_profile` 时没传，因此不产出 span，这部分开销无归属。所有机械环节——入库、L1/L2 写入、各道 gate、投影、`evolve_adopt` 对账——都不调模型，也就没有 trace。

## 可过滤的 metadata 键

`llm_call_config` 返回 `{"callbacks": [...], "trace_metadata": {...}}`。四个键恒定存在：

| 键 | 值 |
|---|---|
| `operation` | 上表里的逻辑操作名 |
| `user_id` | 租户 id（不变量 I1 的第一维） |
| `env` | `local`（目前是常量，还不是配置项） |
| `app` | `pneuma-knowledge-compiler` |

各操作附加键（来自 `extra`；值为 `None` 的条目被丢弃，所以缺值不会变成一个 `null` 分面）：

| 操作 | 附加键 |
|---|---|
| `compile` | `skill_version`、`skill_id`、`job_id`、`source_count`、`image_count`、`image_mode` |
| `compile.challenge` | `job_id` |
| `compile.groom` | `job_id`、`document_path`、`volume_path`、`closed_claims`、`skill_version` |
| `evolve.propose` | `skill_version` |
| `evolve.reorganize` | `task_id`、`skill_version` |
| `recall.fast` | `snapshot_ref`、`kb_snapshot_id`、`image_count`、`image_mode`（作答调用） |
| `recall.deep` | `snapshot_ref`、`kb_snapshot_id` |
| `briefing.ask` | `snapshot_ref`、`briefing_id` |
| `live_context.evaluate` | `focus`、`briefing_id` |
| `chunk.semantic`、`profile.generate`、`live_context.expand` | 无 |

langchain 会另外折入自己的 `ls_*` / `lc_versions` 键；我们的键与它们并列。

## session 合并规则（把多轮循环归一）

工具循环里每次 `invoke` 都会开一条自己的根 trace，于是一个编译 job 的各轮本会散成 N 条互不相关的 trace。为此 `llm_call_config` 会合成 langchain-Langfuse 的保留 metadata 键：

- `langfuse_session_id = f"{operation}:{session}"`，其中 `session` 取 `job_id`、`briefing_id`、`snapshot_ref` 中**第一个存在**的；`extra` 里都没有则不生成 session id。
- `langfuse_user_id = user_id`，恒定写入。

由此产生几个值得记住的后果：`briefing.ask` 按 `briefing_id` 归组（不是同样存在但顺序更后的 `snapshot_ref`）；`recall.fast` / `recall.deep` 按 `snapshot_ref` 归组，所以同一快照上的所有提问共享一个 session；`evolve.reorganize` 只有 `task_id`——它*不是* session 键——因此它的各轮没有 session；`kb_snapshot_id` 同样永不作为 session 键。这两个键是纯附加的，追踪关闭时完全惰性。

## trace-size 纪律

**metadata 只放 id、计数与有限模式枚举——永不放 key，永不放 canonical 正文。** `user_id`、`job_id`、`snapshot_ref`、`source_count`、`closed_claims`、`image_mode`：足够切分 trace，不会撑爆它，也不泄露任何密钥。langchain 作为 span 内容上报的 prompt / 响应正文是模型 I/O 本身，不是 metadata；我们自己加的 metadata 就止步于标识符与有限机器状态。若 `extra` 的值是给人阅读的正文，就不该放这里。

## flush 策略（按进程类型）

Langfuse SDK 在后台线程里批量上报，因此很快退出的进程必须 flush，否则整批丢失。`AppContext.flush_traces()` 排空客户端（`langfuse.get_client().flush()`，因为 SDK 是同步的而包在 `to_thread` 里）。它**不会**强制构建 handler：从未跑过被追踪调用的上下文什么都不 flush，也不打网络。

| 进程 | flush |
|---|---|
| worker | **每个 job 之后**都在 `finally` 里 flush（`drain_user`、`drain_index_jobs`）——一次 sweep 随时可能紧接着退出，绝不指望后台批次活下来 |
| API 服务 | 长驻；靠后台批次即可，另外 lifespan 关停会调 `ctx.aclose()` → `flush_traces()` |
| 脚本 / 示例 | 退出前显式 `await ctx.flush_traces()`（或 `aclose()`） |
| 纯 ingest | 没有模型调用 ⇒ handler 从未构建 ⇒ 什么都不 flush，不打网络 |

## 设计不变量

`pneuma-knowledge-core` 永不导入 `langfuse`——它的依赖始终是 pydantic + langchain-core + langchain（architecture.md §2）。`langfuse` 只是 `pneuma-knowledge-service` 的依赖，且藏在 `wiring._import_langfuse()` 里懒导入，零密钥路径根本不会加载它。
