# 任务书原文（协调者 → 建库代理，2026-08-03 深夜）

> 本文件逐字保存了启动这次干净房间构建时，协调者（Claude Fable 5 / Claude Code）
> 发给建库代理（Claude Opus 5，general-purpose subagent）的完整指令。
> 配合 trace/ 下的完整对话轨迹与 BUILD-LOG.md 一起阅读，即可复现整个流程。

---

你是一位 AI 建库向导。任务：在**干净房间**里，从 scaffold 出发，为主人「林舟」建成他的知识库。这次构建的全过程要能被任何开发者复现，所以：来源只有 scaffold + 材料 + 主人自述，别的一概不许看。

框架仓库 REPO=/Users/pandazki/orca/workspaces/pneuma-knowledge-compiler/platy。

**硬性禁令**：不许读 REPO/examples/（唯一例外：拷贝数据那一步）、不许读 REPO/archive/、不许读 REPO/local/（唯一例外：取 key 那一步）。你对"这批数据以前被怎么处理过"必须一无所知。

**流程**（依据 REPO/scaffold/AGENT-GUIDE.md 与 REPO/docs/guides/compile-contract.zh-CN.md，先通读这两份）：

1. **建干净房间**：`cp -R REPO/scaffold ~/opc-build && cd ~/opc-build && cp .env.example .env`。填 `.env`：OPENROUTER_API_KEY 从 REPO/local/tanka/.env.local 读（key 不得出现在任何输出/日志/文件）；COMPILE/RECALL 模型 `openrouter:openai/gpt-5.6-luna`，EMBEDDING `openrouter:openai/text-embedding-3-small`；`PNEUMA_APP_FRAMEWORK_REPO=<REPO 绝对路径>`；再追加隔离六行：
   PNEUMA_APP_COMPOSE_PROJECT=pneuma-opc-build / PG 15448 / QDRANT 16403,16404 / MEILI 17724 / USER_ID u-opc-lin / PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai
2. **拿材料**：`cp -R REPO/examples/opc/my-data ~/opc-build/my-data`（唯一允许接触 examples 的操作——材料本身就是给你的输入）。
3. **主人自述**（"用户"告诉你的话，据此照指南填 profile.yaml，provenance 相应写 profile）：「我叫林舟，独立开发者，做一个叫 Seamlog 的变更证据链产品，自己写代码、自己卖、自己运营。在杭州，中文交流。时区 Asia/Shanghai。」
4. **读数据 → 写契约**：按指南第 4、5 步，抽读 my-data（190 份，覆盖早中晚与四种类型，至少 25 份），推出主体族与口径，从 contract.md 模板的【示例，替换我】起整段改写，skill_id/version 自定。你的判断就是最终判断。
5. **起栈、摄入、编译**：./app.py up → init → ingest my-data → nohup ./app.py compile 后台 + 前台每 4 分钟 tail 轮询直到完成；绝不允许以"编译还在跑/待命"为由结束任务。
6. **验收环**：glance 通读；ask 5 个真问题（决定与理由/承诺与验收/卡在什么条件/时间线/证据口径各一，--sources）。若判定契约必须改：至多一次「改契约→down --volumes→重编」。
7. **全程写 ~/opc-build/BUILD-LOG.md**：读了哪些材料、推出了什么、契约为什么这样定、编译统计、验收问答摘录与判定、遇到的问题。

完工标准：库编译完成、验收合格、BUILD-LOG 完整、data/ 下有成品。
