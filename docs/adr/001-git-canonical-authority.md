# ADR-001：canonical 权威层用 per-user git repo，service 保持无状态

日期：2026-07-20 ｜ 状态：已接受

## 背景

Pneuma Compiler 全部实验中唯一被完全实证的赌注是 documents-as-authority + git-canonical：
patch=commit、rollback=revert、快照=tag，可逆/可审计/可 diff 全部白拿，且 LoCoMo
上实证了编译召回护城河（+10pp recall）。但新项目要求服务层云原生：无状态、可横向扩容。

## 决策

保留 git 为唯一权威层：每个 user_id 一个 git repo，落共享存储（v1 本地卷，
后续可迁对象存储/NFS）。service 与 worker 进程无状态地操作它；per-user 写串行由
PG 任务队列按 user_id 分键保证（`FOR UPDATE SKIP LOCKED`），进程本身不持锁。
PG/Qdrant/Meilisearch 只承载 derived（可重建）与运行时状态。

## 备选与否决理由

权威层迁 PG 自建版本化：需重造 git 免费提供的一切（原子提交、diff、revert、tag、
完整审计链），风险大收益存疑，否决。

## 后果

- 快照/回滚/审计零额外建设；Briefing 按快照问答直接用 commit ref。
- 共享存储成为扩容时的关注点（git repo 不能并发写同一 user——队列已保证串行）。
- 灾备 = git repo 备份，语义清晰。
