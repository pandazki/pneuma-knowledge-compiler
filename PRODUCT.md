# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

主要用户是以“一人公司（OPC）”方式工作的 AI-Native 个人开发者。他们同时承担产品、工程、研究与经营工作，需要把持续产生的对话、文档、决策、实验和项目材料沉淀为可追溯、可演化的个人知识。

## Product Purpose

Pneuma Knowledge Compiler 是一个业务无关的开源个人知识编译器。它把原始材料异步编译为带来源引用的 canonical knowledge，并通过原文、词法、语义与 canonical 四级访问面支持检索、问答、连续 briefing、Live Context 即时上下文和知识演化。

成功意味着：用户可以从一组完全本地、可复现的 mock 数据开始，跑通“导入 → 编译 → 检索/问答 → 浏览来源与演化历史”的完整链路；权威知识可审计，派生索引可重建，任何回答都能回到来源。

## Positioning

项目的独特机制是“Git-backed canonical truth + 可全量重建的派生层 + 机械化质量门禁”。模型负责提出知识变更，系统负责分配身份、校验引用、保护历史和拒绝不满足契约的写入；实现不会把 prompt 劝说当作数据完整性机制。

## Operating Context

- 本地开发使用 Python 3.12、uv workspace、Docker Compose、FastAPI API/worker 和 React/Vite Web UI。
- 默认基础设施为 PostgreSQL、Qdrant、Meilisearch 与每用户 Git canonical repository。
- LLM 与 embedding 可通过 OpenRouter 接入；测试和演示必须提供无密钥的 deterministic mock 路径。
- 典型工作流是导入个人材料、观察后台编译、检查 canonical 与引用、用多种 recall mode 提问、查看图谱与演化记录。

## Capabilities and Constraints

- 保留源架构的入库、分块、compile、L0–L3 访问、rag/fast/deep recall、briefing、suggestion、evolve、数据集导入导出、可观测性和部署能力。
- 所有状态以 `user_id` 为第一隔离维度；canonical 与 derived 必须在类型和存储语义上分离。
- 默认领域策略服务于 OPC AI-Native 个人开发者，不包含任何特定硬件、消费设备、应用或商业品牌策略。
- 默认中文人设和模拟数据用于可复现演示，必须明确标注为 synthetic，不构成真实客户、性能或商业证明。
- 公共包、Python module、环境变量、API、部署资源和 UI 统一使用 Pneuma Knowledge Compiler 命名。
- 开源版本不承诺托管服务、价格、客户或尚未实现的集成。

## Brand Commitments

- 产品名为 **Pneuma Knowledge Compiler**，仓库名为 `pneuma-knowledge-compiler`。
- 视觉与语言属于 Pneuma 开源家族，并以本地 `pneuma-skills` 与 `pneuma-framework` 项目作为已确认的家族证据。
- 产品语气直接、清晰、工程化，默认中文演示内容；不保留上游私有业务的品牌、硬件或应用标记。
- Web 工作台同时提供日间与夜间模式：日间是瓷白城市导视图，夜间是午夜珐琅控制室；两种模式共享线路、站点与状态语义，但分别调校表面、阴影和对比度，不以简单反色替代主题设计。

## Evidence on Hand

- 架构契约、公开测试、合成 OPC 数据与端到端报告是本仓库唯一的事实来源。
- Pneuma 家族证据来自
  [`pneuma-skills`](https://github.com/pandazki/pneuma-skills) 与
  [`pneuma-framework`](https://github.com/pandazki/pneuma-framework)。
- 当前没有真实客户、公开 benchmark 或生产托管证明；后续界面不得虚构。

## Product Principles

1. **Canonical 有权威，derived 可重建。**
2. **机制保护不变式，模型只提出候选。**
3. **来源先于答案，证据先于声称。**
4. **本地 first-run 必须完整可复现。**
5. **业务无关的核心，允许显式扩展的策略。**

## Accessibility & Inclusion

Web 操作面以键盘可达、可见焦点、语义化结构、减少动态效果支持和至少 WCAG 2.2 AA 对比度作为开源默认质量线。该标准为本次迁移的明确工程假设，后续可由项目维护者调整。
