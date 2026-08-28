# 贡献指南

[English](CONTRIBUTING.md) | **简体中文**

环境搭建与架构见 [README](README.zh-CN.md) 和 [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md)；本页只写发 PR 前需要知道的事。

## 每次提交前的两道门

```bash
uv run pytest                      # 四个包的全部测试
cd apps/web && pnpm run build      # 动过 web 时
```

测试套件完全零密钥：根 conftest 负责注册参考契约，embedding 钉死为确定性的 `fake:384`、切块钉死为机械 `sentence`、Qdrant 用独立测试 collection——不碰你的应用数据、不打任何真实 provider。需要真实中间件的集成测试在 Postgres/Qdrant/Meilisearch 可达时运行，否则以明确的 "middleware unreachable" 理由跳过。根级卫生与 scaffold 测试在默认 testpaths 之外：`uv run pytest tests/`。

## 改动必须保住的东西

新增或改动编译行为需要测试守住四条承重性质：正本/派生边界、`user_id` 隔离、来源引用、合成诚实。[架构 §9](docs/architecture.zh-CN.md#9-不变量) 的七条不变量优先于任何局部取舍。

正本只由四个有界的写动词写入，没有第五个——`create_document` / `append_block`、`edit_claim`、`supersede_claim`（世界变了，而不是我错了），以及唯一一次性整块写入的 `rewrite_overview`——它换掉文档那个有界的头部，账本一字不动。它之所以安全，只因为闸门要求 overview 里每一块都落在一条账本 claim 或一段来源区间上，并把整个区域按字符数封顶。新增写入路径就要同时补上约束它的闸门检查；安全性靠提示词措辞撑着的写动词，闸门接不住。

## 扩展框架

两个扩展缝，扩展的不是同一件东西。**schema pack** 是追加式的契约片段，扩展的是判断力；**索引组件**（core `components/`）扩展的是结构：叠在某个契约 family 之上的业务结构，接入框架自己的那些缝（闸门检查、outline 里的附加一行、给编译与深召回的工具、快召回的路由查询路、编译任务里每个来源下的一行前缀，以及 `on_source_indexed` / `rebuild` 投影通道和它的逐作业 `prepare`）。新写一个组件，四件事必须成立，且每件都可测：

- **只能是派生**——它落盘的一切都能被 `scripts/ops/rebuild_derived.py` 完整重推；
- **正本面只读**——注册时交给它的正本面是 `CanonicalReadOnly`；它索引到的东西只能搭一次普通编译进入文库（I7）；
- **fail-soft**——组件抛错最多让投影变陈旧，绝不让作业失败；
- **缝上有测试**——它提供的每一面都要有，外加一条：不注册时每个缝的渲染逐字节不变。

设计权威（包括写第三个组件的清单）在 [docs/design/index-components.zh-CN.md](docs/design/index-components.zh-CN.md)。

## 数据规则

所有示例与测试数据必须是合成的——不含凭证、真实个人材料或私有品牌内容。内置的人设与旅程都标注为合成，绝不作为真实客户证据呈现。第三方数据集永不入库；它们放在 git 忽略的 `local/` 下，按需重取。

## 语言

文档双语：英文为主（`X.md`）、中文镜像（`X.zh-CN.md`）——改动成对提交。代码与注释只用英文。scaffold 的用户可见文案刻意用中文，请保持。
