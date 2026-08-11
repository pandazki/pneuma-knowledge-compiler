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
| GET | `/…/summary` | 工作区计数：sources、jobs、documents、claims、snapshots |

## 检索

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/recall` | body `{query, mode: rag\|fast\|deep, limit, as_of?, snapshot?, include_original_modalities?: ("image")[]}` |
| POST | `/…/recall/stream` | 仅 deep；SSE——每完成一次工具调用发一条 `event: step`，最后 `done`（或 `error`）。步骤级流式，不是 token 流 |

`rag` 返回命中列表（`source_id`、块区间、文本、路径、分数）。`fast`/`deep` 返回答案及其证据：`used_claims`、`used_windows`、`trail`（deep）、`citation_handles`（`sNN` → 真实 source id）、`documents_read`、`snapshot`、`token_usage`。

`include_original_modalities` 是查询 tool 对成本/注意力的显式选择，不是根据模型能力猜出来的部署默认值。它使用枚举列表，以便未来增加音频/视频时不改 tool 形状；当前唯一值是 `"image"`。纯文本问题保持空列表；只有必须直接视觉核验时才传 `["image"]`，例如判断画中是否出现某物、颜色、文字或布局。未要求原始媒体时，带标签的派生表示仍可使用。答案通过 `included_original_modalities` 与 `original_modality_counts` 回显实际带入的原始模态。原始媒体只适用于 `fast` 与 `deep`；`rag` 返回文本检索命中，非空列表会被拒绝。

Source 详情绝不暴露对象存储 key。每条图片清单只给 `image_id`、MIME 类型、SHA-256、大小、带标签的派生表示和 API URL。浏览器与引用抽屉经服务取这个 URL；S3/RustFS bucket 保持私有。

## 编译、任务、历史

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/compile` | 为每个未消化的 source 各入队一个编译任务（幂等） |
| GET | `/…/jobs` | 队列分页（`status`、`kind` 过滤） |
| GET | `/…/history` | patch、job、快照三类混排的统一时间线，带计数 |
| GET | `/…/history/activity` | 时间线日历 |

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
| GET | `/…/briefings` | 列表 |
| POST | `/…/briefings/{id}/ask` | 对已存证据包提问：`{question}` → 答案 + 引用 |
| DELETE | `/…/briefings/{id}` | 删除 |

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
| POST | `/…/live-context/stream` | 对一段转写窗口的一次性 SSE：每张存活卡片一条 `event: suggestion`，末尾 `done` 带闸门统计 |
| WS | `/…/live-context/ws` | 长连接监听。客户端发 `config` / `turn` / `flush` / `want_more` / `ping`；服务端发 `ready` / `suggestion` / `suggestion_detail` / `stats` / `error`（永不致命）/ `ping`（约 30 秒保活）。完整协议见 [`api/routes/live_context.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/live_context.py) 的模块 docstring |

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
