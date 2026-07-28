# Contributing

感谢你改进 Pneuma Knowledge Compiler。

## 开发环境

```bash
uv sync --all-packages
docker compose -f infra/docker-compose.yml up -d --wait
cd apps/web && pnpm install
```

## 提交前

```bash
uv run pytest
cd apps/web && pnpm run build
```

新增或修改编译行为时，请补充测试，保持 canonical 与 derived 的边界、`user_id` 隔离、来源引用和 synthetic honesty。任何示例数据必须是合成数据，不能包含凭据、真实个人材料或私有品牌内容。

公共术语见 [docs/ubiquitous-language.md](docs/ubiquitous-language.md)，架构不变式见 [docs/architecture.md](docs/architecture.md)。
