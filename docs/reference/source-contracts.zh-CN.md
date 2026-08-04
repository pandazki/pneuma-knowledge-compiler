# 输入契约（v1）

[English](source-contracts.md) | **简体中文**

官方输入边界是四种版本化、provider 中立的 JSON 契约——会议、文档库、IM、邮件。能说其中一种契约的东西就能喂进系统；从具体 provider 格式到契约的转换器在契约之外（见[导入](#导入)）。

- 一个 payload，一个 `schema` 判别字段：`pneuma.source.meeting/v1`、`pneuma.source.document-library/v1`、`pneuma.source.im/v1`、`pneuma.source.email/v1`。
- 校验是严格的（`extra="forbid"`）：未知字段直接拒绝，不是忽略。权威定义是 [`ingest/source_contracts.py`](../../packages/pneuma-knowledge-core/src/pneuma_knowledge_core/ingest/source_contracts.py) 里的 Pydantic 模型；[`source-contracts/`](source-contracts/) 下的 JSON Schema 是它的线上镜像，供工具链使用。
- **所有时间戳必须带显式时区偏移。** naive datetime 过不了校验。
- id 在各自作用域内唯一，身份引用必须能解析：发言人 ⊆ 参会人、会话成员与发送者 ⊆ 用户表、owner id ⊆ 已声明的身份。
- 每一层都有自由的 `metadata` 对象，装 provider 的附加信息。

**展开。** 一个 payload 是一个包，按天然引用边界展开成多个 source：会议保持一个；文档库每篇文档一个；IM 归档每个会话一个；邮件归档每条线程一个。source id 按内容寻址（sha256），重复导入相同内容会去重，不会重复入库。

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

每个会话：`conversation_id`、`conversation_type`（`channel` \| `dm` \| `group_dm`）、`title`、`member_ids`（⊆ 用户表）、`messages[]`（≥1，id 唯一）、`metadata`。每条消息：`message_id`、`sender_id`（⊆ 用户表）、`sent_at`（带时区）、`text`、`thread_id?`、`edited_at?`、`reactions[]`（`name`、`count ≥ 1`）、`metadata`。

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

## 不变量与版本化

- **源文本是不可变证据。** 更正以一次新导入的形式到来，绝不修改已摄入的内容。
- **主人身份由导入方声明**（`owner_participant_ids` / `owner_user_ids` / `owner_addresses`），永不从消息正文推断。
- **版本化**：在 `v1` 内新增可选字段向后兼容；改名/删字段、改身份语义、改可引用单元，需要新的 schema 版本。
- `meta` 信封保留 provider 中立的呈现字段（会议起止/参与者/议程、库内路径/frontmatter/标签/双链、IM 成员/线程/编辑/表态、邮件收发件人/回复链/附件描述）——**但正文永不复制进 metadata**；阅读器按归一化顺序把 metadata 接回块，任何一项都能精确取回对应的 L0 块。
- provider 适配器是防腐层，`mock`（canonical JSON）适配器校验的是完全同一套 schema——mock 导入与真实导入受同样的约束。Obsidian 适配器永不导入库配置、插件代码、点文件、符号链接及库外文件。

内置适配器所依据的上游格式：Zoom 会议转写、Obsidian properties/内链/vault、Slack 导出与 `conversations.history`、RFC 5322（邮件）、RFC 2045（MIME）。

## 导入

- **HTTP**：`POST /v1/users/{uid}/sources/import`，body 就是裸契约 payload。响应报告匹配到的 `contract_schema` 与每个展开出的 source（见 [http-api.zh-CN.md](http-api.zh-CN.md)）。
- **程序化**：`parse_source_contract(payload)` 校验；`normalize_source_contract(...)` 展开成归一化 source。
- **从真实 provider 导出**：`scripts/ops/import_source.py` 一步转换加导入——`--provider {mock, obsidian, zoom, slack, email}`，分别对应 canonical JSON、Obsidian 库、Zoom VTT 转写、Slack 导出 zip、RFC-822 邮件。
