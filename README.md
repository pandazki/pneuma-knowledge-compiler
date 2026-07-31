# pneuma-knowledge-compiler

业务无关的开源知识编译器：把会议、层级文档库、IM、邮件与工作记录编译成带来源引用、可版本化演进的 canonical knowledge。

它不是又一个聊天记录仓库。Pneuma Knowledge Compiler 把知识分成四个可访问层级：

- **L0 · Source**：原始材料与结构化定位；
- **L1 · Lexical**：Meilisearch 全量词法索引；
- **L2 · Semantic**：Qdrant 语义分块与向量索引；
- **L3 · Canonical**：经过引用门禁的结构化知识，存入每用户独立的 Git repository。

Canonical 与原文是权威，派生索引可以随时重建；模型只能提出变更，身份、引用、路径、冲突与提交由程序机制校验。

## 本地开发

需要 Python 3.12、[uv](https://docs.astral.sh/uv/)、Docker、Node 18+ 与 pnpm。

```bash
uv sync --all-packages
docker compose -f infra/docker-compose.yml up -d --wait
```

接着分别运行 `scripts/dev-api.sh`、`scripts/dev-worker.sh` 与
`cd apps/web && pnpm dev`。更完整的通用开发路径见
[docs/getting-started.md](docs/getting-started.md)。

需要一套可浏览的完整应用与合成数据时，使用
[examples/opc](examples/opc/README.md)。它拥有独立 Compose、端口、卷、collection、
策略、画像、数据与评估，不会写入根开发栈。

## 能力

- 会议、Obsidian 层级文档库、Slack IM 与 RFC 5322 邮件的官方 canonical contract；
- Zoom WebVTT、Obsidian vault、Slack JSON export、EML/mbox 真实适配器，以及同约束 mock adapter；
- 异步 `index` / `compile` worker 与按用户串行写入；
- `rag`、`fast`、`deep` 三种召回，以及连续 Briefing 问答；
- Live Context 即时上下文、引用闸门与原文 `want_more`；
- Git canonical、快照、知识图谱、编译审计与 schema evolve；
- 用户画像与可组合的版本化知识策略；
- 数据集导入、全量 derived rebuild、Docker 与 GKE 部署；
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
- `examples/opc`：自包含 OPC 应用、独立 Compose、数据与评估；
- `examples/walkthroughs` / `examples/ops`：通用机制演练与显式运维命令。

四类数据契约与导入方式见 [docs/source-adapters.md](docs/source-adapters.md)；关键不变式与完整设计见 [docs/architecture.md](docs/architecture.md)，迁移验收契约见 [docs/specs/open-source-migration.md](docs/specs/open-source-migration.md)。

## 使用真实模型

测试与机械处理路径无需密钥。需要真实 compile、fast/deep 或 persona generation 时，
从根目录示例配置开始：

```bash
cp .env.example .env
# 在本地 .env 中设置 provider 路由与 key
```

不要提交 `.env`、密钥、真实个人材料或运行时 canonical。

## 验证

```bash
uv run pytest
cd apps/web && pnpm run build
```

真实中间件集成测试会在 Postgres、Qdrant 与 Meilisearch 可达时运行；否则只会因明确的“middleware unreachable”原因跳过。

OPC 应用的浏览器旅程、数据计数与日夜截图随应用保存在
[examples/opc/e2e](examples/opc/e2e/README.md)；界面的长期视觉规则见 [DESIGN.md](DESIGN.md)。

## Pneuma 开源家族

- [pneuma-skills](https://github.com/pandazki/pneuma-skills)
- [pneuma-framework](https://github.com/pandazki/pneuma-framework)

## 致谢

- [霞鹜文楷 LXGW WenKai](https://github.com/lxgw/LxgwWenKai)（屏幕阅读版）——Web UI
  阅读面的中文衬线字体，SIL Open Font License 1.1，可自由商用与再分发。
- [kami](https://github.com/tw93/kami)——文档排版约束系统；其"单一衬线撑起整页"
  的字体决策启发了本项目阅读面的字体选型（注意：kami 中文默认字体仓耳今楷 02
  仅限个人免费使用，商用需另行向仓耳授权，本项目因此未采用）。

## License

[MIT](LICENSE)
