# 配置

[English](configuration.md) | **简体中文**

框架的全部配置都是带 `PNEUMA_KNOWLEDGE_` 前缀的环境变量（默认读取本地 `.env`；未知键忽略）。下表省略前缀。起步可以拷贝 [`.env.example`](../../.env.example)。

环境变量与默认值之间可以插入一层：**引擎目录**（`ENGINE_DIR`，见[架构 §11](../architecture.zh-CN.md#11-引擎目录)）。优先级是**进程 env > 引擎文件 > 框架默认**，并且在 settings 装配处被机械执行：引擎文件的值只在 `os.environ` 未表态的键上被交给 `Settings`。两个值得知道的推论：环境变量存在但为空，仍然算环境层的一次表态；而来自 `.env` **文件**的值不是进程 env，因此排在引擎文件**之下**。`ENGINE_DIR` 不设（默认）就表示这一层根本不存在，每一项配置的解析与这个概念出现之前完全一致。

## 必填

| 配置 | 含义 |
|---|---|
| `USER_SCHEMA_BASE_VERSION` | 本部署通过 `register_skill_base` 注册的编译契约版本。刻意不给默认值：框架不带领域契约，部署必须声明自己的——留空会在第一次编译时大声失败。 |

## 存储与中间件

| 配置 | 默认 | 含义 |
|---|---|---|
| `ENV_FILE` | 工作目录下的 `.env` | 通过进程环境控制 `get_settings()`：未设置时保留本地 `.env` 加载行为；空字符串完全禁用 dotenv；路径则改为加载指定文件。从任意目录运行时，设置 `PNEUMA_KNOWLEDGE_ENV_FILE=` 即可忽略该目录的 `.env`。此项只从进程环境读取，不从 dotenv 或引擎目录读取 |
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
| `ENGINE_DIR` | （空） | 引擎目录：一个被版本化的单元，装着本部署的策略文件、编译契约、提示词覆盖与所有者档案（见[架构 §11](../architecture.zh-CN.md#11-引擎目录)、[设计文档](../design/engine-console.zh-CN.md)）。空 = 本部署没有引擎目录：行为零变化，且 `/v1/engine/*` 返回 404。设上之后 `/v1/engine/*` 那八个端点就服务这个目录；下表里凡是被这个目录声明过的策略配置，只要进程环境不表态，就都从它解析 |

## 模型

| 配置 | 默认 | 含义 |
|---|---|---|
| `LLM_MODEL` | `openrouter:openai/gpt-5.6-luna` | 基础模型规格，也是所有角色的兜底 |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_ANSWER` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_LIVE_DISCOVER` / `_LIVE_PICK` / `_CHALLENGE` / `_BRIEF` | 空 | 按角色覆盖；`answer` 只负责 fast 的最终答题，留空则借用 `recall` |
| `ANSWER_REASONING_EFFORT` | 空 | 只在 fast 最终答题调用中发送的推理强度；生成项目也留空，保持 provider 默认 |
| `LLM_TIMEOUT` | `600` | 秒；防挂死，不防慢 |
| `LLM_MAX_RETRIES` | `3` | 瞬时错误重试（langchain） |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<维度>`（确定性、零密钥）或 `openrouter:<模型>`。一个需要 key 而没人设置的规格并不是一种受支持的「无 L2」模式：启动时会记一条 WARNING，点名这个设置项、对应变量（`OPENROUTER_API_KEY`），以及语义索引与语义检索会一直失败直到它被设置——这是提醒，不是拒绝 |
| `MODEL_PRICING` | （空） | **本部署**为上面这些模型实际支付多少，一行一条（写成单行变量时用 `;` 分隔）：`<模型 id> = <输入>/<输出>/<缓存读>/<缓存写> <货币>`，每项都是每 100 万 token 的价格。空 = 没有声明任何价格：所有显示花费的地方都只显示 token，不显示金额。引擎键：`models.pricing` |
| `COMPILE_CALL_TIMEOUT` | `600` | 一次编译任务里单次模型调用（工具循环、修复轮、编译后简报）的秒数上限。它在 `LLM_TIMEOUT`（供应商客户端的请求护栏）之上：连接挂死时任务会一直停在 `claimed`，直到 worker 重启；超时则任务判失败，正本不受影响。`0` = 不限时。引擎键：`models.compile_call_timeout` |
| `COMPILE_MAX_TOOL_CALLS` | `0` | 一次编译的**一轮**可以花掉多少次工具调用——首轮和它的修复轮都按这个数。`0` 不是不限：它表示这个数由本次任务算出，`max(40, 3 × 来源数)`，因为首轮必须能读完每一个来源、并且每个来源至少追加两次（真实重建里固定的 40 把一个 36 来源的日组截断在追加中途，让 14 个日组没能进库）。任何大于 0 的值都作为绝对上限直接使用。修复轮从不接手首轮剩下的额度：它有自己全新的一份 `max(12, 3 × 违规数)`，同样以这个数封顶——一个旋钮同时约束两轮。引擎键：`models.compile_max_tool_calls` |
| `OVERVIEW_BUDGET_CHARS` | `2000` | 一份正本文档的总览区域可占的字符数——主体画像变了时，一次编译整体重写的那段有界头部。超出则 `rewrite_overview` 工具当场拒绝该次调用、编译闸门也拒绝本轮：它是头部，不是第二本账。引擎键：`models.overview_budget_chars` |
| `OVERVIEW_REQUIRED_AFTER_CLAIMS` | `8` | 一份文档能积累多少条账本断言，才必须由**改动它**的那次编译写出总览（至少写 `definition`）——它是上面那条预算的下限。`finish_compile` 先拒，闸门再拒，两处都点名该文档与它的断言数；本轮没碰过的文档不判。模型只维护已经存在的头部，从不主动开一个（实测：真实库 85 个页面里 41 个从未有过总览，其中不乏 20–31 条断言的）。`0` = 关闭。引擎键：`models.overview_required_after_claims` |
| `COMPILE_IMAGE_MODE` | `auto` | `caption` = 只送带标签的 caption/OCR；`native` = 派生文本加真实图片块；`auto` = 读取编译模型 profile，未知则回落 `caption`。引擎键：`models.image_mode` |

模型规格三种形态：`scripted:<路径>`（本地回放、零密钥——且硬覆盖所有角色，scripted 运行完全确定）；`openrouter:<模型>`（需要 `OPENROUTER_API_KEY`）；以及 `init_chat_model` 认识的任意 provider 前缀（如 `anthropic:claude-sonnet-5`、`openai:gpt-5.6-luna`）。角色回退只有一跳：`answer → recall`、`live_context → recall`、`live_discover → recall`、`live_pick → recall`、`evolve → compile`、`challenge → compile`、`brief → compile`，然后是 `LLM_MODEL`。

其中两个角色属于全量范围的实时上下文车道，它们之所以存在，是因为那条车道每一拍是两次小调用、而不是一次大调用（架构 §7）。`LLM_MODEL_LIVE_DISCOVER`（引擎键 `models.live_discover`）跑第①段——读待处理的对话，决定这一拍到底要不要检索——要的是**小型推理**模型：输出只有几十个 token，需要的是对一场对话的快速判断。`LLM_MODEL_LIVE_PICK`（引擎键 `models.live_pick`）跑第③段——在已经装配好的候选卡片里选一张或一张都不选、写一句短引言、裁剪引用、打分——要的是**又弱又快**的模型，因为这里没有什么要推理的：证据就摆在面前，而且它一个字都不许改写。生成出来的引擎分别写的是 `openrouter:openai/gpt-5.6-sol` 与 `openrouter:openai/gpt-5.6-luna`；两者留空都借用 `recall`，于是已有部署原样继续工作。它们的推理强度由**框架钉死**（发现为 `low`，挑选关闭），并且刻意不做成旋钮：能被部署调高的强度会改变这条车道每一拍的成本，而便宜正是「先花一次调用、再决定要不要检索」这件事的全部理由。`LLM_MODEL_LIVE_CONTEXT` 仍然负责简报范围的那一轮与卡片展开，两者各一次调用，均未改变。脚手架默认让 `recall` 使用 Luna，`answer` 和 `answer_reasoning_effort` 留空：fast 最终答题借用 `recall`，保持 provider 的默认推理强度。单独指定答题模型或推理强度是部署方的可选配置。

### `agent:<backend>`——用编码代理代替模型

`LLM_MODEL_COMPILE`（引擎键 `models.compile`）还接受一种形态：`agent:codex` 或 `agent:claude-code`。它命名的是**执行体**而不是模型——这一轮由本机上的那个编码代理来跑，用所有者自己的订阅，走与模型执行体完全相同的断言级草稿和同一道闸门（见 [coding-agent-mode](../design/coding-agent-mode.zh-CN.md) 裁定 1）。配置在 `restart` 后作用于后续编译，以及继承该执行器的演进作业；改回来同样是一行。

这会改变四项行为：

- **编译与演进都有 agent 门。** `LLM_MODEL_EVOLVE` 接受 `agent:<backend>`，留空时继承 compile 的执行器。两种角色都使用 harness 和各自的持久草稿闸门。challenge 仍跳过借来的 agent 规格、使用基础 API 模型，默认关闭。其他角色显式写 `agent:`，或基础 `LLM_MODEL` 写成它，都会在启动时被拒绝。
- **worker 的姿态覆盖两扇门。** `AGENT_UNATTENDED=true` 时打开并交派 compile/evolve 作业；`false` 时 agent 作业留队等 `pkc draft open` 或 `pkc evolve draft open`。index、projection 和 adopt 等照常排干；两种执行体受同一个逐用户单写者锁约束。
- **agent 编译自己提供简报。** `pkc draft finish --brief <f>` / `--brief -` 接收不超过 8,000 字符的非空文本；无人值守时 harness 的最后消息在同样界限下补全成功版本缺失的简报。不调用 brief API 模型，显式简报不会被覆盖，且不依赖 API 叙述开关 `BRIEF_ENABLED`。
- **语义切分降级。** 编码代理不响应 `ainvoke`，所以 `CHUNK_STRATEGY=semantic` 会像 scripted / 无密钥部署一样回落到机械分句；引擎文件里仍然写着 `semantic`，之后补上密钥再跑 `rebuild_derived` 就能补齐。

| 配置 | 默认 | 含义 |
|---|---|---|
| `EXECUTOR_BACKEND` | （空） | 正在敲 `pkc draft` 命令的是哪个编码代理，由启动那个会话的一方设置。它是**对已发生之事的标注**，不是开关：部署跑在什么上由 `LLM_MODEL_COMPILE` 决定。经 CLI 完成的任务记录 `executor = agent:<后端>`；未设置时只记 `agent`——所有者自己开的终端会话不冒充任何一个 harness。不是引擎旋钮（属于部署接线） |
| `AGENT_UNATTENDED` | `true` | **worker 自己**是否通过编码代理来跑编译与演进作业。worker 按定义就是无人值守的——它运行的地方没有人守着——所以在 `agent:` 执行体下它会认领编译作业、打开草稿，并交给自己拉起的 harness（[coding-agent-mode](../design/coding-agent-mode.md) §9）。`false` 是交互姿态：agent 编译与演进作业留在队列里，由所有者自己的会话用各自的 draft open 打开，其余作业照常流转。在模型执行体下这个开关不决定任何事。不是引擎旋钮（属于部署接线） |
| `AGENT_PROBE_ON_START` | `true` | 启动时探测所配置的编译 harness，不可用就拒绝启动。装了但没登录的 harness 会掉进交互式登录流程并永远等下去，所以「它是否活着」应当在排队派活之前问清楚，而不是等第一次编译才发现。探测的是**活性**，绝不比较版本。只有无人值守姿态会探测——`pkc` 进程从不拉起 harness，所以它从不探测。测试与 CI 用 `false`：那里 PATH 上的是假二进制，登录这件事根本不存在。不是引擎旋钮 |
| `AGENT_RETRIES` | `3` | 当 harness 以**限流**拒绝一轮时，无人值守启动器最多可以重新拉起几次——仅限这一种。其他任何拒绝都只上报不重试（再试一次还是会被拒），超时同样不重试，因为墙钟本身就是「这一轮结束了」的声明。等待按指数增长并带抖动，受启动器自身的上限约束；每一次等待都写日志。`0` 表示只试一次、不退避。不是引擎旋钮 |
| `AGENT_TASK_STRUCTURE_CHARS` | `60000` | 编码代理的编译任务最多携带多少带编号的来源正文，超过就停下并指明其余部分：每个被截断的来源有一行，说明哪些块未展示，以及读取它们的确切命令 `pkc source fetch <id> ¶a-b --page N`——用的是库里的 id，而不是本轮的 `sNN` 句柄。只有代理轮次有上限——模型执行者没有第二种读取材料的途径，它的任务逐字节不变。可以引用的范围也不变：闸门按 L0 而不是按任务核对引用。`0` = 不设上限。不是引擎旋钮 |
| `AGENT_RATE_LIMIT_COOLDOWN_S` | `900` | 当 harness 说订阅没额度了、又没说什么时候回来时，worker 把这个租户走 agent 的作业晾多久。每次连续命中翻倍，上限为 `AGENT_RATE_LIMIT_COOLDOWN_MAX_S`；第一轮真正跑起来的轮次会把它忘掉。它是兜底，不是规则：harness 自己点名了时刻时（Codex 会打印 `try again at Sep 15th, 2026 9:23 AM`，按 `DEFAULT_TIMEZONE` 解读），以那个时刻为准，因为那是服务商自己的答案，而这只是猜测。等待表现为重新入队那一行上的 `not_before`，所以没有任何东西在睡觉，重启后读到的也是同一个答案。不是引擎旋钮 |
| `AGENT_RATE_LIMIT_COOLDOWN_MAX_S` | `21600` | 翻倍停在哪里——六小时。猜短了才是贵的那个错误：在这条存在之前，853 个作业在四小时里穿过了一份已经死掉的额度。不是引擎旋钮 |
| `AGENT_MODEL` | （空） | 拉起的 harness 跑**哪个模型**，作为启动模板的模型参数（`-m` / `--model`）传入。留空则交给 harness 自己——也就是所有者的全局 harness 配置，因为每个作业的配置目录正是从那里播种的。当一个知识库的编译轮不该继承所有者为自己终端所设的东西时，就在这里点名。不是引擎旋钮 |
| `AGENT_REASONING_EFFORT` | （空） | 告诉那个 harness 想多深：`minimal`、`low`、`medium`、`high` 或 `xhigh`，其余取值在启动时即被拒绝。Codex 以 `-c model_reasoning_effort=<e>` 承载；本版本的 Claude Code CLI 没有这个开关，会直接丢弃。留空即 harness 自身的默认。不是引擎旋钮 |
| `AGENT_KEEP_WORKDIR` | `false` | 保留启动器为每一轮建的工作目录（system 文本、任务、harness 的最后一条消息），而不是删掉它。仅供调试：这些文件里装着知识库的材料，把它们留在 `/tmp` 应当是运维者刻意做的决定。不是引擎旋钮 |
| `PROJECT_DIR` | （API 的 cwd） | 控制台的 Steward 视图在哪里拉起 harness（[coding-agent-mode](../design/coding-agent-mode.md) §5.6）。就是技能包被装进去的那个项目目录，好让 harness 读到本部署自己的 `AGENTS.md` / `CLAUDE.md`，并在旁边找到技能——与 `pkc` 和无人值守 worker 遵循的是同一个约定。之所以做成配置项，是因为 API 与 worker 并不一定共用同一个工作目录。不是引擎旋钮（属于部署接线） |
| `STEWARD_SESSION_IDLE` | `1800` | 控制台的 Steward 会话在开启它的那个浏览器标签页关掉之后还能活多少秒。关掉标签页不等于结束一场对话：harness 进程仍然在跑，重新连上就会重新接回它，并用会话自己保留的事件尾巴重绘。超过这个时限后，进程**组**会被 TERM→KILL 收掉，会话的逐字记录（`steward_turns`）随之删除；下一次接入开的是一段新会话。`0` 表示最后一个 socket 一走就收掉会话。不是引擎旋钮 |
| `STEWARD_SKILL_HASH` | （空） | 教会这个 Steward 会话的那份技能包的 sha256。由 `pkc skill install` 写下的 shim（`<技能目录>/pkc-steward/scripts/pkc`）导出，读一次，然后作为 `Executor-Skill:` trailer 盖进这个会话产出的每一次正本提交——就在 `Skill-Content-Hash` 与 `Prompt-Overlay-Hash` 旁边，好让执行体读到的措辞和契约给它的措辞一样事后可辨。未设置时不写这一行，模型编译出的提交与它一直以来逐字节相同。没有任何东西会替你设置它：没走 shim 的代理会话诚实地无法辨认，而不是被猜一个。不是引擎旋钮（属于会话接线） |

**技能包。** 在代理执行体之下，Steward 由一份生成出来的技能来教——`SKILL.md`、组合契约、编译指令、命令参考、闸门参考，以及那个 shim——由 `pkc skill install [--backend codex|claude-code|all] [--project <目录>]` 装进项目。它是本部署的一次*渲染*（契约 × 提示词覆盖 × 语言 × 组件 × 命令树），永不手写，所以 `pkc skill verify` 会重新渲染一遍，有漂移就列出来并以 `4` 退出；`pkc skill show` 打印哈希与文件清单。脚手架在生成时按 `compiler = codex | claude-code | all` 这个回答安装它，引擎 apply 会重新安装，影响范围 `future_compiles`——已经在跑的会话保持它开始时的措辞，直到重启。这三条命令只读引擎目录：不需要数据库、不需要密钥、不需要跑着的栈。

**任务上的 `executor`。** 每个完成的任务都记录是谁跑的这一轮：worker 自己的循环记 `langchain:<解析后的模型规格>`，编码代理记 `agent:<后端>`。它和 `token_usage` 并排，因为两者合起来回答同一个问题——由代理执行的任务会写明执行体、并且**完全不报** token，因为 harness 的计数属于所有者的订阅，本进程根本没看见过。是缺席，而不是零：写零等于宣称这一轮免费。两个字段在 `GET /jobs` 和控制台的过程视图里都能读到。

在这三者之外，同一条车道上还有第四个、可选的模型：`LIVE_WEB_SEARCH`（引擎键 `models.live_web_search`，默认 `false`）会在知识库旁边再开一条**补充**的互联网面，`LIVE_WEB_SEARCH_MODEL`（引擎键 `models.live_web_search_model`，默认 `openai/gpt-5.6-luna`）指定承接它的 OpenRouter 模型，背后用的是该服务商自己的原生网页搜索。它复用 `OPENROUTER_API_KEY`——不需要第二个密钥——没有密钥时这条搜索会自报不可用，无论开关怎么设，`web` 这个查询种类都不会被提供。在这里打开只是打开了可能性，并不等于对谁都打开：必须**部署与那一条连接都同意**，发现契约才会把这个查询种类写进去；而 `ready` 帧回送的是「批准了什么」，不是「请求了什么」（见 [http-api.zh-CN.md](http-api.zh-CN.md)）。它按次搜索计费，每次搜索的花费会记进那一拍的记录里。

`native` 是一次明确断言：选中的模型和实际路由 provider 能接收 LangChain 图片 content block；不兼容就失败，不会悄悄把图片压成文本。`caption` 要求 importer 提供带标签的 `caption`/`ocr` 表示，也绝不声称编译模型看过原图。`auto` 会把直连 OpenAI 和 OpenRouter 上的 GPT-5.6 全系识别为原生图片模型，即使网关没有附 LangChain model profile；其他能力未知的 profile 保持保守的 `auto → caption`。

### 一次调用花了多少

框架自己不持任何价格观点，`MODEL_PRICING` 就是部署自己表态的地方。四项费率都必须写——把两项缓存
费率省掉，并不等于说它们免费——货币也必须写，因为默认一个 `USD`，就是框架替一个可能用任何币种结算
的部署做了猜测。读不出来的声明会在启动时、以及引擎控制台 apply 时被拒绝，并点名出错的那一条，而不是
悄悄地什么金额都不显示。

```yaml
# engine.yaml
pricing: |
  openrouter:openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD
  openrouter:openai/gpt-5.6-sol  = 0.25/2/0.025/0.25 USD
```

查价先按实际路由的完整规格（`openrouter:openai/gpt-5.6-luna`），再按去掉 provider 前缀后的裸模型
id，于是一张按模型报的价目表，也能给通过网关买的同一个模型定价；而完整规格一旦写了就优先——留给那些
确实为两个网关付不同价钱的部署。

金额是**读取时算出来的**，从不入库：改一次费率，所有数字同时被改对，也不会有哪条记录带着一个季度之
后没人能复现的金额。入库的是 token 用量本身（咨询记录上的 `token_usage`、编译任务上的
`token_usage`）。

有两处拒绝是刻意的。**没有声明价格的模型**只报 token、旁边不给金额——绝不给 0，因为 0 是在说这次调用
免费。另一处：如果一条车道的模型角色解析出**两个不同的价格**，这条车道同样只报 token——车道的用量是它
所有调用的一个总和（fast 花在 `recall` 与 `answer` 上，实时上下文的一拍花在 `live_discover` 与
`live_pick` 上），这个数字内部没有按角色的拆分，那么在两份都适用的费率里挑一份来算，就是给编出来的
金额贴上「派生」的标签。角色们在同一个价格上取得一致时，这条车道就被算得分毫不差。

## L2 切块

| 配置 | 默认 | 含义 |
|---|---|---|
| `SEMANTIC_RETRIEVAL` | `on` | `on` / `off`；引擎键为 `intake.semantic_retrieval`，修改后需要 `restart` + `derived_rebuild` |
| `CHUNK_STRATEGY` | `semantic` | `semantic` = 一次编译角色调用同时返回主题/episode 边界和用于 L2 检索与派生回答上下文的有根据标题/描述（`scripted:` 模型下回落 `sentence`）；`sentence` / `recursive` = 机械切分，零 LLM 成本 |
| `SEMANTIC_OVERLAP` | `smart` | 只对 `semantic` 有意义。`smart` = 模型返回前闭后闭区间，转折块同时属于前后两段；`off` = 原来的零重叠切法 |
| `CHUNK_SIZE` | `768` | 语义边界检测后的 embedding 单元上限；按 token 计，CJK 约 1 token/字 |
| `CHUNK_OVERLAP` | `128` | token 计 |

**`SEMANTIC_RETRIEVAL`。** 设置 `PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL=off`，或运行
`pkc config set semantic_retrieval off`，将 `semantic_retrieval: "off"` 写入
`intake/intake.yaml`。此命令在中间件启动前也能执行；显式进程环境变量仍优先于引擎文件。
`off` 时启动过程不创建 embedding 客户端和向量客户端，因此不需要 embedding 密钥。
接收提案强制 `semantic_indexing: none`，预设选择器只提供该值的处理意图。索引仍写入 L1，
不产生 L2 chunk 或 chunk manifest。fast、rag、deep、briefing 和 live context 使用来源词法搜索
与正本断言检索面，跳过向量分支及 episode 摘要，并在阶段计时中标明 skipped。
`pkc search --mode semantic` 会解释该分支已关闭。两个运维重建命令都会打印 L2 已跳过；
`rebuild_derived` 仍重建 L1、词法/PG 断言投影及组件。

修改后需重启。为已有来源启用语义索引时，运行 `pkc config set semantic_retrieval on`，
在模型需要时配置 embedding 密钥，重启后执行 `rebuild_derived`。当部署开关把非 `none` 的方案
压成 `none` 时，接收记录会用 `semantic_indexing_requested` 保留来源原本的处理模式，因此重建
可恢复该模式而无需改写 L0；明确选择仅词法检索的来源仍保持仅词法检索。缺失的 manifest 会在
首次语义重建时计算并记录，后续重建回放它。关闭期间已有 manifest 不会被修改。

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
| `COMPILE_DRAFT_TTL` | `21600` | 一个打开着的编译或演进草稿（`pkc draft open` / `pkc evolve draft open`，[coding-agent-mode](../design/coding-agent-mode.md) §6）可以静默多少秒，之后队列自愈就视其为被放弃。草稿会被每一条 `pkc draft` 命令重写，所以 `updated_at` 就是「确实有人在推进这一轮」的存活信号；超过 TTL 后草稿被删除、其 job 重新入队——与 worker 中途被杀掉的 job 是同一个结局，且任何情况下都不会写正本，因为未完成的一轮什么也没写。`0` 关闭草稿保护：worker 启动时把所有 claimed 的 job 一律重新入队，与草稿这个概念出现之前完全一致 |
| `RECALL_HANDOFF_TTL` | `86400` | 一次**待答交接**在被同一个启动自愈删除之前，可以等多少秒。`pkc recall --evidence`（[coding-agent-mode](../design/coding-agent-mode.md) §5.1）把 fast lane 装配好的上下文交给 Steward，并记下这次交接——问题、时刻、library ref、证据清单——好让 `pkc consult answer` 之后把它变成一条咨询。一天足够 Steward 隔夜回来，也短到让无人作答的问题不会一直堆积；超时之后这一行就没了，那个问题也就没有留下任何咨询——事实本来就是如此。`0` 关闭这次清扫 |
| `ROLLOVER_THRESHOLD_CHARS` | `40000` | 文档超过此字符数入队轮转；`0` 关闭 |
| `ROLLOVER_KEEP_RECENT_CHARS` | `12000` | 活动文档保留的近期尾部 |
| `RECALL_CLAIM_CANDIDATE_CAP` | `80` | 内容包含去重、可选重排与最终上下文裁剪之前的 claim 检索深度 |
| `RECALL_CLAIM_CAP` | `40` | 进入 fast 最终回答上下文的已编译 claim 数 |
| `RECALL_WINDOW_CANDIDATE_CAP` | `60` | 检索后保留的词法/raw/episode 融合源区间数 |
| `RECALL_EPISODE_SUMMARY_CAP` | `16` | 进入最终上下文、明确标为派生内容且元数据完整的 episode 摘要数 |
| `RECALL_WINDOW_CAP` | `6` | 进入最终上下文的精确逐字源窗口数 |
| `RECALL_EVIDENCE_STRATEGY` | `ranked` | 仅 fast 的上下文编排：`ranked` 保留固定检索头部；`select` 增加一次结构化 recall 模型调用，在断言、episode 摘要、raw 窗口和已知 canonical 文档之间选择受上限约束的组合；`all` 完全不做选择调用，把同一个候选池整体交给回答，只受 `RECALL_ALL_CONTEXT_CHARS` 约束。逐次覆盖字段：`evidence_strategy` |
| `RECALL_ALL_CONTEXT_CHARS` | `120000` | 只有 `RECALL_EVIDENCE_STRATEGY=all` 会读它，也是那条路径唯一的边界：组装后的证据面最多可占多少字符。超出时依次丢弃窗口、episode 摘要、排名最低的断言，并在回答上标记 `evidence_selection_degraded="all:truncated"`、在 `assemble` 阶段预览里给出各面的丢弃条数。`0` 表示不设上限 |
| `RECALL_ANSWER_FORMAT` | `text` | 仅 fast 的回答线格式：`text` 是既有自由文本调用；`structured` 将回答类型、干净回答正文与精确引用分开，再只准入证据中出现过的精确区间。逐次覆盖字段：`answer_format` |
| `RECALL_SELECTION_REASONING_EFFORT` | （空） | `select` 调用的可选 provider 推理强度提示；留空不发送覆盖值 |
| `RECALL_PLAN_QUERIES` | `0` | `0` 关；N>0 = 一次规划调用派生至多 N 条额外检索查询，单次 RRF 融合成池 |
| `RECALL_RERANK_MODEL` | （空） | 空为关；`llm` = 召回模型 + reasoning effort `none` 做 LLM 重排；`llm:<spec>` 指定模型；裸模型名（如 `cohere/rerank-4-pro`）走 OpenRouter `/rerank` 端点 |
| `RECALL_RERANK_CANDIDATES` | `120` | 重排时每查询每路的检索深度；reranker 对完整去重并集打分（硬上限 1000） |
| `RECALL_ANSWER_STYLE` | `conversational` | fast/deep 回答的输出风格预设：`concise` = 只给所问的精确值/短语（判分器、脚本消费），`conversational` = 自然对话式回答，`detailed` = 自成一体的书面纪要。只管形态——红线/引用/诚实收尾与风格无关。recall 请求可逐次覆盖（`answer_style`） |

`select` 是质量／延迟取舍，不是另一份检索权威。选择器只返回候选下标和已知路径；框架会验证它们、并入一小段确定性的高排名安全头部，再把选中的 claim／episode 来源追到有上限的 L0 原文。超时、schema 或 provider 失败会回落 ranked 上下文，并通过 degraded telemetry 披露。因为这次调用串行位于检索与回答之间，把它设成部署默认前应单独测量 selector 延迟。`ranked + text` 仍是兼容且延迟最低的档位。

`all` 走的是相反的取舍：它既不花选择调用，也不按检索名次截断，`select` 本该评判的那个候选池整体进入回答——一次回答调用，
同样的证据面、同样的顺序与格式，代价是更长的提示词和更高的输入账单。它买下的是「材料检索到了却没被选中」这一类失败；付出的是
输入 token 与回答端的注意力。在 `structured` 下，它的 schema 以一个有界的 `deliberation` 字段开头，于是那次没有 selector 来做的
证据审视发生在回答调用内部、在回答定稿之前；这段审视以 `deliberation` 回传，且从不进入系统消息。上下文上限是唯一能裁剪这份
上下文的东西，而且它从不悄悄裁剪。

具体业务该跑三者中的哪一个、`deliberation` 与两个 reasoning-effort 旋钮值不值：[guides/recall-strategies.zh-CN.md](../guides/recall-strategies.zh-CN.md)。

## 提示词语言

| 配置 | 默认 | 含义 |
|---|---|---|
| `PROMPT_LANGUAGE` | `en` | **框架自身**提示词文案用哪种语言：`en` = 英文目录，`zh` = 核心自带的中文语言包（`prompts.lang_zh.chinese_overlay()`，目录里每个键都有译文、插槽完全一致）。它作为一层 overlay 铺在**部署自己的 overlay 之下**，所以手写的文案永远盖过语言包。`en` 一条 overlay 都不注册，因此与语言包之前的行为逐字节相同 |

它只改模型读到的文案，别的都不改——不改策略、不改机制、不改插槽契约。特别地，它**不**决定文库用什么语言写：那取决于知识主体自己声明的语言（`compile.owner_env.write_language`）。


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
| `BRIEF_ENABLED` | `false` | API 执行器每次编译落地后，用一次模型调用把这次编译的机械 claim 事件叙述成一段简报，存在 job 行上、显示在 History 时间线（标注为派生） |
| `LLM_MODEL_BRIEF` | 空 | 叙述用的模型；留空借用编译角色 |

API 生成的简报，其输入只有机械记录——从 diff 推导出的 claim 事件加上各来源的出处句——从不包含编译对话本身，因此模型没有记录之外的东西可叙述。它是展示文案而非知识：不带引用、不写正本，生成失败只是没有简报，不会让任务失败。它的提示词（`compile.brief.system`、`compile.brief.task`）住在 prompt 目录里，与其他模型可见文案同一机制。

## 检索访问统计

框架自己那个使用侧记录的消费者：按目标的访问元数据——最后访问、最近 7 天与 30 天的命中——留在
派生层，读取时联结。它不属于任何组件，也不需要注册任何组件：每一条 `business` 咨询都会到达它。
即便如此它默认仍是惰性的，因为访问者级别默认是 `silent`，而 `silent` 访问者根本什么都不记。

| 配置项 | 默认 | 含义 |
|---|---|---|
| `ATTENTION_HALF_LIFE_DAYS` | `14` | 记录下来的注意力衰减多快：这么多天前的一次阅读只算今天的一半。分数不入库（热度是读取时算的），所以改这个值不重写任何行。`0` = 不衰减。`access-stats` 端点与 `attention` 组件的报告读的是同一个值 |

投递走的是普通作业队列。应答路由写下咨询记录行，并为 `business` 访问者在同一个事务里入队一个
`recall_projection` 作业；compile worker 排掉它，在一个事务里施加统计与该记录的 `projected_at`
戳，然后才通知已注册的组件。请求路径上什么都不处理，所以答案不等其中任何一步——于是投影总要
滞后于它那次咨询一个队列排空的时间（按用户、FIFO、同时一个作业在飞：闲置的库是几秒，排在编译
之后就更久）。`scripts/ops/rebuild_derived.py` 通过入队一个 `recall_rebuild` 作业并把它排掉来
重新推导账本，于是重放拿的是同一把按用户的认领，不可能与在飞的投影交错。

## 索引组件

| 配置 | 默认 | 含义 |
|---|---|---|
| `COMPONENTS` | 空 | 启用的索引组件名，逗号分隔（architecture §6）；空 = 不启用。随包附带：`people`、`time`、`attention` |
| `PEOPLE_FAMILY` | `memory/people/{slug}.md` | `people` 组件绑定的契约路径模板——skill `path_templates` 之一 |
| `ATTENTION_WINDOW_DAYS` | `60` | `attention` 报告往回读多久。更早的日子仍留在表里，只是不在这个问题的范围内 |
| `ATTENTION_EVIDENCE_CHARS` | `1500` | `attention` 交给结构演进提案的那一段的字符上限。按行截断，没放下的部分会被数出来 |
| `RECALL_COMPONENT_PATHS` | `true` | fast 通道：已启用组件提供查询路时，用一轮路由 tool call 选择运行哪些（architecture §7）。没有路 = 没有路由调用。`false` 完全忽略组件路 |
| `RECALL_COMPONENT_BUDGET_CHARS` | `6000` | 整个组件面的字符上限。各路自己的上限约束条数，这一项约束它们能占多少上下文。超出后相关度最低的条目先落下、长摘录按块边界裁剪——两者都写在面上，绝不静默 |

`COMPONENTS`、`PEOPLE_FAMILY` 与三项 `ATTENTION_*` 旋钮写在 engine 目录的 `engine.yaml` 里；两项召回旋钮写在 `recall/recall.yaml` 里。完整设计——组件是什么、可以填哪些面、怎么写一个——见 [design/index-components.zh-CN.md](../design/index-components.zh-CN.md)。启用一个组件，下次进程启动时加入它的闸门检查、outline 行和工具；停用则移除，正本不受影响——组件不持有知识，只有从它声明的底派生出来的结构。开启 `people` 后，人物页的 frontmatter 带逗号分隔的 `identities`（`scheme:value`；按来源契约的记录写成 `mailto:` / `im:` / `meeting:`）与 `aliases`。两者都属于文档的总览，随它整体写入（`rewrite_overview(fields=…)` / `set_fields`）——是快照，不是只增不减。关于它们有三件事在写入面与闸门被机械拒绝，且只针对本轮**动过**的页面——正文或 frontmatter 与本轮开头时不同，或页面是新建的（`people.identity_shape`、`people.identity_duplicate`、`people.identity_cospeakers`、`people.alias_collision`）：身份必须是 `scheme:value` 且至多绑定一个页面；在同一场对话里都发过言的两个「人的 id」是两个人，一个页面不能同时绑住它们——IM 的 `sender_id`、会议的 `speaker_id` 是「人的 id」，邮箱地址不是（一个人用两个地址写信再寻常不过，而 `email/v1` 不确立它们之间的任何同一性），所以邮件线程不贡献任何同场发言证据；别名不能是别人的名字（另一个人物页的别名、标题或 slug，或者来源为某个不在本页上的身份记下的显示名）。第四条规则是判断而不是事实，而且**只问一次**：凡是本次编译的来源里出现的人，全库为他报出的每一个称呼词，都必须在本轮结束前要么被记进该页的 `aliases`，要么被 `decline_alias(path, term, reason)` 否掉。一次否掉什么都不写——不写 claim，不写别名，不写字段，页面上不留一个字——因为正本记的是关于一个人已知的事，不是那些不属于他的名字；它只回答调用它的那一轮，哪里都不存。把问题关掉的是这一页**被写下**，判据是两件派生的事实：投影里的 `reported_since`（该「称呼词 → 身份」对第一次越过报出门槛的那一天），对上正本最后一次提交这一页的日子（`written_on`，一次限定在本族路径下的 `git log` 遍历）。在那一天当天或之后被提交过的页面，就是被摆到过这个问题面前的页面，从此不再问，不管它当时怎么决定；本轮新建的页面没有日期，投影里早于这一列的行也没有——两种未知都意味着要问。所以一轮否掉了却什么都没写，下一轮还会再问，这是对的：没提交，就没回答。还有第五种不属于任何页面：`people.not_ready` 会在全库镜像加载失败时拒绝这一轮，因为拿一座空文库去判上面那些事实，恰好会放行它们本来要拒的写入——什么都不写，下一次编译重新读。这样的镜像有两份，各自只被需要它的那一轮索要：来源边界（本轮写过声明了这些字段的人物页、或本轮来源里带着身份时才需要）与称呼词投影（只有那条称呼词决定真的适用时才需要），所以一次只写主题的编译，不会被一份它什么都不问的投影故障拒掉。另有一条运维须知：只要启用了任何组件，一个进程同一时刻只跑一次编译（框架从 `prepare` 一直锁到作业结束），因此部署应当靠增加 worker 进程来提高编译吞吐，而不是在一个进程里并发跑。编译模型得到 `find_person` 与 `decline_alias`；深召回得到 `enumerate_identities`（按需从该用户的 L0 来源元数据算出）与 `person_profile(alias, identity, section, offset, limit)`。两条快路都返回自己知道的全部——整页、整段区间——由框架先按问题排序，再把该路的上限花在这个顺序上（architecture §7）；两个深工具都分页，并在每次响应结尾给出取回其余部分的确切调用，因为在 agentic 通道里，上限绝不能是死路。`people` 还维护一份持久化投影（PG `component_people_terms`）：从对话结构读出的每个**称呼词 → 目标身份**对一行，带上它在全库范围的支持度。只有当一个称呼词攒够支持度、来自不止一份来源、且某个目标占了它总支持度的大部分时，才对该目标报出——靠集中度而不是频次，这正是把昵称和任何一个逗号前的短语分开的东西。报出的称呼词会带着完整分布出现在编译任务的每个来源下，也出现在 `enumerate_identities` 里每个身份旁边；这份来源自己重复了、但全库还撑不起来的词，标为 *emerging*。还有第三条更弱的线，列出这份来源里重复出现、又对不上任何在场身份的类名字词，不附带任何目标——那些没有任何轮次结构能指向某个人的提及。这些行随来源索引累加，且每份来源只累加一次：旁边还有一张清单表（`component_people_indexed`），与计数在同一个事务里认领，所以重投递的索引作业什么都不加——正因为这份幂等，归档来源的那一份贡献才能从 L0 重算出来、在读取时被精确减掉。计数早于这张清单表的老库，升级后第一次启动会做一次回填：把该库已有的每一份来源都记为已累加，因此已经计过的不会再计一遍；而那些其实什么都没贡献过的来源，要等到下一次重建才被计入。两张表都由 `scripts/ops/rebuild_derived.py` 从 L0 从零重新推导。每一行还带着 `reported_since`，即该对第一次越过报出门槛的那一天——那条只问一次的别名决定所用的时钟，写一次、此后不动，由同一次重建重新推导（早于这一列的行没有日期，会一直被问，直到一次重建把它填上）。它只保有这一张表；一次否掉哪里都不存。

开启 `time` 后，组件维护一份持久化投影（PG `component_time_blocks`）：每个 L0 块一行，记录该块的 UTC 瞬间，以及它落在**知识主体时区**里的哪一个日历日——就是 ingest 写进块所属章节的那一天，而不是 UTC 日期，因为对 +08:00 的主体来说，本地 00:00 到 08:00 之间发出的一切都带着前一天的 UTC 日期。每一行还记录它是在哪个时区下归一化的、那个时区从哪里来（`DEFAULT_TIMEZONE`、画像，或已注册的 provider），于是改动主体时区绝不会悄悄把两套日历混在一起：既有行照实说明自己是按什么建出来的，由 `scripts/ops/rebuild_derived.py` 显式重新推导。快召回得到 `timespan(since, until)` 一条路，深召回得到 `timeline(since, until, granularity, offset, limit)`（`granularity="verbatim"` 逐块读完某一天，而不是给出摘要）与 `as_of(date, alias, identity)`，编译任务里每个来源多出一行，说明它在所有者日历里的日期与钟点（来源自带时区与主体不同时，两个钟点并列）。所有日期参数都是主体时区里的 ISO `YYYY-MM-DD`：组件从不解析自然语言时间——路由轮能看到 `as_of` 与主体时区，会先把"上季度"解析成 ISO 日期；非 ISO 的参数会在回答的审计轨迹里变成一条 `invalid_args`，而不是一个悄悄不同的区间。

## 行为开关

| 配置 | 默认 | 含义 |
|---|---|---|
| `DEFAULT_TIMEZONE` | `UTC` | 画像未声明时区时统计"日历天"用的兜底时区 |
| `LOG_LEVEL` | `INFO` | 这套部署自己的日志有多响——`pneuma_knowledge_service`，以及站在库之上的应用启动引擎时点名的它自己的 logger。在组装引擎进程的那一处统一配置（`engine_process.configure_logging`），输出到 stderr，每行带上 logger 名字；uvicorn 保留自己的 handler，不会被重复打印。在此之前，worker 对一次无人值守轮次的交代（`round finished: exit 1`、`cooling until …`）发给了没人配置过的 logger，于是引擎日志里只有 `print()` 出来的行和 uvicorn 的 INFO。名字不认识就按 `INFO` 读，而不是拒绝启动。不是引擎旋钮 |
| `USER_SCHEMA_PACKS` | `true` | 每用户 schema pack 组合 |
| `USER_SCHEMA_MATRIX_PATH` | 未设 | 部署自带的 pack matrix JSON；未设用内置 |
| `CONTEXT_STREAM_RENDER_ROLES` | `true` | 摄入时渲染 owner/participant 标签 |
| `CONTEXT_STREAM_COMPILE_GUIDANCE` | `true` | 编译时注入按类型的指引 |
| `BRIEFING_CITATION_ALIAS` | `true` | briefing 里把真实 source id 别名成 `sNN` 句柄 |
| `WORKER_TENANTS` | （空） | 这个 worker 只处理哪些租户的作业，逗号分隔的 user id。留空即全部租户——一个 worker 对一套栈，与一直以来的行为完全一致。它存在是因为一个 Postgres 上可以放多个 library，而一个 library 就是一个租户（[single-machine-edition](../design/single-machine-edition.md) §11.7）：每个 library 的引擎进程注册自己的编译契约，worker 若认领了邻居的作业，那份知识就会在错误的契约下被编译。这道限制是认领查询里的一个谓词，绝不是「先认领再放回」——放回去的作业已经占用过那个租户唯一的在途名额。启动时的孤儿回收也用同一道边界：别的引擎手上 claimed 的作业是它正在跑的一轮，不是这个 worker 的孤儿。设置之后，worker 启动行里会把它明说一次。不是引擎旋钮（属于部署接线） |
| `CORS_ALLOW_ORIGIN_REGEX` | `https?://(localhost\|127\.0\.0\.1)(:\d+)?` | 设为空串完全关闭 CORS |

## 无前缀（直读）

| 变量 | 含义 |
|---|---|
| `OPENROUTER_API_KEY` | `openrouter:` 的对话与嵌入规格共用；实时上下文那条补充互联网搜索（`LIVE_WEB_SEARCH`）也用它，不需要第二个密钥 |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | 追踪；缺任意一个整体降级为空操作 |

## 仅脚本与 compose 读取（服务不读）

| 变量 | 默认 | 使用方 |
|---|---|---|
| `PNEUMA_KNOWLEDGE_API_HOST` / `_API_PORT` | `127.0.0.1` / `18000` | `scripts/dev-api.sh` |
| `PNEUMA_KNOWLEDGE_PG_PASSWORD` / `_MEILI_KEY` | `pneuma_knowledge` / — | `infra/docker-compose.yml` |

## 所有者档案来源标记

`pkc profile show [--json]` 展示每个可编辑字段及其来源标记，并识别占位档案。
`pkc profile set --field display_name="Chen Wan" --provenance inferred` 将字段值和标记一起写入
`persona/profile.yaml` 与持久化档案。YAML/JSON 输入可使用 `--file <path>`、`--file -` 或 `-`。
未显式指定标记时，携带 `PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH` 的进程写入 `inferred`，
其他进程写入 `owner`。`pkc profile confirm --field display_name` 只确认该字段；
`--all` 确认全部可编辑字段，均不改变字段值。

来源映射与 `--field` 使用相同的点分字段名，包括 `locale.timezone` 和
`preferences.response_language`。值为 `inferred`、`owner` 或 `placeholder`；已有的
`profile`、`deployment_default`、`unstated` 及旧地区键仍可读取，点分键优先于旧别名。
推断值在编译 system 文本中带有标记，全部为 owner 的档案保留原有渲染字节。
打开草稿时，占位或未确认档案会触发一条提示，但不会阻止本轮打开。档案编辑不写正本；
实质性证据仍通过 `pkc owner say` 进入。
