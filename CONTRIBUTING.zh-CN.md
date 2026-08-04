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

新增或改动编译行为需要测试守住四条承重性质：正本/派生边界、`user_id` 隔离、来源引用、合成诚实。[架构 §9](docs/architecture.zh-CN.md#9-不变量) 的五条不变量优先于任何局部取舍。

## 数据规则

所有示例与测试数据必须是合成的——不含凭证、真实个人材料或私有品牌内容。内置的人设与旅程都标注为合成，绝不作为真实客户证据呈现。第三方数据集永不入库；它们放在 git 忽略的 `local/` 下，按需重取。

## 语言

文档双语：英文为主（`X.md`）、中文镜像（`X.zh-CN.md`）——改动成对提交。代码与注释只用英文。scaffold 的用户可见文案刻意用中文，请保持。
