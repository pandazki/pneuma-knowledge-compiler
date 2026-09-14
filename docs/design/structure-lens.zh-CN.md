# 结构透镜——从外部读这座库的形状

[English](structure-lens.md) | **简体中文**

## 1. 为什么

Steward 在库内工作，一次一份源。每一次编译都是契约之下的一个局部决定，而每一个决定都可以是对的，总和却在漂移：一个项目页悄悄被会话叙述填满、一个演进页的带日期小节按摄入顺序而不是按时间到来、一个散落的标题把一页改了名、一个主题以两种写法存在两次、一族页面没有任何东西链接向它。这些没有一个是捏造——每条 claim 仍然引用着它的区间——也没有一个能从 Steward 站的位置看见。它们只能从外部被看见：一个把整座库一次收进眼里、带着框架自己对「什么是好的、可演进的知识布局」的看法、并且不关心任何一页是怎么变成现在这样的读者。

控制台的图谱视图是这个读者的第一次尝试，而它停在了仪表上：它数出死路页和无人抵达的页面，把最大的三个数字打出来。它没说一个数字让 Owner 付出什么，没说该做什么，也没有任何东西到达 Steward，于是同样的漂移在下一轮继续。本文用**结构透镜**取代它：一个派生的、无模型的正本库读者，它的产物是一份**报告**——一条条发现，每条带着它的证据、它的代价和它的建议动作——由 Owner 在控制台里读，也由任何人（Steward 也在内）在终端上读。

三条裁定定下形状：

- **一条发现是说给某个人听的，并且说出该做什么。** 每条发现点名它所关于的页面、展示它的那几句话或那几个数、它让一位读者或一次检索付出什么，以及一条带执行者的建议动作：常规一轮里的 Steward、作为一个决定的 Owner，或者机制本身。一个没有后果、也没有动作的数字不是发现。
- **能机械判定的东西在写入处被拒绝，绝不去劝。** claim 块里的一个标题、没有真实换行的正文、一个会遮蔽兄弟页的标题——透镜报告一座库已经持有的那些实例，闸门拒绝新的。劝模型别犯一个机械错误，正是框架禁止的那种劝说。
- **一条发现怎样到达 Steward，另行设计，等 Owner 读过这份报告之后再定。** 把一条发现放进另一个作业的上下文不是一个中性的动作：它改变模型写出的东西，在一个不是它选的界限之下，关于一页它可能根本没在读的页面。本版给 Steward 的是一个它可以主动查阅的面（`pkc lens`），没有任何它无法拒看的东西。强制点、被保留的回绝记录与 evolve 证据在 §9 里作为下一步设计勾勒出来，本版不做。

透镜是派生的，也是无模型的。它读正本与契约的 path templates，不向正本写任何东西，只从正本算出；本版不持有任何自己的状态。它是一个 core 模块，带两个读取面（一条 HTTP 路由和一个 CLI 命令）；成为一个索引组件是 §9 描述的那一步。

## 2. 透镜读什么

- 一个 ref 上的每一份正本文档（默认 HEAD；快照对比可用任意 ref），经由只读的正本面。归档文档不计入任何计数，只出现在它自己那条发现之下。
- 生效 skill 的 `path_templates`，用来认出各个族，并把一份已结卷（`<doc>/aNN.md`）折回它的当前页——与 `compile/patch.py::path_allowed` 和 `history_volume_owner` 是同一条规则。一个**主题**就是一个当前页加上它的各卷；一卷的 claim、字符与链接都归这个主题。
- **族角色**，按名字从模板派生：最后一段是 `overview.md` 的模板是这个族的枢纽；`evolution.md` 是编年页；名为 `features`、`decisions` 的目录（或 `features/{slug}.md` 之类）是子族；`owner/…` 是 Owner 的视图；`memory/people`、`memory/topics` 是记忆族。透镜只从这些角色、不从别的任何东西得知一份契约对一个族的期待；不带这些名字的契约只得到与族无关的那些透镜。角色是 `core/lens/families.py` 里的一张表，不是散文。
- 一条**边**是一个 href 以 `.md` 结尾的 markdown 链接，位于某个 claim 块内或总览区域内，相对文档所在目录解析，片段被剥掉；用的是闸门那个解析器（`compile/links.py`），而且是经由它来用。一卷的边被改记到它的主题名下；一个主题指向自己某一卷的链接不算边。
- 一条 **claim** 就是账本里的一个锚点，数法与 `canonical_glance.claim_count` 相同：总览块不是 claim。（旧的图谱视图把它们算了进去；透镜与 core 保持一致。）

## 3. 报告

```
Report
  ref                读取这份报告时所在的正本 ref
  read_at            ISO 时间（派生；不属于发现的 key）
  subjects, files, claims, edges         基础计数
  score              0–100，§3.3
  findings[]         Finding，按 §3.4 排序
  families[]         FamilyRow（name, pages, claims, share）   用于均衡表

Finding
  key          稳定 id："<lens>:<path or family>:<evidence hash>"——同样的证据，同样的 key
  lens         §4 里的某个 lens id
  level        "principle" | "drift" | "shape"
  actor        "steward" | "owner" | "mechanism"
  paths[]      它所关于的那些主题（当前页路径；一卷以它的页面命名）
  targets[]    牵涉到的其他路径（缺失的链接目标、那个孪生页……）
  evidence[]   只来自库里的逐字字符串——一条路径、一个标题、一个小节标题、一个
               日期、一个 href、一个 source id——≤ 5 条，每条 ≤ 200 字符；计数与
               份额是 `impact`/`action` 的字段，在那里被说出来，绝不裸列
  impact       {key, fields, text: {en, zh}}   它让人付出什么——目录键、它的字段，
               以及从目录在两种语言包下渲染出的那句话
  action       {key, fields, text: {en, zh}}   该做什么，说给 `actor` 听
  weight       0–1，它触及的基数占比（用于排序）
  decision     本版里是 null——留给 Steward 那条被保留的回绝（§9）
```

### 3.1 级别

- **shape**——一页的形态坏了，而写入机制本该拒绝它。actor 是 `mechanism`：点名现在拒绝它的那条闸门规则，并把已经存在的那个实例列出来等待修复。不要求 Steward 去判断它。
- **drift**——一页没有达到契约对它所属族的期待，而常规一轮就能在这一页上修好。actor 是 `steward`：这条 action 是写给 Steward 的，而本版里它只经由 `pkc lens` 到达（§5.2）。
- **principle**——这座库的布局错了，而没有任何单独一页能修好它：一个跨路径重复的主题、一个没有页面的族、一个别的页面都到不了的项目、一个什么都往里装的页面。actor 是 `owner`：控制台把它展示为一个归 Owner 的决定；它怎样变成一件 Steward 的任务属于 §9。

### 3.2 文案走目录

`impact` 与 `action` 是带具名字段的提示词目录键（`lens.<lens>.impact`、`lens.<lens>.action`）。报告携带的是已经渲染好的句子，英文来自目录，中文来自语言包（`text.en`、`text.zh`），于是控制台展示自己 locale 的那一句、自己不留任何副本；`pkc lens` 打印当前生效语言包的那一句。一份目录，一套措辞，所有面——一个经由 overlay 缝改写某个键的应用，改变的是每一个读者看到的东西。

### 3.3 分数

一个 Owner 可以在两次快照之间盯着看的数字，仅此而已：**没有任何未决发现点名的主题所占的份额**，取 0–100 的整数。被任何一条发现点名的主题——只要出现在 `paths` 里，不论级别——就不干净；一条 principle 发现会点名它所关于的每一页。它不是打分，也不是一个加权和：在一座有几百条发现的库上，加权和停在零、怎么都不动，而「基数里有多少是无事可修的」每修好一页就动一页。对比页签展示它的变化量，连同推动它的那些发现计数。

### 3.4 顺序

principle 在 drift 之前，drift 在 shape 之前；同一级别内按 `weight` 降序；再按 lens id；再按路径。控制台的头条——最先该做的三件事——取排名最高的三个**透镜**各自的第一条发现，每个透镜一条，于是三座孤岛绝不会把一个重复主题和一个形态坏掉的页面挤出去。

## 4. 各个透镜（v1）

每个透镜都是机械的、无模型的。这里点名的谓词就是谓词的全部。

### 4.1 可导航性

| id | level | 谓词 | 证据 |
|---|---|---|---|
| `nav.dead_end` | drift | 出度为 0 的主题 | — |
| `nav.arrival_blind` | drift | 入度为 0 的主题 | 它持有的 claim |
| `nav.dead_link` | shape | 一条指向没有任何文档占着的路径的链接 | 那个 href |
| `nav.hub_incomplete` | drift | 一个族枢纽（`overview.md`）没有链接到自己子树里的每一页（features、decisions、evolution） | 缺失的那些目标 |
| `nav.chronology_unlinked` | drift | 一个有 ≥ 3 个带日期小节的 `evolution.md`，在自己项目确实有 feature 或 decision 页面时，却不链接其中任何一个 | 子页数量 |
| `nav.decision_unlinked` | drift | 一个没有出向链接的 `decisions/*.md` 页面 | — |
| `nav.mention_unlinked` | drift | 一页的 claim 正文 N ≥ 3 次点名另一个活主题的确切标题（≥ 4 字符，且不是自己的），却从不链接它 | 那个标题，N |
| `nav.island` | principle | 一个项目目录，它的每一页都没有一条边通向或来自项目之外的任何页面 | 页面数、claim 数 |

`nav.dead_end` 与 `nav.arrival_blind` 各自是**对整座库的一条发现**（`paths` = 受影响的每一个主题，证据 = 那个计数与那个份额），而不是每页一条：它们自己说不出欠的是哪一条链接，所以每页一行不过是同一个数字重复一百遍。那四个契约角色透镜才是 action 点得出页面的那几个，而它们是每页一条发现。

### 4.2 身份

| id | level | 谓词 | 证据 |
|---|---|---|---|
| `id.title_duplicate` | principle | 两个活主题有相同的归一化标题（`normalize_title`） | 两条路径 |
| `id.title_child_collision` | shape | 一页的标题等于它自己子树里某一页的标题（那个取了某条 decision 名字的 evolution 页） | 子页路径 |
| `id.title_degenerate` | drift | 标题为空、只等于它的族角色词（`演进`、`Evolution`、`项目演进`、`Overview`……），或等于项目 slug | 那个标题 |
| `id.title_shared_with_hub` | drift | 一个 `evolution.md` 的标题等于它的 `overview.md` 的标题 | — |

### 4.3 形态

| id | level | 谓词 | 证据 |
|---|---|---|---|
| `form.collapsed_body` | shape | 一行正文 ≥ 1 000 字符，或正文含有两个字符 `\n` 超过两次、而真实换行比转义的还少 | 行长、计数 |
| `form.stray_heading` | shape | 一个 `# ` 行不是正文的第一个非空行 | 行号、那个标题 |
| `form.unanchored_citation` | shape | 账本里一行带着 `[cite: …]`、而它所在的块没有锚点 | 计数 |
| `form.overview_restates` | drift | 一个总览块的文字在剥掉引用与锚点之后，与同一页的某条账本 claim 逐字节相同 | 那个 slot |
| `form.legacy_sections` | drift | 一页有总览头，下面却仍然带着 `## definition|summary|introduction|connections` 小节 | 那些小节 |
| `form.definition_empty` | shape | 一个 `definition` 块没有散文（只有引用 / 锚点） | — |
| `form.unordered_chronology` | drift | 一个 `evolution.md` 的 `## YYYY-MM-DD` 小节不是升序，或者重复了某个日期 | 第一处倒置、重复项 |

### 4.4 集中度与均衡

| id | level | 谓词 | 证据 |
|---|---|---|---|
| `conc.catch_all` | principle | 一个主题持有 > 20 % 的 claim 且 > 均分份额的 3 倍，或者领先第二名 4 倍以上（≥ 5 个主题） | 份额、倍数 |
| `bal.family_heavy` | principle | 一个族的 claim 份额 ÷ 页面份额 ≥ 2 且 claim 份额 > 20 % | 两个份额 |
| `bal.family_empty` | principle | 一个声明了却没有页面的族 | 模板 |
| `bal.session_shaped` | drift | 一个主题 ≥ 60 % 的 claim 各自只引用一个源、并带着日期前缀（`YYYY-MM-DD，`）——把会话叙述当知识记下来的特征 | 份额 |

`bal.session_shaped` 是唯一一个启发式透镜；它的证据是数出来的、不是判出来的，而它的 action 是一个问题（「这个主题是一个项目，还是一份使用它的会话日志？」），不是一条指令。

### 4.5 佐证

| id | level | 谓词 | 证据 |
|---|---|---|---|
| `corr.single_source` | drift | 一个主题有 ≥ 8 条 claim，且全部引用同一个 source id | 那个 source id |

## 5. 两个面

### 5.1 控制台

`#/lens` 取代 `#/graph`（后者重定向；`#/graph/node/<id>` 仍然解析到它的文档）。一个视图，两个页签：

- **Reading**——分数，然后是**最先该做的三件事**：按 §3.4 排在最前的那些发现，每条一句话，加它的 impact、它的 action 与它的 actor；再往下是全部发现，按 principle / drift / shape 分组，带着页面（点进文档）与证据。
- **Compare**——两个 ref（HEAD、任意 commit、任意冻结快照）；分数变化量、基础计数变化量、按 key 算的已解决 / 新增 / 仍然未决的发现，以及每一条新边连同促成它的那句话。两侧同一个透镜，同一套模板。

报告来自服务（`GET /v1/users/{uid}/lens?at=`）；控制台自己不算任何东西，所以 Owner 看到的数字，就是一个跑 `pkc lens` 的 Steward 看到的数字。`lib/structureLens.ts` 只留下文库视图的邻域卡片需要的那部分。

### 5.2 `pkc lens`

`pkc lens [--path <doc>] [--json] [--at <ref>]` 在终端上渲染同一份报告——分数与计数，然后是按级别列出的那些发现，带着它们的页面、证据、impact 与 action；`--path` 收窄到一页。它是一个像 `pkc outline` 那样的读取面：没有任何东西替 Steward 调它，没有任何东西因它被拒绝，它说的话也不进入任何任务。

## 6. 机制从此拒绝什么

这些落在 core 的闸门与工具面上，与这个组件是否注册无关。每一条都有一个 `shape` 透镜，列出一座库已经持有的那些实例。

- `heading_in_block`——`append_block`、`edit_claim`、`supersede_claim` 以及每一个总览 slot 都拒绝含有以 `# ` 开头之行的文字；`create_document` 只在 `# ` 行是正文第一个非空行时接受它。
- `escaped_newlines`——一份正文或一个块的文字含有两个字符 `\n` 却不含任何真实换行，或者任何单行 ≥ 1 000 字符，在工具面被拒绝，消息点名这个毛病；它不会被悄悄当成一个块接受。
- **标题只能是打头的那个标题行。** `derived_title` 只在 `# ` 行是正文第一个非空行时才读它；出现在别处的标题就是文字。已结卷在任何读取面上都没有自己的标题：glance、提纲、dataset 与透镜都把它标作 `<owner title> · vol. NN`，来自它所属的那一页。一页的 `title:` 在含有 YAML 会读错的字符时以 YAML 引号写出。
- `retitle(path, title)`——一个新的写入动词，改写打头的那个 `# ` 行（这一页没有时插入一行），于是一个取错了名字的页面不必碰任何一条 claim 就能被给上对的名字；它像 `create_document` 一样过闸门的标题遮蔽检查，而闸门拒绝与某个活兄弟页相同的标题。它就是 `id.title_child_collision` 与 `form.stray_heading` 两个透镜所列页面的修复手段。

已经存在的已结卷保持逐字节不变：它们那些散落的标题被报告出来，它们的标题从所属的那一页读出，这就是它们需要的全部修复。

## 7. 各个面

- `GET /v1/users/{uid}/lens?at=<ref>` → `Report`（JSON，形状见 §3）。
- `pkc lens [--path <doc>] [--json] [--at <ref>]`——整份报告，或一页的那些发现。
- §4 里的那些阈值是透镜模块的常量，只命名一次，控制台不重复它们。本版没有设置项，没有表，也不注册组件。

## 8. 怎么衡量它

与每个组件同样的纪律：对一座固定的库，同一个 ref 下的报告逐字节稳定；评估集的 D 组（`navigability.reachability`）与透镜在死路页和无人抵达的页面上按构造一致（它们共用那个解析器和那条卷规则）。这些 note 是否改变 Steward 写出的东西，按任何质量主张的衡量方式衡量——同一 harness，开与不开这个组件各一遍——这里不作主张。

## 9. 下一步：触达 Steward（本版不做）

如果同样的漂移在下一轮继续，这份报告就没多大价值，而框架对「模型可靠做到的是被强制且被校验的那些事」的回答是一个强制点，不是一条 note。但一条被放进编译任务的发现，就是对 Steward 写出的东西的一次改动，它必须像一条契约条款那样被同等仔细地设计：究竟哪些发现可以进任务、用什么措辞、在什么界限之下、以及 Steward 的回答被记成什么。正在考虑的形状，等 Owner 对着一座真实的库读过本版的报告之后再定：

- 透镜成为一个索引组件（`lens`），由 `outline_tail` 为一个存在未决 drift 发现的页面至多带一行有界的文字；
- 闸门上为本轮写过的页面设一个强制点——满足这条发现，或者以一条理由回绝它——与 people 组件的 `alias_undecided` 同形，而这条回绝是一条**保留记录**（`component_lens_decisions`），也正是 §3 里预留的 `decision` 字段被填上的地方；
- principle 发现作为 `evolve_evidence`，用控制台自己的措辞；
- 控制台里一个「递给 Steward」的动作，只预填，绝不发送。

这些都不在当前版本里；一个 Steward 只有主动去要，才看得到这份报告。
