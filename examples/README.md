# Examples

示例按职责分成三组，避免把演示业务、通用机制和运维命令混在一起。

## `opc/`：完整应用示例

`examples/opc` 是一个自包含的虚构 OPC 应用，也是仓库唯一拥有林知远/林舟画像、
Seamlog 故事、中文编译策略、84 天数据与评估 truth 的目录。它有独立的
`compose.yaml`、端口、卷、数据库、Qdrant collection、prompt overlay、skill 和
schema matrix。

```bash
uv run python -m examples.opc --help
docker compose -f examples/opc/compose.yaml up -d --build
docker compose -f examples/opc/compose.yaml --profile tools run --rm cli seed
```

完整说明见 [`opc/README.md`](opc/README.md)。

## `walkthroughs/`：通用机制演练

这些脚本只演示框架能力，不拥有 OPC 的业务配置：

| 模块 | 说明 |
|---|---|
| `rag_e2e` | L0/L1/L2 双路召回与租户隔离 |
| `compile_e2e` | ingest → compile → canonical git → projections |
| `briefing_e2e` | fast / deep / briefing 连续问答 |
| `live_context_e2e` | 流式上下文、机械闸门与引用回放 |
| `upgrade_e2e` | 投影重建与 skill 前向升级 |
| `context_stream_ab` | upload 与 context stream 编译对比 |
| `smoke_openrouter` | 真实 provider 全链路冒烟 |

例如：

```bash
uv run python -m examples.walkthroughs.rag_e2e
uv run python -m examples.walkthroughs.context_stream_ab --show-prompt
```

## `ops/`：显式运维命令

| 模块 | 说明 |
|---|---|
| `import_source` | 导入 mock / Zoom / Obsidian / Slack / email 数据 |
| `rebuild_derived` | 从 L0 + canonical 重建 L1/L2/L3 |
| `reindex_l2` | 只重建指定用户的 L2 |

运维命令不再内置示例用户；必须显式传入目标 tenant，或使用 `--all`：

```bash
uv run python -m examples.ops.rebuild_derived <user-id>
uv run python -m examples.ops.reindex_l2 <user-id>
```

旧 preset 导入导出、一次性 canonical 修复和旧 OPC 生成/验收脚本已经移除。
最终示例数据只保留在 `examples/opc/data`，运行产物写入被忽略的
`examples/opc/var`。
