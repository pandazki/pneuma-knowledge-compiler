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
| GET | `/…/sources/{source_id}` | 详情：元信息、结构图、blocks |
| POST | `/…/sources/{source_id}/fetch` | 按 `locator` 逐字取 L0 原文 |
| GET | `/…/summary` | 工作区计数：sources、jobs、documents、claims、snapshots |

## 检索

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/…/recall` | body `{query, mode: rag\|fast\|deep, limit, as_of?, snapshot?}` |
| POST | `/…/recall/stream` | 仅 deep；SSE——每完成一次工具调用发一条 `event: step`，最后 `done`（或 `error`）。步骤级流式，不是 token 流 |

`rag` 返回命中列表（`source_id`、块区间、文本、路径、分数）。`fast`/`deep` 返回答案及其证据：`used_claims`、`used_windows`、`trail`（deep）、`citation_handles`（`sNN` → 真实 source id）、`documents_read`、`snapshot`、`token_usage`。

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
