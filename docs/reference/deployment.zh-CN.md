# 部署

[English](deployment.md) | **简体中文**

## 本地开发

四个中间件容器加两个宿主进程：

```bash
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres、Qdrant、Meilisearch、RustFS
bash scripts/dev-api.sh          # uvicorn 于 127.0.0.1:18000，自动重载
bash scripts/dev-worker.sh       # 编译 worker（排空任务队列）
cd apps/web && pnpm dev          # Vite 于 :5173，把 /v1 与 /healthz 代理到 :18000
```

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

启动刻意做成 fail-closed 且依赖网络：`build_context()` 先建 schema，再用**一次真实 embedding 调用**探测向量维度，然后连上 Meilisearch 与 Qdrant——四者齐备前不服务任何请求，启动窗口要给足预算。S3 client 是惰性的：第一次图片导入才创建或确认私有 bucket；compose 健康检查仍会确保整栈报告 healthy 之前 RustFS 已就绪。探测出的维度是承重的：换 `EMBEDDING_MODEL` 意味着换 collection 名并重建派生层；不同维度不能共存一个 collection。

## Web 层

`docker/web.Dockerfile` 构建 `apps/web` 并用 nginx 在 8080 托管：

- `/v1/` 与 `/healthz` 反代到 API 服务；关闭缓冲、`proxy_read_timeout 600s`，deep 检索的 SSE 流才活得下来。
- Live Context 的 WebSocket 路径（`/v1/users/*/live-context/ws`）单独一个 location，`proxy_read_timeout 3600s`。
- 其余走 SPA history 回退；`/_nginx_health` 本地返回。

API 侧还会对 WebSocket 客户端做约 30 秒一次的 ping，避免带空闲超时的中间层（如 Cloudflare 约 100 秒）掐断长连接。

## 运维

- **派生层全部可重建**：`scripts/ops/rebuild_derived.py <user-id>|--all` 重建 L1 + L2 以及其上的各份投影，每一份都从它声明的底重建——两类权威（L0 横跨 Postgres 与 S3，正本位于 Git），使用侧投影再加上被保留的咨询记录——并前后对账。记录是保留的，不是重新推导的：重建重放它们，不动它们分毫。适用于中间件被清空或换版本、换嵌入模型（新 collection）、改切块策略之后。
- **只重切块**：`scripts/ops/reindex_l2.py <user-id>` 单独重跑 L2 切块与嵌入。
- **任务自愈**是内建的：worker 重启时回收死进程留下的孤儿任务；任何异常都以失败完结，不会卡死该用户的队列。死掉的启动若留下一份已写有内容的 coding-agent 草稿，这份草稿会随重新入队的任务保留，下一次启动接着做，而不是从头来过。同一次清扫在 worker 运行期间也按时钟跑一遍（`WORKER_SELFHEAL_S`，60 秒；`0` 关闭），跳过它自己正在跑的那些认领，于是一条谁也说不清来历的认领会在一分钟内回到队列，而不是等到下一次进程启动。
- **基础设施中断不会让引擎停下。** Postgres、Qdrant、Meilisearch 或 RustFS 断开或重启时，worker 只记一行日志（`[compile-worker] infrastructure unavailable (postgres: <原因>); retrying in 2s`），从 2 秒起退避、逐次翻倍、最长 60 秒，探测出故障的那个服务，等它有了应答再继续（`… infrastructure back after Ns; resuming (job <id> requeued)`）。**一条认领熬不过一次中断**：从认领到完结之间无论哪一步抛出异常——那一轮本身，或是紧随其后的派生工作——当时持有的任务都会放回队列；如果它的工作其实已经做完，就补写它的完结记录。无论哪种情况，任务既不会丢失，也不会重复执行，而且恢复那一行永远写明它对在途任务做了什么（`(job <id> requeued)`、`(job <id> completed)`、`(no job in flight)`）。若一个传输层错误没有被它的客户端包起来就直接抛到 worker 面前，那也是同一件事，按同样的方式处理（`http: <原因>`，并逐一探测每个外部依赖——赤裸的那种错误并不说是哪一个不见了）。而真正因自身原因失败的作业永远说得出理由：行上写异常自己的话，没有话就写它的类名（`worker error: httpx.ReadError`），worker 日志里则留下带 lane 与 job id 的完整堆栈。而一个被反复中断、drain 不再放回的作业写的是这件事本身（`infrastructure repeated: qdrant (ReadError) interrupted this job 4 times; failed`），行上和一行 warning 里各说一次。这期间 API 对受影响的请求返回 `503 {"code": "infrastructure_unavailable"}`，并且无需重启就能恢复，因为 Postgres 连接池在交出每一条连接之前都会先检查它。若 worker 在 drain 循环之外被中断停下，引擎会就地重启它（`[engine] worker stopped: …; restarting in Ns`），API 照常服务。每条 Postgres 连接都在 `application_name` 里写明自己的进程角色（`pkc-engine-api`、`pkc-engine-worker`、`pkc-api`、`pkc-worker`、`pkc-cli:<命令>`），除非 DSN 或 `PGAPPNAME` 已经设了名字。
- **追踪**（Langfuse）在三个 `LANGFUSE_*` 变量齐备时才开启；worker 每个任务结束后 flush。
