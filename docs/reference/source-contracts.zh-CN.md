# 输入契约（v1）

[English](source-contracts.md) | **简体中文**

官方输入边界是六种版本化、provider 中立的 JSON 契约——会议、文档库、IM、邮件、所有者对话、代理会话。能说其中一种契约的东西就能喂进系统；从具体 provider 格式到契约的转换器在契约之外（见[导入](#导入)）。

- 一个 payload，一个 `schema` 判别字段：`pneuma.source.meeting/v1`、`pneuma.source.document-library/v1`、`pneuma.source.im/v1`、`pneuma.source.email/v1`、`pneuma.source.owner-dialogue/v1`、`pneuma.source.agent-session/v1`。
- 校验是严格的（`extra="forbid"`）：未知字段直接拒绝，不是忽略。权威定义是 [`ingest/source_contracts.py`](../../packages/pneuma-knowledge-core/src/pneuma_knowledge_core/ingest/source_contracts.py) 里的 Pydantic 模型；[`source-contracts/`](source-contracts/) 下的 JSON Schema 是它的线上镜像，供工具链使用。
- **所有时间戳必须带显式时区偏移。** naive datetime 过不了校验。
- id 在各自作用域内唯一。声明了封闭身份集合、并据以解析每个引用的有两种契约：`meeting/v1`（发言人与 owner id ⊆ `participants`）和 `im/v1`（会话成员与发送者 ⊆ `users`）。`email/v1` 只对 `owner_addresses` 做归一，不声明名册；`document-library/v1`、`owner-dialogue/v1` 与 `agent-session/v1` 不声明身份集合——一段对话把 `owner_id` / `steward_id` 留在信封里，给编译器看的是**角色**，不是 id。
- 每个 payload 的信封都有自由的 `metadata` 对象，装 provider 的附加信息。信封以下则因契约而异：`im/v1` 在会话、消息、图片上各有一个，`email/v1` 在线程与消息上有，`document-library/v1` 在文档上有，而 `meeting/v1`、`owner-dialogue/v1` 与 `agent-session/v1` 在信封以下没有；代理会话的 metadata 同样禁止工具数据。

**展开。** 一个 payload 是一个包，按天然引用边界展开成多个 source：会议保持一个；文档库每篇文档一个；IM 归档每个会话一个；邮件归档每条线程一个；一段所有者对话就是一次陈述，保持一个；一次代理会话保持一个。source id 按内容寻址（sha256），重复导入相同内容会去重，不会重复入库。

## `pneuma.source.meeting/v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | 字面量 | `pneuma.source.meeting/v1` |
| `provider` | 字面量 | `zoom` \| `mock` |
| `meeting_id`、`title` | string | 非空 |
| `started_at` / `ended_at` | datetime / 可选 | 带时区；结束不得早于开始 |
| `timezone` | string，可选 | 如 `Asia/Shanghai` |
| `owner_participant_ids` | string 列表 | ⊆ `participants[].participant_id` |
| `participants[]` | 对象 | `participant_id`、`display_name`、`email?` |
| `agenda` | string 列表 | 可选，默认 `[]` |
| `segments[]` | 对象，≥1 | `segment_id`、`speaker_id`（⊆ 参会人）、`started_at`（带时区）、`ended_at?`、`text` |
| `metadata` | 对象 | 自由 |

## `pneuma.source.document-library/v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | 字面量 | `pneuma.source.document-library/v1` |
| `provider` | 字面量 | `obsidian` \| `mock` |
| `library_id`、`title` | string | 非空 |
| `documents[]` | 对象，≥1 | id 唯一；路径唯一（不分大小写） |
| `metadata` | 对象 | 自由 |

每篇文档：`document_id`、`path`、`title`、`content`、`frontmatter`（对象）、`tags`（唯一）、`links[]`（`target`、`label?`、`embedded`）、`created_at?` / `modified_at?`（带时区）、`metadata`。`path` 必须是库内安全相对路径——不许绝对路径、不许 `..`、不许点开头的组件。

## `pneuma.source.im/v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | 字面量 | `pneuma.source.im/v1` |
| `provider` | 字面量 | `slack` \| `mock` |
| `archive_id` | string | 非空 |
| `owner_user_ids` | string 列表 | ⊆ `users[].user_id` |
| `users[]` | 对象 | `user_id`、`display_name`、`email?`、`is_bot` |
| `conversations[]` | 对象，≥1 | 见下 |
| `metadata` | 对象 | 自由 |

每个会话：`conversation_id`、`conversation_type`（`channel` \| `dm` \| `group_dm`）、`title`、`member_ids`（⊆ 用户表）、`messages[]`（≥1，id 唯一）、`metadata`。每条消息：`message_id`、`sender_id`（⊆ 用户表）、`sent_at`（带时区）、`text`、`thread_id?`、`edited_at?`、`reactions[]`（`name`、`count ≥ 1`）、`images[]`、`metadata`。

**v1 的图片边界。** 图片是第一种受支持的原生媒体，目前只挂在 IM 消息上。每张图片声明唯一的 `image_id`、受支持的 `mime_type`（`image/jpeg`、`image/png`、`image/webp`、`image/gif`），以及不可变的 `source`：规范 base64 字节或公网 HTTPS URL，两者都必须带预期 SHA-256。导入会机械校验大小、摘要与图片文件签名，再把原图放入私有 S3 兼容 L0 存储。可选的 `derived[]` 必须明确标为 `caption` 或 `ocr`，并写明 `producer`；派生表示补充原图，绝不替代原图。

图片属于消息原有的归一化块。因此 claim 继续使用既有引用，例如 `[cite: <source-id> ¶7]`，同一个 locator 同时解析消息文本和图片。`caption` 编译模式只把带标签的派生文本交给模型；只要有图片既无 caption 也无 OCR，编译就会明确失败。`native` 还会交付重新校验过的真实图片 content block；`auto` 读取当前模型 profile，能力未知时回落 `caption`。fast recall 会把同一套 caption/native 区分应用到与已选正文窗口重叠的图片，因此即使编译契约没有把某条图像事实提升为 canonical claim，回答仍能查看原图并沿用原始块引用。音频、视频、通用文件、会议媒体与邮件附件正文不属于这个 schema 版本的原生媒体输入。

冻结知识库快照会在就绪前把所有被引用对象服务端复制进快照租户。带图片的 `prebuilt/` 文库也必须在 `l0.jsonl.gz` 旁按 `media/sha256/<前两位>/<sha256>` 携带每份原件；恢复时重新核验摘要、大小与文件签名，写入目标租户并重定向 L0 清单。媒体缺失时会在写入正本或 L0 行之前拒绝恢复。

## `pneuma.source.email/v1`

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | 字面量 | `pneuma.source.email/v1` |
| `provider` | 字面量 | `rfc822` \| `mock` |
| `archive_id` | string | 非空 |
| `owner_addresses` | string 列表 | 归一化（去空白、casefold），唯一 |
| `threads[]` | 对象，≥1 | 线程 id 唯一；消息 id **跨全部线程**唯一 |
| `metadata` | 对象 | 自由 |

每条线程：`thread_id`、`subject`、`messages[]`（≥1）、`metadata`。每封邮件：`message_id`、`sent_at`（带时区）、`from`（`{address, display_name?}`，地址归一化）、`to[]`、`cc[]`、`subject`、`text`、`in_reply_to?`、`references[]`、`attachments[]`（`filename`、`content_type`、`size_bytes ≥ 0`、`content_id?`）、`metadata`。

## `pneuma.source.owner-dialogue/v1`

所有者对管理代理说过的话，作为一种普通来源。所有者只能通过说话来作用于知识库，因此一次订正、一条指示或一次补充，是与其他证据同等的证据——L0 逐字保留，L1/L2 无条件，引用写作 `[cite: <source-id> ¶n]`，与引用一条聊天消息完全一样；它进入正本的唯一途径是一次普通编译加引用门禁。没有所有者专用写入通道，没有自己的引用语法，也没有自己的门禁规则。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | 字面量 | `pneuma.source.owner-dialogue/v1` |
| `provider` | 字面量 | `console` \| `mock` |
| `dialogue_id` | string | 非空 |
| `owner_id` | string | 所有者在应用自己的 id 体系里的 id |
| `steward_id` | string，可选 | 管理代理的 id，如果应用给它命名的话 |
| `turns[]` | 对象，≥1 | `turn_id`（唯一）、`role`（`owner` \| `steward`）、`said_at`（带时区，非递减）、`text`（不得为空白）；**至少一轮的 `role` 是 `owner`** |
| `metadata` | 对象 | 自由 |

**至少要有一轮是所有者自己说的，而且那一轮得真说了话。** 这份契约的全部立足点在于：知识库所写的那个人亲口说了话——规范化按此打标签，编译任务的按来源行按此点名，完整正本处理也由此而来。只有管理代理轮次的对话，是管理代理写的关于所有者的文档；把它当作所有者自己的陈述来编译，等于让管理代理写的文字变成所有者的正本知识。而一轮空白的所有者发言，只在形式上满足这条规则：对话在实质上仍然只有管理代理在说，空白轮次也成不了任何东西可以引用的块。因此**任一角色**的空白轮次都被直接拒绝，并点名是哪一轮、什么角色，而不是悄悄滤掉——声明了一轮没人说过的话的 payload，它的作者相信着这份契约并不相信的东西。两者都在契约处拒绝，导入表单也在写下一轮非空白的所有者发言之前禁用提交。

**顺序即含义，因此校验而不修正。** 其他契约都会对收到的东西排序——provider 归档的顺序是导出的副产物。对话的顺序就是它的内容：一句限定前一句的话，两句一换位就不再限定了。因此 `said_at` 倒退的 payload 会被拒绝，而不是被排序。

**规范化。** 每轮一块，按**角色**打标签（`Owner:` / `Steward:`，取自 prompt 目录）。`owner_id` / `steward_id` 是应用自己的 id，与 turn id 一起留在来源的 `meta` 信封里，像其他契约的并行元数据一样按规范化顺序与块对齐——它们从不出现在模型读到的文本里。小节按主体的日历日切分，陈述自身的日期成为 `meta.occurred_on`。摄入提案是完整正本处理加完整语义索引：这是唯一一种作者就是所有者本人的材料，而一段编译永远读不到的陈述，就是一次永远落不了地的订正。

**种类由框架陈述，判断由契约给出。** 这些块读起来像转录，但它不是，因此编译任务的按来源行点出种类——所有者在直接对这座库说话，是他自己的话，而不是某件事的记录。这段陈述*该得到*什么——一次 `edit_claim`、一次 `supersede_claim`、一个新页——是编译契约的判断，因此刻意不写进那一行。

## `pneuma.source.agent-session/v1`

Provider 中立的编码代理会话：知识主体的原话、代理逐字保留的叙述，以及有界的机械动作短记。一次会话保持一个来源，沿用所有契约共同的 L0 块、引用语法和编译闸门。

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema` | literal | `pneuma.source.agent-session/v1` |
| `provider` | string | 非空白；`claude-code`、`codex` 或其他 harness 名称 |
| `session_id`、`owner_id` | string | 非空白；provider 内的会话身份，以及应用自身方案中的 Owner 身份 |
| `owner_name?` | string | 单行非空白；Owner 回合所带的名字。缺省时标为「用户：」——id 永不进入文本 |
| `agent` | object | `name`（非空白）、`model?`（string） |
| `project` | object，可选 | `path`（非空白工作目录）、`name?`、`git_remote?` |
| `started_at`、`ended_at?` | datetime | 显式时区；结束不能早于开始 |
| `turns[]` | object，≥1 | `turn_id`（唯一、非空白）、`role`（`owner` \| `agent`）、`kind`（`say` \| `narrative` \| `action`）、`at`（显式时区、非递减）、`text`（非空白） |
| `metadata` | object | provider 附加信息；下述工具数据禁令同样适用 |

**拒绝工具数据、角色矛盾和空白发言。** Owner 回合只能是 `say`；代理回合只能是 `narrative` 或 `action`。至少有一个 Owner 回合，任何回合都不能空白。`action` 必须是至多 200 字符的单行机械短记，例如 `edited src/x.py`、`ran: uv run pytest`、`read docs/a.md`；换行字符一律拒绝。任何字段都不接纳工具输入输出：递归拒绝 `input`、`output`、`result` 键，嵌套 metadata 也不能绕过（`agent_session_tool_payload`）。代码属于 git，文件内容和工具结果不等于知识主体的知识。其他关系型拒绝名为 `agent_session_role_kind`、`agent_session_action_stub`、`agent_session_owner_required`、`agent_session_duplicate_turn_ids`、`agent_session_turn_order`、`agent_session_time_range`；字段形状使用通常的校验错误名。导入方须逐字提供代理叙述，契约不从散文推断作者。

**顺序就是含义，所以校验而不修复。** `at` 倒退直接拒绝；时间相等时保持提交顺序。日历日分节遵循知识主体时区，没有提供主体时钟时遵循时间戳自身偏移。公开的 [JSON Schema](source-contracts/agent-session-v1.schema.json) 表达结构型拒绝；时间顺序、身份唯一性和显式时区还会在运行时边界检查。

**归一化。** 每个回合一个块，只在原文前加英中 prompt 目录中的角色/种类标签：`<owner_name>:`（契约未给名字时为 `User:`）、`<agent.name>:`、`<agent.name> did:`（中文为「<owner_name>：」或「用户：」、「<agent.name>：」「<agent.name> 执行：」）——双方都带契约里自己的名字，如「Momo：」和「Codex 执行：」，不是抽象角色也不是 id；编译任务的逐来源说明行点名同一个 Owner 标签，其余文字逐字保留。`meta` 保存 `provider`、`session_id`、`owner_id`、代理名称/模型 `agent`、`project`、时间戳，以及与块顺序对齐的 `turns` 元数据（角色、种类、回合 id 和时间），不复制回合正文。内部 origin 是 `agent_session`，自由格式的 harness 名称保留在 `meta.provider`。`pkc source structure <source-id>`（`source show` 的别名）输出 `block_authorship` 行（`index`、`role`、`kind`），无需读取动作正文。动作短记和其他小块一样进入 L1/L2。Owner 回合少于三次时提议 `canonical_treatment: none`；三次及以上沿用普通工作流提议（当前为机械的完整编译）。两者都提议完整语义索引，再由部署的 semantic-retrieval 开关封顶。理由写明触发的阈值规则，原型与用户覆写保持不变；L0/L1 始终无条件可达。

**种类由框架声明，判断归编译契约。** 编译任务每个来源前的一行说明这是编码代理会话：Owner 回合是知识主体的原话；代理叙述是机器对自己工作的记述，可证明做过什么，不能代表主体的想法；动作短记是活动日志，不是知识。该行位于 HumanMessage，会话内容不会改变 SystemMessage。什么值得写成主张由编译契约决定。路径模板还可声明 `owner_voice: true`，在写入面和闸门机械要求知识主体亲自撰写的证据；见[编译契约怎么写](../guides/compile-contract.zh-CN.md)。

## 不变量与版本化

- **源文本是不可变证据。** 更正以一次新导入的形式到来，绝不修改已摄入的内容。
- **所有者身份由导入方声明**（`owner_participant_ids` / `owner_user_ids` / `owner_addresses` / `owner_id`），永不从消息正文推断。
- **版本化**：在 `v1` 内新增可选字段向后兼容；改名/删字段、改身份语义、改可引用单元，需要新的 schema 版本。
- `meta` 信封保留 provider 中立的呈现字段（会议起止/参与者/议程、库内路径/frontmatter/标签/双链、IM 成员/线程/编辑/表态、邮件收发件人/回复链/附件描述）——**但正文永不复制进 metadata**；阅读器按归一化顺序把 metadata 接回块，任何一项都能精确取回对应的 L0 块。
- provider 适配器是防腐层，`mock`（canonical JSON）适配器校验的是完全同一套 schema——mock 导入与真实导入受同样的约束。Obsidian 适配器永不导入库配置、插件代码、点文件、符号链接及库外文件。

内置适配器所依据的上游格式：Zoom 会议转写、Obsidian properties/内链/vault、Slack 导出与 `conversations.history`、RFC 5322（邮件）、RFC 2045（MIME）。

## 导入

- **HTTP**：`POST /v1/users/{uid}/sources/import`，body 就是裸契约 payload。服务在归一化前把声明的图片实体化。响应报告匹配到的 `contract_schema` 与每个展开出的 source（见 [http-api.zh-CN.md](http-api.zh-CN.md)）。
- **CLI**：`pkc ingest --contract agent-session/v1 --file session.json`；JSON 中的 `schema` 必须与 `--contract` 一致。
- **程序化**：`parse_source_contract(payload)` 校验。带图片的调用方先经 `materialize_contract_images(...)` 实体化，再把结果作为 `materialized_images` 传给 `normalize_source_contract(...)`；纯文本契约可以直接归一化。
- **从真实 provider 导出**：`scripts/ops/import_source.py` 一步转换加导入——`--provider {mock, obsidian, zoom, slack, email}`，分别对应 canonical JSON、Obsidian 库、Zoom VTT 转写、Slack 导出 zip、RFC-822 邮件。
