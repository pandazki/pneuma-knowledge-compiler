# Coding agent 模式——让 coding agent 充当 Steward

[English](coding-agent-mode.md) | **简体中文**

状态：设计稿；§11 第 1 到 4 步已在 feature 分支实现——draft 状态形式、`pkc draft`、`open`/`finish`
生命周期、字节相等；`RoundRunner` 抽取、把 `agent:<后端>` 作为模型规格、worker 在它之下的行为、
过程视图里「等 Steward」这一状态；每条命令的写后自检、`pkc draft check` 与 `pkc library check`、
带 `pkc recall --evidence` 及其交接的读命令、`pkc owner say` 和 `pkc ingest`；以及现在的技能包——
后端清单、生成器、`pkc skill install / verify / show`、`pkc:start` 块、`Executor-Skill:` trailer、
脚手架里「谁来编译」这一问，以及引擎 apply 时的重新安装；再往后是后端本身——活性探针与
`pkc skill probe`、无人值守启动器（超时、退避、每作业独立的密闭配置目录、被收割的进程组、从
harness 自己的 JSON 读用量）、agent 轮次执行器与 worker 的无人值守姿态，以及 `open` 的 trailer
审计。以及现在的控制台 Steward 视图（第 5b 步）：`WS /v1/users/{id}/steward` 这座桥与它的 `GET`、
API 进程里每位所有者一场的活 harness 会话、把两条线归一为一套事件词汇的两个协议适配器（Codex 的
app-server JSON-RPC 与 Claude Code 的 stream-json）、所有者视角下渲染它的 Steward 视图、让版次 /
工序 / 来源三视图在 Steward 还在打字时就动起来的那次失效，以及 `pkc owner say` 上的逐字校验。
以及现在这道门上的归档（第 5c 步）：`pkc archive propose / confirm / ls / show / drop /
inventory` 跑在上游的归档服务之上、每一条会列举或检索的读命令上的 `--include-archived`，以及
skill 里属于它自己的那一节。先读 [steward-owner-visitor.zh-CN.md](steward-owner-visitor.zh-CN.md)：
本页是给 Steward 这个角色安上一具身体，所有内容都建立在那个框架之上。

## 0. 为什么有这一页

框架里每一次模型调用今天都走 langchain：service 按 `engine.yaml` 里的角色装配一个
`BaseChatModel`。Coding agent——Claude Code、Codex——已经强到能做同样的工作，而且带来两样
API 模型没有的东西：所有者自己的订阅，以及那个订阅能到达的任何模型。知识库对此毫不在意。
它的权威是 L0 和正本，它的归因写的是契约、措辞和组件，从来没有声称记录模型
（[architecture §6](../architecture.zh-CN.md)），Steward 框架也早已裁定"Steward 用哪个模型是
Steward 自己的事"。所以*由谁执行一轮模型调用*是 Steward 内部的选择，本页设计的就是 Steward
可以拥有的第二具身体：**一个 coding agent，由生成的 skill 教导，通过框架自己的 CLI 行事**。

三条裁定先把形状定住，再谈机制：

- **门是 CLI，不是协议。** agent 通过 `pkc`——框架的命令行面——触达一切，skill 教它这张脸。
  不做 MCP server：coding agent 天然会跑命令读输出，而 CLI 是每个 harness 都有的那一面。
- **Steward 读一切、写一门。** 作为知识库的 Steward，agent 可以读任何 L0 块、任何索引、任何正本
  页面、任何保留的记录。它写正本只走 langchain 编译用的同一份 claim 级 draft，过同一道 gate。
  上下文完整是机制不是请求：这道门拒绝对本轮未读过的页面的写入。
- **先做 Codex 和 Claude Code，其中 Codex 更先。** Kimi 的无头模式尚不能承载结构化流程，也不报
  token 拆分，第一版不做。早期测试围绕 Codex。

## 1. 角色，以及推动每个角色的动机

框架命名了三个角色；一套部署还有第四个，一个人全干时框架把它折进所有者。下面的故事都对着
这些动机写，§5 起的每个机制都能回溯到一条故事（§12）。

### 所有者（Owner）

知识库为之存在的人。提供材料、陈述意图、校准。

| | 动机 | "好"是什么感觉 |
|---|---|---|
| O1 | 不学机器就从原始材料**建出**一座可信的库 | "我把 agent 指向我的数据，一个下午就有了库" |
| O2 | **看懂**库知道什么、怎么组织的 | 一眼概览、一页、一段历史，形状讲得通 |
| O3 | **提问**，得到引证据的回答 | 回答说出自哪里，引用能解析 |
| O4 | 靠*告诉* Steward 来**订正**任何错处——一个事实、一个状态、一处归档、一个名字，并看到它带着来源落地 | "我说金额是 5,400，页面现在就是 5,400，旧数字留作历史" |
| O5 | **塑造**记什么、怎么记——契约、族、结构 | 库在分支上重组，我读 diff，我采纳 |
| O6 | 不用盯着也**活着**：新材料按时编译，并被告知变了什么 | 早上一份简报，而不是一早上的活 |
| O7 | **自选模型和账单**：用我的订阅、用更好的模型、以后再换、什么都不丢 | "我从 API key 换到 Codex，库没察觉" |
| O8 | **信任与审计**：每条 claim 有引用、每次变更有日期、每个问题有记录、坏编译能回滚 | 库里没有任何东西是没留痕进来的 |
| O9 | **私密**：数据留在本机，只有模型提供方看到片段，agent 不外泄 | 安装时一句话，之后一直成立 |
| O10 | **委派常设工作**："每天早上从这个 IM 拉昨天的对话、从这几个人那里拉邮件，分别存成这几座库"——不等框架长出连接器，随时可撤销 | 我把例程说一遍，Steward 就跑；停掉是一句话 |
| O11 | **退役不再成立的知识**：结束的项目、错了的主题——移出当前图景，留作历史 | 页面被归档、有日期，不是删除，且不再浮现 |
| O12 | **在库所在之处与 Steward 对话**：控制台里一场对话，用我的话，一边看它对库做了什么 | 我在聊天里说了，Steward 还在打字，历史视图已经动了 |

### Steward

编译、答复、起草演进、整理的代理。本设计中它的身体是跑在所有者账户下的 coding agent。它的
动机是它把活干好所需的条件。

| | 动机 | 缺了会怎样 |
|---|---|---|
| S1 | **写之前上下文完整**：契约、outline、本次作业的来源、即将触碰的页面 | claim 归错页，改写一个从未读过的状态 |
| S2 | **在写入处就被拒绝的门**，并说明错在哪 | 整轮花完 gate 才说不行 |
| S3 | **读得到一切**：L0 逐字、L1/L2 检索、正本、glance、咨询记录、编译事件、作业 | 只凭恰好被展示的东西作答 |
| S4 | **掌握自己的一轮**：领活、知预算、知欠账、finish、修复 | 不知道何时算完 |
| S5 | **把所有者的话变成动作**：陈述变成有引用的来源和一次编译；意图变成契约草案；无论所有者怎么措辞都不绕门 | "直接改掉"写出一条无引用的 claim |
| S6 | **汇报**做了什么、没做成什么、花了多少 | 所有者去翻 git 才知道 |
| S7 | **两种姿态同一双手**——陪着所有者，或无人值守跑队列 | 两套工具面、两种行为 |
| S8 | **每次行动之后被告知库是否仍然完整**——而不是被要求保持它完整。它可能读错、可能归错；它做不到的是留下悬空或无引用的内容，因为会造成这一结果的命令会拒绝并说明原因 | 正确性系于 agent 的勤勉 |
| S9 | **用自己的手做所有者的非标工作**——抓取、整形、排期——只经官方输入边界进入框架 | 要么框架为每个上游长一个连接器，要么 Steward 直接写库 |

### 访客（Visitor）

按权限读。本设计对访客无改动，只加一条边界：coding agent 是所有者的 Steward 实例；访客通过
API 和控制台触达知识库，从不通过所有者的 agent 会话。

| | 动机 |
|---|---|
| V1 | 提问并得到有引用的回答 |
| V2 | 留痕或不留——`business` 计为使用，`silent` 什么都不留 |
| V3 | 浏览库，不碰机器 |

### 运维者（Operator）

跑栈的人。个人部署里就是所有者本人，而 Steward 既然是 coding agent，被吩咐时也能干大半。

| | 动机 |
|---|---|
| P1 | 拉起、停掉、恢复、升级机器、重建派生层——全程正本不动 |
| P2 | 看到健康状况：作业在等、*谁应该来处理它们*、什么卡住了 |
| P3 | 密钥和机密永不进入被版本化的文件 |

## 2. 用户故事

每条故事写明角色、做什么、看到什么。标 **v1** 的在第一版；标 **v2** 的在此定形，随后实现。

### 所有者指挥 Steward 修改知识库（O4、O5——主流程）

- **2.1 一个错数字（v1）。** 所有者在项目目录的 Codex 会话里说*"合同金额是 5,400 不是 5,000"*。
  Steward 把这句话记成一份 `owner-dialogue/v1` 来源，打开它入队的编译，读持有该 claim 的页面，
  写 `supersede_claim` 引用这份陈述。所有者看到页面的当前视图显示 5,400，旧 claim 仍在、已冻结、
  带日期；历史视图多出一条 `claim_superseded` 事件，引用的是他们自己陈述的 `¶1`。
- **2.2 一处归错（v1）。** *"那个决定属于 Harbour 项目，不属于那个人。"* 同一条路：一份陈述、
  一次编译；Steward 把 claim 追加到项目页，同时引用原始来源**和**这份陈述，并编辑人物页的 claim
  记录这次改归。什么都没删；账本说了什么挪了、为什么。
- **2.3 一个名字（v1）。** *"阿宝就是张伟。"* 陈述编译进人物页总览的 `aliases`，受 `people`
  组件同样的检查——如果这个别名是别人的身份，日常编译会遇到的拒绝这里一样遇到。
- **2.4 "直接删掉"（v1）。** 所有者让 Steward 删掉一条 claim。Steward 做不到：账本没有删除，
  skill 用一句话说明这一点，并给出它能做的两件事——用一份陈述取代它，或者它写下时就错了则原地
  编辑。拒绝来自门，不来自 agent 的客气。
- **2.5 合并两页（v1）。** *"这两个人是同一个人。"* 这是结构而非内容：Steward 在分支上打开一份
  **evolve draft**，移动 claim，退役一页，evolve gate 核算每一个锚。所有者在控制台读 diff 并采纳；
  三方合并落地。同一道门，evolve 模式。
- **2.6 改变记什么（v1）。** *"给每个项目开始记时间线。"* Steward 把契约修改和受影响的路径模板
  起草成一份 evolve 提案；所有者审阅理由和 diff，采纳，之后的编译遵循它。正本不因此重写。

- **2.5b 让一个主题退场（v1）。** *"Harbour 项目结束了，归档掉。"* `pkc owner say` 记下所有者真正
  说过的话并打印来源 id。`pkc archive propose --document memory/topics/harbour.md --statement
  <sid>` 从它算出牵连出什么——只有这一页引用的来源、倚靠这些来源的页面——并在这一页下面摊出它会留
  下的那页记录：Harbour 是什么、它装着多少、以及所有者给出的理由。Steward 把这个闭包读回给所有者，
  只确认所有者点名的那些；一个作业把这一页连同它的封存卷一起、带着历史搬到 `archive/` 之下，并在腾
  出的路径上写下那页记录，同一次提交。从此这**一页**退出默认检索范围——不在 glance 里、不在 fast 的
  claim 面里、不在简报包里、不在 `pkc search` 里——而这个**主题**照旧有答案，以「已归档」的身份，答
  自那页记录。*"取消归档"*是 `--action unarchive`：页面回来，记录退场。
- **2.5b′ 连材料一起退役（v1）。** *"……Harbour 的聊天记录也一起。"* 没有另外一条命令要跑：这些来源
  就在同一份提案里、作为这一页牵连出来的部分——已无活页引用的被勾上，另有活页倚靠的被列出并点名那
  些页——而 `--cascade` 就是所有者对它们点头的方式。归档的来源退出 L1、L2 检索和每条 lane 的窗口的
  默认范围；它在 L0 里保留每一个块，引用照样解析，`pkc source fetch` 无条件可达，
  `--include-archived` 把它放回检索。

### 所有者委派常设工作（O10）

- **2.5c 每日拉取（v1）。** *"每天早上七点，通过 API 抓我们团队 IM 昨天的消息，再拉我和这三家
  供应商之间的邮件；聊天按 IM 存进这座库，邮件按 email 存。"* Steward 在 `steward/tasks/` 下写出这
  个任务：一段调上游 API 的抓取脚本、一段整形成 `im/v1` 和 `email/v1` 载荷的转换、目标租户与
  intake、一个日程。它当着所有者跑一次，`pkc ingest` 接受载荷，编译队列接手。框架没有变：五个来源
  契约是门，`pkc ingest` 是手。排期是 harness 的或机器的 cron，从不是框架的 worker。
- **2.5d 撤销它（v1）。** *"停掉供应商邮件拉取。"* 任务从任务表和日程里移除。它已摄入的东西留
  着：L0 是权威，由它编译出的知识留着，直到所有者退役它（2.5b）。之后重跑一个任务无害——来源的
  身份是它的内容，库已持有的载荷是一次空操作。
- **2.5e 所有者看不见的任务不存在（v1）。** 每个任务是所有者能读的一个目录，随项目版本化；上游凭据
  放 `.env` 或机器的钥匙串，永不进任务文件。任务碰不到 `data/`：它产出载荷、调用 `pkc ingest`，
  skill 在描述任务的唯一那一处写明这一点。

### 所有者在控制台与 Steward 对话（O12、O3、O4）

- **2.5f 那场对话（v1）。** 所有者视角下控制台有一个 **Steward** 视图：与 agent 的对话，它在项目
  里运行，加载的 skill 与终端会话相同。所有者输入*"这周进来了什么，招标那件事有没有互相矛盾的
  地方？"*；Steward 的回合流式出现，它跑的每条命令——`pkc jobs`、`pkc recall --evidence …`、
  `pkc draft append-block …`——都渲染成一个步骤，结果折在下面。一条命令改了库，同一浏览器里的历史
  与流程视图不刷新即更新。
- **2.5g 聊天里的一句陈述（v1）。** *"对了，李在六月离开供应商了。"* Steward 用 `pkc owner say`
  记录它。控制台姿态下桥持有 transcript，所以该命令**机械校验记录文本是所有者所打原文的逐字子串**
  ——对所有者的转述不是所有者的陈述，被拒绝。所有者把拒绝当作一个普通步骤看到，通过时在来源列表里
  看到这份来源出现。
- **2.5h 离开再回来（v1）。** 关掉标签页不会丢掉 Steward：会话是 harness 自己的，重新打开视图即
  续接。访客视角永远没有这个视图；Steward 是所有者的。

### 所有者建库、养库（O1、O6、O7）

- **2.7 第一座库，Codex 编译（v1）。** `./init.py` 像今天一样要 embedding key，外加一个新问题：由谁
  编译——API 模型，还是所有者本机的 coding agent。所有者选 Codex；生成器探测 `codex login status`，
  把 skill 装进项目，把 `compile: agent:codex` 写进引擎（§3.1）。`./start.sh` 摄入演示材料，所有者在项目里打开 Codex：
  *"把待编译的编译掉。"* 他们看着 Steward 打开作业、读来源、一条命令一条 claim 地写——每条的引用
  都在终端里可见——然后 finish。控制台的历史视图出现这次提交。
- **2.8 无人值守（v1）。** 所有者把一周的材料丢进 `my-data/`，运行 `./app.py compile`。在 agent
  执行器下，worker 领取每个作业并用同一份 skill 无头拉起 harness；所有者第二天早上读简报。队列、
  每用户单写者、自愈，一样都没变。
- **2.9 陪着 Steward（v1）。** 同样的材料，但所有者想引导：*"编今天的，招标那场会才是重点。"*
  Steward 交互式地编译，所有者中途纠正；门一样、预算一样、gate 一样。
- **2.10 换执行器（v1）。** 所有者把 `engine.yaml` 里的 `compile` 从一个 OpenRouter 模型改成
  `agent:codex`。引擎控制台标出爆炸半径——重启，且只影响未来编译——之后库字节不变。改回去是同一
  个编辑。
- **2.11 更好的模型（v1）。** 订阅用哪个模型是 harness 在跑的那个。所有者在 harness 里改，不在
  引擎里改；编译记录写明跑的是哪个。

### 所有者看懂、提问、审计（O2、O3、O8）

- **2.12 问 Steward（v1）。** *"招标现在谁负责？"* 配了回答模型时，Steward 跑 fast lane。没配时，
  它向 CLI 要装配好的证据——claim、逐字窗口、glance——据此作答，引用 CLI 给它的句柄。两种情况
  下所有者都在编译的同一个会话里得到有引用的回答。
- **2.13 你做了什么？（v1）。** 编译后 Steward 读编译后简报，用所有者的语言说变了什么；所有者也
  能在控制台打开同一份简报。
- **2.14 这为什么在这？（v1）。** 所有者指着一条 claim；Steward 取出被引用的段落逐字展示。这就是
  框架已有的 L0 取回，从 CLI 到达。
- **2.15 花了多少？（v1，部分）。** 无人值守的运行把 harness 的 token 用量记在作业上。交互式运行
  看不到 harness 的计数器；作业记录执行器且*不记*用量——缺席而非零，token 从不猜。
- **2.16 回滚（v1）。** 一次编译落了一堆胡话。所有者说出来；Steward 报出版本，所有者在控制台
  回退，或让 Steward 去做。派生层重建；正本历史保留被回退的版本。

### Steward 干活（S1–S7）

- **2.17 打开作业（v1）。** `pkc draft open <job>` 领取作业，渲染契约和任务——与 langchain 编译放进
  system 和 human 消息的字节相同——并在磁盘上创建 draft。此命令未跑之前，该作业不存在任何写命令。
- **2.18 在写入处被拒（v1）。** `pkc draft append-block` 的文本无引用、span 错、路径在模板之外、
  或页面本轮尚未读过——以 langchain 工具会返回的同一段文字拒绝，非零退出，什么都没写。
- **2.18b 写后即检（v1）。** 通过参数检查的写入被应用，然后命令对它触碰的页面跑 gate 的谓词——
  锚、页上每条引用解析到本作业来源或祖传、路径归属、总览规则、组件检查。任一失败，draft 不持久化，
  拒绝被打印，命令非零退出。Steward 读到自己错在哪，重试。没有任何悬空的东西能活过一条命令；
  `finish` 仍对每一页再跑一次完整 gate，作为最终裁决。
- **2.19 预算（v1）。** 每条命令花掉本轮预算的一次调用，公式与今天相同。`pkc draft status` 说
  还剩多少、gate 已经发现欠什么；越过低水位后每次写入的结果都带上这条提示。
- **2.20 Finish（v1）。** `pkc draft finish` 先跑总览下限，再跑 gate。干净：提交、发出事件和简报、
  删除 draft、完成作业。有违规：打印违规和修复预算，draft 保持打开供一轮修复；第二次失败则作业
  中止，正本不动。
- **2.21 读一切（v1）。** `pkc source fetch`、`pkc search`、`pkc canonical read`、`pkc glance`、
  `pkc history`、`pkc consultations`、`pkc jobs`——HTTP API 的读半边变成命令，租户都取自项目。
- **2.22 无人值守，同一双手（v1）。** worker 用 skill 的 system 文本和渲染好的任务经 stdin 拉起
  `codex exec`；进程跑的是同样的 `pkc draft` 命令。启动器负责超时、限流退避、进程组清理和用量
  捕获。

### 访客、运维者

- **2.23 访客提问（不变）。** 通过控制台或 API，带他们选的类别。coding agent 不是访客面。
- **2.24 作业在等 Steward（v1）。** agent 执行器下编译作业不会自己消化。控制台的流程视图说清：
  *"3 个编译作业在等 Steward——在项目里打开你的 agent，或运行 `./app.py compile`。"*
- **2.25 重建派生层（v1）。** Steward 被吩咐时可以运行 `rebuild_derived`；这是只动派生层的操作，
  不需要模型。

### 冷启动：Steward 已经知道的（O1、O2、S1）

- **2.26 Steward 已经认识所有者（v1）。** Steward 跑在所有者对着说了几个月话的那个 harness 里：它的会话
  历史、它的记忆文件、所有者用的其他 skill 留下的偏好档案。首次编译之前，Steward 读它已经掌握的关于
  所有者的东西，也读材料显示的东西——谁在用第一人称说话、每条消息都写给谁、什么语言、什么时区——用
  `pkc profile set … --provenance inferred` 写下 profile：名字、职业、简介、兴趣、地区。然后在所有者
  在场时把推断摊开请他们纠正，一次一项；确认过的字段翻为 `owner`。编译 system 消息把每个字段连同出处
  一起渲染，读到一个推断出的名字的模型知道它是推断。关于所有者的任何东西都不经此进入**库**：profile 是
  登记级的自我介绍；Steward 从别处知道的实质事实，只有所有者说出来（`pkc owner say`，以所有者的话）才
  成为知识。
- **2.27 语义检索是一个选择，不是默认（v1）。** 没有 embedding key。Steward 问：*"我可以不带语义检索
  跑这座库——只有词法检索和编译出的页面——或者你现在给我一个 OpenRouter key。"* 答案记录一次
  （`pkc config set semantic_retrieval off`，或 key 进家的 credentials），不再问；选了 `off`，不建
  embedding，每个 intake plan 都是 `semantic_indexing: none`，每条 lane 只跑 L1 加正本。日后加 key、
  `semantic_retrieval on` 加 `rebuild_derived` 就把 L2 补上；正本不动。
- **2.28 新会话找到库（v1）。** 几周后所有者在别的目录打开 Codex。全局 skill 的第一步是 `pkc home
  status`：这台机器上登记的库，逐一探测——栈可达、框架仓库在、key 在、skill 已装且新鲜——Steward 在
  所有者指的那一座里继续，而不是提议再建一座。
- **2.29 初始化被记住（v1）。** 每座登记的库在家里带着自己的初始化状态：栈的端口和 compose 项目、检索
  选择、backend、哪些步骤已完成（栈已启、profile 已确认、skill 已装、首次编译）。发现已完成的 Steward
  不重做，所有者第一次答过的问题不会被问第二次。
- **2.30 Steward 从别处知道的事实（v1）。** Steward 在另一个会话里读到所有者换了团队。它不能把这写进
  库——那不是来源——但它可以说出来并问；所有者的*"对，五月起"*就是陈述（`pkc owner say`，在控制台下
  逐字校验），编译把它归档。

## 3. 所有者的体验，一次走通

本节回答的问题：*我用新版本，Codex 是我的 Steward——是什么感觉？*

**安装。** `cd scaffold && ./init.py`。key 照今天的方式询问；唯一的新问题是*由谁编译*：API 模型
还是本机的 coding agent。选 Codex 会跑一次探测——CLI 在、已登录——生成器把 `compile: agent:codex`
写进 `engine/engine.yaml`，把 skill 装到 `.agents/skills/pkc-steward/`，在项目的 `AGENTS.md` 里
放一个 `pkc:start` 块（Claude Code 的对应物一并生成，两个 agent 都能在同一项目里打开）。
key 与执行器自由组合（§3.1）。

**建库。** `./start.sh` 拉起栈、摄入随附材料。所有者在项目目录打开 Codex。Codex 读 `AGENTS.md`，
知道自己是这座库的 Steward，知道 skill 在哪。所有者输入*"把待编译的编译掉"*。Codex 跑 `pkc jobs`，
看到编译作业，逐个：`pkc draft open` 打印契约和任务；它读；它用 `pkc draft append-block …` 写
claim，每条命令的文本和引用都在终端可见；`pkc draft finish`。所有者看着一次编译以一串小的、可读
的、可拒绝的步骤发生——这正是框架的整套写入纪律，现在上了屏幕。控制台开着时，历史随提交落地而
填满。

**与它相处。** 新材料进 `my-data/`；`./app.py ingest`，然后要么 `./app.py compile` 无人值守跑一
遍，要么对 Codex 说一句话带着跑。问题问 Codex 或问控制台。订正就是句子：*"那个数字错了，是
5,400"*——所有者可以看着 Steward 记录陈述、打开编译、读页面、取代 claim，它若试图做任何 gate
会拒绝的事，就当场被拒。

**它不做什么。** 它不让 Steward 直接编辑页面，无论所有者说得多清楚——门里没有这个命令。它不删
知识。它不在算不清时猜一次运行花了多少。它也不把 Codex 变成必需：API 执行器原样保留，两者随时
可换。

### 3.1 key 留在原处；执行器是另一个问题

选 coding agent 替换的是编译模型，不是部署的 key。`init.py` 仍像今天一样询问 embedding key（以及可
选的回答模型 key），写进 `.env`，`pkc` 像 API 和 worker 一样读这个文件——所以 Steward 跑 `pkc
ingest` 时，L1 和 L2 用配置好的 embedding 建起来，skill 只需说"摄入会索引"。两个问题自由组合：
一个 OpenRouter key 管 embedding 和检索，Codex 管编译，是预期的形状。

coding agent 驱动 compile、episodes 及默认的 evolve；简报由 Steward 自己写。
语义检索开启时，片段判断经索引门运行（§5.12），配置好的 embedding 仍负责构建 L2。
`semantic_retrieval: off`（§5.9）跳过这些工作，也不需要 embedding key。
对于启用但缺少 key 的供应商 embedding，启动时解析其规格（`wiring.warn_missing_embedding_key`，就在 `check_executors`
旁边），当这个规格需要一把该部署没有设置的 key 时，记一条 WARNING，点名设置项
（`PNEUMA_KNOWLEDGE_EMBEDDING_MODEL`）、变量（`OPENROUTER_API_KEY`）以及会坏掉的东西——语义索引与
语义检索，在第一次 embed 调用处。生成器在答案把 key 留空时打印同一句话，`./app.py up` 与
`./app.py preflight` 也是；`pkc` 因为共用 `build_context`，在同一个启动点每进程说一次。这是提醒，不
是拒绝：L0/L1 依旧无条件（I3），正本照常编译，补上 key 再 `rebuild_derived` 就把 L2 填回去。无需
key 的规格（`fake:<维度>`，以及 scripted 与测试配置）什么都不会说。本地 embedding 适配器——真正让无
key 部署在 L2 也完整的那件事——是后续项（§13）。

## 4. 裁定

1. **执行器是 Steward 内部的选择，以 model spec 的形式配置。** 一个角色的模型可以写
   `agent:codex` 或 `agent:claude-code`，位置与今天写 `openrouter:…`、`scripted:…` 完全相同
   （`wiring.resolve_model_name`）。compile 与 evolve 都支持；evolve 未单独指定时继承 compile。
   episodes 经索引门使用 compile 执行器的 harness（§5.12），简报由 Steward 自己写。
   agent compile 执行器下跳过 challenge：没有作业、门或技能步骤，即使配置了 API challenge 模型也一样。
   库的归因 trailer 不变；作业记录增加
   `executor`。
   **在 agent 执行器下，消费是 agent 按 `references/consume.md` 指引自行阅读；
   API 通道是有密钥的控制台用来测试质量的工具。**
2. **一道门，两种姿态。** claim 级 draft 加它的写工具加 gate，是两种执行器进入正本的唯一路径。
   langchain 循环和 CLI 是它的两个客户端。CLI 能拒绝的，langchain 工具以同一段文字拒绝；同一个
   测试序列走两条路产生同样的文件。
3. **agent 持有期间 draft 落在磁盘。** CLI 在两次调用之间没有记忆，所以 `PatchDraft` 获得序列化
   形式和每作业一个的家。它既不是正本也不是保留的记录：临时物，finish 或 abandon 时删除；对已有
   draft 的作业再次 `open` 只允许同一执行者续接；其他执行者会被拒绝。
4. **skill 是一次渲染，不是第二份文本。** agent 读到的、影响判断的一切——契约、编译指令、工具
   描述、组件 preamble——都已在 prompt catalog 里，按（契约 × 措辞 × 组件）字节钉住。skill 包由
   它生成；哈希盖在 overlay 哈希旁边。没有任何东西被手写两遍。
5. **散文是完整规格；workflow 是只在能跑它的那个 backend 上的强制升级。** SKILL.md 对每个 harness
   都承载完整流程。Claude Code 额外得到一个 dynamic workflow，让"先读、再计划、再写"成为唯一的
   工作顺序。Codex 遵循同样的文字。
6. **上下文完整是被拒绝出来的，不是被请求出来的。** 三个机制：`open` 渲染任务之前不存在写命令；
   对已有页面的写入在该页本 draft 内被读过之前一律拒绝（今天的 `mark_read` 规则从总览动词扩到
   所有动词）；引用必须解析到本作业的来源，或从先前提交祖传而来（gate 现状）。
7. **所有者的话以来源进入，从不以编辑进入。** 每一次订正、改归、别名、状态陈述，先是一份
   `owner-dialogue/v1` 来源，然后才是一次编译。CLI 的 `owner say` 命令只做这件事；不存在任何
   不经作业就改动 claim 的命令。
8. **结构变更走 evolve 门。** 合并、拆分、重命名页面，改族或改契约：Steward 在分支上起草 evolve
   draft，evolve gate 核算锚，所有者采纳。已在 v1 实现（§5.7）。
9. **backend 是数据。** 每个 harness 由一份清单描述——二进制、安装布局、无头启动形状、能力——
   清单之外没有任何代码按它的名字分支。探针探活性，从不比版本号。
10. **正确性归框架，且每次行动之后告知。** Steward 可能出错、可能误解；框架不允许的错误由本会造成
    它的那条命令捕获——在应用变更之后、持久化之前。每条写命令用 gate 自己的谓词对触碰的页面做后置
    检查，失败即回滚；`pkc draft check` 随时对打开的 draft 跑完整 gate；`pkc library check` 对已提交
    的库跑全库谓词。skill 永不承载一条命令不强制的规则。
11. **Steward 的常设工作住在框架之外。** 从上游抓取、整形、排期、决定喂哪座库：全部是 Steward 自己
    的代码和 harness 自己的调度器，放在项目的 `steward/` 下。它只经五个来源契约和 `pkc ingest` 进入
    框架。新上游永不需要改框架，任务永不触碰 `data/` 或正本。
12. **归档是上游的机制；在这道门上，理由永远是所有者的原话，而 Steward 只确认所有者点名的东西。**
    归档是一次搬到 `archive/` 之下的搬移、外加一页留在腾出的路径上的记录，什么都不会被删掉
    （[archive.zh-CN.md](archive.zh-CN.md)）——本 feature 不添任何状态、任何过滤、任何自己的算术——
    「陈述或备注」这条规则如今是**服务的**（确认处 `422 note_required`，作业里
    `statement_missing`），因为框架在任何地方都不再造句。本 feature 添的是 CLI 上的一种姿态，而这姿
    态就是两次拒绝：`pkc archive confirm` 在没有 `--statement` 也没有 `--note-file` 时，在问服务之前
    就拒绝，并点名 `pkc owner say` 作为所有者原话的来处；以及一次确认只勾上所有者**点名**的那些，牵
    连出来的无论如何都列出来、只在 `--cascade` 下才一并确认。读过去只差一个旗标
    `--include-archived`，加在每一条会列举或检索的命令上——而按名字点到一样东西完全不需要旗标，那
    正是 I3 与 I4 早已给出的承诺。
13. **控制台的 Steward 视图是同一个 harness 会话的一张脸，不是第二个 Steward。** service 用同一份
    skill 在项目里拉起 harness，把它的流桥接到浏览器；agent 通过同样的 `pkc` 命令行事；库以同样的
    方式更新。桥增加的是终端没有的一个机制：因为它持有 transcript，从对话里记录的所有者陈述必须是
    某个所有者回合的逐字子串。对话本身是 harness 的会话，不是库的保留记录。
14. **profile 是 Steward 的第一次推断，由所有者确认。** 每个 profile 字段带出处——`inferred`
    （Steward 从自己对所有者的记忆或从材料里读出）、`detected`（系统探测）、`owner`（所有者确认或
    亲写）——编译 system 消息把这个词渲染在值旁边。Steward 先写再问；所有者是纠正而不是填空。Steward
    从材料之外知道的关于所有者的事，只以所有者自己的陈述进入库。
15. **语义检索是一个被记录的选择。** `semantic_retrieval: on | off` 是引擎旋钮。off 意味着不建
    embedding 模型、每个 intake plan 都是 `semantic_indexing: none`、每条 lane 和索引作业跳过 L2——
    不是假向量，也不是一次失败的调用。选择由生成器或 Steward 问一次并记录；日后带 key 打开，是一处
    编辑加 `rebuild_derived`。
16. **`~/.pkc` 是这台机器上库的家，它是状态，不是知识。** 这台机器上项目的登记表及各自的初始化状态、
    所有者提供过一次的凭据（0600，设置装配时作为进程环境和项目 `.env` 之下的最低层读入）、所有者的
    默认值。在任何地方启动的 Steward 读它、探测它指的东西、继续；里面没有来源、claim 或库的记录，
    没有它项目也是完整的。

compile 与 evolve 都可使用 `agent:<backend>`；evolve 未单独指定时继承 compile 的执行器。
compile、evolve 与 episodes 三类作业在无人值守时交给同一 launcher，在交互姿态下留队等各自的 open。
简报是 Steward 自己的文本；agent 执行器跳过 challenge。采纳仍由 Owner 决定。

## 5. `pkc` CLI

`pneuma-knowledge-service` 里的一个控制台脚本（`pkc = pneuma_knowledge_service.cli:main`），读
API 和 worker 读的同一套设置，所以项目的 `.env` 和 `engine/` 对它的解析与对它们完全一致。scaffold
生成一个 `bin/pkc` 垫片，加载项目 `.env` 后运行框架的入口。**`pkc` 是 Steward 的全部词汇**：skill、
`pkc:start` 块和每一次拒绝都只提 `pkc` 命令。`app.py` 仍是所有者的项目壳——拉栈、停栈、演示——
面向 agent 的文本一律不提它；Steward 需要做的任何事，`pkc` 都做。每条命令的租户取自项目（`app.py` 今天
的 `PNEUMA_KNOWLEDGE_TENANT`）；多租户部署有 `--user` 覆盖，这是唯一需要手打用户 id 的地方。

### 5.1 读——Steward 的眼睛

HTTP API 的读半边变成命令。同样的 handler、同样的形状，可要求 JSON。每条读命令都**分页**：
散文一页 8,000 字符，页脚点名下一页（`--page N`、`--all-pages`、`--page-chars CHARS`）；`--json` 按条目给
载荷里唯一的那个列表（hits、pages、jobs……）分页并附 `paging` 字段——读者带着上下文窗口来要一页，
一次交出 200 KB 的检索结果，是库替读者花掉了他的注意力。`pkc canonical read` 一次可读多页。

| 命令 | 读什么 |
|---|---|
| `pkc outline`（`--json`、`--family <template>`、`--definitions`、`--include-archived`） | 完整地图：每一页都在所属族下，一页一行，没有 top-K 或字符预算；用于会话开始及编译后检查 |
| `pkc glance`（`--include-archived`） | 回答通道的有预算地图（`canonical_glance`）：每个族的头部页面，报告省略数量；outline 太长、难以扫读时用来挑选主题 |
| `pkc canonical ls`（`--include-archived`） / `read <path> [<path> …]` / `history <path>` | 页面、一页、一条 claim 链；每页显示「最后改动」（路径提交）、与 outline 一致的账本断言数、概览块数、全库替代关系及后继地址、「最新被引来源（引用块的最新日期，缺失时取来源日期）」和当前租户待处理及失败的编译作业数。来源索引逐引用块标注发言者及块自身的已记录日期，缺失署名明确标为「未知」。来源日期优先发生日期，否则标为「导入 …」；`read` 与 `history` 无条件；日期统一按头部声明的 Owner 时区计算，未记录时明确使用 UTC；JSON 保留日期及带偏移的原始时刻。引用块的日期与发言者仅在元数据长度、标识符及块顺序校验通过后附加，否则标为未知；邮件块展示发件人、角色及发送日 |
| `pkc source ls`（`--include-archived`） / `show <id>` / `fetch <id> ¶a-b [<id> ¶c-d …]` | L0：来源、结构、逐字 span；每个读取区间标注完整来源 id、逐块发言者（缺失时明确标为「未知」）、块自身的已记录日期，以及来源发生日期或带「导入」标签的日期。JSON 为列表，分页时包装为 `items` 并附 `paging`；仍支持单来源多区间；`show` 与 `fetch` 无条件；日期统一按头部声明的 Owner 时区计算，未记录时明确使用 UTC；JSON 保留日期及带偏移的原始时刻。引用块的日期与发言者仅在元数据长度、标识符及块顺序校验通过后附加，否则标为未知；邮件块展示发件人、角色及发送日 |
| `pkc archive propose` / `confirm` / `ls` / `show` / `drop` / `inventory` | 让一个主题退场，以及把它请回来（§5.5）——一份提案、一次确认，以及排在普通队列上的一个作业 |
| `pkc search <q>`（`--lexical` / `--semantic` / 融合；`--include-archived`） | 在指定范围内返回 L1 / L2 排名命中，逐块标注发言者及日期。词法/融合头部报告每个词项及全部词项的**已索引块**数估计，说明单块匹配、相邻块可能合并涵盖词项、索引可能落后于 L0，并列出当前租户待处理及失败的索引作业数。引号短语算一个词项；语义模式无词法计数；融合模式单独报告词法总数；日期统一按头部声明的 Owner 时区计算，未记录时明确使用 UTC；JSON 保留日期及带偏移的原始时刻。引用块的日期与发言者仅在元数据长度、标识符及块顺序校验通过后附加，否则标为未知；邮件块展示发件人、角色及发送日 |
| `pkc recall <q> --evidence`（`--include-archived`） / `pkc recall --evidence --handoff <id> --page N` | fast 证据，不含回答调用：头部列出统计、第三行 handoff 及精确的下一页命令；依次为断言、原文窗口、片段摘要（派生）、地图。有相关性评分的章节按排名排序，否则标注保留 lane 顺序。句柄到来源的索引列出引用块、发言者和日期。文本随 handoff 保留，silent 调用也如此：`--handoff` 读取保留分页，不重新检索或创建第二个 handoff；仅用 `--page` 会重新检索。JSON 保留完整 lane `content`，附 `tally` 和 `sources`；日期统一按头部声明的 Owner 时区计算，未记录时明确使用 UTC；JSON 保留日期及带偏移的原始时刻。引用块的日期与发言者仅在元数据长度、标识符及块顺序校验通过后附加，否则标为未知；邮件块展示发件人、角色及发送日 |
| `pkc recall <q>`（`--include-archived`） | 配置了回答模型时的 fast lane |
| `pkc jobs` / `pkc history` / `pkc brief <version>` | 队列、编译版本、编译后简报 |
| `pkc consult answer <handoff_id> --text-file <f>` / `pkc consult record --question <q> --text-file <f>`（或 `-`；`--kind no_record`） | 关闭交接回答，或不经过交接直接记录阅读；每个引用都必须可解析 |
| `pkc consultations` / `pkc spend` | 使用侧保留记录、交接证据数与直接引用数及其花费 |
| `pkc evolve ls` / `show` | 提案及其 diff |
| `pkc library check` | 对已提交的库跑全库谓词：锚唯一与连续、引用形状与可解析、路径归属、总览规则、组件检查、每次提交带 trailer——只报告，不修复 |

读命令的文本按字符分页，JSON 按完整列表条目分页。顶层列表分页时包装为 `items`；对象含多个
列表时，对序列化后最大的列表分页，并在 `paging.list` 中标明。`--all-pages` 返回完整载荷。
Recall 证据的 JSON 始终完整。保留的 recall 分页沿用初次读取的页大小，重复显示头部；在交接
被回答或过期前均可读取。

两种地图默认省略已归档页面，保留 live 路径上的归档记录；显式纳入的已归档页面按 live 路径
归入所属族、排在 live 页面之后，并标明状态。Outline 按契约声明顺序点名空族，在页面旁计数
关闭卷，以 `[record]` 标记记录，以 `[archived]` 标记显式纳入的已归档页面。JSON 是带页面总数
的族树；不属于已声明族的页面仍可见，其 template 为 null。它从一次 canonical listing 推导
元数据，不逐页读取，也不调用模型。当前 listing 会加载正文；持久化页头索引留作后续优化。

`pkc recall --evidence` 露出 fast lane 中无模型的那一半。JSON 的 `content` 完全保留
lane 本会递给回答模型的字节。文本保留各证据章节的内容，将地图放最后，便于已经掌握地图
的读者；元数据页头和来源索引提供机械阅读信号，不改变 lane。

**交接本身就算使用。** 在 `business`（`--evidence` 的默认值）或 `audit` 下，检索立即记录
咨询的**开场事件**：`consultation_id`、`user_id`、`created_at`、lane、访客类别、问题、`as_of`、
检索开始前采样的 canonical HEAD 和 `evidence_handed`。咨询 id 就是证据第一页打印的 handoff id。
agent 可能回答了 Owner 就停下，不再关闭交接；这不能抹掉库被问过、证据已递出的事实。
只有开场、没有答案的咨询明确显示为**未作答**，既不是命中也不是落空（`miss: null`）。
CLI、API 和控制台都列出其问题、开场时间与递交地址数。

一条咨询是**同一 id 下两个不可变的保留事件**，绝不是答案到来后改写原记录。
`pkc consult answer <handoff_id>` 只追加一次答案事件：`answered_at`、答案文本、引用、
`answer_kind`、此时计算的 miss 分类，以及 fast lane 构造器的其他字段。当前存储用一行表达：
开场列只写一次，答案列初始为 NULL，事务用 `answered_at IS NULL` 守卫，只填入答案列。
这次填入是在追加第二个事件，不是改写。重复或并发关闭会以「已经作答」拒绝。
直接 `pkc consult record` 和模型应答 lane 一次写入两个事件；已有完整记录的两个事件
沿用其原本记录的时刻。

会过期的 handoff 单独保留阅读文本、句柄表和检索状态。句柄按表还原，真实来源区间和 canonical
锚点则在当前租户的 L0 块范围与 canonical 中解析。交接引用保留 `origin: "handed"`；清单外
解析成功的直接读取记为 `origin: "direct"`，不扩充 `evidence_handed`。无效引用以退出码 4
拒绝，不追加任何答案，交接保留以便纠正。CLI 等待 `_spawn_recording` 持久化成功后才报告成功并
删除 handoff。无人关闭的 handoff 按 `PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL` 过期；过期只删除
保留的文本和句柄，**绝不删除开场记录**，它继续显示为未作答。

对 `business`，每个事件与其投影作业在同一事务中提交。worker 分别投递开场（递交证据增加权重）
和后来的答案（引用增加权重；只有此时才计落空）。投影按 `(consultation_id, event)` 幂等，
两个事件各有自己的投影标记。重建按事件时间重放已投影事件，同一时刻开场在答案前；尚未投影的
事件仍由自己的排队作业处理。因此答案仍在等待时，已投影的开场也能完整重建。
注意力报告分别列出交接证据、答案引用、落空和未作答计数。`audit` 保留两个事件但不影响注意力；
`silent` 两步都不记录。交接页头和帮助说明这个选择。单独 `pkc recall` 仍默认 `silent`；
读取保留分页不会创建新事件。

未运行 `recall --evidence` 时，`pkc consult record --question <q> --text-file <f>`（或 `-`）
走相同的解析、构造器和发出路径，lane 为 `direct`，不需要交接。它接受
`--visitor-class business|audit|silent`，默认 `business`，也接受 `--kind no_record`。
一个问题，一个 id，两个保留事件：纠正被拒绝的回答，不要重跑 recall 来修复它。无密钥的 `recall --evidence`
不构造模型，报告哪些分支运行、哪些被跳过（JSON 的 `arms`），包括无法运行的 glance 选页；
空或稀薄的清单不意味着 agent 无法直接阅读库。

### 5.2 写——那一道门

```
pkc draft open <job-id>                      领取作业；渲染契约 + 任务；创建 draft
pkc draft status                             剩余预算、已读页面、gate 已发现的欠账
pkc draft list-documents
pkc draft read-document <path>               把该页标记为本 draft 已读
pkc draft create-document <path> --frontmatter <json> --body-file <f>
pkc draft append-block <path> --heading <h> --text-file <f>
pkc draft edit-claim <path> <anchor> --text-file <f>
pkc draft supersede-claim <path> <anchor> --text-file <f>
pkc draft rewrite-overview <path> --json-file <f>
pkc draft set-fields <path> --json <json>
pkc draft search-knowledge <q> | search-source <q>
pkc draft <component-tool> …                 启用的组件贡献什么就有什么
pkc draft check                              对打开的 draft 跑完整 gate，不 finish
pkc draft finish [--brief <f>|-]              总览下限 → gate → 提交 | 违规；Steward 简报
pkc draft abandon [--take-over]              释放作业；删除 draft；显式恢复其他执行者的草稿
```

文本经文件或 stdin 到达，从不经 argv：一条 claim 是一个段落，shell 引号出错不该是 agent 拿本轮
预算去买单的编译错误。命令名、描述和拒绝文本来自 langchain 工具用的同一组 prompt catalog 键
（`compile.tool.*`），所以 agent 在 skill 里、在 `--help` 里、在每一次拒绝里读到的是同一套词汇。

每条命令加载 draft，为作业用户跑组件的 `prepare`，应用一个工具函数——`_build_tools` 构造的同一
批闭包——**用 gate 的谓词对触碰的页面做后置检查**，然后才持久化 draft、退出。参数面的拒绝是工具
自己的 `AnchorToolError` 文本输出到 stderr、退出码 2；后置检查失败同为退出码 2，违规按 gate 的渲染
输出，磁盘上的 draft 是命令之前的那份；预算耗尽是退出码 3 加 `compile.budget.call_refused` 文本；
`finish` 或 `check` 处的 gate 失败是退出码 4 加渲染后的违规。退出码是让 workflow 脚本不解析散文就
能分支的机制，而后置检查让"库仍然完整"成为 Steward 被告知的事实，而不是被交付的职责。

`finish --brief <f>`（或 `--brief -`）接收 Steward 为该版本写的简报：非空、不超过 8,000
字符，作为派生文本存在成功的编译作业上，并能跨修复轮保留。agent 执行器不再调用简报模型。
无人值守时，launcher 的最后消息在同样的界限下补全成功版本缺失的简报；显式 brief 优先。
中止、放弃和无改动轮不产生简报。

### 5.3 所有者的话

```
pkc owner say --text-file <f> [--about <path>…]   记录一份 owner-dialogue/v1 来源；入队它的编译
```

一条命令，一个效果。`--about` 是带进作业 source guidance 的提示，让编译任务点名这份陈述涉及的
页面；它不改变 gate 要求的任何东西。skill 告诉 Steward 每次订正从这里开始，而不存在其他任何写路径
才是这句话成立的原因。

**所有者自己的档案。** owner **是谁**，是材料本身唯一说不出的那件事；而契约要把他自己的事实归到
他的档案上、而不是归到一页关于陌生人的页面上，前提是档案点名了他。验收那次跑出了代价：owner 被编
译成了 `memory/people/chen-wan.md`，因为 `engine/persona/profile.yaml` 还写着
`display_name: "Someone"`。

```
pkc profile show [--json]                       本库编译时所依据的档案；并说明它是否仍是占位
pkc profile set --file <f>|-                    一份档案映射（YAML 或 JSON），与文件同形
pkc profile set --field name=value …            一次一个字段，应付常见情况
```

`is_placeholder` 是机械的那一半——生成器自己的 `display_name`，旁边没有任何事实——它就是 `show`
报告的东西、`pkc draft open` 在这一轮之上打印的那**一行**（是提示，不是拒绝；交给宿主的那两份表面
逐字节不变），也是 skill 第一条规矩所依据的东西。`set` 是一次写：
`persona_profile.save_owner_profile` 以**文本**方式改写项目的 `persona/profile.yaml`（它的注释就是
给人读的文档），并写入这一轮据以渲染的持久化 `UserProfile`，于是文件与记录无从漂移。`app.py init`
也走同一组函数。一页最后发现其实就是 owner 本人的页面，照别的页一样退场——先把值得留下的事实记进
档案，再由他亲口说出来。

### 5.4 摄入与常设任务——Steward 自己的领地

```
pkc ingest --contract im/v1|email/v1|meeting/v1|document-library/v1|owner-dialogue/v1 --file <f> [--intake <archetype>] [--user <tenant>]
```

`pkc ingest` 是 `/sources/import` 的 CLI 面：五个契约之一的载荷、可选的 intake 覆盖、租户。它就是
整个输入边界，而且足够，因为以契约形状到达的东西是框架的事，它如何被整成那个形状不是。

它上游的一切都是 Steward 的：

```
steward/
  tasks.yaml                    启用的任务，各带日程与目标（租户、契约、intake）
  tasks/<name>/TASK.md          这个任务做什么，给所有者读
  tasks/<name>/fetch.*          Steward 自己写的、对上游 API 的代码
  tasks/<name>/transform.*      上游记录 → 契约载荷
```

skill 用一节描述这块领地：任务是一个目录；它从 `.env` 或钥匙串读凭据、从不存储；它产出载荷并调用
`pkc ingest`；有 harness 调度器的用它排期，没有的用机器 cron 无头拉起 harness；从 `tasks.yaml`
移除即撤销。框架的 worker 从不跑抓取。幂等是框架的：来源的身份是它的内容，库已持有的载荷被接受
且什么都不改，所以一个任务失败后可以放心重跑。`steward/` 随项目版本化，所有者能读到每个任务和它
的每次改动；它不是 `engine/`，因为任务是操作而非策略，任务的改动不改变任何东西被编译的方式。

这条边界正是架构已有的那条——SourceAdapter 是"唯一允许随输入类型增长的层"——只是挪到了增长最
便宜的地方：Steward 在所有者的项目里为所有者的那一个上游写适配器，框架的五个契约仍是五个。

### 5.5 退役知识——这道门上的归档

*机制在上游，并且只说一次：[archive.zh-CN.md](archive.zh-CN.md)。归档是一次搬到 `archive/`
之下的**搬移**，外加一页留在腾出的路径上的简短记录；来源由 `archived_at` 标记；什么都不会被删
掉；每个地址照旧解析；集合从所有者点名的东西**算**出来，并针对同一个库状态确认。本节不往上面添
任何东西——没有新状态、没有新过滤、没有自己的算术。*

本 feature 添的是那张脸。`pkc archive` 是六条命令，跑在 HTTP 路由所调用的同一批 `archive_service`
函数之上，从不走 HTTP：

| 命令 | 做什么 |
|---|---|
| `pkc archive propose (--document <path>)… (--source <id>)… [--action archive\|unarchive] [--statement <sid>] [--note-file <f>]` | 算出闭包并保留它；把每一项连同它那条结构化理由印成话，并在每一页下面印出它会留下的那页记录——定义、事实行、理由 |
| `pkc archive confirm <id> [--cascade] [--deselect <ref>]… (--statement <sid> \| --note-file <f>)` | 接受它、排入那一个作业并打印作业 id；`409 stale` 是退出码 2，并点名移走的那个 HEAD |
| `pkc archive ls` / `show <id>` / `drop <id>` | 保留下来的提案（`stale` 对着当前 HEAD 算出来）、完整的一份连同它的作业，以及关掉没人会去动的那一份 |
| `pkc archive inventory` | 此刻归档里有什么：页面连同它进去的那天、以及立在它活路径上的那页记录；来源连同 `archived_at` |

在它们旁边，每一条会**列举或检索**的读命令都拿到 `--include-archived`：`pkc glance`、`pkc
canonical ls`、`pkc source ls`、三种模式下的 `pkc search`，以及 `pkc recall` 的两张脸。它按路由传
它的方式传给端口和 lane，从归档里回来的东西按线上的方式打标——`--json` 里是 `archived`，散文里是
`[archived]`。`pkc recall --evidence` 把这个范围留在待办的交接行上，于是 `pkc consult answer` 把
它收成一次「在这个阅读范围内」的咨询记录。按名字点到**一样**东西不需要任何旗标——`pkc canonical
read`、`pkc canonical history`、`pkc source show`、`pkc source fetch`（I3、I4）——那里没有旗标，本身
就是承诺。

**有两条规则属于这道门，而不属于那条线。**

**理由永远是所有者的原话。** 记录的第三块**引用**某个人（archive.zh-CN.md §2.3），而那个人绝不
会是框架——如今在任何地方都不会：框架不再替他们造句，`archive_service` 拒绝一次既不带备注
也不带 `statement_ref` 的确认（`422 note_required`），归档作业还会再防御性地拒绝一次
（`statement_missing`）。所以这条规则既是这道门的，也是服务的；这道门添的是它被说出来的位置：
`pkc archive confirm` 在既没有 `--statement` 也没有 `--note-file` 时，在问服务之前就拒绝，并在措
辞里点名 `pkc owner say`——Steward 用来记下所有者的那条命令。`propose` 不受这条约束：一份计划什么
都不决定、也不引用任何句子，它的 `--note-file` 是展示用的文字；在一个用不上这些话的时刻要来所有者
的原话，只会教会 Steward 以为他给出的那条备注就是记录将要引用的那一句。在控制台的 Steward 会话里，
`--note-file` 要过 `pkc owner say` 同样的逐字校验（裁定 13）——这条备注会被引进一页活页上的 claim
里，而那正是这项校验存在的理由。与陈述并列给出的备注由服务对着它的 ¶0 比对，不一致就以
`statement_mismatch` 拒绝，而不是悄悄替你选一个；陈述本身在算集合时就定下了：确认只能点名提案已
经点名的那一份，或者把原话作为备注给出。

**默认只确认种子；牵连出来的要专门说。** 规划器算的是从种子**牵连**出什么，而牵连出来的东西不是
所有者说过的话。所以一次确认勾上 `seed` 那些项，并把每一个 `cascade` 项取消勾选，除非
`--cascade` 另说；`--deselect <ref>` 再把某一项留在原地。两类项无论如何都会被列出来——在提案里，
在确认自己的输出里也是——因为 Steward 若确认得比它摊出来的少，就是在藏起它拿到的那个闭包。这是
经由确认那套普通的逐项覆盖表达出来的**收窄**，所以没有任何东西是被手工加进集合的：要扩大一个集
合，就带更多种子重新算一份。

Steward 拿它怎么用，按顺序：`pkc owner say`（留住来源 id）→ `pkc archive propose --statement
<sid>` → 把闭包和记录预览读给所有者听 → `pkc archive confirm <id> --statement <sid>`，只有当所有
者对牵连出来的东西也点头时才加 `--cascade`。此后那页记录只读，一次以 `archived_path` 被拒的写入
是关于这个知识库的事实、而不是障碍：这个主题已经退场，而所有者靠取消归档来撤回它。

### 5.6 控制台里的 Steward 视图

每个所有者会话一条 WebSocket，`/v1/users/{user_id}/steward`，桥接到 service 在项目目录拉起的
harness 进程：Claude Code 走 `--print --input-format stream-json --output-format stream-json`，
Codex 走 `app-server` JSON-RPC。桥把两者归一为控制台渲染的一套事件词汇——一个回合、一个步骤
（命令、结果、时长）、一次权限请求、带用量的回合结束——并把所有者的消息送下去。每个 backend 的
适配器是 backend 清单上的数据（§8），与无人值守启动器读的是同一份清单；线上层面的差异（Claude 在
第一次 prompt 之后才宣布会话、Codex 不合成回合结束且报累计与最近一次两种 token、Claude 换模型必须
走 control request）住在适配器里，别处没有。

控制台一侧只在所有者视角下，紧挨着它会推动的那些视图：一个跑了 `pkc draft finish` 的步骤之后，历史
视图多出一次提交，因为二者读同一个 API。步骤就是 agent 自己的工具调用，渲染出来——控制台不添加
agent 没做的，也不隐藏它做了的。断开的标签页让 harness 会话存活 `STEWARD_SESSION_IDLE`，重连即
续接；被杀的 harness 如实报告，从不静默重启成一个新会话。

**实现阶段定下来、而 §5.6 没有写的事。**

- **第二次接入是**加入**这场会话，而不是被拒绝。** 一座知识库开两个标签页，是一个人开了两扇窗，
  两边看的是同一场对话——各自由会话自己保留的有界事件尾巴（200 条）重绘，而不是从空白开始。拒掉
  第二个标签页什么也保护不了：真正不能发生的是两个 harness 同时编译同一座知识库，而「每位所有者
  一场会话」本身就是这一条。
- **重启是一条消息，不是一次重连。**「绝不静默重启」需要给所有者的这个决定一个落脚处，于是这条
  socket 接受 `{"type":"start"}`，而只有视图上的「重新开始」会发它。会话已死之后重连拿回的还是
  那场死会话和它的记录——正因如此，页面才能先把发生了什么摆出来，再提议开一段新的。
- **交互式的启动形状同样是数据。** 清单新增了 `interactive_command`、`wire_protocol` 与
  `interactive_adapter`；模板表达不了的两件事由适配器承担——一轮用户输入怎样写进这条线，以及会话
  或 thread 的 id 怎样读回来。这里同样没有 `backends.py` 之外的地方按后端名字分支。
- **所有者的这一轮在 harness 看到它之前就写下了。** `steward_turns` 先被追加（内存与 Postgres
  各一份），因为 `pkc owner say` 是在它所引用的那一轮**里面**跑的：事后再写的记录，恰好会在被读
  的那一刻落后一轮。桥接会话若读不到记录就**拒绝**，而不是跳过这项校验——一条在无法执行时自动关
  掉自己的规则，不成其为规则。
- **桥在项目目录里跑 harness，而不是在空目录里。** 无人值守启动器的空 `mkdtemp` 之所以存在，是
  因为没有人在看；这里所有者盯着每一条命令，而 harness 需要 `AGENTS.md` / `CLAUDE.md` 和装好的
  技能包，它们都在项目里。`PNEUMA_KNOWLEDGE_PROJECT_DIR` 点名它，默认就是 API 自己的工作目录。

逐字校验（裁定 13）：桥接会话里的 `pkc owner say` 通过桥设置的环境变量拿到会话 id，向桥索取所有者
回合，拒绝任何不是其中之一的子串（空白归一后）的文本。桥之外——终端会话——该命令没有 transcript
可对，skill 里写明；陈述仍是来源、有引用、有日期，库的诚实不依赖这项校验，只有"这是所有者的话"
依赖它。

有意不做的：第二个聊天面（live context 的房间仍是它自己——库在旁听的一个房间，不是 Steward 的
对话）、面向访客的 agent、把对话存进库的任何形式。把库的控制台作为一个通用 agent 外壳里的 mode
来承载的方案被权衡过；控制台已经拥有视角模型和那些必须在 Steward 打字时就动起来的视图，所以桥来
到它这边。

### 5.7 结构——evolve 门（v1）

```
pkc evolve draft open (<job-id> | --new) [--from <proposal>]
pkc evolve draft status
pkc evolve draft propose (--file <f> | -)
pkc evolve draft move-claim <from-path> <anchor> <to-path>
pkc evolve draft rename <path> <new-path>
pkc evolve draft retire <path>
pkc evolve draft contract edit (--file <f> | -)
pkc evolve draft check
pkc evolve draft finish
pkc evolve draft abandon
pkc evolve adopt <id>
```

`open` 在队列的逐用户锁下认领 evolve 作业；`--new` 创建 Owner 主动请求的作业。它把 kind 为
`evolve` 的 `DraftSession` 放进编译使用的同一个 DraftStore，受 `COMPILE_DRAFT_TTL` 保护。
放弃与过期都释放作业，不写正本；恢复会重新打印固定的两份文本。`--from` 在原始基线上复制一份
审阅提案的工作文档与判断，不会采纳它。

任务带有当前契约、模板和 packs、近期编译事件的机械摘要、文档树、组件的 `evolve_evidence`
块。易变内容只进任务；两个 evolve 契约和门的规则构成逐字节稳定的 system message（I5）。
Steward 读证据，先提交符合 `EvolveProposal` 的第一阶段 JSON 判断，再调整结构。必填字段仍为
`packs` 与 `rationale`；可选 `retire_packs`、`rename_packs` 和完整的 `path_templates` 列表
表达现有结构的修改，`dropped_anchors` 逐个点名损失。错误 JSON、模型验证失败、未知 pack 名称
和非法模板均被拒绝。空 packs 加理由、且没有结构改动，会留下不变判断记录。

move 逐字搬移断言与引用，必要时创建空目标页；rename 保留文档身份；retire 只移除空页或已点名
将丢失锚点的页面。归档记录与关闭卷保留现有保护：闸门允许它们沿用基线中的精确路径，但内容
不得改动；带有关闭卷的页不能改名或退役。每次写入运行 evolve gate 的谓词，有新增违规
就回滚整条命令；被拒也通过编译门的共享事务花掉一次预算。家族退役期间，其页面可以暂留旧路径，
但 check 与 finish 都要求最终模板集。默认演进预算为 120 次调用；显式
`COMPILE_MAX_TOOL_CALLS` 覆盖它。finish 失败后只有一次独立预算的修复轮。

`contract edit` 接受不超过 100,000 字符的非空文本，可附带声明 `path_templates` 的契约
frontmatter。框架分配版本并将其保存在该用户的提案 manifest 中。采纳后，正本 manifest 中的
版本成为该租户注册的契约，进程重启仍然有效；它不修改其他租户的注册表，也不编辑部署的引擎文件。
契约与 schema 变化只影响未来编译，结构命令保留已有断言。

finish 运行同一个 `run_evolve_gate`，核算每个锚点与引用，再调用模型路径使用的分支和审阅记录
写入器。rename/retire 在分支里显式移除旧路径；采纳把这些删除与合并后的文件放进同一次原子提交。
`pkc evolve ls/show`、控制台和原有机械三方合并都读取普通提案。**采纳由 Owner 决定**：
`pkc evolve adopt <id>` 只排入这条合并流程。无需新增 `workflows/compile.js` 的姊妹脚本；
双语 skill 流程与 argparse 机械生成的 CLI 参考足以把这扇门教给两种宿主。

### 5.8 profile——`pkc profile`

```
pkc profile show [--json]                        每个字段及其出处；是占位符时说明
pkc profile set (--file <f>|-) | --field k=v…   --provenance inferred|owner（Steward 会话里默认 inferred，否则 owner）
pkc profile confirm --field k…                   把字段翻为 owner；--all
```

一条写路径（`persona_profile.save_owner_profile`）：引擎的 `persona/profile.yaml` 和持久化的
`UserProfile` 一起动，`provenance` 是覆盖 Steward 可设的每个字段的映射，不只三个地区键。
`render_system_contract` 把出处词渲染在每个推断值旁边（`display_name: 陈晚 (inferred)`），这就是让模型把
推断出的所有者当作假设的东西。已确认值保留原有渲染，因此全部为 owner 的档案与原来的 system 契约
逐字节相同。profile 是占位符或含未确认推断时 `pkc draft open` 打印一行提示；它不拒绝任何东西。

未知所有者用 `UserProfile.unstated()` 表示：姓名、个人事实和日期为空，`source="unstated"`，
所有可设字段的出处均为 `placeholder`。空姓名、`Someone` 和 `Owner` 都是占位姓名；仅声明行业、
没有姓名，也已经是一份档案。引擎文件中已声明字段的出处为 `owner`，空字段为 `placeholder`；
旧地区标记 `profile` 映射为 `owner`，检测所得或未声明的地区值不进入个人档案。Steward 写入的
字段在确认前保持 `inferred`，即使只设置一个字段也如此。所有者通过 API/CLI 编辑时保留
`source="user"`。加载器不补写无人声明的加入日期、开始活动日期或个人偏好。个人版把未经编辑的
引擎模板持久化为 unstated，档案是否完成由两件事推导：已不是占位符，且没有 `inferred` 字段。

skill 的首轮规则两头都有机制托底：占位符可检测，出处会被渲染。Steward 拿来推断的是它自己的东西——
harness 对所有者的记忆、材料里的第一人称、`people` 组件已经报告的称呼——skill 只说它这么做，以及之后
逐项、摊开推断地问所有者。

### 5.9 检索选择——`semantic_retrieval`

`PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL`（引擎键 `intake.semantic_retrieval`，默认 `on`）。`off`：
从不调用 `build_embeddings`，不需要 embedding key；intake 提议强制 `semantic_indexing: none`，原型选择
只给这些；索引作业写 L1、跳过 L2；fast、rag、deep、briefing 各 lane 和 live context 不跑向量臂、不产
片段摘要（词法臂和 claim 面承担回答；响应的阶段计时把这些臂标为 `skipped` 而非失败）；
`rebuild_derived` 跳过 L2。`pkc config set semantic_retrieval on|off` 写引擎旋钮（爆炸半径
`restart` + `derived_rebuild`）。`embedding_key.py` 的启动提醒变成 Steward 能回答的问题：没有 key 且
选择为 `on` 时，`pkc` 说明两处编辑中哪一处能解决。

### 5.10 家——`~/.pkc`

个人版：库之上的一个应用，每台机器一套共享基础设施，库作为它上面的租户，skill 装进 harness 而不是
项目，每个选择和每个初始化步骤在 `~/.pkc` 下记录一次，之后的会话不再问。它自己的命令是 `pkchome`；
`pkc` 仍是库的，不为它添一个字。它有自己的一页：
[single-machine-edition.zh-CN.md](single-machine-edition.zh-CN.md)；profile 流程（§5.8）和检索选择
（§5.9）是它冷启动要问的两个问题。

### 5.11 技能包——`pkc skill`

```
pkc skill install [--backend codex|claude-code|all] [--project <目录>]     文件装进项目，外加那个路由块
pkc skill render --out <目录> [--backend …] [--language en|zh] [--force]   同一份包写进一个目录；什么都不安装，不碰指令文件
pkc skill verify [--backend …] [--project <目录> | --dir <目录>]           重新渲染并逐字节比对；有漂移就列出并以 4 退出
pkc skill show [--backend …] [--project <目录>]                            哈希、契约与文件清单
pkc skill probe [--backend …] [--deadline <秒>]                            harness 是否活着？不可用则以 4 退出
```

`render` 就是不安装的 install，面向被人读的那份包，而不是 harness 打开的那个项目：个人版正是用它把
每个库的参考包渲染到 `~/.pkc/libraries/<name>/skill/` 下
（[single-machine-edition.zh-CN.md](single-machine-edition.zh-CN.md) §4.9）。同一次部署解析、同一次
渲染调用、同一份 `skill-version.json`，所以它打印的哈希就是 `install` 会盖下的那一个——这正是它是这
条命令而不是第二个渲染器的原因。`verify --dir` 对那个目录问同一个新鲜度问题，只是少了路由块：那里
没有指令文件可以承载它。包里*有什么*，见 §7。

### 5.12 片段——索引门

片段判断是 agent 在编译前做的一步。index 作业仍无条件写 L1。语义检索开启且来源 IntakePlan
要求 L2（`full` 或 `summary`）时，agent compile 执行器为此来源入队一个 `episodes` 作业；
当前每个 index 作业本来就恰好持有一个来源。它绝不用机械切分代替 agent 的判断。
已有匹配的留存清单就重放；index 重试不会重复创建尚未完成的 episodes 作业。
检索关闭或来源计划为 `none` 时不建 episodes 作业。API 执行器的模型路径与无 key 回退保持原样。
编译读 L0，绝不等待 episodes；技能中的阅读顺序不增加队列依赖。

```
pkc index episodes open <job>
pkc index episodes status
pkc index episodes propose (--file <f> | -)
pkc index episodes finish
pkc index episodes abandon
```

`open` 认领来源作业，在 compile、evolve 共用的 Postgres DraftStore 中持久化 kind 为 `episodes`
的草稿。它打印结构图、每个带编号的块及契约携带的 role/kind 元数据、片段规则与预算。
规则文本字节稳定；来源内容和预算放在任务里。共享的命令事务对拒绝计费、回滚被拒提案，复用
compile 的预算、退出码和 TTL。`status` 免费，`abandon` 释放认领。finish 时没有提案会获得一轮
修复预算，再次缺失则中止：沉默永不等于空选择。

`propose` 用 `{"start": a, "end": b, "title": "…", "description": "…"}` 对象数组替换完整选择。
分块器的门检查真实且有序的端点、严格递增的起点、相邻最多共享三块、片段数不超过块数。
**这里明确去掉无缝隙覆盖要求。** 写入时逐项列出所有违规；标题和描述必须非空且有界；
未覆盖块列为 `no episode`。`[]` 是有效且明确的判断。agent 根据所给块撰写描述；
机械保证是真实的来源坐标和派生表示，不是对生成文字的语义真伪检验。这里不写 L0 或正本。

`finish` 写同一张 `chunk_manifests` 表和语义重放键（租户、来源、compile 执行器规格、内容摘要）。
v3 信封明确记录 `producer: agent`、`coverage: partial`、smart 重叠、执行器和 `Executor-Skill`
哈希，以及本次观察使用的细分设置。哈希来自已安装的 shim 或技能包；缺少此身份的 finish 被拒，
不编造归因。agent 区间始终使用这套 smart 重叠契约；API 的 `semantic_overlap` 旋钮不会重新解释它们。
重建读取记录（包括空数组），绝不填补空隙、调用模型或改写记录。按章节细分和长片段再切分仍是
机械操作，不能把覆盖范围伸入被省略的块。

嵌入步骤生成普通 raw 与 episode 向量，仅替换此租户、此来源的 L2 点，避免旧向量在省略后残留。
清单发布后若嵌入或向量存储失败，留存判断仍在；重试 finish（包括 abandon 或 TTL 恢复后）
继续同一份记录，而不接受新提案。打开的一轮中途关闭语义检索时，finish 保留清单但不建向量；
日后重建可以重放它。

交互作业等待 `open`；无人值守作业复用 compile、evolve 的启动器和草稿生命周期，任务文本为
`steward.unattended.episodes_task`。生成技能增加「编译前的片段划分」，`references/cli.md`
从当前解析器自动获得全部动词。

## 6. 磁盘上的 draft

`PatchDraft` 今天是内存对象：基础文档、工作文档、已读标记、路径模板、总览预算。它获得
`to_state()` / `from_state()`，落成一个 JSON 文档，同时携带 runner 在它旁边持有的东西：作业 id 与
用户、来源句柄映射（`sNN` ↔ 真实 id）、轮次（`first` / `repair`）、已花调用数与本轮预算、低水位
提示是否已给、渲染任务的哈希——于是在一份契约下打开的 draft 不能在另一份契约下 finish。它住在
Postgres 里，每作业一行（`compile_drafts(user_id, job_id, state, round, updated_at)`），紧挨着它所
属的队列：管作业的每用户锁、TTL、自愈在同一处管它们的 draft，draft 永不触碰 `engine/` 或正本。
core 定义状态形式；service 的 Postgres 适配器存它。

**一份 draft，一个执行者。** `state` 中的 session 还记录不透明的 `executor`、`opened_at` 和
打开时的 worker 姿态；这与作业用于用量记账的 `agent:<backend>` 标签不同。CLI 优先使用
`PKC_DRAFT_EXECUTOR`，否则由已安装 skill 的哈希与 shim 导出的 Steward 会话令牌生成身份
（`PKC_STEWARD_SESSION`，使用 harness 的线程 id，或父 shell 的 pid 与主机名）；没有会话信息的
直接 CLI 调用退回 `pid@host`。无人值守 runner 生成 `worker:<harness>:<launch id>`，将同一令牌
导出给所有子命令，包括修复轮。再次 `open` 只允许该执行者续接；其他执行者得到退出码 2，点名持有者、
打开时间、空闲秒数、worker 姿态和恢复命令。status、读写、check、finish 与 abandon 都检查同一归属。
没有 executor 的旧 draft 视为 `legacy:unknown` 持有，不能被静默接手。

`pkc draft abandon --take-over`（evolve 与 episodes 门同样支持）显式丢弃另一执行者的草稿并释放
作业。草稿空闲不足 `max(60, COMPILE_DRAFT_TTL / 12)` 秒时拒绝接管，除非持有它的 worker 启动实例
已消失。作业的运行 payload 记录原持有者、接管者、时间和机械判定的原因；临时草稿删除后审计仍在。
每租户的 PG advisory lock 将整条命令（包括 gate 和提交）与接管、恢复串行化，已经执行中的命令不会
在写入中途失去归属。

两条命令把握生命周期。`open` 以 worker 同样的方式领取作业（`FOR UPDATE SKIP LOCKED`，每用户一个
在飞作业），所以不论 Steward 是哪具身体，每用户单写者都成立；被 draft 持有的作业对 worker 不可见。
`finish` 重放今天 `run_compile` 结尾做的事：总览下限、gate、带 skill trailer 的 `commit_patch`、
`derive_events`、简报；有违规时把修复预算写进 draft 并返回它们。被放弃或过期的 draft——队列自愈把
超过 `COMPILE_DRAFT_TTL` 的 draft 视为孤儿——释放作业。
worker 启动实例在整轮运行期间持有独立的 PG advisory lease，进程死亡就会释放该租约。启动恢复保留
仍存活的实例，直到完整 TTL 过期；即使空闲超过接管宽限也不回收，已死亡的实例则立即重新入队。
TTL 为零时关闭空闲草稿保护，但活着的启动实例仍受租约保护。领取查询拒绝任何已有草稿的租户，即使
其队列行曾被错误地重新入队。已完成作业不能再次认领，也不能通过 `claim=False` 重开；迟到的完成
调用保留既有结果，worker 的迟到失败只能结束它自己的 claim。runner 同时固定作业 id 与执行者，
因此 finish 后返回也不能操作该租户的下一份草稿。
worker 的失败收尾在同一把锁下只删除它自己的终态草稿；启动恢复也会清理此前崩溃留下的终态草稿，
不会重新打开对应作业。

**字节相等是验收测试。** 同一个工具调用序列，一次经 scripted 模型走 langchain 循环，一次经
`pkc draft` 命令，产出同样的提交文件、同样的事件、同样的违规。这条测试在 CLI 有用户之前就存在。

第二处差异，也是 CLI 先做出的改进：langchain 循环只在 `finish` 处过 gate，一条悬空的 claim 可以
在 draft 里躺一整轮；CLI 对每次写入触碰的页面过 gate（裁定 10）。最终 gate 相同，所以提交结果的
字节相等成立；不同的是一次错误写入多早被点名，langchain 循环日后可以采用同样的逐调用检查而不改变
结果。

一处明说的差异。langchain 循环在一轮中间以 human 消息投递低水位提示；CLI 无法在 agent 的回合之间
说话。提示改为追加到越线那次写入的结果里，并在 `status` 里重复。两种渲染来自同一个 catalog 键；
两种执行器分别钉住。

## 7. skill 包

由 `scaffold/init.py` 生成，每次 engine apply 重新生成，输入与渲染编译 system 消息的相同：组合后
的契约、prompt 语言与 overlay、启用的组件。爆炸半径 `future_compiles`。布局遵循 harness 自己的
约定，而约定是 backend 清单上的数据（§8）：

```
.agents/skills/pkc-steward/            Codex           .claude/skills/pkc-steward/   Claude Code
  SKILL.md                             路线：你是谁、阅读、一轮怎么走、门、两种姿态、owner 说话、归档
  references/consume.md                知识库设计、阅读原语、已解析的领域族和咨询流程
  references/contract.md               组合后的契约，逐字
  references/compile-instructions.md   渲染后的编译 system 消息，逐字
  references/cli.md                    每条命令、描述、拒绝什么、退出码
  references/gate.md                   `finish` 拒绝什么，作为事实
  scripts/pkc                          垫片
  workflows/compile.js                 仅 Claude Code：读 → 计划 → 写 → finish 作为工作顺序
AGENTS.md / CLAUDE.md                  一个 `pkc:start … pkc:end` 块：这是一座库、你是它的 Steward、skill 在 <path>
```

`references/consume.md` 从 prompt catalog 的 `steward.consume.*` 渲染，族和 `owner_voice`
标记从已解析契约的路径模板枚举。它明确教三个时刻：会话开始用完整的 `pkc outline`；回答时
用 outline 找页面、`canonical read` 读页面、`recall --evidence` 取 fast 通道证据、`search`
查名字和原句、`source fetch` 核对原文事实。仅当 outline 太长、难以扫读时，才使用有预算的
`glance`。`draft finish` 后，对每个写入过的族运行 `outline --family <template>`，查看新页面
的落点。这三个时刻也出现在 SKILL.md 路线中，包括编译轮次的前后步骤。两条命令的描述来自
双语 catalog，同时出现在 CLI 帮助和 `references/cli.md`，完整与有预算的差别在命令处可见。
它计入包哈希，不向 system 消息加入内容（I5）。阅读通过
`pkc` 原语沿引用和链接进行；`recall --evidence` 汇集上下文而不构建 chat model，
`consult answer` 为交接时已开场的咨询追加答案。关闭语义检索时也不构建 embedding。Outline、glance 和证据读取
组合后的契约，不推导 pack，也不写 manifest。

SKILL.md 能写什么不能写什么，遵循一条检验，与 compile-contract 指南给契约作者的那条相同：*违反
它会让写入被拒的，是机制，作为关于门的事实来描述；只有读者能分辨对错的，是判断，属于契约。*
所以 skill 承载流程——open、读任务、读你要触碰的页、写、不确定时 `status`、`finish`、修复一次——
每种拒绝的描述、两种姿态，以及那句 Steward 做不到什么（删除、不经作业编辑）。它不含"记得引用"。归档自己那一节（§5.5）是同一条检验又用了一遍：那个次序和那两次拒绝都是门的，
而"不要搬动 `archive/` 之下的任何东西"是「你做不到的事」里多出的一行——闸门以 `archived_path`
拒掉它。
一条测试在生成的 SKILL.md 里 grep catalog 的拒绝文本、断言每条都被描述，并 grep 项目禁用的命令
式（"always"、"never forget"），断言引用的拒绝文本之外一处不出现。

`pkc:start` 块是路由不是规则书：这个目录是什么、skill 在哪、以及 harness 需要的那一条"从项目而非
全局缓存读 skill 文件"。它被拼接在 marker 之间，从不触碰 marker 之外的文本；重新生成替换该块，
所有者自己的 `AGENTS.md` 文字原样不动。

skill 包的 sha256 盖进 agent 执行器产生的每一次正本提交，作为 overlay 哈希旁的 `Executor-Skill:`。
一条 freshness 测试从 catalog 渲染包并断言它等于已安装的那份，于是一个偏离了 catalog 的 skill 会
让套件变红，而不是在不同的措辞下编译。

版本：安装旁的 `skill-version.json` 记录框架版本、包哈希、后端，以及渲染时所用的语言包；
`pkc skill install` 重新生成；正在运行的会话看不到被改写的 skill 或 workflow，重启才见，skill
里写明这一点。

**真正落地的实现与上面的草图有六处不同**，每一处都是代码这么说的：

- workflow 装到清单的 `workflows_dir`（`.claude/workflows/compile.js`），而不是像上面那棵树画的
  那样装在技能目录里：宿主是去那儿找它的。包里仍然把它渲染在 `workflows/` 之下，由安装器把两者
  对上，所以「能不能装 workflow」仍然全部由 `workflows_dir is None` 回答。
- `skill-version.json` 放在技能目录**旁边**（`<技能目录>/skill-version.json`）而不是里面，因为
  安装会整体清空那个目录，否则会把关于它自己的记录一起带走。
- workflow 脚本没有 shell，也没有文件系统。所以 Open 与 Finish 这两个「脚本步骤」是单一用途的
  agent，整段提示词就是「跑这一条命令、把输出还回来」。阶段——因而工作顺序——完全按设计强制；
  workflow 唯一给不了的是一个步骤*内部*的确定性。
- 脚手架产出的 `bin/pkc` 是一个两行的指路牌，指向已安装技能里那个 `scripts/pkc`，而不是第二个
  shim。shim 只有一份，由框架渲染；人打的那个短名字指向它。
- 技能包是按**部署**渲染的，不是按租户：`pkc skill` 只读引擎目录、从不碰数据库，这正是 `init.py`
  能把它装进一个从未启动过的项目的原因。组合契约在租户的正本仓库已经落盘时从那里读回，没有时回落
  到部署的基座——与 `path_templates_for` 同一套解析，只是高一层。
- 框架自己不注册任何契约，所以 `pkc skill install` 需要一个框架侧的引擎 `compile/contract.md`
  读取器（`engine/contract.py`）。它是兜底：已经注册过契约的进程保留自己的那份。

## 8. Backend

每个 harness 一份清单，数据优先：

| | codex | claude-code |
|---|---|---|
| 二进制 | `codex` | `claude` |
| skill 目录 / 指令文件 | `.agents/skills` / `AGENTS.md` | `.claude/skills` / `CLAUDE.md` |
| workflow 目录 | — | `.claude/workflows` |
| 探针 | `codex login status` 退出 0 | `claude -p ping --output-format text` 在期限内答复 |
| 无头启动 | `codex exec --skip-git-repo-check --color never --json --sandbox workspace-write -c sandbox_workspace_write.network_access=true [-m <model>] --output-last-message <f> -` | `claude -p --output-format json --tools "Bash,Read" --permission-mode bypassPermissions [--model <m>] --add-dir <project> --system-prompt-file <f>` |
| system 文本 | 前置到 stdin（无 system 通道） | `--system-prompt-file`，替换 harness 自己的前言 |
| 用量 | `--json` 事件里的 token 数；无价格 | `result.usage` 与 `total_cost_usd` |
| 会话 | 每轮新线程；修复轮是每作业 `CODEX_HOME` 下的 `codex exec resume --last`，不支持则新进程喂违规 | 每作业独立 `CLAUDE_CONFIG_DIR` 下 `--resume <session>`（取自 `result.session_id`），随 draft 删除 |
| owner 自己敲的：交互会话 | `codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true` | `claude` —— 无需额外参数；它问的时候放行 Bash |
| owner 自己敲的：一条指令 | `codex exec --skip-git-repo-check --sandbox workspace-write -c sandbox_workspace_write.network_access=true "…"` | `claude -p --permission-mode bypassPermissions "…"` |

最后两行之所以落在 manifest 上，是因为端到端验收发现它是这个特性最大的一个缺口：**宿主以默认姿态
启动时，连不上项目自己的 Postgres**，于是 `pkc` 在抵达知识库之前就失败，§3 的那个头号体验——owner
在项目目录里打开 Codex，敲一句「把待编译的编译掉」——开箱即坏。Codex 默认把文件系统和网络都关进
沙箱；Claude Code 两者都不关，而是当场问你，所以它的交互一栏是空的，只有一次性的 `-p` 形态需要一个
权限模式（那时没有人可问）。这些参数只在三个地方出现，且全部由这两个字段渲染：`pkc:start` 路由块、
`SKILL.md` 的姿态一节、以及生成出来的项目 README——生成器在生成结束时也会打印一次。没有任何地方重
敲它们。

**无人值守启动器**（拓扑 2.8）负责 harness 不会替你做的事：每轮的墙钟超时（复用
`COMPILE_CALL_TIMEOUT`）、对表示限流的退出码与消息做带抖动的退避、一个只装垫片和项目 `.env`
路径的全新 `mkdtemp` 工作目录、进程作为独立进程组启动并在 worker 退出时 TERM→KILL 收割、从
harness 的 JSON 结果把用量读进作业记录。prompt 经 stdin 从文件进入，从不进 argv。启动时探针失败
是致命的并点名缺什么；未知的协议表面降级并记录；版本号从不比较。

**交互姿态**下这些都不跑：所有者的 harness 已经开着，skill 就是启动器。
`PNEUMA_KNOWLEDGE_AGENT_UNATTENDED` 决定 worker 取哪一种姿态，默认无人值守——因为 worker 按定
义就是无人值守的。

实现阶段定下来、而上表没有写的四件事，每一件都是清单上的数据，而不是任何地方的分支：

- **给 harness 一个 shell，而不是整个世界。** 本启动器所参照的单发 leaf 用 `--tools ""` 跑
  Claude；编译轮次不能这样，因为跑 `pkc` **就是**这一轮。于是：Claude 用
  `--tools "Bash,Read"` 加 `--permission-mode bypassPermissions`（无人值守、目录为空，弹出的
  权限询问没有人来回答），Codex 用 `--sandbox workspace-write` 并放开网络——它可以执行，而唯一
  能写的地方是启动器新建的那个空工作目录。
- **密闭的配置目录管的是会话，不是凭据。** 挪动 `CODEX_HOME` / `CLAUDE_CONFIG_DIR` 等于挪走
  harness 的整个世界，空的那一个就是一个突然退了登录的 harness。清单点名哪些文件必须在
  （`auth.json`、`config.toml`；`.credentials.json`、`settings.json`），启动器把它们从所有者
  真正的家目录**链接**进来：没有任何密钥被复制进临时目录，这一轮刷新的 token 就刷新在所有者自
  己的会话之后会读到的地方，而其余一切——会话、日志、缓存——都落在每作业目录里，随作业一起消失。
- **子进程里 `CLAUDECODE` 被取消设置。** Claude Code 会话一旦发现它被设了就认为自己是嵌套的并
  短路返回，于是从一个 Claude 会话里启动的 worker 拉起的每一轮都会什么也不做。
- **两家提供方，两套 token 词汇。** Anthropic 把缓存读写报在 `input_tokens` **之外**，所以要
  相加；OpenAI 把 `cached_input_tokens` 报成 `input_tokens` 里被缓存的那一**部分**、把
  `reasoning_output_tokens` 报成输出里推理的那一部分，相加就会重复计数。Codex 在
  `turn.completed` 上报出它的计数；若某个版本报的是累计的 `total_token_usage`，那么最后一条就
  是总数。什么都没找到就是 `usage is None`——绝不是零。

harness 自己的工具能碰到什么，明说而不假设。无人值守时工作目录是空的，被限制到 Bash 与 Read
（Claude）或只能写这个空目录的沙箱（Codex），让 `pkc` 垫片成为唯一的手。交互时 agent 坐在项目里，可以编辑 `data/` 下的文件；
那里的门不是一条约定，而是两次机械的拒绝。一处**尚未提交**的改动在任何写入之前就被正本适配器拒
掉：每一个改动方法都先记下自己即将触碰的足迹，而一棵脏树只有在它的占用者被证明已经不在、且每一
条脏路径都落在那枚占用记下的足迹之内时才会被回收——其余一概是 `canonical_dirty`，点名那些路径，
什么都没有写（[archive.zh-CN.md](archive.zh-CN.md) §3.1）。一次**已经提交**的改动则在 `pkc draft
open` 处被抓住：它拒绝在 HEAD 缺少框架 trailer 的仓库上打开 draft，并点名那次提交。于是一次绕过
gate 的写入在下一轮建立在它上面之前就被拦住，而不是被叠加。

## 9. 接到哪里

- **`agent:<backend>` 作为 model spec。** `resolve_model_name` 原样返回；`build_chat_model_for`
  拒绝据此构造 chat model（执行器不是模型），compile worker 改问 `executor_for(settings,
  role)`，支持 compile 和 evolve。其他角色显式写 `agent:` 会在启动时失败。
  episodes 共享 compile 的执行器并有自己的草稿门；该执行器下跳过 challenge，agent 自己提供简报。
- **core 里的 `RoundRunner`。** `run_compile` 保留循环周围的一切——别名、`prepare`、draft、gate、
  提交——把循环委托给一个只有一个方法的协议：在预算下对一份 draft 的工具面跑一轮，返回花掉的调用、
  是否被截断、用量。`LangchainRoundRunner` 就是今天的 `tool_loop`，挪了个位置。CLI 执行器不在进程
  内实现它：worker 的 `AgentRoundRunner` 把 draft 写到盘上、拉起 harness、等待、再把 draft 读回。
  core 知道协议和 draft 的状态形式；子进程住在 service。
- **无人值守那一轮在哪里收尾，以及为什么不是 `run_compile`。** `RoundRunner` 接一份消息列表和一
  个工具面、返回这一轮花了多少——当循环和 draft 活在同一次函数调用里时这个形状有意义，当 draft
  活在 `DraftStore` 里、调用由另一个进程敲出来时它就没有意义了。从 worker 里驱动 `run_compile`
  意味着造一份没人读的消息列表和一个没人调的工具面，好让它的 `finalize_compile` 在 harness 已经
  收过尾的 draft 上再收一次尾。那是一轮假的轮次，也是第二条终结 draft 的代码路径。所以无人值守
  的 worker 绕过 `run_compile`：它用 CLI 自己的 `open_round` 打开 draft、拉起进程，然后读存储
  ——draft 没了，且作业行确认完成，才说明 harness 已经 finish；草稿被释放或被另一执行者接管时，
  本次启动的权限已经结束。仍属于自己的 draft 还开着，说明它停下了，
  由 worker 跑同一个 `cmd_finish`，于是 gate 照样判；draft 开在 `repair`（或被 overview 下限
  拒掉），就再拉起一次、带上 gate 说过的话，然后再 `cmd_finish`，第二次失败与今天一样中止。
  `cmd_finish` 是唯一终结 draft 的函数，不论谁来调。归属与终态检查阻止迟到的 runner 重开已完成
  作业，或结束接替执行者的草稿。
- **`open` 在领取之前先审计库的 HEAD。** 本框架的每一条正本写入通道都会盖上 `Skill-Version`
  trailer，所以没有 trailer 的 HEAD 就是一次不是这里做出的提交：`pkc draft open` 以退出码 2 拒
  绝，并点名那次提交和它的标题，而不是在一次无从归因的改动上继续堆断言。没有任何提交的仓库正常
  打开——git 适配器只跑 `git init`、不自己造 bootstrap 提交，所以「没有提交」是唯一被豁免的状态。
- **API。** 增加 Steward WebSocket 与桥（§5.6）。API 对库仍是无状态的；它持有的是每个所有者会话
  一个 harness 进程句柄，如同 live-context socket 已经持有一次运行——对话住在 harness 的会话里，
  不住在 API 里。
- **worker。** agent 执行器下，compile、evolve、episodes 作业交给同一个启动器（无人值守），
  或留在队列里等各自的 open（交互）。每次启动重新读取并记录 `PNEUMA_KNOWLEDGE_AGENT_UNATTENDED`。
  认领之前会跳过 Steward 持有的草稿，对每个持有者只记录一次日志；SQL 领取查询执行同样的排除。
  重复 `open` 只允许同一执行者续接，其他执行者会被拒绝并看到持有它的 worker 已记录的姿态。
  index 写 L1 并入队片段判断（§5.12）；投影和重建仍是机械工作。
- **`engine.yaml` 与控制台。** `models.compile: agent:codex` 是和其他一样的策略值；引擎 schema 增加
  `agent:` 形式，控制台在旁边显示探针结果，流程视图增加"等待 Steward"状态。
- **单次角色（v2）。** 同一启动器之上的 `LeafChatModel` 让 `agent:` 可用于 fast、live：system 文本走 harness 的 system 通道，消息走 stdin，结构化输出以 prompt 里的 schema 加
  pydantic 模型校验、一次重问。不在 v1；形状写明，是为了清单和启动器只造一次。

## 10. 不变量与纪律

- **I1。** 每条命令从项目或唯一的 `--user` 旗标得到用户；draft 文件按作业键、作业按用户键；
  `open` 经 worker 同一把每用户锁领取。
- **I2 / I7。** draft 是临时物，既非权威亦非记录；skill 包从 catalog 派生、apply 时重建；组件不动。
- **I3。** 保证的内容不变：没有任何 plan 或策略决定可达性。归档是所有者的决定，作为默认施加、一个
  旗标撤回；按定位符的 `fetch`、`source show`、`canonical read` 与 `canonical history` 从不过滤。
- **I4。** CLI 只说 `source_id ¶a-b` 和 `c:xxxx`；`recall --evidence` 发出的是 lane 同样的查询局部
  句柄。
- **I5。** agent 收到的 system 文本是字节稳定的契约；Claude Code 上替换 harness 前言，Codex 上作为
  stdin 开头。任务内容留在任务里。交互姿态从 `open` 的输出读到同样的字节。
- **I6。** 不变；eval 包不知道执行器。
- **机制优于说服。** skill 里每个"必须"都是 CLI 里的一次拒绝；§7 的测试把二者钉在一起。
- **成本与质量分开。** agent 编译的库只在同语料、同契约、同 harness 下与 API 编译的库比较；本页
  不声称任何质量差异。

## 11. 测试与实施顺序

默认无 key，与套件其余部分一致：

- **字节相等**（§6）：langchain 循环与 `pkc draft` 在同一 scripted 工具序列上——第一条写的测试。
- **拒绝一致**：工具抛出的每个 `AnchorToolError` 经 CLI 以同样文本和退出码复现。
- **假 harness**：`PATH` 上一个 `codex` 和一个 `claude`，重放一段记录好的 `pkc draft` 命令序列，
  于是无人值守启动器、超时、退避、用量捕获都无需订阅即可练到——`scripted:` 的思路往外挪一个进程。
- **skill 新鲜度与内容**：生成包等于一次新渲染；拒绝文本被描述；禁用命令式不出现。
- **实机套件**，由 `PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT=codex` 门住，在默认 testpaths 之外：对 scaffold
  演示材料做一次真实编译。

顺序，全程 Codex 优先：

1. `PatchDraft` 状态形式；`pkc draft` 命令；`open`/`finish` 生命周期；字节相等。
2. 抽出 `RoundRunner`；`agent:` model spec；worker 行为；流程视图状态。
3. 逐命令后置检查、`pkc draft check`、`pkc library check`；读命令、`owner say`、`pkc ingest`。
   （原本挂在这一步的归档那张脸移到了第 5c 步——等机制自己先在 `main` 落地之后。）
4. skill 包生成器；scaffold 集成；`pkc:start` 块；trailer 哈希；freshness 测试。
5. Codex 清单、探针、无人值守启动器、假 harness；然后 Claude Code 清单与 workflow。**已完成。**
   两份清单都已填好；`pkc skill probe` 报活性；启动器负责超时、退避、收割与用量；agent 轮次执行
   器与 worker 的无人值守姿态让每一轮都经由同一个 `cmd_finish` 收尾；`open` 审计 HEAD 的
   trailer。无 key 的覆盖跑在 `PATH` 上的假 `codex` / `claude` 之上；一条集成测试用真实子进程对
   Postgres 跑完整一轮；`PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT=codex uv run pytest tests/live` 用真实
   CLI 编译一份极小的样本，位于默认 testpaths 之外。
5b. 控制台的 Steward 视图：先 Codex 桥、再 Claude Code；`owner say` 的逐字校验；重连续接。
   **已完成。** API 进程里每位所有者一个 `StewardSession`，在 `PROJECT_DIR` 里拉起，沿用启动器
   自己的密闭配置目录并取消设置 `CLAUDECODE`；两个适配器把两条线归一为一套九个事件的词汇；
   `WS /v1/users/{id}/steward` 接入即发 `snapshot`，另有一个 `GET` 供视图画空态 / 禁用态；所有者
   视角下的视图把每个步骤渲染成 agent 自己的命令、结果折在它下面；五条会改动知识库的命令让版次、
   工序、来源三视图无需刷新就动起来；`pkc owner say` 拒绝任何不是所有者某一轮逐字子串的文本。
   全程无密钥：第 5 步那两个假的 `codex` / `claude` 增加了交互模式，在 `PATH` 上说的是真协议。
5c. 这道门上的归档（§5.5）。**已完成。** `pkc archive propose / confirm / ls / show / drop /
   inventory` 跑在 `archive_service` 自己的函数之上；两条 Steward 姿态规则——propose 与 confirm 都
   要所有者的原话，默认只确认种子而把算出来的牵连项列出并留在原地；`pkc glance`、`pkc canonical
   ls`、`pkc source ls`、`pkc search` 与 `pkc recall` 两张脸上的 `--include-archived`，按线上的方式
   打标，并经 `--evidence` 的交接一路带进咨询记录；以及 skill 里属于它的那一节，和其他每一节一样由
   catalog 双语渲染出来。
6. 在 Codex 上对演示语料实跑；然后以 OPC 语料对 API 执行器做同 harness 比较，记录进
   `examples/opc/build-record/`。
7. 文档：本页保持现行，[configuration](../reference/configuration.zh-CN.md)，
   [architecture](../architecture.zh-CN.md) §6/§10 各一段，scaffold 指南。

## 12. 追溯

| 故事 | 机制 |
|---|---|
| 2.1–2.3 | `pkc owner say` → owner-dialogue 来源 → gate 下的 `pkc draft`（§5.3、§5.2） |
| 2.4 | 没有删除命令；skill 的"你做不到什么"里的拒绝文本（§5.2、§7） |
| 2.5、2.6 | evolve 门（§5.7），v1 |
| 2.5b、2.5b′ | 上游的归档（一次搬移 + 一页记录，`include_archived` 贯穿每条 lane），经 `pkc archive propose / confirm / ls / show / drop / inventory` 抵达，外加读命令上的 `--include-archived`；两条门上的规则：要所有者的原话、默认只确认种子（§5.5） |
| 2.5c–2.5e | `pkc ingest`、`steward/` 领地、内容身份幂等、凭据不进任务文件（§5.4） |
| 2.5f–2.5h | Steward 视图：harness 会话之上的桥、步骤即 agent 自己的命令、`owner say` 逐字校验、重连续接（§5.6） |
| 2.18b | 逐命令用 gate 谓词后置检查、失败回滚；`pkc draft check`、`pkc library check`（§5.1、§5.2） |
| 2.7 | `init.py` 在 key 提问旁的执行器提问、探针、skill 安装（§3、§7、§8） |
| 2.8、2.22 | 无人值守启动器、`agent:` 下的 worker（§8、§9） |
| 2.9 | 交互姿态：同样的命令、同一份 draft（§5.2、§6） |
| 2.10、2.11 | `agent:` model spec、爆炸半径、作业记录上的执行器（§9、§4.1） |
| 2.12 | `pkc recall --evidence`，递交即记咨询（§5.1） |
| 2.13、2.14 | `pkc brief`、`pkc source fetch`（§5.1） |
| 2.15 | 无人值守从 harness JSON 取用量；交互时缺席（§8） |
| 2.16 | 现有快照回退，经 CLI 到达（§5.1） |
| 2.17–2.20 | draft 生命周期、拒绝、预算、finish（§5.2、§6） |
| 2.21 | 读命令（§5.1） |
| 2.24 | 流程视图的等待状态（§9） |
| 2.25 | `rebuild_derived` 不变 |
| 2.26、2.30 | 带出处的 `pkc profile set/confirm`，渲染进编译 system 消息；实质事实只经 `owner say`（§5.8） |
| 2.27 | `semantic_retrieval` 引擎旋钮，intake、索引与每条 lane 的 off 路径，`pkc config set`（§5.9） |
| 2.28、2.29 | 带初始化状态的 `~/.pkc` 登记表、`pkc home status` 探测、全局 `pkc-steward` skill（§5.10） |

## 13. 边界，以及之后

- **单次角色跑在 agent 上**（§9）仍推到 v2。结构演进已通过 evolve 草稿门运行（§5.7）。
- **常设任务是 Steward 的，不是框架的。** 框架提供 `pkc ingest` 和五个契约；它不排期、不抓取、
  不整形、不知道任务存在。所有者想跨部署共享的任务是一个待分发的 skill，不是一个待加的框架功能。
- **家持有状态，从不持有知识。** `~/.pkc` 记住项目、选择和凭据；它没有来源、claim 或记录。第二台
  机器从空的家开始，一个项目目录没有家也是完整的。
- **退役不是移除。** 归档把页和来源移出 lane 默认读的内容，并在这一页原来站的地方留下一页记录；
  没有任何东西把一条 claim 移出账本、把一个字节移出 L0，来源删除仍未设计。要改机制本身——默认句子
  说什么、脏树怎么恢复——归 [archive.zh-CN.md](archive.zh-CN.md)，不归这道门。
- **Steward 记忆**留在框架放下它的地方：CLI 暴露保留的记录；本页不给 agent 任何超出 harness 会话
  的自有记忆。
- **本地 embedding 适配器**能让无 key 部署在 L2 也完整；那是单独的 feature。
- **Kimi** 等它的无头模式能承载结构化流程并报 token。
- **来源删除**（移除 L0 及一切引用它之物的隐私请求）不在此设计；Steward 做不了。
- **订阅条款与限额**是提供方的。启动器退避并汇报；不绕过它们。
