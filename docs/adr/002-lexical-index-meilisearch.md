# ADR-002：词法全文检索用 Meilisearch

日期：2026-07-20 ｜ 状态：已接受（CJK 质量为 M1 验收项）

## 背景

不变式 I3 要求全部素材无条件词法可检索（"ES 那套"）。约束：单用户数据量有限、
无跨 user 搜索、客户端限制超大文档——ES/OpenSearch 过重。用户群中英日混合，
CJK 分词质量是硬要求。

## 决策

Meilisearch：单二进制容器、内存占用小、CJK 分词开箱即用（内置 Jieba/Lindera 系
分词）、typo 容忍；index-per-user 天然满足 I1 隔离。经 `LexicalIndex` 端口接入，
业务层不感知实现。

## 备选与否决理由

- PG 自带 FTS：少一个组件，但中文需 zhparser 扩展、部署摩擦大、质量一般。
- Qdrant sparse vector (BM25)：组件复用诱人，但 CJK 分词弱、非真正的全文检索体验。
- ES/OpenSearch：对本场景数据量是牛刀，运维成本不成比例。

## 后果

infra 三容器：Qdrant + PG + Meilisearch。M1 验收必须包含中文/日文查询实测；
若 CJK 质量不达标，经 `LexicalIndex` 端口换实现，业务层零改动。
