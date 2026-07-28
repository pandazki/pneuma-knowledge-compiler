# `context_stream` 第一方来源：公开复测脚手架

本文只描述公开仓库内可复现的机制与合成实验入口，不提供真实用户结果或性能结论。

## 机制

`context_stream` 是一种保留说话人结构的第一方来源类型。它通过
`FirstPartySourceType` 接入四个 seam：

| seam | 公开实现 |
|---|---|
| load | 将 `self/*` 与 `others/*` 声道规范为 `owner` / `other` |
| format | 渲染为“本人 / 参与者 N”，保留稳定块编号与引用边界 |
| compile guidance | 注入来源字段语义和“什么值得形成长期知识”的公开策略 |
| index | 使用可配置的语义分块策略 |

基本纪律是不从噪声中臆造事实：提议不等于决定，参与者观点不等于本人承诺，
不确定的高影响信息必须保留不确定性。

## Keyless 机制检查

```bash
uv run pytest \
  packages/pneuma-knowledge-core/tests/test_source_types.py \
  packages/pneuma-knowledge-core/tests/test_context_stream_adapter.py -v

uv run python examples/context_stream_ab.py --show-prompt
```

第二条命令只渲染仓库内合成片段对应的 prompt，不调用模型。检查：

- `self/*` 被渲染为“本人”，`others/*` 被渲染为稳定编号的参与者；
- guidance 位于 blocks 之前；
- 通用 `upload` 路径没有第一方 guidance；
- prompt 中没有设备、企业品牌或私有业务假设。

## 可选真实模型 A/B

配置 `.env` 并启动本地依赖后：

```bash
docker compose -f infra/docker-compose.yml up -d --wait
uv run python examples/context_stream_ab.py
```

脚本把同一份合成片段分别作为 `upload` 与 `context_stream` 编译。它是开发者冒烟，
不是 benchmark。评审时只检查以下属性：

1. 本人与参与者的事实、建议和承诺没有串位；
2. 建议、疑问和回应没有被升级为已经确认的决定；
3. 环境噪声不进入 canonical；
4. 每条长期知识可以回到明确的合成来源块。

模型输出具有非确定性，单次结果不能形成效果结论。正式数据合成、评测集、judge
设计和统计实验应在独立任务中完成，并且只能使用经公开审查的合成数据。

## 增加新的第一方类型

1. 在 `domain/source.py` 增加来源枚举；确有必要时再扩展原始块结构。
2. 实现 `load`、`format`、`compile_guidance` 和 `indexing`。
3. 注册到 `_FIRST_PARTY_TYPES`。
4. 增加纯逻辑单测，并用 `--show-prompt` 检查真实 prompt 布局。

`compile_guidance` 应只表达该来源的公开数据语义与长期知识目标，不能嵌入某个设备、
客户、公司或私有产品的业务策略。
