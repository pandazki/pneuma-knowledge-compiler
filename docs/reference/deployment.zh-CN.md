# 部署

[English](deployment.md) | **简体中文**

## 本地开发

三个中间件容器加两个宿主进程：

```bash
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres、Qdrant、Meilisearch
bash scripts/dev-api.sh          # uvicorn 于 127.0.0.1:18000，自动重载
bash scripts/dev-worker.sh       # 编译 worker（排空任务队列）
cd apps/web && pnpm dev          # Vite 于 :5173，把 /v1 与 /healthz 代理到 :18000
```

所有容器只绑回环地址，带健康检查（`--wait` 因此可用）。端口刻意避开常见默认值，且仓库里每套可运行的栈各占一个不相交的端口块：

| 栈 | Compose 项目名 | Postgres / Qdrant / Meili | 其他 |
|---|---|---|---|
| 开发（本页） | `pneuma-knowledge-compiler` | 15432 / 16333 / 17700 | API 18000、Vite 5173 |
| 生成的项目（`scaffold/init.py`） | `pneuma-<名字>-<hex>` | 生成时探测空闲端口 | |
| `examples/opc/` | `pneuma-opc-example` | 25432 / 26333 / 27700 | API 28000、web 24173 |

## 容器镜像

一个后端镜像，按命令分两个层：

- **API 层**（默认 `CMD`）：`uvicorn … --host 0.0.0.0 --port 8080`。
- **Worker 层**：把命令改成 `python -m pneuma_knowledge_service.workers.compile_worker`。两者都无状态；API 可水平扩容，worker 至少一个副本即可（按用户的任务串行由队列保证，与副本数无关）。

两条硬约束写死在 Dockerfile 里，自建镜像最容易栽在这儿：

1. **整仓复制、用 `uv run` 运行。** Postgres 适配器按自身源码路径定位 `infra/schema.sql`，裸 wheel 安装跑不起来——源码目录布局必须原样进镜像。
2. **运行时必须有 `git` 二进制**（正本适配器走子进程），并加 `git config --system --add safe.directory '*'` 应对卷 uid 与容器用户不一致的情况。正本数据放持久卷，`PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical`。

启动刻意做成 fail-closed 且依赖网络：`build_context()` 先建 schema，再用**一次真实 embedding 调用**探测向量维度，然后连上 Meilisearch 与 Qdrant——四者齐备前不服务任何请求，启动窗口要给足预算。探测出的维度是承重的：换 `EMBEDDING_MODEL` 意味着换 collection 名并重建派生层；不同维度不能共存一个 collection。

## Web 层

`docker/web.Dockerfile` 构建 `apps/web` 并用 nginx 在 8080 托管：

- `/v1/` 与 `/healthz` 反代到 API 服务；关闭缓冲、`proxy_read_timeout 600s`，deep 检索的 SSE 流才活得下来。
- Live Context 的 WebSocket 路径（`/v1/users/*/live-context/ws`）单独一个 location，`proxy_read_timeout 3600s`。
- 其余走 SPA history 回退；`/_nginx_health` 本地返回。

API 侧还会对 WebSocket 客户端做约 30 秒一次的 ping，避免带空闲超时的中间层（如 Cloudflare 约 100 秒）掐断长连接。

## 运维

- **派生层全部可重建**：`scripts/ops/rebuild_derived.py <user-id>|--all` 从两个权威存储重建 L1 + L2 + L3 投影，前后对账。适用于中间件被清空或换版本、换嵌入模型（新 collection）、改切块策略之后。
- **只重切块**：`scripts/ops/reindex_l2.py <user-id>` 单独重跑 L2 切块与嵌入。
- **任务自愈**是内建的：worker 重启时回收死进程留下的孤儿任务；任何异常都以失败完结，不会卡死该用户的队列。
- **追踪**（Langfuse）在三个 `LANGFUSE_*` 变量齐备时才开启；worker 每个任务结束后 flush。

