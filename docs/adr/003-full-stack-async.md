# ADR-003：全栈异步（ports / core / adapters / 路由 / worker）

日期：2026-07-22 ｜ 状态：已接受

## 背景

context_stream 的 AI cue 功能要用 WebSocket 长连接。GKE 上 API 是**单 uvicorn 进程、无
`--workers`**（`deploy/gke/base/app-deployment.yaml`），也就是**一个事件循环服务整个 API**。
WS handler 必须是 `async def`；若在其中直接调用当时的同步 core，一次 3 秒的 LLM 调用会占住
循环，把所有用户的 recall、所有其他 WS 连接、以及 `/healthz` 探针一起卡住——最后一项会让
Kubernetes 判定 pod 已死并在请求中途重启它。

此前所有路由都是同步 `def`，FastAPI 把它们丢进 anyio 线程池，因此不存在这个问题。引入 WS
就引入了它。

## 决策

全栈异步：23 个端口 Protocol 方法、core 中所有碰端口或模型的函数、全部 adapter、21 条路由、
compile worker，一路改到底。

边界纪律：**凡不 await 任何东西的就不是协程**。`spine` / `citation_alias` / `projection` /
`gate` / `patch` / `domain` / RRF 与各 render 助手全部保持同步——无谓的 async 传染会逼所有
调用方 await 却零收益。

## 备选与否决理由

- **async 边界只放在路由层**（路由 `async def`，core/adapter 保持同步，交界处统一 `to_thread`）：
  能拿到同等的「循环不被阻塞」正确性，零依赖变更，现有测试一个不用改。否决理由不是性能，而是
  这条边界**没有机械保障**：它靠每个调用点记得包 `to_thread`，漏一个就是一次静默回归，且症状
  （偶发的探针超时、莫名的 pod 重启）离病因极远。全栈异步让「忘记 await」变成一个显式的
  `RuntimeWarning: coroutine was never awaited`，把纪律换成机制（§0 纪律 1）。
- **维持同步 + 为 WS 单开一个进程**：绕过问题而非解决，且立刻要面对两套部署、两份配置。

## 后果

- **换包**：官方 `meilisearch` 0.42.0 仅同步 → `meilisearch-python-sdk` 7.3.0 的 `AsyncClient`。
  `psycopg` / `qdrant-client` 自带异步类，无需换包。
- **新增 dev 依赖** `pytest-asyncio`，配 `asyncio_mode = "auto"`。
- **三处仍是线程池，且在代码里明确注明不是真异步**（不假装）：`git_canonical`（git 是
  subprocess，整个同步方法体一次 `to_thread`，保证多命令写不被打断）、`flush_traces`
  （langfuse SDK 同步）、chonkie 分块（CPU 密集）。
- **`on_step` 获得一条阻塞契约**：core 的 `_NotifyingTrail.append` 同步调用它，而它现在从
  async 工具闭包里、在事件循环上、await 中途触发。传进去的回调一旦阻塞就会拖垮所有请求。
  SSE 端点传的是纯 `put_nowait`（无界队列）。
- **并发性质本身被测试守住**：迁移前后测试数都是 257 passed，因为每个测试都只发一个请求，
  分辨不出「重叠」和「串行」——整场重构的唯一目的此前零覆盖。新增
  `test_async_concurrency.py`（并发不串行 / `/healthz` 后发先至 / 所有路由处理器必须是协程）
  与 `test_recall_stream.py`（此前零测试的 SSE 端点）。两者都做了变异验证：把实现改回阻塞
  或改成攒完再发，对应断言确实变红。
- **examples 脚本**入口改 `asyncio.run(main())`（每个 helper 各自 `asyncio.run` 会新建循环，
  使 PG 连接池与 httpx client 这类绑定循环的资源失效）。

## 未决

真正的并发上限尚未被压测过。此次改动移除了「每请求一线程」的天花板，但 PG 连接池大小、
OpenRouter 的速率限制、以及单进程单循环本身都可能先成为瓶颈。等 cue 的 WS 长连接上线、
有了真实并发形态再测，不预先调参。
