# 归档——不删除地退出关注

[English](archive.md) | **简体中文**

## 1. 为什么

一个用得够久的知识库，会积累起 Owner 已不再关心的知识：交付完的项目、弃用的供应商、解散的团队。这些知识没有任何*错误*——每条 claim 仍引用着源，每个源仍逐字保存——只是不再值得占一个回答的名额。放在原处，它就要每次检索都付代价：候选名额被它消耗，glance 列出它，compile 的 outline 把它当作可写的位置，一个关于当下的问题被过去回答。

框架禁止删除：canonical 是只追加的历史，L0 是逐字记录，所以「把它删掉」不是知识库拥有的操作。它拥有的是**归档**：Owner 把知识移到一个地方，它在那里保持完整、有引用、可寻址，而任何常规检索都不从那里读取。

收起知识不等于收起**主题**，这个区别就是下面的第四条裁定。离开回答集合的是页面与它的 claim；留下的是一份简短的归档记录，说明这个主题曾经在这里、Owner 把它收起来了。归档之后再问 Aurora，仍然会得到回答——「Aurora 是那个交付项目，覆盖一月到六月，拥有者在四号归档了它，因为团队解散」——而不是那一页，也不是什么都没有。

四条裁定定下形状：

- **归档是一次移动，不是一个标记，也不是一次删除。** canonical 文档被逐字节、连同 git 历史一起移到库内的一个根目录下；源保留全部 block，只多一个时间戳。两者都是这个状态的权威记录——所有派生层的重建都从它们读取状态，而不是从任何旁表。
- **默认排除，例外须声明。** 每个检索面——四条 lane、live context、compile 模型看到的库、源与文档列表——都排除归档，除非调用方声明 `include_archived`。声明包含的 lane 会给它展示的内容打标，归档永不被当作现状呈现。
- **先提案，再执行。** 知识是相互牵连的：文档引用源，源被文档引用。Owner 点名一件东西；框架计算随之而来的东西，把整个集合连同每一项的理由展示出来，在 Owner 对着那个确切的库状态确认那个确切的集合之前，什么都不移动。
- **主题以归档记录的方式离开，而不是以沉默的方式。** 一页就这么消失，会把它的主题一起带走——而库并没有停止提到这个主题：别的活页面仍链接向它，关于它的问题只能靠散落在邻居页面上的零星提及来回答，而没有任何一个面说得出「拥有者把它收起来了」。那是一个库无法给它打标的片面事实。所以那次移动会在活路径上留下一份**归档记录**（§2.3）：这个主题曾经是什么、它覆盖的时间跨度、它承载了多少、以及 Owner 的理由，并引用 Owner 自己的陈述。归档记录是普通的活知识——出现在 glance 里、被投影成 claim、默认被检索到——所以这个主题继续被回答，*以已归档的身份*。

这里的一切都不是 [architecture §5](../architecture.zh-CN.md#5-正本写入机制) 的轮转机制。轮转出来的卷是同一部著作的**已结卷**：一页活得够久就成为一部分卷的著作，已结卷与当前卷并置（`<doc>/aNN.md`），每条 lane 都照常索引、检索、列出它们——它们是活着的知识。归档是另一个问题——不是「这本书写长了」，而是「这个主题不再是我们的了」——一页进入归档时带着它的各卷。两者用词从不重叠：只有归档叫归档。

## 2. 思路：什么都不删

删除不是这个知识库拥有的操作。canonical 是只追加的历史，L0 是逐字记录，没有任何写入路径能移走一条 claim 或一个 block——归档也不新增这样一条路径。它改变的是**关注**，而一个没有删除的系统只能用一种方式改变关注：**两个权威标记，加上一个读取它们的默认值。**

**两个标记。** canonical 文档已归档，当且仅当它的路径位于 `archive/` 下；源已归档，当且仅当 `sources.archived_at` 非空。这就是状态的全部。两个标记都落在权威之上——git 库里的一条路径、L0 上的一列——所以没有任何旁表需要跟着对齐，每一个派生层都从它们读取状态（I2）。

**每个派生存储把这个标记作为它自己重新派生的一个字段携带。** L1 blocks、L2 chunks 与 L3 claim projection 各持有一个布尔值，由两个标记写出，也由 `rebuild_derived` 从同样这两个标记重新派生。这个字段存在，是为了让每个存储**自己的**搜索能在索引处排除归档：只靠后过滤，归档项会在回答看见任何活项之前吃光候选上限（80 条 claim、60 个 span）。

**每一次搜索默认排除它。** 每个存储用它自己的方言过滤——SQL 里的 `archived_at IS NULL`、Meilisearch 里的 `NOT archived = true`、Qdrant 里的 `must_not archived = true`——于是排除的代价是一个谓词，而不是一遍结果扫描；四条 lane、live context、compile 模型看到的库、源与文档列表，都由此继承这个默认。

**core 里再有一道后过滤，管两个索引产不出的那部分证据。** 检索不只是那两个索引：路由到的 component path 读自己的投影与 L0，briefing pack 由交给它的任何东西一次构建。所以各 lane 在证据组装时还施加一道无模型过滤，基于它们已经握有的两个权威事实——归档源 id 集合，与所得文档路径上的 `archive/` 前缀。同一道过滤还把每条 claim 钉在 lane 所得的文档集合上，从而封住归档 commit 与其后 L3 sync 之间的窗口（§3.9）。

**`include_archived` 是须声明的例外，并且会给它接纳的东西打标。** 一个布尔值，默认 `false`，出现在每个读取请求上（§4）。接纳归档的 lane 会把它排在活证据之后，并把 `archived` 标签带进 prompt 与线上响应，于是历史永远不会被读成现状。

**而只要归档还是空的，整套机制就是惰性的。** 归档源 id 集合为空时没有源落在里面，树里没有 `archive/` 时也没有路径以它开头，所以每一项检查本来就是空操作；唯一不是空操作的那部分——文档集合那道钉——在视图**活跃**之前被关掉（`ArchiveView.active`：L0 上出现一个归档源，或者树里出现一份归档文档）。什么都没归档的 Owner，在这个特性前后把同样的问题各问一遍，看不出任何差别。

**离开存储的是零；离开检索的是默认值。** 归档中的 claim 保留 anchor，归档中的源保留每一个 block，两者在按 id 寻址或被点名索取时照常回答。第 3 节逐个存储说明这件事在各处的代价。

### 2.1 文档标记：`archive/` 下的路径

库根多出一个保留目录 `archive/`。归档 `work/products/aurora.md` 即把它移到 `archive/work/products/aurora.md`；它的已结卷 `work/products/aurora/aNN.md` 移到 `archive/work/products/aurora/aNN.md`。取消归档就是同样的移回。

路径就是状态。`archive/` 在 core 里只声明一次（`domain/archive.py`），每个读者都从路径前缀推导「这是否已归档」，不依赖任何别的东西。这正是标记可重建的原因：`rebuild_derived` 读树，看见前缀。

为什么是移动而不是 frontmatter 标志。compile 模型通过 `set_fields` 与 `rewrite_overview` 写 frontmatter；放在那里的标志是又一个需要看守的保留键。而 `archive/` 下的路径在结构上就位于所有 contract 的 path templates 之外——模板是精确模式，contract 没有理由在那里声明一个 family——所以现有的 ownership 判定已经拒绝 `create_document` 写进去，而树的形状本身就把整件事讲给任何不带框架读仓库的人。

### 2.2 源标记：`archived_at`

`sources` 多一个可空列 `archived_at timestamptz`。block、结构图、媒体与 chunk manifest 都不动；`RawSource` 携带这个值。按 locator 取 L0 保持无条件（I3）：引用归档源的 claim 仍能解析到确切段落，`GET /sources/{id}` 仍然回答。变化的是搜索面——L1、L2——与列表默认值。

L0 这一侧不留下任何东西。源不是主题——它是材料——而让**主题**继续可被回答的那份归档记录（§2.3），是为关于它的那份文档写的。所以只含源的提案既不写归档记录，也不摄入陈述。

### 2.3 归档记录

移动页面把它收了起来。同时，仅凭这一步，主题也**消失**了，而这正是归档记录要修的那个失败：`work/atlas.md` 仍然链接向 `work/products/aurora.md`，关于 Aurora 的问题只能靠残留在邻居页面上的碎片来回答，而没有任何一个面说得出「拥有者把它收起来了」。所以把页面移到 `archive/<path>` 的那同一次 commit，会在 `<path>` 上写下一份简短的**归档记录**。

归档记录是**活的**。它在 glance 里，它的块被投影成 claim，每条 lane 默认检索到它，没有任何 lane 对它作特殊处理——于是「Aurora 后来怎么了？」得到的回答是*它曾经是 X；覆盖 A–B；拥有者在 D 归档了它，因为 R*，最后那一句带引用。它不可写：每个 compile 写入动词都拒绝它，gate 拒绝它上面的任何差异。

**机械的，没有模型。** 归档记录由 archive job 通过它自己的窄写入通道、带自己的闸门写出，与轮转写一份机器管理的文档完全同形（[architecture §5](../architecture.zh-CN.md#5-正本写入机制)）。每一个字节都从被归档的页面、Owner 自己的陈述和一个时钟派生；这个通道不写别的东西，同样输入渲染两次逐字节相同。

frontmatter：`doc_id`——**归档记录自己的**那个，由一个任何路径都不可能等于的键派生（`record_doc_id`）：这次移动往树里放进了两份文档，而仅由活路径派生的 id 正是被移走的那份副本已经带着的那个，`read(user, doc_id)` 就只能答出列举先碰到的那一份——`type: archived`、`slug`、`title`，外加 `archive_of: archive/<path>`（完整副本）、`archived_on: YYYY-MM-DD`、`archive_statement: <source_id>`，以及机器事实——`archive_span: <from>/<to>`（被引用的源都没有日期时不写这个键）、`archive_claims`、`archive_sources`、`archive_volumes`、`archive_inbound`。

正文：三个带锚点的块，锚点由**系统**按 `(path, slot)` 确定性派发——就是轮转那套派生，所以重建是空操作，且这些 id 在全仓库内唯一，包括与同一次 commit 写入的那份完整副本的锚点。

1. **这个主题曾经是什么。** 页面 overview 的 `definition`，逐字照搬，连同它自己的落点引用（它们指向的锚点现在住在 `archive/` 下，仍然全仓库唯一），后面接上标记「—— 已归档」。没有 definition 的页面改用它自己的第一条**在用**断言（`first_current_claim`）——同样逐字，连 `[cite: …]` 一起带过来，而**不是** glance 的那条 `ledger:` 行：那一行是展示文本，会把引用一并剥掉，而归档记录的块是要被投影成断言的，一句在路上被拿掉了出处的话，就是一句站在每个默认回答里的无落点断言（I4）。两者都没有的页面只用它的标题，而这**唯一**一种情况也是闸门的落点底线唯一豁免的那一种（`GROUNDING_EXEMPT`）——这样的页面里没有任何东西可供落点。没有任何东西是生成的：一份为一个已收起的主题编造句子的归档记录，正是这个框架在别处让其不可能发生的那种捏造。
2. **它承载了多少。** 一行机械的话：`覆盖 {from}–{to} · 账本 claim {claims} 条 · 源 {sources} 个 · 已结卷 {volumes} 卷 · 被活页链接 {inbound} 处`——带标签的数字，数字在后：这条通道里没有模型，无法随数量变形，而每个标签还得说清它数的是**哪一个**数（`claims` 是**账本**的数：这一页加上它的已结卷；库视图对同一页给出的那个数还把 overview 的投影块算进去）。时间跨度是这一页的 claim 所引用的源的 `occurred_on` 的最小/最大值（经由 `RawSource.occurred_on()`）；没有任何带日期的源时，这一节被省略而不是猜一个。`inbound` 统计正文链接到这个路径、且自己不在同一次 commit 里离开的活页面——而「离开」指的是 Owner **最终确认**的那个集合，所以 job 会在执行时用与提案预览同一个纯函数（`record_facts_in_move`）把每个数字重算一遍。`library_ref` 钉住的是**树**，所以从页面派生出来的东西不会漂；它对**集合**什么都没说，而把一个被另一个选中页面链接着的页面取消勾选，恰好改变那一页的 `inbound`。**这一块不引用任何来源**，而这个豁免是一条有名字的规则（`FACTS_EXEMPT`），不是缺口：它的出处是上面的 frontmatter，那里把这些数字每一个都作为机器字段带着，而闸门会核对两者一致。
3. **它为什么离开。** `拥有者于 {date} 归档：「{note}」`，引用 `[cite: <statement_sid> ¶0]`——Owner 的陈述，一个块，于是读者会引用回去的那一句，正是有证据托底的那一句。被引述的话是 ¶0 自己的话（`statement_quote`），绝不是在它旁边另打的一句——是那条 turn 的正文剥掉**角色标签**、并把空白折叠成一行，刻意不是逐字节照搬：标签是 `owner-dialogue/v1` 用来交代「谁在说」的框架，不是 Owner 打下的字，而留痕的块只有一行。一个字都不删。note 是 Owner 的散文，也就按散文对待：带着系统自己机械记号的 note——HTML 注释、`__AUTO__`——在 `plan` 与 `confirm` 处按编译闸门自己的判据被拒（`422 note_machinery`），因为这段文字会被插进一个会被投影成断言的块里；渲染器仍然做一次消毒（注释去掉，`[cite: …]` 降为纯文本，一个字都不删），这样即使是在那道拒绝存在之前写下的行，也无法把第二个引用塞进这个唯一带引用的块。

**陈述。** Owner 只通过说话作用于知识库（[Owner/Steward/Visitor §1](steward-owner-visitor.zh-CN.md#1-框架)），所以这个理由需要一份可引用的源。执行时，job 为每份提案摄入**一个** `owner-dialogue/v1` 源——一个 owner turn，承载确认时写下的 note，或者 Owner 什么都没写时那句点名了被归档标题的默认句——走常规的 `ingest_source_contract` 通道，只有一处覆盖：`canonical_treatment: none`、`semantic_indexing: full`。归档记录**就是**这份陈述的正本表达，在与移动同一次 commit 里机械地写出；对同一段文字再编译一次，只会让模型把这个决定改写到它以为自己碰到的任意页面上。这份契约的**每一个**字段都由**提案**派生——`dialogue_id`、turn id，以及 `said_at`（就是提案行的 `confirmed_at`，绝不是墙上时钟）——所以这一步跑两次构造出的是同一份契约，`ContentStore.add` 的 checksum 去重答出同一个 source id，而一个在摄入之后、写下 `statement_ref` 之前被杀死的 worker，重来时是把它已经做过的那份陈述重新派生出来，而不是铸造第二份。这个 id 在摄入之后、commit 之前立刻写到提案行上，于是续跑是引用它而不是重新派生它。这次回写以「行仍然是 `confirmed`」为前置条件，而前置条件**失手**会在任何东西移动之前否掉整个作业（`statement_ref_unsaved`）：继续走下去，会提交一份引用了这个决定并未点名的源的留痕，而终态写入会在同一个前置条件上同样失手、对此只字不提。

在规划时就提供了 `statement_ref` 的 Owner 已经说过话了：归档记录引用**那**份源，什么都不摄入。两种情况下这个 ref 都会被**核对**——在 `plan`，以及在执行时再核对一次——它必须属于这个用户、必须是 `owner_dialogue` 源、必须有一个 ¶0（`422`/`statement_unknown`、`statement_not_owner`）；在一份说着别的话的陈述旁边另给一条 note，会被拒绝而不是被悄悄调和（`statement_mismatch`）。陈述与归档记录说的是同一句话，因为一份引用了某个源、却引述了那个源没说过的话的归档记录，是一次带着引用的捏造。

**通道自己的闸门**（`archive/record.py: run_archive_record_gate`）全部硬拒绝，任何一条违规都导致什么都不写：三个锚点必须是本路径按槽位派发的那三个、且没有一个在仓库任何地方被占用；第三块引用陈述；第一块带着 definition 原本依托的每一个落点引用，**并且**本身有所依托（上面说的那唯一一种豁免除外）；没有任何一块的正文带着系统自己的机械记号，判据就是编译闸门自己那一个；每个机器字段齐备、`archive_of` 指向完整副本、每个写下的数字与第二块正文里说出的那个相等——而且是**双向**核对：先把机器字段与本次渲染所依据的 facts 对一遍，再把第二块从页面上**解析**回来，要求它就是这些字段渲染出的那一行，因为 `FACTS_EXEMPT` 承诺的是站在**页面上**的那一行的出处，而正文来自那个对象之外的任何地方，恰恰就是这条承诺要管的那一页；归档记录的 `doc_id` **就是**这条通道为这个路径派生出来的那一个（`record_doc_id`），且没有被树里任何别的文档占着——派生这一半才让占用那一半有意义，因为别处来的 id 很可能正是归档副本已经带着的那一个；`archive/` 下的副本与原本站在活路径上的页面逐字节相同——归档是移动，绝不是改写。

**在 compile 边界上**归档记录是**只读**的。每个写入动词在工具面拒绝它，gate 拒绝它上面的任何差异，两者都在 `archived_path` 类别下、使用归档记录自己的文案（「这个主题已归档，它的归档记录只读；要取回它，是拥有者取消归档的事」），并都以 `record` 这个码汇入 `archive_refusals`。它**会**出现在 outline 里，行文说明它是什么，`read_document` 在一条只读提示之下返回它——因为这正是一轮编译得知这个主题是**被收起**而不是从未存在的方式，也正是归档记录不被简单藏起来的全部理由。`list_documents` 列出它。归档记录与完整副本是两份文档、两个 id，所以 `read(user, doc_id)` 依然是一个只有一个答案的问题。路径遮蔽现在由归档记录的存在本身蕴含（活路径被占着）；标题遮蔽规则对其他 slug 依然成立，所以一个在自己路径上被拒的主题不会在下一个空闲 slug 上被重建。

**在 glance 上**归档记录是普通的活页面，只多一个尾标——与从归档接纳的项所带的 `archived` 标签相同，但它是从文档自身读出的，而不是由调用方要求的——于是一个正在决定读什么的读者会看到：这一页是一份归档记录，而不是主题本身。

**取消归档把归档记录换回它所代表的那一页**：一次 commit 里的 `git rm <path>` 加 `git mv archive/<path> <path>`，各卷一并回来。归档记录的锚点随它**退休**，与 overview 区域的锚点出于同一理由——它们不携带永久身份，而它们所代表的那份身份的页面已经回来了。projection 的丢失护栏会被明确告知这一点：job 向 `sync_projection` 传入 `retired_anchors`，这是 overview 之外第二道、也很窄的一道豁免，由**做了退休这件事的那个通道亲自声明**，而不是被推断出来的（别的任何消失仍然算丢失，仍然会被拒绝）。在自己的移动 commit 已经落地之后**续跑**的 job，会从 `library_ref` 那棵树上把这些锚点读出来：那些归档记录已经不在 HEAD 里、也不在新的 claim 集合里，规划时的那棵树是唯一还留着它们的地方，而少了这次读取，唯一还没跑的那一步恰好就是会拒绝的那一步。不摄入新的陈述：Owner 是在撤销一个决定，而不是在做第二个决定。

## 3. 逐个存储：要求与实现

| 存储 | 由什么承载状态 | 默认读取 | 由谁写入 |
|---|---|---|---|
| canonical（git 库） | 路径本身：`archive/<path>` | 只有活树（`live_documents`） | `move_documents`，一次 commit |
| L0（Postgres `sources`） | `archived_at timestamptz`，NULL 即活 | `list_sources_page`：`archived_at IS NULL` | `set_source_archived` |
| L1 blocks（Meilisearch `blocks_<uid>`） | 每个 block 文档上的 `archived: bool` | `NOT archived = true` | `index_blocks`；由 `update_documents` 翻转 |
| L2 chunks（Qdrant，`layer=chunk`） | payload 中的 `archived: bool` | `must_not archived = true` | `upsert_chunks`；由 `set_payload` 翻转 |
| L3 claims（Meili `claims_<uid>` + Qdrant `layer=claim` + PG `canonical_claims`） | 由 `document_path` 推导的 `archived: bool` | 同上两种过滤 | claim projection |
| component 投影（`time`、`people`、`attention`） | 什么都不承载——没有这个字段 | **读取**时对活集合作 join、减法或钉住 | 照旧从 L0 重建（I7） |
| 保留记录（`archive_proposals`、Owner 的陈述） | 决定本身，不是派生标志 | — | API 与 archive job |

下面每一小节说同样四件事：**要求**及它服务的不变量、满足它的**实现**、这个标记出现之前写下的**历史数据**如何表现，以及**由什么验证**。

### 3.1 canonical——git 库

**要求。** 路径就是权威标记（I2），所以移动必须真的是移动：逐字节、历史完整、一次 commit，且绝不留下半棵树。此后 `archive/` 下不得有任何变化，被腾空的活路径也不得被一次重写重新占据。

**实现。** `CanonicalStore.move_documents` 接收移动、写入与删除，并把它们作为**一次** commit 提交，带常规 skill trailer 外加 `Archive-Proposal: <id>`。归档是「移动 + 写入」（页面去 `archive/<path>`，归档记录落到移动刚刚腾出的活路径）；取消归档是「删除 + 移动」（归档记录出去，页面回来）。这个动词先删除、再移动、最后写入——这是两个方向都能表达自己、且磁盘上从不出现中间状态的唯一顺序——并拒绝写向一个在删除与移动之后依然存在的路径。`git mv` 让 `git log --follow` 一路读穿，frontmatter、正文、anchor 与 `doc_id` 都不动。每一次拒绝都由一次在 overlay 上**模拟整个序列**的预检在第一次重命名之前决定；中途失败只按逆序撤销本次调用做过的重命名、写入与删除，绝不整树重置。一次写入在**文件落到磁盘的那一刻**、即它的 `git add` **之前**，就被记为本次调用的产物——若记录放在 `add` 之后，一次失败的 `add` 会让回滚唯一的凭据对本次调用唯一可能写出的那个文件保持沉默，而下一个写者的 `add -A` 会把它裹进一次无关的 commit。队列并非唯一的写者——skill manifest 由 API 进程写出，不走队列——所以 adapter 为每个仓库持有一把 advisory 锁（`.git/pneuma.lock`），覆盖每一次改动序列的全程；多主机部署超出文件锁能串行化的范围，是已知残留。在这把锁之下，一个改动方法**入口处**的脏树只有一种解释——死掉的写者留下的残渣——所以它在那里被**回收**（`reset --hard HEAD` + `clean -fd`，从不触及 `.git`，每条路径以 WARNING 记录），而不是被拒绝：`commit_patch` 用 `add -A` 暂存，一次崩溃的归档留下的已暂存重命名否则就会搭上下一次无关 compile 的 commit。commit 之后、且在回滚够不到的地方，被这次移动腾空的目录会被清理。三条 gate 规则维持这棵树的状态，都是机械的，都在 `archived_path` 这个类别下：

- **compile 中 `archive/` 下的任何东西都不变。** 草稿在任何归档路径上与 base 不同的一轮被拒绝——与已结卷的 5b 检查同形。
- **归档路径遮蔽它的活路径。** 只要 `archive/work/products/aurora.md` 存在，`create_document("work/products/aurora.md")` 就在工具面和 gate 都被拒绝：文档的 id 由路径推导，两个文档一个 id 是一次移动绝不能产生的东西。主题靠取消归档回来，而不是靠重写。
- **归档标题遮蔽它的主题。** 路径换起来很便宜——在被遮蔽路径上吃到拒绝的模型会换一个 slug、用同一个名字把主题在活区重建。参考语料上实际观测到：`threads/small-group-invitation.md` 被归档后，模型新建了标题一字不差的 `threads/small-scale-invitation.md`。所以新建文档的归一化标题（NFKC、casefold、去空白与一组固定的分隔/终结标点——`#`、`&`、`+` 这类符号保留，`C#` 与 `C` 是两个主题）与任一归档文档标题相同时同样被拒绝，工具面与 gate 双重，拒绝文案点明两条合法出路：把确实新的事实记到它所属的活页上，或者不记——主题由 owner 取消归档来恢复。这是相等判定而非相似判定：改写过的标题在构造上就能绕过，所以拒绝同时也是一个**信号**——一轮里吃到的每次归档路径/归档标题拒绝都汇集在 compile 结果的 `archive_refusals` 上并写进 job 的完成详情，owner 能看到新材料正在触及某个归档主题，并据此决定。

compile 模型看不见归档。`PatchDraft` 仍持有每一份文档——anchor 连续性与全库唯一性是对整棵树判定的——但渲染进任务的 outline、`list_documents` 与 `read_document` 只覆盖活文档，读取归档路径得到的是拒绝而不是正文。groom 跳过归档文档。evolve 只枚举活文档，在分支上让 `archive/` 保持原样。

**历史数据。** 这里没有需要迁移的东西：状态就是那棵树，每次列出都现读，而一个没有 `archive/` 目录的库就是一个什么都没归档的库。比**归档记录**更早的情况按名字处理——取消归档只删除确实持有归档记录的路径（`_record_removals`），所以一份在归档记录出现之前被归档的页面回来时不删除任何东西，而那时规划的提案也不摄入陈述。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_git_canonical.py`（连卷带历史的移动、写到腾空路径上的归档记录、作为一次 commit 的取消归档、各种作用域受限的回滚、残渣回收、manifest 写入与移动互不吸收）、`packages/pneuma-knowledge-core/tests/test_archive_gate.py`（三条 `archived_path` 规则）与 `packages/pneuma-knowledge-service/tests/test_archive_other_writers.py`（groom、evolve 与 adopt 让归档保持原样）。

### 3.2 L0——Postgres `sources`

**要求。** L0 是逐字记录，它的可达性无条件（I3），所以这个标记可以改变一次**列表**和一个搜索面，但绝不能改变一个地址。它还必须是每个派生标志重新派生时所依据的权威（I2）。

**实现。** 一个可空列 `archived_at timestamptz`——NULL 是活的，时间戳是 Owner 收起这份材料的那一天。`PostgresStore.set_source_archived` 设置或清除它并返回该行现在的值；`archived_source_ids` 用一条查询读出这个用户的归档 id 集合，这正是每次检索的组装过滤只做一次的那次读取（§3.9）。可达性在不变量说的地方无条件成立：`get` 像返回任何源一样返回归档源（`RawSource.archived_at` 携带这个值），`fetch` 把 locator 解析到 block 区间时根本没有谓词，而 `list`——权威自己的枚举——什么都不隐藏，由它的读者去过滤。默认排除的那个面是**分页列表**：`list_sources_page` 在没有 `include_archived=True` 时追加 `archived_at IS NULL`，两种情况下每一行都带 `archived_at`，好让调用方给它展示的内容打标。还有一个谓词不关乎读而关乎写：`undigested_source_ids` 排除 `archived_at IS NOT NULL`，所以一个从未被编译的归档源不会再被提供给 `POST /compile`——Owner 已说明这份材料不是当下的，编译它会写出关于归档主题的活 claim。快照租户随行复制这一列（`copy_tenant`），于是冻结租户持有它源库当时的归档状态；`archive_proposals` 则刻意不复制，因为冻结租户拒绝一切写入，那里的提案永远无法被确认。

**历史数据。** 这一列由 `ALTER TABLE sources ADD COLUMN IF NOT EXISTS` 添加（schema 文件就是迁移），所以此列存在之前写下的每一行读作 NULL，也就是活的。不需要回填，也不需要任何重建，源就照旧回答。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`（`test_the_l0_mark_round_trips_and_leaves_reachability_alone`、`test_the_listing_excludes_the_archive_unless_the_call_says_otherwise`、`test_an_archived_source_is_not_offered_to_compile_again`）。

### 3.3 L1——Meilisearch blocks 索引

**要求。** 索引保持无条件（I3）：归档源像任何源一样被索引，回来时不需要重新索引。变化的是默认**搜索**，而且必须在索引处变——事后过滤会让归档先把候选上限花掉。

**实现。** 每个 block 文档携带 `archived: bool`，由 `index_blocks` 依调用方传入的 L0 标记写出。`set_source_archived` 在不重新索引正文的情况下翻转一个源：对 `index_blocks` 写下的确定性 id `{source_id}_{block_index}` 作一次**部分**更新（`update_documents` 是合并而非替换），一次请求，且不会扰动它没有提到的逐字文本（block 数量由调用方传入，因为一个源有多少 block 是 L0 说了算，这个索引是派生的，不被问）。`search` 在调用没有声明 `include_archived` 时传 `filter="NOT archived = true"`。这个表达式写成 `NOT … = true` 而非 `= false` 是有意的，并对 Meilisearch v1.11 实测验证过：完全**不带** `archived` 字段的文档会被 `NOT archived = true` **返回**，而被 `archived = false` **丢弃**。`filterable_attributes` 才是让这个过滤合法的东西——Meilisearch 对未配置字段的过滤是**报错**而不是忽略——所以 `blocks_<uid>` 声明 `["archived", "source_id"]`，`source_id` 与标志并列，好让翻转能按源寻址。而一个只**搜索**的进程（API，索引归 worker）否则就会拿索引碰巧被创建时的设置去过滤，所以读路径走 `_configure_for_read`：先探测存在性，于是一次搜索永不**创建**索引，再把设置应用到它找到的索引上。而只有一个 API 错误码意味着不存在——`index_not_found`。其余每个错误都向上抛，因为 `except MeilisearchApiError: return []` 会把鉴权失败或连接重置读成「这个用户什么都没索引」，然后当作库里没有词法材料来作答。

**历史数据。** 此字段存在之前写下的文档在这道过滤下读作**活的**，所以尚未重建派生层的部署照旧回答；而由旧版本创建的索引，会在本进程第一次读它时被应用上当前设置。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`（`test_meili_default_search_keeps_legacy_documents_and_drops_the_archive`、`test_meili_flips_one_source_without_touching_its_text`、`test_a_search_only_process_configures_an_index_an_older_build_created`）。

### 3.4 L2——Qdrant chunk 层

**要求。** 与 L1 相同：状态搭在点上，默认搜索在索引处排除它，而归档是关注的改变而非内容的改变——不得为了表达它而重新嵌入任何东西。

**实现。** `upsert_chunks` 依 L0 标记把 `archived` 写进 payload。`set_source_archived` 用 `set_payload` 合并这一个键，选择器是租户子句（I1）加 `source_id`，再减去 `layer = claim`：一条 claim 的归档状态是它**所属文档**路径的性质、由 projection 写出，所以按源寻址的翻转不得触及 claim 点，哪怕同租户里有 claim 引用了那个源。向量、逐字文本与字符 span 都不动。两处搜索都以 `must_not archived = true` 排除——与既有的 `must_not layer = claim` 同形，理由也相同。这里每一个被过滤点名的字段都是声明过的 payload 索引——`user_id`、`source_id`、`archived`、`layer`——而 `ensure_collection` 对**已存在**的 collection 也声明它们，不只对新建的：已经持有 collection 的部署早于此后新增的每一个索引，提前返回意味着最需要这个索引的 collection 恰恰永远拿不到它。`create_payload_index` 是幂等的，所以重复声明每次启动只多一次空操作调用。

**历史数据。** 此字段存在之前写下的点不带 `archived` 键，不匹配这个条件，因而保持**活的**——这正是子句写成 `must_not … = true` 而非正向 `must archived = false` 的原因。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`（`test_qdrant_archives_one_source_of_a_tenant_and_brings_it_back`、`test_qdrant_points_written_before_the_flag_existed_read_as_live`、`test_ensure_collection_declares_payload_indexes_on_an_existing_collection`）。

### 3.5 L3——claim projection

**要求。** 一条 claim 已归档当且仅当它的**页面**已归档，所以这个标志必须由文档路径、且只由文档路径派生（I2）——而一次**移动**不得被 projection 自己的护栏读成知识丢失。

**实现。** `project_snapshot_claims` 对 `archive/` 下文档的每条 claim 置 `archived = is_archived_path(doc.path)`；这个标志随一行进入 L3 的三个面——PG `canonical_claims.archived`、Meilisearch `claims_<uid>` 文档、Qdrant `layer=claim` payload——各由 §3.3 与 §3.4 里该存储自己的子句过滤。projection 不需要任何新东西来察觉一次移动：它的键是 `(document_path, anchor)`，所以归档 commit 之后的常规增量 sync 会在旧键下删除、在新键下 upsert 这份页面的 claim。丢失护栏按 **anchor** 而非按键计数（`_lost_anchors`），而 anchor 全仓库唯一且在移动中存活，所以归档一个库里最大的文档不丢失任何东西、也不会被拒绝——正是让轮转安全的那条性质。`archived` 是**两个**签名函数（`_claim_signature` / `_row_signature`）共有的字段，这才让一次只翻标志的 sync 真正到达索引，而不是报「未变」。唯一那道窄豁免是 `retired_anchors`：取消归档移走了归档记录，而它的三个块不携带永久身份，所以由 archive job 向 `sync_projection` **声明**这些 anchor，而不是由函数去推断——别的任何消失仍然算丢失，仍然会被拒绝。`claims_<uid>` 在 `archived` 之外声明 `document_path` 可过滤，于是归档的单位——一个页面——在这里像源在 blocks 索引里那样可寻址。

**历史数据。** `canonical_claims.archived` 是追加式的 `ADD COLUMN IF NOT EXISTS … NOT NULL DEFAULT false`，而 `_row_signature` 把缺失值读成 `False`，所以归档出现之前写下的行读作活的，一次重建会从路径重新派生出真相。

**由什么验证：** `packages/pneuma-knowledge-service/tests/test_projection_sync.py`（`test_archiving_a_page_re_keys_its_claims_and_is_not_a_loss`、`test_a_flag_flip_alone_still_reaches_the_indexes`）与 `tests/integration/test_archive_marks.py`（`test_meili_claims_exclude_the_archive_by_default`、`test_qdrant_claim_layer_excludes_the_archive_by_default`）。

### 3.6 component 投影——`time`、`people`、`attention`

**要求。** 没有 component 知道归档存在，也没有一个被给予 `include_archived`（I7）；它的投影仍然派生自全部 L0，并可从它声明的基质重建（I2）。但 component 的面返回的是**散文**——逐字 block 文本、身份、文档行——这些是框架的组装过滤事后无法涂抹的。所以每个面只能读库仍在展示的东西，而这个排除必须发生在下一层，也就是读取处。

**实现。** 三种形状，一条规则。

- **`time`。** 投影行带 `source_id`，所以排除是一次 join：`time_blocks_in_range` 里写着 `LEFT JOIN sources … AND s.archived_at IS NULL`。行本身保留每一个源，并从全部 L0 重建——归档是**读取**的性质，不是行的性质。（`LEFT JOIN` 加 `IS NULL` 也照旧保住源行已不在的投影 block。）
- **`people`。** `enumerate_identities` 是对活源的**封闭世界**枚举。称呼词表是唯一要付算术代价的地方：`component_people_terms` 是一张**累加**表，全库每个 `(term → target)` 对一行，所以它没有可 join 的源列，且它的主键就是那个对。但把它建起来的是加法，而加法可逆：归档源自己的贡献由写路径用的同一个纯函数 `term_rows` 从 L0 重新算出，并在**每一次读取**时被减掉（`subtract_term_rows`）。这件事之所以精确，只因为累加是每个源至多一次的——`component_people_indexed` 是那张 manifest，与计数在同一事务里以 `ON CONFLICT DO NOTHING` 认领，一个被加过两次的源会在每次排除它的读取里留下自己的一半。被归档完全解释掉的那个对是**被丢弃**而不是归零，并在取消归档时整个回来；计数被 clamp 在零而不是被信任。归档 id 集合每次调用读一次，重新计算的结果被缓存到这个集合本身变化为止。
- **`attention`。** 一条账本行是关于**过去某次**咨询的事实，寿命长过它所点名的页面，所以两个面都被钉在它们所得的文档上——deep 工具经 `recall_tools(..., documents=)`，fast path 经 `run(..., documents=)`，而没有拿到集合的调用则从只读 canonical 面读出**活树**。交来的集合也仍要再过滤一遍，因为这条规则是这个面的性质，而不是它调用方的性质。集合里没有的目标被**丢弃**而不是加注：这一块要被一轮 evolve 和一条 agentic lane 读，而两者都打不开的路径，两者都无法据以行动。

三者共有的一点是：读取失败被点名而不是被吞掉。一个在构建归档 id 集合中途抛错的存储，绝不能与一个本来就没有东西可建的存储无法区分，所以只有该方法的**缺席**——由 introspection 判定——才读作「没有归档」。

**历史数据。** 这三个投影都不新增字段，所以没有东西要迁移、要回填；每一个都由同一个 `rebuild_derived` 从 L0（use-side 投影还从保留的咨询记录）重建。`attention` 那道钉是这里唯一在未动过的库上**不是**空操作的规则——一条账本行可以点名一个后来被 compile 删除或改名的页面——所以它只在**完整**树里出现归档文档时才打开（`any_archived`），在那之前报告与它一贯的样子逐字节相同。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_component_time_pg.py`（`test_deep_timeline_excludes_archived_source_blocks`）、`tests/integration/test_component_people_pg.py`（`test_enumerate_identities_excludes_archived_sources`、`test_a_term_only_archived_sources_support_is_no_longer_reported`、`test_archiving_one_of_a_terms_sources_leaves_the_rest_of_its_support`）与 `tests/test_attention_component.py`（`test_the_report_names_no_page_that_is_in_the_archive`、`test_with_nothing_archived_the_report_is_byte_for_byte_the_one_it_always_was`）。

### 3.7 保留记录——提案与 Owner 的陈述

**要求。** Owner 提了什么、对着哪个库状态提的、他决定了什么，是一份**保留记录**（I2）：重建重放它、从不重写它，也没有任何东西去重算一个已经被回答过的决定。决定与执行它的 job 绝不能单独存在。

**实现。** `archive_proposals(user_id, proposal_id, action, seeds, items, library_ref, status, note, statement_ref, created_at, confirmed_at, executed_at, job_id, detail)`，主键 `(user_id, proposal_id)`，按用户以最新在前列出。`seeds` 与 `items` 是 jsonb，因为它们的形状属于规划器而不属于存储层；`library_ref` 是计算时的 canonical HEAD。生命周期是 `proposed → confirmed → executed | failed`，旁边还有 `dropped` 与 `stale`，而每一次转移都是带谓词的写：`confirm_archive_proposal` 在 `status = 'proposed'` 之下于**同一个事务**里翻转该行并插入 job，job id 只铸造一次并写进两张行；job 的终态写入以 `status = 'confirmed'` 为守卫。`stale` 在**读**时算出（`library_ref != HEAD`）而不是被扫出来，唯一**写**它的地方是那次拒绝 `409 stale` 的 confirm——完整的生命周期与理由见 §5。

Owner 的陈述是第二样被保留的东西，而它是一份普通的源而不是一行记录：每份提案一份 `owner-dialogue/v1` contract、一个 owner turn，走常规的 `ingest_source_contract` 摄入，`dialogue_id = proposal_id`，于是陈述与决定在统一寻址方案里互相指认。这份契约的每一个字段都是提案的函数，`said_at` 也是（就是该行的 `confirmed_at`），所以重试时契约还是同样的字节，checksum 去重返回同一个 source id——这份陈述是一件崩溃也复制不出第二份的保留物。唯一的覆盖是 intake plan（`STATEMENT_INTAKE`）：`canonical_treatment: none`，因为归档记录已经**就是**这份陈述的正本表达，而对同一段文字再编译一次只会让模型把这个决定改写到它以为自己碰到的页面上；`semantic_indexing: full`，因为这份陈述与任何 L0 一样是 L0——可搜索、可寻址、可引用。

**历史数据。** 在归档记录出现之前规划的提案，它的项上没有 `record` 字段；那么 job 既不写归档记录，也在「有归档记录要写」这个守卫下不摄入陈述——没有任何东西引用的陈述会是 Owner 从未要求过的 L0。同一个守卫也覆盖只含源的提案，那不是历史数据，而是同一种形状。

**由什么验证：** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`（`test_archive_proposals_are_kept_and_advance_without_losing_earlier_stages`、`test_the_lifecycle_predicate_lets_exactly_one_writer_win`、`test_the_confirm_writes_the_decision_and_its_job_in_one_transaction`、`test_a_confirm_that_loses_the_predicate_queues_nothing_at_all`）与 `packages/pneuma-knowledge-service/tests/test_archive_job.py`。

### 3.8 重建

**要求。** 每个派生存储里的每个归档标志都是派生的，所以 `scripts/ops/rebuild_derived.py` 必须只从两个权威标记就把它们全部恢复出来（I2）——而对一个归档没有变化的库，一次重建不得改变它回答的内容。

**实现。** L1 从 L0 重放这个标记：脚本先删掉该用户的词法索引，再逐源调用 `index_blocks(..., archived=raw.archived_at is not None)`，并报告其中有几个是归档的。L2 在 `upsert_chunks` 上同样处理，chunk 由语义策略从已存的 chunk manifest 重放，所以 L2 的重建是字节确定的。L3 完全不需要额外的东西——`rebuild_projection` 重新投影 canonical HEAD，每条 claim 的 `archived` 从它所属文档的路径读出。component 投影在同一趟里重新派生：作为一个 `recall_rebuild` job 入队并由脚本抽干，因而不会与该用户在飞的 `recall_projection` job 交错。

归档验证那次跑在 OPC 库上、含两份归档文档时的实测：`rebuild_derived` 之后，每个存储上的标志都被重新派生出来——Qdrant 29 个归档 point、Meilisearch 27 个归档 block 文档、15 个归档 claim 文档，以及两份归档页面各自的 `canonical_claims` 行。同一个 rag 查询在重建前后返回同样的 20 条命中、每条同样的 `(source_id, block_start, block_end)`、且**顺序**相同；全部差异只有三个 RRF 分数在小数点后第四位的移动，是单条 lane 内部的名次微移，被融合吸收了。两次的默认档都没有任何归档命中。

**历史数据。** 这一节**就是**本页其他各处「历史数据」的答案：存储早于归档的部署照旧正确回答，是因为每一道过滤都把缺失的标志读作活的（§3.3、§3.4、§3.5）；而跑一次 `rebuild_derived`，就把「读作活的」换成真正从两个标记派生出来的标志。

**由什么验证：** 上面各存储的重放（§3.2–§3.5）；`packages/pneuma-knowledge-service/tests/test_rebuild_derived_reachability.py` 验证 component 那一趟经队列覆盖到每个租户；`tests/integration/test_archive_e2e.py`（`test_one_confirmed_proposal_moves_a_subject_out_of_every_default_face`）在真实中间件上重新投影后再读一遍每个默认面。脚本本身是运维命令，端到端由一次验证运行而非由测试驱动。

### 3.9 core 里的后过滤，与那个让它不运行的开关

**索引过滤之外，core 里再有一道后过滤。** 检索不只是两个索引：路由到的 component path（`timespan`、`person`）读自己的投影与 L0，briefing pack 由交给它的任何东西一次构建。所以各 lane 还在证据组装时施加一道无模型过滤，基于它们已经握有的两个权威事实——归档源 id 集合（`ContentStore.archived_source_ids`）与所得文档路径上的 `archive/` 前缀。归档页上的 claim、归档源的 window 或 span、指向两者之一的 component 结果，都在那里被丢弃并计数，与 `hide_already_shown` 的计数方式相同。索引过滤让常见情况便宜；组装过滤让这个性质在证据来自任何地方时都成立，包括归档出现之前写成的 component。

同一道过滤还带一项机械检查：`document_path` 不在 lane 所得文档集合里的 claim 同样被丢弃，计入同一个 `archive_hidden` 数字。这封住了归档 commit 与其后 L3 sync 之间的窗口——被移动页面的行在 sync 落地前仍带着旧的活路径，sync 失败则一直带着——因为 lane 看不见的页面不是 lane 能展示的证据。有两条 lane 根本不携带文档集合，因而跳过这项检查：rag（它返回命中，而非对页面作答）与对已存 pack 的 briefing `ask`。回答 lane 则总是拿到集合；canonical 读不出来时，它们**拒绝**（`503 canonical_unavailable`），而不是无钉作答；Live Context 出于同样的理由跳过这一拍（`canonical_unavailable`）。

**两种"空"不是一回事，把它们读成一回事就会失败向开。** *没有文档集合*是 None，不钉任何东西。*空的*文档集合是一个集合，它说的是：回答所用的知识库里没有一页是这个 lane 可以展示的——于是钉到空集上，索引提出的每一条 claim 都被丢弃。这正是所有者归档掉最后一个活页面之后那个状态的正确读法：权威答案就是"没有"，而此时每一条仍带着旧活路径的 L3 行按构造都是陈旧的。因此服务端**总是**把集合交给回答 lane：`_glance_inputs` 无论多短都返回活文档列表。

**而读取**失败**既不是空集，也根本不是一个答案。** 一旦文档集合就是那道钉，因为 git 忙而拿不到集合的 lane 会放行每一条陈旧的行——正是这项检查存在的理由所指的那个结果——所以失败不被降级，而被拒绝。canonical 读取是 `_glance_inputs` 里唯一不属于辅助信息的一步：它抛出 `CanonicalUnavailable`，`POST /recall` 与 `/recall/stream` 都答以 `503 {"detail": …, "code": "canonical_unavailable"}`（流式路由在响应打开之前读 canonical，所以读不出的库在那里同样是一个状态码，而不是在已发出的 200 之上叙述一个 `error` 帧），对读不出的库构建 briefing 亦然。Live Context 以自己的方式作同一个拒绝：这一拍以 `canonical_unavailable` 跳过而不去检索，房间安静一轮。仍然失败向软的只有 glance 的其余部分——skill 或 pack 加载失败只让 glance 降级，文档照旧到达 lane。生产环境里，要么这道钉是开着的，要么这条 lane 根本没跑。

**而只要归档还是空的，整道过滤——连同那道钉——就是惰性的。** 在从未归档过任何东西的库里，其余每一项检查本来就已经是空操作：归档源 id 集合为空，没有源落在里面；树里没有 `archive/`，也就没有路径以它开头。那道钉是例外，而且是真的例外——它丢弃页面不在 lane 所得文档集合里的 claim，而这在完全没有归档的地方也会发生：一次编译恰好在回答组装期间落地，或者以历史版本 `at=` 钉住的集合去搜实时索引。但这道钉只为封住一个窗口而存在，即归档 commit 与其后 L3 sync 之间的窗口，而一个既无归档源、也无归档文档的库从未打开过这个窗口。所以过滤带一个开关：钉只在**活跃**视图上运行，而视图在出现第一个归档源（`ContentStore.archived_source_ids`）或第一份归档文档（由 `_glance_inputs` 从**完整**目录树上读出——它是唯一看得见这件事的那次读取——并以 `archive_active` 交给每条 lane）时变为活跃。这与 index component 守的是同一条纪律——未注册即不存在——也正是它让所有者可以在什么都没归档的前提下，把同样的问题在这个特性前后各问一遍，看不出任何差别。

**由什么验证：** `packages/pneuma-knowledge-core/tests/test_archive_recall.py`（每条 lane 上的丢弃与打标、component 的面、两种空、坏掉的存储，以及 `test_with_an_empty_archive_the_pin_is_off_on_every_lane` / `test_the_pin_turns_on_with_the_first_archived_document_or_source`）与 `packages/pneuma-knowledge-service/tests/test_archive_recall_routes.py`。

## 4. `include_archived`

一个布尔值，默认 `false`，出现在每个读取请求上：

| 面 | 位置 | 关（默认） | 开 |
|---|---|---|---|
| `POST /recall`（rag · fast · deep）、`/recall/stream` | `RecallIn.include_archived` | 索引与组装两处排除归档；glance 只覆盖活文档 | 归档 claim、window、派生 episode 摘要与 glance 条目被接纳，各带 `archived` 标签 |
| `POST /briefings` | `BriefingBuildIn.include_archived`，存进 scope | pack 只在活知识上构建 | 归档被接纳并打标；`ask` 继承 pack 的选择 |
| Live context | — | 始终排除 | 不提供：这里没人提问，一个房间默认不该被端上过去 |
| `GET /sources` | query `include_archived` | 省略归档源；每行都有 `SourceOut.archived_at` | 包含 |
| `GET /dataset` | — | 全部文档，记录上带 `archived: bool` | 由 console 决定如何展示归档 |
| 组件的 deep 工具 / fast 路径 | — | 只有活源 | 不提供 |
| Compile · groom · evolve | — | 只有活文档 | 不提供 |
| 归档记录（§2.3） | — | **始终包含**——它是一个活页面 | 不适用 |

最后一行是这张讲排除的表里唯一值得写明的例外：归档记录不在归档里，它是在活的这一侧**代表**归档站着的东西。没有 lane 过滤它，没有调用需要要求它，它带的 `archived` 标签是活知识上的一个标签——「这个主题已被收起」——而不是被接纳的归档项所穿的那个标签。

标签是 `superseded` 纪律的再次应用（[architecture §7](../architecture.zh-CN.md#7-检索)）：lane 从归档接纳的项排在活项之后，并把 `archived` 标签带进 prompt 与线上响应，被交付了历史的模型知道这一点，读回答的人也能看出哪是哪。

**在返回里，这个标记在每一张面上都是同一个名字。** 窗口和片段摘要带 `archived: bool`；被接纳的 claim 在自己的 `labels` 之外带同一个字段（`UsedClaimOut.archived`，由标签派生，绝不再从路径重算一遍）。三张面在同一份响应里一起到达，若 claim 那张要读得不一样，客户端最后只能自己去解析 `archive/` 前缀——那就是本节只想说一次的那条规则的第二份实现。

## 5. 提案

`POST /archive/proposals` 接收 Owner 的种子，返回计算出的集合：

```json
{
  "action": "archive",
  "documents": ["work/products/aurora.md"],
  "sources": [],
  "note": "Aurora 六月已交付；团队已解散。",
  "statement_ref": "src_…"
}
```

`statement_ref` 可选，指向 Owner 提出这一请求的那份 `owner-dialogue/v1` 源——当请求经由 Steward 而非 console 到来时，这是提案在统一寻址方案里的出处。

规划器（`archive/proposal.py`，纯 core）把整棵 canonical 树读一遍，解析每条 claim 的引用，计算闭包：

- **从一份文档出发。** 它的 claim 引用的每个源都是候选。一个不被选中集合之外任何活文档引用的源被**选中**；仍被别的活文档引用的源**列出但不选中**，并点名那些文档。
- **从一个源出发。** 引用它的每份活文档都是候选，附带**依赖度**：引用选中源的 claim 数除以全部 ledger claim 数（overview 块不计）。依赖度为 `1.0` 的文档被选中；更低的列出并附比率。
- 两条规则对选中集合迭代到不动点，所以一份在第二个源被选中后才变成完全依赖的文档也会被抓到。集合只增不减，计算必然终止，且是确定的——同一棵树与同样的种子逐字节产生同样的提案。
- 文档的已结卷是它那一项的一部分，绝不单独成项。
- `unarchive` 镜像上述：归档文档所引用的归档源是候选且被选中；源的归档文档是候选，当它们引用的所有源在移动后都将是活的时被选中。

每一项携带 `kind`（`document` / `source`）、`ref`、`title`、`role`（`seed` / `cascade`）、`selected` 与结构化的 `reason`（`cited_by_live: [...]`、`cited_by_archived: [...]`、`dependence: {cited, total}`、`note`），console 可以把理由渲染在复选框旁，Steward 也能读。

**两个 `cited_by_*` 字段各对应库的一侧，这个拆分不是修辞。** `cited_by_live` 回答「哪些**活**页面会失去这个源」——这是归档方向的问题，也是一个 `still_cited` 源被列出而不被选中的理由。`cited_by_archived` 回答「哪些**归档**页面把这个源一起带回来」——这是取消归档方向的问题，配它自己的 note `restored_with_page`。用一个字段承载两者，那份路径列表的含义就取决于 action，而一个正在决定要不要取消勾选的读者，会在一个写着「live」的名字下读到 `archive/…` 路径。因此 `note` 的词表是：`seed`、`orphaned`、`still_cited`、`restored_with_page`、`fully_dependent`、`partially_dependent`、`already_archived` / `already_live`（种子已经处在该动作要把它放到的状态里——列出，永不选中），以及 `unknown`。

`archive` 提案的**文档**项还多带一个字段：`record`（`{title, definition, span: [from, to] | null, claims, sources, volumes, inbound, reason}`）——这一页的归档记录将会说的话（§2.3），在这里算出来，好让 console 在任何东西移动之前预览每个复选框会创建的那一页。`reason` 就是归档记录第三块将会引述的那一行原文（note、所提供 `statement_ref` 的 ¶0，或那句默认句）：它是这一页里唯一一件关于**决定**而不是关于文档的事实，所以由这一层拍板，并在 confirm 换掉 note 时跟着走。job **引述**这条被保留下来的行，而不是从 note 重算一条，于是 Owner 确认的那一句和页面上的那一句在构造上就是同一个字符串。规划器为它多收一个输入 `source_occurrence: Mapping[source_id, occurred_on]`，由服务端从源清单里提供：一个源**关于**哪一天属于 L0，纯规划器不自行派生任何与日期有关的东西。`inbound` 排除本次计划自己要移动的页面——一个自己也要离开的页面留下的链接，不是归档记录被留下来握着的链接——这同时让这个数字在 confirm 唯一允许的那种覆盖下保持稳定。

这些数字是**预览**。`library_ref` 钉住了计算所依据的那棵树，对着别的 HEAD 的 confirm 会被拒绝，所以从页面派生出来的东西不会漂——但它对**集合**什么都没说，而 confirm 唯一允许的那种覆盖恰好改变集合：把一个被另一个选中页面链接着的页面取消勾选，会把那一页的 `inbound` 从「一个自己也要离开的链接」变成「一个归档记录被留下来握着的链接」。所以 job 在执行时用这份预览来自的同一个纯函数（`record_facts_in_move`）、对着最终选中的集合把每个事实重算一遍——一个定义、两个调用方，而那一页说的是这次 commit 即将改变的那棵树上为真的话。`unarchive` 的项不带 `record`：它是把归档记录**换回**归档记录所代表的那一页。

提案是**保留记录**：`archive_proposals(user_id, proposal_id, action, seeds, items, library_ref, status, note, statement_ref, created_at, confirmed_at, executed_at, job_id, detail)`。`library_ref` 是计算时的 canonical HEAD。

`POST /archive/proposals/{id}/confirm` 可选地逐项覆盖 `selected`——用于把一个被选中的项留在原处——并入队一个 `archive` job。要加入一个提案列出但未选中的项，做法是把它作为种子重新规划，让它自己的级联被计算而不是被跳过；console 在复选框被勾上时正是这么做的。当 HEAD 自规划以来已移动，它拒绝（`409 stale`）——对一个此后又编译过的库的预览，是对另一样东西的预览，Owner 重新规划。

**决定与它入队的 job 是同一个事务**，谓词是 `status = 'proposed'`（`PostgresStore.confirm_archive_proposal`）。这一次同时定下两件事。谓词决定这次转移——两个确认，或一个确认与一个 drop，只会有一个赢家，而不是一次移动排了两个 job，因为写之上的那次读根本分不出它们。而两半也无法单独存在：绝不会有一份 `confirmed` 却没有 job 的提案（一个没人执行、也没人报告的决定——它不是卡住，而是根本看不见），也绝不会有一个没人做过的决定的 job。job id 只铸造一次并写进两张行，因此不需要事后再挂一次，也就没有那第二次写入本会打开的、能让 worker 先跑完的窗口。失败会把两半一起回滚，所以这里没有补偿路径、也没有为补偿准备的短码：那是一次普通的 500，提案仍然开着。

confirm 的 `note` 有三种状态，也就按三种存：**缺省**（`None`）表示它什么都没说，规划时的 note 留着；**给了值**就替换掉；**给了空串**则是把它**清掉**，有意写入 NULL。存储层因此在值旁边多收一个 `note_given` 标志——`COALESCE` 拼不出「沉默」和「抹掉」的区别，而把后者读成前者，会让预览按默认句算出来、行里却还留着旧 note 供留痕引述。

note 与 `statement_ref` 在被打出来的地方就被核对。带着系统自己机械记号的 note 是 `422 note_machinery`；本库没有的 `statement_ref`、或者不是一份带可引述块的 `owner-dialogue/v1` 源，是 `422 statement_unknown` / `422 statement_not_owner`；与所点名陈述的 ¶0 说法不同的 note，是 `422 statement_mismatch`——归档记录引述的就是它引用的那个源，而在两者之间悄悄挑一个，等于框架替 Owner 决定他的意思。这四条在 `plan`、在 `confirm`、以及在 job 里各做一次：请求与执行之间隔着一条队列。

`POST /archive/proposals/{id}/drop` 关闭一个未执行的提案。`GET /archive` 列出当前归档中的东西：按路径列出的文档、它们的归档日期、`record_path` 以及归档记录陈述的那些事实（从它自己的 frontmatter 读出——没有任何东西存这个连接，因为归档记录的 `archive_of` 与那份副本本来就互相指着对方），以及带 `archived_at` 的源。

**被库甩在身后的提案读作 `stale`，而这是算出来的，不是扫出来的。** `proposed` 的意思是「仍在等待一个决定」，而一份预览着库已经走过的 HEAD 的行永远不可能被确认——把它显示成开着的，列表就会报告一些没人能做的决定，console 自己打开又取消的对话框也会在那里无限堆积。但 `library_ref != HEAD` 就是它的全部定义，而每一次读本来就同时握着这两半：所以 `GET /archive/proposals` 与 `GET /archive/proposals/{id}` 在一行仍存着 `proposed` 的记录之上，呈现状态 `stale`。没有任何东西替它们去写。一次扫除会是一次写，去和所有在飞的确认抢着说一件任何读者都能自己推出来的事，而且它还得对没人碰过的行下判断。

唯一**写**它的地方，是那次拒绝 `409 stale` 的 confirm：那一次调用是拿它拒绝时的 HEAD 做的比较，所以记录这次拒绝，是关于一个真的被尝试过的决定的事实。它在作答之前先把行移过去，并把移动后的提案放进错误体，好让只读到错误的 console 不至于仍握着一份 `proposed` 的副本。两种写法——存下来的 `stale`，还是算出来的那一个——都没有任何东西能确认它，Owner 可以 drop 掉它，这就是它身上剩下的全部可做之事。

## 6. 执行

`archive` job 像每个 canonical 写者一样跑在按用户的队列上，所以它永不与 compile 竞争（每用户单个在飞 job 就是单写者保证）。它重新核对 `library_ref` 与 HEAD，不一致则以 `stale` 失败，而不是对着 Owner 没见过的树移动——除非这份提案**自己的**移动 commit 已经在历史里。worker 若在移动 commit 与终态写入之间被杀掉，重启时这个 job 会被重新入队，它此时看到的漂移正是自己的成果；移动 commit 的 `Archive-Proposal` trailer 会指名说出这一点，于是 job 把这次移动记为 `already_landed`，接着把它后面的步骤跑完（那些步骤每一个都是幂等的），而不是对着一次已经立在树里的移动报 `stale`。恢复时搜索的是**自计划那次 ref 以来的整段区间**里属于这份提案的那次 commit，而不是只读 HEAD，所以一次落在它上面的 manifest 写入——`write_meta` 跑在 API 进程里，不走队列——不会把这个 job 搁浅。然后按序：

1. **Owner 的陈述**，在任何东西移动之前（§2.3）：每份提案一个 `owner-dialogue/v1` 源，走常规 contract 通道并以 `canonical_treatment: none` 摄入，它的 id 在同一步里、commit 之前写上提案行——于是崩溃后被重入队的 job 引用的是它已经摄入过的那份陈述，而不是再铸一份。契约本身由提案派生，`said_at` 也是，所以即使重试发生在那一行被写下之前，重新派生出来的仍是同样的字节，checksum 去重答出同一个 source id。以「有归档记录要写」为守卫，而这就是全部条件：只含源的提案，或者在归档记录出现之前规划的提案，都不摄入陈述，因为没有任何东西引用的陈述会是 Owner 从未要求过的 L0。Owner 在规划时自己给出的 `statement_ref` 被原样引用，什么都不摄入。
2. `CanonicalStore.move_documents`——一次 commit 移动每份选中文档及其卷，**并把归档记录写到移动刚刚腾出的那个活路径上**，带常规 skill trailer 外加 `Archive-Proposal: <id>`。归档是「移动 + 写入」；取消归档是「删除 + 移动」（归档记录出去，页面回到它的路径上）。两个方向都是一次 commit，因为归档记录与移动是同一个动作：页面已经离开而归档记录尚未到达的那棵树，正是整套机制存在要防止的那个状态。这个动词先删除、再移动、最后写入，并拒绝写向一个在删除与移动之后依然存在的路径——归档记录只会落在移动为它腾出的地方。中途失败只撤销本次调用做过的事——它做的重命名、它写的文件、它删的文件——绝不整树重置。队列并非唯一的写者——skill manifest 由 API 进程写出，不走队列——所以 git adapter 为每个仓库持有一把 advisory 锁（`.git/pneuma.lock`），覆盖每一次改动序列的全程，manifest 写入与移动再不会把对方已暂存的路径 commit 进自己那一次；多主机部署超出文件锁能串行化的范围，是已知残留。在这把锁之下，一个改动方法**入口处**的脏树只有一种解释——每个写者都会把自己写的东西 commit 掉，而锁排除了活着的并发写者——所以那是一个死掉的写者留下的残渣，会在那里被**回收**（`reset --hard` + `clean -fd`，每条路径以 WARNING 记录），而不是被拒绝。把它留着才是更糟的选项，而不是更安全的：`commit_patch` 用 `add -A` 暂存，所以一次崩溃的归档留下的已暂存重命名，否则就会搭上下一次无关 compile 的 commit，挂在它的 message 之下。
3. 为每个选中源设置（或清除）`sources.archived_at`。
4. 按源翻转 L1 与 L2 标志；从新 HEAD 同步 L3 projection——归档记录自己的块也正是这样到达 claim 索引的：它是一个活页面，所以这里不需要告诉 projection 它有什么特别。
5. 提案标记为 `executed` 并附 commit ref，或 `failed` 并附详情——详情仍记录 ref 与已落地的步骤，移动 commit 之后的失败对着它产生的树仍是可读的。`archive_records_written` 与 `archive_records_removed` 在**每一条路径**上都写出来，包括零、也包括续跑的那一次；续跑时这两个数由规划时的那棵树与已确认的集合重建出来，因为写下它们的那次 commit 已经在历史里了。
   两种终态写入都以 `status = confirmed` 为前提：在 job 运行期间挪动过这一行的任何东西，都拥有一份跑完的 job 不该覆盖的主张。confirm 那边则不需要同样的守卫来写 job id，因为那个 id 是与状态翻转同一条语句写下的——不存在一份 `confirmed` 的行还在等人告诉它属于哪个 job 的窗口，也就没有办法让一个跑得快的 worker 被一次记账写入拉回 `confirmed`。

快照租户（`kbsnap-` 前缀）拒绝整条路径，如同拒绝每一次写。

## 7. 这触及不变量的哪些部分

- **I1**——每个新端口方法与表都以 `user_id` 为首；Meilisearch 过滤搭在按用户的索引上，Qdrant 过滤在 adapter 内与租户子句合成。
- **I2**——两个标记落在两个权威上（canonical 里的路径、L0 上的列）；每个索引字段由它们派生，`rebuild_derived` 重新派生它；提案行是保留记录，永不重建。
- **I3**——按 locator 取 L0 与 L1 的*索引*保持无条件；归档改变的是搜索的默认值，而非按地址的可达性。
- **I4**——归档 claim 的引用与归档源的 span 仍是原来的地址；引用归档源的活 claim 仍能解析。
- **I5**——`include_archived` 改变组装的证据，永不改变 system message。
- **I7**——没有 component 知道归档；core 里的组装过滤是让 component 证据保持诚实的东西，component 的投影照旧重建。

## 8. 边界

归档是 Owner 对注意力的判断，框架只计算从引用关系机械地推出的东西。它不猜测某个主题已经沉寂——`attention` component 报告什么未被读到，由 Owner 或 Steward 读报告后提案。没有任何东西被移除：归档中的 claim 保留 anchor，归档中的源保留 block，两者在按 id 寻址或调用声明 `include_archived` 时照常回答。

而**主题**在没有任何调用声明什么的情况下也继续回答：归档记录（§2.3）是一个活页面，正是它让归档成为「库对某个主题的说法变了」，而不是「主题原来所在的位置多了一个洞」。归档从默认回答里拿走的是**细节**——每条 claim、每个 span、每一次跳进材料——从不拿走「这个主题存在过」「它是什么」「Owner 把它收起来了、为什么」。归档记录是能站在那里的最小的诚实之物，且在构造上有界：三个块，从页面、Owner 的陈述和一个日期派生，没有任何通道能把它撑大。
