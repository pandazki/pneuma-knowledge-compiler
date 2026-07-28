# pneuma-knowledge-compiler

面向 AI-Native 个人开发者的开源知识编译器：把对话、文档、决策、实验与运营记录编译成带来源引用、可版本化演进的 canonical knowledge。

它不是又一个聊天记录仓库。Pneuma Knowledge Compiler 把知识分成四个可访问层级：

- **L0 · Source**：原始材料与结构化定位；
- **L1 · Lexical**：Meilisearch 全量词法索引；
- **L2 · Semantic**：Qdrant 语义分块与向量索引；
- **L3 · Canonical**：经过引用门禁的结构化知识，存入每用户独立的 Git repository。

Canonical 与原文是权威，派生索引可以随时重建；模型只能提出变更，身份、引用、路径、冲突与提交由程序机制校验。

## 开箱跑通：无密钥完整链路

需要 Python 3.12、[uv](https://docs.astral.sh/uv/)、Docker、Node 18+ 与 pnpm。

```bash
uv sync --all-packages
docker compose -f infra/docker-compose.yml up -d --wait

# 合成 OPC 数据实际经过 L0 → L1/L2 → L3 → Git，不调用外部模型
uv run python examples/seed_demo.py

# API 与 Web
bash scripts/dev-api.sh
cd apps/web && pnpm install && pnpm dev
```

打开 `http://localhost:5173`。默认合成人设是杭州的一人公司开发者「林知远」，演示内容覆盖产品范围、检索实验和公开发布检查；界面会持续标记 `SYNTHETIC`，不会把它呈现为真实客户或 benchmark。

也可以在一套干净中间件中直接导入已处理的四层 preset：

```bash
uv run python examples/import_presets.py
```

更完整的上手与 API 示例见 [docs/getting-started.md](docs/getting-started.md)。

## 能力

- 对话、结构化上下文流与 Markdown 文档入库；
- 异步 `index` / `compile` worker 与按用户串行写入；
- `rag`、`fast`、`deep` 三种召回，以及连续 Briefing 问答；
- 主动 context cue、引用闸门与原文 `want_more`；
- Git canonical、快照、知识图谱、编译审计与 schema evolve；
- 用户画像与可组合的版本化知识策略；
- 数据集导入/导出、全量 derived rebuild、Docker 与 GKE 部署；
- React/Vite 操作台，支持瓷白城市导视图与午夜珐琅控制室两套完整主题。

## 架构

```text
raw material
    │
    ├── PostgreSQL ─────────────── L0 source + jobs + audit
    ├── Meilisearch ────────────── L1 lexical projection
    ├── Qdrant ─────────────────── L2 semantic projection
    └── compile gate → per-user Git
                          │
                          └─────── L3 canonical + rebuildable projections
```

- `packages/pneuma-knowledge-core`：纯领域逻辑与 Protocol 端口；
- `packages/pneuma-knowledge-service`：FastAPI、adapter、worker 与数据集投影；
- `apps/web`：Pneuma 操作台；
- `infra` / `docker` / `deploy`：本地与云端运行资产；
- `examples`：keyless E2E、真实 provider 冒烟与维护脚本。

关键不变式与完整设计见 [docs/architecture.md](docs/architecture.md)，迁移验收契约见 [docs/specs/open-source-migration.md](docs/specs/open-source-migration.md)。

## 使用真实模型

Keyless 路径足以运行测试、生成/导入 mock、浏览全部视图。需要真实 compile、fast/deep 或 persona generation 时：

```bash
cp .env.example .env
# 在本地 .env 中设置 OPENROUTER_API_KEY
```

不要提交 `.env`、密钥、真实个人材料或运行时 canonical。

## 验证

```bash
uv run pytest
cd apps/web && pnpm run build
```

真实中间件集成测试会在 Postgres、Qdrant 与 Meilisearch 可达时运行；否则只会因明确的“middleware unreachable”原因跳过。

本次开源迁移的完整浏览器旅程、数据计数与日夜/移动端截图见
[E2E 验收报告](docs/e2e-report.md)；界面的长期视觉规则见 [DESIGN.md](DESIGN.md)。

## Pneuma 开源家族

- [pneuma-skills](https://github.com/pandazki/pneuma-skills)
- [pneuma-framework](https://github.com/pandazki/pneuma-framework)

## License

[MIT](LICENSE)
