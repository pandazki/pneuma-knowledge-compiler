# HTTP API

[English](http-api.md) | **简体中文**

约定：

- 所有业务路由都在 `/v1/users/{user_id}/…` 之下——租户隔离在路径里，不在 header 里。全局路由只有下面第一组。
- 对冻结快照租户的写入返回 **409**（全局处理器；冻结就是冻结）。`snapshot` 参数解析不到返回 **404**；快照尚未就绪返回 **409**——钉住的查询绝不静默回退到活数据。
- 校验错误返回 **422**（严格枚举、长度上限、契约的未知字段）。
- 游标是续读点，不是偏移量：`/snapshots` 沿上一页最后一个 ref 的祖先链继续，第一页之后新落的提交不会让后面的页错位。畸形或上下文不匹配的游标返回 **422**——绝不静默回到第一页。
- 服务起着的时候自带接口文档：Swagger UI 在 `/docs`，schema 在 `/openapi.json`。

## 全局

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/healthz` | 存活探针：`{status, version}` |
| GET | `/v1/users` | 有数据的 user id 列表（界面的用户切换器） |
| POST | `/v1/profile/generate` | 一句话 → 完整 `UserProfile` 草稿（LLM）；**不落库** |
| GET | `/v1/intake/archetypes` | 摄入原型注册表 |
| GET | `/v1/live-context/focuses`、`/v1/live-context/kinds` | Live Context 词表 |

## 画像

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/…/profile` | 持久化画像，没有则给确定性 mock |
| PUT | `/…/profile` | 部分字段合并（嵌套对象逐子字段合并）；服务端维护只追加的 `timezone_history`、强制 `source="user"`；非法枚举 → 422 |

## 原始材料（L0）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/sources/import` | 导入官方[输入契约](source-contracts.zh-CN.md)；包按边界展开，每个 source 一条 |
| POST | `/…/sources/document/preview` | 归一化 + 提议 IntakePlan，零副作用 |
| POST | `/…/sources/document` | 文档摄入（接受 `plan_override`） |
| POST | `/…/sources/conversation` | 会话摄入——**已弃用**，请改用契约 |
| GET | `/…/sources` | 目录，keyset 游标分页（`limit` 1–500、`cursor`、`query`、`kind`） |
| GET | `/…/sources/activity` | 摄入日历热力图（`offset_minutes` −840…840） |
| GET | `/…/sources/{source_id}` | 详情：元信息、结构图、blocks 与块级图片清单 |
| GET | `/…/sources/{source_id}/blocks/{block_index}/images/{image_id}` | 私有图片字节；校验 source/block/image 归属与已存摘要 |
| POST | `/…/sources/{source_id}/fetch` | 按 `locator` 逐字取 L0 原文 |
| GET | `/…/summary` | 工作区计数：sources、jobs、jobs_failed、documents、claims、snapshots |

## 检索

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/recall` | body `{query, mode: rag\|fast\|deep, limit, as_of?, snapshot?, answer_style?, evidence_strategy?: ranked\|select\|all, answer_format?: text\|structured, include_original_modalities?: ("image")[]}` |
| POST | `/…/recall/stream` | 三种模式皆可；SSE——通道运行途中发 `stage`（答题通道另有 `token`，deep 再多一个 `step`），最后 `done`（或 `error`） |

`rag` 返回 `{mode, hits, stages}`——融合后的命中列表（`source_id`、块区间、文本、路径、分数），以及找到它们花了多少时间。`fast`/`deep` 同时返回不含引用的语义正文 `answer_text` 与向后兼容的带引用 `answer`，以及其证据：`used_claims`、`used_episode_summaries`（fast）、`used_component_evidence`（fast）、`stages`、`used_windows`、`trail`（deep）、`citation_handles`（`sNN` → 真实 source id）、`documents_read`、`snapshot`、`token_usage`。每条 episode 摘要都带来源标题、发生时间、章节与精确块区间，并固定标记 `derived: true` / `verbatim: false`，让客户端不会把生成的 L2 压缩内容当成原文。两条答题通道都会回显 `mode` 与本次解析出的 `as_of`，以及 `glance_chars`——提示词里那份知识库概览的字符数，正本为空或读不出时为 0——和 `documents_read`，即整篇读过、而非按检索片段进来的文档（fast 走概览挑选，deep 走 `read_document`）。`glance_degraded` 只属于 fast，用来说明概览挑选是失败了（`timeout`/`error`）；跑过但一篇都没挑中，与这条通道里其他挑选一样仍是 null。

fast 调用方可以分别覆盖上下文编排和回答线格式。`evidence_strategy: "select"` 会增加一次串行的结构化 recall 模型调用，在宽断言、episode 摘要和 raw 窗口候选（以及已知 canonical 路径）之间选择受上限约束的组合；非法坐标会被丢弃，失败则回落 ranked 头部。`answer_format: "structured"` 将回答类型、回答正文和引用分开，只准入证据中真实出现过的精确引用区间。响应会回显候选数，以及加入安全锚点和依据回跳前模型实际选中的 claim、episode 与窗口数；同时回显 `evidence_strategy`、`evidence_selection_degraded`、`answer_format`、`answer_kind` 与 `answer_format_degraded`。`evidence_strategy: "all"` 不做选择调用：同一个候选池整体交给唯一一次回答调用，因此模型入选数保持为 0、`select` 阶段回报 `skipped`，唯一能裁剪上下文的是组装后上下文的字符上限——它以 `evidence_selection_degraded: "all:truncated"` 自报。在 `answer_format: "structured"` 下，这一档还会返回 `deliberation`：回答调用自己那段有界的证据审视，写在答案之前。它是模型关于证据的输出，不是证据、也不能当引用，其他路径上一律为 null。两个请求字段都只适用于 fast；rag/deep 会拒绝非空值。

组件路是第四个证据面，不是第五份排序列表。已启用的索引组件提供快路时（见[配置](configuration.zh-CN.md#索引组件)），fast 通道花掉一轮路由 tool call：这些路被绑成工具，recall 模型在一轮里发出零个或多个带结构化参数的调用（不循环），选中的路并发运行，与内建检索并排——内建那几面从不等它。`route_offered` 是那一轮见到的路名，`route_chosen` 是每次被采纳的调用，写成 `name({json 参数})`；`route_degraded` 只在路由调用本身失败时取 `timeout` 或 `error`——没有哪条路对得上这个问题、于是什么都不选，是正常结果，不是降级。一条路都没有提供时，路由调用根本不会发生：`route_offered` 为空、`route_degraded` 为 null，通道的消息与没有这道接缝时逐字节相同。这几个都是 fast 的响应字段；deep 只是让它们停在默认值，并不拒绝。

`used_component_evidence` 是这次查过什么的审计轨迹——每次被采纳的调用一条，每次无法采纳的调用也留一条，模型试过什么不会丢。每条带 `path`、路由选定的 `args`、这次查询贡献的 `claims` 与 `windows`，以及 `degraded`：`timeout`、`error`、`invalid_args`（工具名不认识，或参数过不了这条路的 schema），或 null。路返回自己知道的全部、由框架决定展示多少，所以每条也说明自己没展示什么：`dropped` 是被该路上限与字符预算挡下的候选数，`dropped_summary` 用 `(章节或日期, 条数)` 按相关度顺序把同一件事描述出来，`already_shown` 是排序面已经带着的那些——在这里隐去而不是重复一遍，这也是为什么一条排序面的断言可能带回 `used_claims[].labels` 里的 `via:<路名>`（路自己也可能附上机械标签，如 `current`、`superseded`）。组件面的结果从不进 RRF；它们每一条都是普通的断言锚点或 `source_id + 块区间`（I4），因此引用别名、结构化回答的准入校验与回显都原样适用。

`evidence_strategy: "select"` 下，组件面不绕过候选池，而是加入其中；`model_selected_component_items` 是选择器真正从中取走的条数（ranked 路径下为 0，那里这一面是按自己的标题渲染出来的，不供挑选；池子本身的计数不回显）。被选中的条目按它本来的身份渲染——断言进断言笔记，窗口进原文摘录——并带上 `via:<路名>` 标签，因此这一面不会以自己的标题再出现一次。无论走哪条路径，`used_component_evidence` 都会返回：查过什么的记录，不取决于上下文是怎么编排的。

`stages` 是这次回答各阶段的实测墙钟（毫秒），平铺成一个列表，用的是所在答题通道自己的词汇表。在 **fast** 里，这套词汇表是固定的，列表也按固定顺序返回——`plan`、`retrieve`（其后紧跟它的子项）、`route`、`rerank`、`select`、`assemble`、`answer`、`total`。每个阶段每次都在：没跑过的那个也会返回，只是 `status: "skipped"`、`ms: 0`，客户端因此能排出一条稳定的条带，并且分得清「没发生」和「不费时」。`status` 取 `ran`、`skipped` 或 `degraded`；降级的阶段在 `detail` 里带着这条通道自己的原因（`timeout`、`error`、`invalid_args`），与对应的 `*_degraded` 字段说的是同一件事。并发检索那一把的各条路是子项，用带点的名字表示（`retrieve.claims`、`retrieve.windows`、`retrieve.glance`，以及每条被路由选中的组件路一条 `retrieve.path:<路名>`）：子项各报各的耗时，而 `retrieve` 报的是这次并发的墙钟，所以子项相加会大于父项，`route`——同一把并发里的一次模型调用——也与它重叠。这正是要的效果：只有各路各自的时钟才说得出是哪条路慢。唯一的算术保证是 `total >= 其余任何一个阶段`。

在 **deep** 里没有固定词汇表可发：这次 agentic 循环走了几轮、伸手拿了哪些工具，本来就是这份计时要报的东西。列表就是这次运行自己的顺序——`turn:1`、`tool:search_claims`、`tool:read_document`、`turn:2`……最后是 `total`；工具预算耗尽、被迫补一次无工具的收尾调用时，会多出一个 `finalize`（`status: "degraded"`、`detail: "budget"`）。失败的工具调用是 `degraded` 并带上原因，无论它是抛了异常还是把失败写成了一句明说的回答。这里永远不会出现 `skipped`，因为不存在一张「本可以跑」的阶段清单。`total` 收口的是这个 **agentic 循环**；它之前的种子检索不是循环里的阶段，也就不在这个 total 之内。同一条算术保证依旧成立：`total >= 其余任何一个阶段`。

在 **rag** 里词汇表同样固定，而且是三者中最短的一套，因为这条通道根本不碰模型：`embed`（问题向量）、`retrieve`——其后紧跟子项 `retrieve.lexical` 与 `retrieve.vector`——`fuse`（RRF 融合以及由此生成的命中），`expand`（融合之后的重叠归并，即在两个重叠区间之间判定谁拥有那段可引用证据，以及取上限），最后 `total`。与 fast 那把并发不同，这两个子项是先后执行的，因此子项相加即等于父项，图上画成一条链是对的。调用方已经握有问题向量时，`embed` 返回 `skipped`。同一条算术保证依旧成立：`total >= 其余任何一个阶段`。

除耗时之外，一个阶段还可能带 **`preview`**：一个小对象，说明它拿到了什么、又产出了什么。耗时只说这个阶段慢，从不说它慢在**什么**上——`retrieve.claims 812ms` 这一行，无论那一面回了两条断言还是八十条，长得都一样。阶段没有可预览的东西时 `preview` 为 null——没跑过的阶段、没什么值得一瞥的阶段，或者版本更早的服务——这与「空对象」是两件事，绝不伪造成后者。这些键归阶段所有，不归线上协议：客户端拿到什么行就渲染什么行，通道长出一个新阶段不需要客户端跟着发版。

**预览说的是一个条目「是什么」，而不是它「是哪一个」。** 凡是阶段预览一串结果的地方，每一项都是一个对象，用同一套字段：先 `text`（该条目自己那句话的定长开头，markdown、`[cite:]` 区间与锚点均已剥去），再是它在哪（画布文档用 `doc`，原文段落用 `source` + `span`），最后 `id` 作为尾部标签：

```json
{"hits": 80, "items": [{"text": "试点在三月结束。", "doc": "试点", "id": "c1a2b3c4"}]}
```

一次工具调用按它本来的样子预览——`person(alias="…")`，参数就写在里面；一次选择则预览为每一面一句话（`claims 80 → 1, windows 60 → 0`），其下按面列出被选中的条目。

各阶段目前预览的内容：

| 阶段 | 键 |
|---|---|
| `plan` | `cap`、`queries`——规划轮写出的额外检索问法，原样 |
| `retrieve.claims` / `retrieve.windows` | `hits`、`items`（前 ≤5 项），断言那一面另加候选池 `pool` |
| `retrieve.glance` | `offered`、`cap`、`hits`、`items`——每个被选中的页面，标题之下是它的定义 |
| `retrieve.path:<路名>` | `call`（这次查找被调用时的样子，参数写在里面；被拒的那条带上原因）、`hits`、`items` |
| `route` | `tool_calls`——每条被选中的路渲染成一次调用；一条都没选时是一句 `"no path chosen — offered: person, timespan"`，点名它放弃的那些路 |
| `rerank` | `candidates`、`kept`、`top`（≤5 项）；组件那一趟另加 `component_*` 三项同名字段 |
| `select` | `faces`（`claims 80 → 1, episodes 52 → 0, windows 60 → 0`——没有候选的那一面不列）、被选中的条目分列在 `claims` / `episodes` / `windows` / `components` 下（合计 ≤10），展开了页面时另有 `documents`；选择调用失败时为 `chosen: "none"` |
| `assemble` | 各段的条数与字符数，跨几趟合并（`windows` / `window_chars`、`episode_summaries` / `episode_chars`、`provenance_passages` / `provenance_chars`、`images`），外加 `sections`——同样这些事实的一行写法：`claims 8 · windows 12 · episodes 4 · 11.5k chars` |
| `answer` | `format`、`turns`（结构化调用回退到文本契约时为 2）、`sections`、`input_chars` 及构成它的各面条数 |
| deep/ask `tool:<工具名>` | 模型写下的 `call`（参数写在里面）、`result_chars`、`result`（回来的东西 ≤120 字的开头，已转为展示文本）——回来了**多少**、开头说了什么，而不是结果本身 |
| deep/ask `turn:N` | 该轮发出的 `tool_calls`，同样按调用渲染；收尾轮为 `"none"` |
| 构建 `retrieve.claims` / `retrieve.passages` | `cap`、`hits`、`items` |
| 构建 `expand` | `passages` / `passage_chars`、`sources` / `source_chars` |
| 构建 `pack` | `documents`、`glance_chars`、`sections`、`pack_chars`、`budget_chars`、`prefix_chars` |
| rag `embed` | `dimensions` |
| rag `retrieve.lexical` / `retrieve.vector` | `candidates`、`hits`、`top`（≤5 项）；向量那一路另加 `raw` / `episode` |
| rag `fuse` / `expand` | `rankings` 或 `fused`，随后是 `hits` 与 `top` |

预览的上限是**机械的，且只有一处**：服务把序列化后的对象压在约 1 KB 以内，按逐级收紧的档位截断列表（被截的列表以 `…+N more` 收尾）、依固定顺序摘掉条目上的附饰（先 `id`，再 `span`，再 `doc` / `source`）、省略字符串，最后仍超标就从尾部丢键。**一个条目说了什么，比它旁边那个 id 活得久**：这个次序属于压缩机制本身，不是一条约定，所以预算再紧也不会花在 id 上而把话切掉。因此预览永远小到可以整体渲染，也永远不可能变成源文本离开知识库的第二条、无上限的通路——证据只经答案与其引用抵达读者。

每条 `trail` 记录都带着它所描述那次调用的 `ms`——与对应 `tool:<工具名>` 阶段报的是同一个数——而且是在这一步被推送出去之前就盖上的，所以客户端在 `/recall/stream` 上把 trail 一步步长出来时，渲染的是实测耗时，而不是靠两次到达的间隔估出来的。那条流最后的 `done` 事件会带上完整的 `stages` 列表：只有在那里，夹在各次工具调用之间的模型轮次才看得见。

### 边跑边看

每条真正花掉用户秒数的通道，都有一个 SSE 双生路由把过程讲出来：`POST /…/recall/stream`（三条检索通道）、`POST /…/briefings/stream`、`POST /…/briefings/{id}/ask/stream`。原有的普通路由一字未动。

三者共用一套事件词汇，各条通道只发自己有的那几种：

| 事件 | 载荷 | 含义 |
|---|---|---|
| `stage` | `{name, key, phase, at_ms, ms, status, detail, preview}` | 某个阶段开始（`phase: "start"`，`ms: null`、`preview: null`）或落定（`phase: "end"`，并带上它的 `preview`） |
| `token` | `{text}` | 模型正在写出的答案增量，按到达顺序追加——`mode: rag` 从不发送，那条通道不碰模型 |
| `step` | 一条 trail 记录 | 仅 deep recall——一次 agentic 工具调用，`ms` 已经盖好 |
| `done` | 该通道的完整结果 | 与同一请求走普通 POST 拿到的载荷逐字相同 |
| `error` | `{detail}` | 通道中途失败，随后流关闭 |

`stage` 事件出自与最终 `stages` 列表**同一批**测量点，所以边跑边画的那张图与 `done` 带回的耗时不可能对不上。`at_ms` 是服务端时钟上、自通道启动起算的毫秒数——它把这个事件放到通道的时间轴上，而不是计数器的起始值：一个在通道第 3 秒才开始的阶段，此刻已跑的时间是 0 而不是 3 秒。所以客户端应从帧到达的那一刻起算，`end` 事件再交回服务端真正测出的数。

`preview` 只搭 `end` 帧：`start` 什么都还没测到、也什么都还没产出，给它挂一个预览，就成了这一帧里唯一不是观测所得的值。那一帧上的对象与随 `done` 抵达的 `stages` 里的那一个出自同一个记录器，所以它们是一件事，而不是两件可能各说各话的事。

**结构化答案是以 JSON 的形式流出来的。** `answer_format: "structured"` 向 provider 要一个 JSON 对象，而 provider 就是逐 token 写这个对象，所以结构化通道的 `token` 增量是 `{"answer_kind":…,"answer":"…","citations":[…]}` 的碎片，而不是散文。要显示临时答案的客户端，应从这个半成品对象里把 `answer` 字符串读出来（残缺的转义——末尾一个 `\`、写了一半的 `\uXXXX`、代理对的一半——应扣住不显示，而该字符串闭合之后的内容都不是答案）；`text` 通道的增量本身就是散文，照原样显示即可。无论哪种，`done` 帧都会替换掉临时文本。路由不给这些帧打标签：缓冲区自己的首个字符就说明了形状，而格式由部署决定，不由请求决定。

`key` 标识的是一个**节点**，归通道所有而不归客户端。固定词汇（fast recall、briefing 构建）按名字累加——`assemble` 会被测多次却只是一个阶段——所以那里 `key == name`，同一 key 的后一条 `end` 覆盖前一条。agentic 通道则是追加：同一件工具被调两次就是两步，于是每步新铸一个 key（`tool:search_claims#3`）。客户端按 `key` 建节点、按 `name` 显示，就能同时对两种通道都正确，而不必知道自己在看哪一条。

凡是在通道启动之前就能判定的，一律是状态码而不是被讲述的失败：未知 mode、在 deep 模式里传 fast 专属开关、无 key 部署（503）、不存在的 briefing（404）。响应体一旦开始流，状态行就已经发出去了，此后的失败只能以 `error` 事件抵达。

`as_of` 是提问发生的时间，不是来源文档的时间。实时问题可以省略；历史回放必须传当时的、带时区的时间戳。scaffold CLI 使用同一契约：`./app.py ask '…' --as-of …`。

`include_original_modalities` 是查询 tool 对成本/注意力的显式选择，不是根据模型能力猜出来的部署默认值。它使用枚举列表，以便未来增加音频/视频时不改 tool 形状；当前唯一值是 `"image"`。纯文本问题保持空列表；只有必须直接视觉核验时才传 `["image"]`，例如判断画中是否出现某物、颜色、文字或布局。未要求原始媒体时，带标签的派生表示仍可使用。答案通过 `included_original_modalities` 与 `original_modality_counts` 回显实际带入的原始模态。原始媒体只适用于 `fast` 与 `deep`；`rag` 返回文本检索命中，非空列表会被拒绝。

Source 详情绝不暴露对象存储 key。每条图片清单只给 `image_id`、MIME 类型、SHA-256、大小、带标签的派生表示和 API URL。浏览器与引用抽屉经服务取这个 URL；S3/RustFS bucket 保持私有。

## 编译、任务、历史

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/compile` | 为每个未消化的 source 各入队一个编译任务（幂等） |
| GET | `/…/jobs` | 队列分页（`status`、`kind` 过滤） |
| GET | `/…/history` | patch、job、快照三类混排的统一时间线，带计数 |
| GET | `/…/history/activity` | 时间线日历 |

任务队列只存三种 status——`queued`、`claimed`、`done`——「失败」不在其中：被闸门驳回的编译和
提交成功的编译一样以 `done` 收尾，成败写在 `ok` 上。所以 `GET /…/jobs?status=` 在三个存储值之外
再接受两个派生名：

| `status=` | 选出 |
|---|---|
| `queued` / `claimed` / `done` | 存储值本身；`done` 仍然同时含两种结果 |
| `succeeded` | `done` 且 `ok=true`——该任务提交了 |
| `failed` | `done` 且 `ok=false`——该任务收尾但没有提交（闸门驳回、中止的一轮） |

`GET /…/summary` 以 `jobs_failed` 给出同一个集合的计数，于是「这个工作区的编译全在中止」不必翻
队列就能看见。`status` 会被绑进分页游标：翻页途中改它会返回 422，请从第一页重新提问。

## 快照——两个不同的概念

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/…/snapshots` | **正本版本历史**——只读浏览，免费 |
| GET | `/…/kb-snapshots` | **冻结租户副本**（状态 `creating`/`ready`/`failed`，带计数） |
| POST | `/…/kb-snapshots` | 冻结整座文库 → **202**，后台复制；`{label}` 必填 |
| DELETE | `/…/kb-snapshots/{id}` | 从各存储清除冻结副本；正本历史不动 |
| GET | `/…/dataset` | 正本 + 审计装配成界面的多视图数据（`at`、`audit`） |

`/dataset` 之所以存在，是因为文库/图谱视图合法地需要一个快照下的全部文档；正本适配器用一次 `git archive` 整树读出来供给它。

## Briefing

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/briefings` | 在钉住的快照上构建稳定证据包：`{query?, source_ids[], budget_chars, snapshot?}` |
| POST | `/…/briefings/stream` | 同一次构建，SSE——过程中发 `stage`，最后 `done` 带回同样的响应体 |
| GET | `/…/briefings` | 列表 |
| GET | `/…/briefings/{id}` | 读回单条：`{briefing_id, snapshot_ref, created_at, char_count, scope, text, stages}`——`text` 即证据包原文 |
| POST | `/…/briefings/{id}/ask` | 对已存证据包提问：`{question}` → 答案 + 引用 |
| POST | `/…/briefings/{id}/ask/stream` | 同一次提问，SSE——发 `stage` 与 `token`，最后 `done` |
| DELETE | `/…/briefings/{id}` | 删除 |

两条流式路由都遵循上面那套词汇。构建的那一行是在 `done` **之前**落库的，所以看到这一帧的客户端，一定能把这份 briefing 读回来。

两半都用 `stages` 报自己的耗时，形状与答题通道一致（`{name, ms, status, detail}`），但各自是各自那份活该有的样子。

**构建**是机械的——检索、扩展、拼装，全程没有模型调用——所以它有一套固定词汇表，并按固定顺序完整发出：`retrieve`（其后紧跟子项 `retrieve.claims` 与 `retrieve.passages`）、`expand`、`pack`、`total`。没跑过的阶段也在，只是 `status: "skipped"`、`ms: 0`，因此一个没有 `query` 那半的 scope 会明说，而不是让它从条带上消失。与 fast 通道那把并发检索不同，这里两次查询是先后执行的，因此子项相加即等于父项。`expand` 是把命中与锚定来源变成带出处的证据那一步（上下文窗口、材料卡、引用反查、L0 原文摘录），每锚定一个来源就累加一次；`pack` 是概览、片段拼接与预算截断。`total` 收口整个构建。

构建的这份耗时**与 briefing 一起持久化**，所以 `GET /…/briefings/{id}` 能把几周前那份证据包的耗时原样交回——是当时测出来的，从不事后重算。在这一列存在之前存下的 briefing 读回时是 `stages: []`，那是「没有记录」，不是「不费时」。

**提问**是一次 agentic 循环，报法与 deep 一致：列表就是这次运行自己的顺序——`turn:1`、`tool:search_knowledge`、`tool:fetch_verbatim`、`turn:2`……最后是 `total`；工具预算耗尽、被迫补一次无工具的收尾调用时会多出 `finalize`（`status: "degraded"`、`detail: "budget"`）；失败的工具调用是 `degraded` 并带原因，无论它是抛了异常，还是把失败写成一句明说的回答。每条 `verbatim_fetches` 记录都带着它自己那次调用的 `ms`，与对应的 `tool:fetch_verbatim` 阶段报的是同一个数。`total` 只收口**这次循环**：证据包是更早——可能是几天前——构建的，把它算进这次提问，等于把时间花在哪儿这件事说错了。两半都成立同一条算术保证：`total >= 其余任何一个阶段`。

## 演进与契约

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/evolve` | 触发一轮；已有草稿或在飞任务 → **409**（单飞） |
| GET | `/…/evolve` | 任务列表（先做惰性 TTL 清扫） |
| GET | `/…/evolve/{task_id}` | 评审载荷：提案、理由、`changed_files[{path, old_body, new_body}]`、`dropped[]` |
| POST | `/…/evolve/{task_id}/adopt` | 入队机械采纳 → **202**；非草稿态 → 409 |
| POST | `/…/evolve/{task_id}/drop` | 立即丢弃草稿 |
| GET | `/…/skill` | 当前生效的组合契约：版本、`content_hash`、`path_templates`、packs、claim 词表 |

## Live Context

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/live-context/stream` | 对一段转写窗口的一次性 SSE：每张存活卡片一条 `event: suggestion`，末尾 `done` 带这一拍做了什么 |
| WS | `/…/live-context/ws` | 长连接监听。客户端发 `config` / `turn` / `flush` / `reset` / `want_more` / `ping`；服务端发 `ready` / `suggestion` / `suggestion_detail` / `stats` / `error`（永不致命）/ `ping`（约 30 秒保活）。`reset` 表示对话被清空：会话丢掉待处理队列、上文尾巴、主体台账、已推送列表与 seq，作废在飞的那次评估，并回一帧新的 `ready`——策略不动。没有它，客户端的「清空对话」只清了自己那一半，清空前提到过的主体再被提起时会被判为 `already_mined`，而据以判断的那张卡已经没人看得见了。完整协议见 [`api/routes/live_context.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/live_context.py) 的模块 docstring |

投递出去的卡片带着两段文字、两个不同的作者，分开正是要点所在：`body` 是**引言**——一到两句话，猜测此刻这件事对这个读者为何重要，由挑选模型写出并被机械截断；`evidence` 是压在它下面的逐字断言文本与原文摘录，由检索结果机械渲染，没有任何人改写过。`subject` 指出这张卡片讲的是哪份正本文档或哪个来源；客户端在 `already_shown` 里把它带回来，于是重连不会把读者已经认识的主体再介绍一遍。

**两种引用形状，由 `kind` 说明是哪一种。** `concept` 与 `fact` 卡片带的是 `citations`——覆盖知识主体自己材料的那一套唯一寻址方案，`{source_id, block_start, block_end}`（I4）。`kind: "web"` 的卡片带的是 `web_citations`——`{title, url}`——因为它立在网页上而不是来源块上，而网址不是那套方案里的地址：它解析不到存储里的任何东西，也绝不该被硬塞进一个 `Citation`。一张卡永远只带其中一种，而两个字段都恒为列表，于是客户端是去读一个字段，而不是去嗅探。除此之外，两者的证据面完全一致：同样编号的行、同样折叠的段落，挑选阶段的引用子集也用同一条按编号取值的规则落在任一份清单上（子集为空或全部越界时回退为全部，而不是把卡片的出处剥光）。只有交互不同——来源区间在应用内打开，网址在新标签页打开——并且 `want_more` 在 web 卡上不可用：没有来源块可以逐字取回，也就没有可供展开的边界。

`stats`（WS，需显式开启）与 `done`（SSE）都带着这一拍的**处理记录**：`skipped`（投递时为 `""`，否则说明是哪道门关上的——发现阶段给的 `small_talk` / `already_mined` / `nothing_new`，或 `low_worth`、`no_plan`、`no_candidates`、`no_coverage`、`none_chosen`、`low_confidence`、`uncited`、`duplicate`、`unparsed`、`pick_failed` 之一）、`intent`、`worth`、`plan`（实际跑了哪些查询）、`rejected`（计划里指向未启用查询路的条目）、`candidates`（每条 `{index, kind, title, subject, origin, provenance, citations}`）、`chosen`、`web`（`{tier, searches, cost, pages}`，见下），以及 `stages`（`discover` / `retrieve` / `retrieve.semantic` / `retrieve.web` / `retrieve.path:<名字>` / `pick` / `total`，各带 `ms` 与 `status`）。`no_coverage` 是挑选阶段自己给的 `choice: 0`——它把每一张候选对着意图读过，没有一张覆盖它——刻意与 `low_confidence`（一个被压住的弱答案）和 `none_chosen`（一个畸形的编号）分开：这三者在一次沉默的拍子上看起来一模一样，含义却不同。`dropped` 仍在，是简报那一轮的四道闸门账；全量车道下它为空，对应的东西是 `skipped`。

`config` 与 `ready` 上的策略字段：`focus`、`min_confidence`（一个数字两道门——发现阶段的 `worth` 下限与挑选阶段的 `confidence` 下限）、`max_pending_turns`、`quiet_period`、`web_search`、`briefing_id`、`stats`。`web_search` 是在请求那条补充的互联网路；`ready` 回送的是**生效值**，因为部署自己也有一个答案（`PNEUMA_KNOWLEDGE_LIVE_WEB_SEARCH`），而一个请求了 `true` 却读回 `false` 的客户端，是被机械地告知了「不行」，而不是只能从「没有 web 卡片」里去推测。随后那一拍的 `web` 记录说明这条路做了什么：`tier` 是 `off`、`planned`（发现阶段规划了这次查询，于是它与知识库各面并发跑）或 `fallback`（发现阶段没规划，而知识库给出的候选池是空的，于是它在其后跑），并附上 `searches`、`cost` 与 `pages`——那几次搜索一共点名了多少个网页。`cost` 不为零而 `pages` 为 0，正是那个否则完全看不见的结局：一次搜索跑了、被计了费、却没有引用任何网页，于是它的回答在装配处就被拒绝，从来没有成为候选。`turn_window` 作为 `max_pending_turns` 的旧名被接受；`max_suggestions` 被接受并忽略——全量车道按构造每一拍只投递一张卡。

## 引擎控制台

按部署划分，不按用户：引擎目录是这套安装自己的配置，而不是某个租户的知识，路径里没有 `user_id`，因为这里能拿到的东西没有一样属于用户（不变量 I1 不受影响）。除非 `PNEUMA_KNOWLEDGE_ENGINE_DIR` 有值，否则每条路由都返回 **404**——没有采用这个概念的部署一点新界面也不会多出来。设计见 [design/engine-console.zh-CN.md](../design/engine-console.zh-CN.md)。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/v1/engine/schema` | 导出的引擎 schema：各阶段、各旋钮（env 名、默认值、枚举、生效语义、双语标签）、流水线连边 `edges`，以及四层访问路线 `access_routes` |
| GET | `/v1/engine/state` | `files`（引擎相对路径 → 内容）、`skipped`（路径 → 它为什么不在 `files` 里：过大、非 UTF-8、读不了——一个有名字的缺口，因为静默的缺口读起来就是一个空文件）、`values` 与 `resolution`（`<stage>.<key>` → 值 / `env`\|`engine`\|`default`）、`version`（`head`、`dirty`）。每次请求都重读磁盘；文档只出现在 `files` 里 |
| GET | `/v1/engine/file?path=…` | 单个引擎文件原样返回，不经任何解析——`/state` 解析不出来时的修复通道：`{path, content}`。寻址方式与 apply 完全一致（一种规范写法、必须在目录内、不含点文件）；什么都没有时 **404**，目录拒绝的路径或交不回文本的文件是 **400** |
| GET | `/v1/engine/history?limit=50` | 提交列表，最新在前：`sha`、`label`、`at`、`files` |
| GET | `/v1/engine/history/{sha}/files` | 某个版本当时的引擎文件：`{sha, files: {path: content}}`，走 `git show` 读对象库，不动 HEAD、也不动工作区。正是它让「撤销」变成一次普通 apply：把某个版本的内容载入草稿、复核、带标签 apply；没有 revert 原语，也不改写历史。`sha` 可以是缩写，返回时回显解析后的完整值。清单按与「读取目录」完全相同的寻址规则过滤（不含点文件、不含过大文件、不含非 UTF-8 文本），所以一个版本永远不会交出 apply 路径会拒收的内容。本仓库没有这个 sha 时 **404**，git 自己会求值的版本表达式（`HEAD~1`、`main@{yesterday}`）同样 **404**——这条路由解析的是提交 id，不是 git 的版本语法 |
| GET | `/v1/engine/prompts` | 提示词工作台的读取面：`{surfaces: [{id, group, kind: "assembled"\|"fragments", title{en,zh}, summary{en,zh}, note{en,zh}\|null, segments: [{key, label{en,zh}, context{en,zh}\|null, framework_text, override_text\|null, placeholders, shared_with}], assembled_framework, assembled_effective}]}`。一个**面**（surface）是由有序目录段组成的、模型可见的提示词——覆盖的单位仍然是目录键，理解的单位变成它落进去的那条提示词。`kind: "assembled"` 的面携带组装函数真正产出的字节（在 core 里被逐字节 pin）；`kind: "fragments"` 的面是模型**一次只收一条**的子句族（条件式引言、工具面、闸门的拒绝行）——两个组装字符串都是 `""`，因为把替代项拼起来会展示出模型从未收到过的文案，而每条子句自带 `context`：一句双语的适用语境（只有当子句在组装中的位置已经说明了这一点时才为 `null`）。解析对象是引擎目录磁盘上的覆盖文件（不是运行进程已注册的覆盖，也不是客户端未保存的草稿——草稿走普通 apply）。运行时占位符在组装文本里保持字面，并逐段报告；而 `note` 就是拦住读者把它当成最终消息的那句话：一段双语横幅，说明每次调用时框架会代入什么（当时生效的契约、主体档案）、哪一条子句是由旋钮挑出来的、以及有什么东西是随人类消息单独到达的。`null` 表示这些字节确实就是模型收到的原貌——14 个组装面里有 13 个带 note，碎片族则永远不带，因为它没有可加注的组装文本。覆盖文件解析不了时 **400**；另一个坏掉的阶段文件不会让这条路由失去答案 |
| POST | `/v1/engine/prompts/rewrite` | `{key, intent, locale: "zh"\|"en"}` → `{draft, notes}`——用部署的召回角色模型起草一段替换文案，输入包含这段文案在它所属面里的位置、紧邻前后段、**按引擎自己的语言包给出的**框架原文、当前生效的覆盖，以及它必须保留的插槽契约。写成哪种语言由语言包决定，而不是由 `locale` 决定（`locale` 只决定 `notes` 写给谁看），并且提示里点名了必须存活下来的术语，这样中文包就不会经由助手退化成英文行话。**绝不写盘**：草稿回到普通的「草稿 → 复核 → 带标签 apply」。部署无密钥时 **503**（浏览与编辑照常可用），提示词目录里没有这个键时 **400**，模型没给出可用文案时 **502** |
| POST | `/v1/engine/apply` | `{changes: [{path, content}], label, expected_head?}` → `{sha, effects: [{key, apply}]}`。先写文件，再以引擎仓库自己的身份**只提交这些路径**——目录里其余的脏东西仍然是脏的，也进不了这个版本。每个部署同时只有一次 apply 在跑。`expected_head` 对不上时 **409**（是读旧了，不是请求错了；`null`/不传 = 没有前置条件）。**400**：路径要逃出去或藏起来（穿越、绝对路径、点文件、符号链接逃逸）、不是文件的规范写法（`./x`、`x//y`）、形似密钥的内容、超过 512 KiB 引擎文件上限的内容、阶段未声明的键、超出枚举或类型不对的值（`int` 旋钮就是整数）、坏掉的 YAML、提示词目录里没有的覆盖键、丢掉或凭空多出原文未声明的具名插槽的覆盖、以及会让目录解析不成 settings 的变更集——全部在写第一个字节之前校验完。什么都没改的变更集不会造出提交，返回当前 head 且 effects 为空 |
