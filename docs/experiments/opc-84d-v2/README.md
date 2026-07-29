# OPC 84 天验收语料

这是一套面向 AI-native 独立开发者的全合成纵向语料，用于验证四类来源导入、
增量编译、引用回放、检索和前端浏览。故事覆盖连续 84 天；所有人物、组织、
地址、项目、消息和附件均为虚构内容。

仓库只保留最终有效资产：

- `story-bible.md` 与 `daily-beats.json`：最终叙事约束和逐日事实台账；
- `research-ledger.md`：只记录用于约束结构与常识的公开研究来源；
- `group-content.schema.json` 与 `qa-rubric.md`：创作契约和 fail-closed 质检规则；
- `groups/`：28 组最终 authored corpus；
- `accepted/`：通过验收的逐字节快照；
- `qa/deterministic/`：每组最后一次通过的确定性质检；
- `qa/reviews/`：每组唯一一份最终独立复审；
- `qa/accepted/`、`qa/acceptance-audit.json` 与 `qa/global.json`：验收绑定和全局
  质检证据。

被退回的草稿、已被取代的复审、修复过程记录和中间评估不属于发布资产，
不会保存在仓库中。真实可导入数据由 `accepted/` 经装配器产生，最终运行与评估
摘要位于相邻的 `../results/`。

## 复验

```bash
uv run python examples/refresh_opc_84d_v2_deterministic.py
uv run python examples/audit_opc_84d_v2_acceptance.py
uv run python examples/validate_opc_84d_v2_global.py
uv run pytest packages/pneuma-knowledge-service/tests/test_opc_84d_v2_*.py
```

所有 QA 路径均使用仓库相对路径，因此 clone 到任意目录后仍可复验。
