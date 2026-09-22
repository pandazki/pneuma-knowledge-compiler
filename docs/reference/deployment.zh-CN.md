# 部署

[English](deployment.md) | **简体中文**

## 本地开发

需要 Python 3.12、uv、Docker、Node 18+ 和 pnpm。在仓库根目录执行：

```bash
uv sync --all-packages
cp .env.example .env             # 配置所选模型与契约；不要提交 .env
docker compose -f infra/docker-compose.yml up -d --wait
cd apps/web && pnpm install
```

用三个终端分别运行，每个都从仓库根目录开始：

```bash
bash scripts/dev-api.sh          # API 于 127.0.0.1:18000，自动重载
bash scripts/dev-worker.sh       # worker：正本与派生任务两条道
cd apps/web && VITE_ENGINE_FIXTURES=false pnpm dev  # Vite 于 :5173
```

该开关让引擎控制台连接真实引擎；不设时，该视图使用内置 fixture。其他视图仍调用 API。需要托管的单机安装，使用[个人版](../../personal/README.zh-CN.md)。

所有容器只绑回环地址，带健康检查（`--wait` 因此可用）。端口刻意避开常见默认值，且仓库里每套可运行的栈各占一个不相交的端口块：

| 栈 | Compose 项目名 | Postgres / Qdrant / Meili / RustFS | 其他 |
|---|---|---|---|
| 开发（本页） | `pneuma-knowledge-compiler` | 15432 / 16333 / 17700 / 19000 | API 18000、Vite 5173；RustFS 控制台 19001 |
| 生成的项目（`scaffold/init.py`） | `pneuma-<名字>-<hex>` | 全部在生成时探测空闲端口 | RustFS 控制台也单独探测 |
| `examples/opc/` | `pneuma-opc-example` | 25432 / 26333 / 27700 / 29000 | 纯文本示例；API 28000、web 24173；RustFS 控制台 29001 |

## 容器镜像

一个后端镜像，按命令分两个层：

- **API 层**（默认 `CMD`）：`uvicorn … --host 0.0.0.0 --port 8080`。
- **Worker 层**：把命令改成 `python -m pneuma_knowledge_service.workers.compile_worker`。两者都无状态；API 可水平扩容，worker 至少一个副本即可（按用户的任务串行由队列保证，与副本数无关）。

两件事写死在 Dockerfile 里，自建镜像最容易栽在这儿：

1. **镜像整仓复制、用 `uv run` 运行。** 这是一种做法，而非硬性要求：service wheel 现在把引导 schema 带进包内（`pneuma_knowledge_service/infra/schema.sql`），Postgres 适配器优先读这份打包副本，读不到才回落到源码目录里的 `infra/schema.sql`。所以裸 wheel 安装同样跑得起来；整仓复制适用于你希望把 checkout 的目录布局——测试、运维脚本、compose 文件——原样带进镜像的场景。
2. **运行时必须有 `git` 二进制**（正本适配器走子进程），并加 `git config --system --add safe.directory '*'` 应对卷 uid 与容器用户不一致的情况。正本数据放持久卷，`PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical`。

建 schema 的只有引擎自己的进程：引导批处理是 DDL（`CREATE INDEX IF NOT EXISTS` 即便索引已在，也要拿表的 ShareLock），所以其余进程——每个 `pkc` 命令、每个 `scripts/ops/` 命令——改为读 `schema_applied` 标记行（记录上次应用的 schema 文本的 sha256），只有该哈希与本次构建不符时才跑那批 DDL（全新数据库，或引擎尚未重启的升级）。

启动应用数据库 schema 并装配已配置的适配器。启用语义检索时，普通引擎启动会探测 embedding 维度并确认 Qdrant collection；`fake:<dim>` embedding 在本地运行，不需要密钥。`SEMANTIC_RETRIEVAL=off` 跳过 embedding 与 Qdrant。S3 client 是惰性的，首次导入图片时才创建或确认私有 bucket。切换 embedding 模型需要兼容的 collection 与派生重建；不同维度不能共用 collection。见[配置参考](configuration.zh-CN.md)。

## Web 层

`docker/web.Dockerfile` 构建 `apps/web` 并用 nginx 在 8080 托管：

- `/v1/` 与 `/healthz` 反代到 API 服务；关闭缓冲、`proxy_read_timeout 600s`，deep 检索的 SSE 流才活得下来。
- Live Context 的 WebSocket 路径（`/v1/users/*/live-context/ws`）单独一个 location，`proxy_read_timeout 3600s`。
- 其余走 SPA history 回退；`/_nginx_health` 本地返回。

Live Context 定期发送 WebSocket ping。Steward 对话同样需要 WebSocket upgrade 转发；仓库的 `docker/nginx.conf` 目前只为 Live Context 配了专用 upgrade location，因此通过它开放 Steward 前，需为 `/v1/users/*/steward` 扩展代理配置。Vite 代理和个人版引擎已支持该路由。

## 运维

- **派生层全部可重建**：`scripts/ops/rebuild_derived.py <user-id>|--all` 重建 L1 + L2 以及其上的各份投影，每一份都从它声明的底重建——两类权威（L0 横跨 Postgres 与 S3，正本位于 Git），使用侧投影再加上被保留的咨询记录——并前后对账。记录是保留的，不是重新推导的：重建重放它们，不动它们分毫。适用于中间件被清空或换版本、换嵌入模型（新 collection）、改切块策略之后。
- **只重切块**：`scripts/ops/reindex_l2.py <user-id>` 单独重跑 L2 切块与嵌入。
- **任务恢复**：重启和定时清扫都会回收孤儿认领（`WORKER_SELFHEAL_S`，默认 60 秒；`0` 关闭）。保留的 coding-agent 草稿随任务一起恢复，下一次启动可接着做。
- **重试、暂停、恢复**：可恢复失败依次间隔 1 分钟、5 分钟、15 分钟、1 小时、4 小时、24 小时重试，随后暂停。修好所报原因后，执行 `pkc jobs resume --job JOB_ID`。来源已删除、任务种类不受支持等明确不可恢复的错误直接失败。用 `pkc jobs` 查看原因与状态。
- **基础设施中断**：worker 按 2–60 秒退避探测故障服务，记录在途任务是重新入队还是已完结，服务恢复后继续。任务反复被中断时进入自己的重试计划。API 对受影响请求返回 `503 {"code": "infrastructure_unavailable"}`，可无需重启恢复。除非显式覆盖，连接的 `application_name` 标明进程角色。
- **追踪**（Langfuse）在三个 `LANGFUSE_*` 变量齐备时才开启；worker 每个任务结束后 flush。
