# 远程采集云端

[English](README.md) | **简体中文**

这个可选的 Cloudflare 应用将远程 Codex、Claude Code 采集器接入个人知识库。每套部署属于一个 Owner。本机控制台生成十分钟有效的邀请和目标机器的安装命令；设备接入后，即使本机离线，也能继续采集上传。知识处理仍在本机通过共享的 agent-session 处理器进行；core 不依赖这个应用，也不要求向云端注册。

Worker 提供安装资产，并认证每一次材料操作。SQLite Durable Object 保存邀请、设备凭据、策略与投递回执；私有 R2 bucket 保存不可变的标准化快照和清单。上传下载都通过 Worker binding，邀请和采集器都不会得到 R2 凭据。

## 准备部署

需要 Node.js 22.13 或更新版本、pnpm 和 Python 3。`scripts/build_collector_assets.py` 从源码打包 Python 采集器和共享解码器；不要直接编辑 `public/` 内的生成文件。

```bash
cd apps/collector-cloud
pnpm install
pnpm run check
pnpm test
pnpm run dry-run
```

`check` 先根据 `wrangler.jsonc` 生成 binding/runtime 类型，再执行 TypeScript 检查。`dry-run` 打包实际采集器资产并验证部署，不会发布。测试使用本地 Miniflare、SQLite 和 R2，不需要 Cloudflare 账户、模型密钥或生产知识库。

为新 Owner 部署时，在 `wrangler.jsonc` 设置独立的 Worker、bucket 名称，登录该 Owner 的 Cloudflare 账户，创建私有 bucket，并配置至少 32 个字符的随机 Owner token：

```bash
pnpm exec wrangler login
pnpm exec wrangler r2 bucket create pneuma-collector-materials
pnpm exec wrangler secret put HOST_TOKEN
pnpm run deploy
```

在 Wrangler 的 secret 提示中输入 token。将 Worker 的 HTTPS 地址和同一个 Owner token 保存到本机控制台的远程数据源配置。这个 token 能管理本次部署内的所有知识库；不要放进采集器命令、URL、仓库或普通项目变量。本地运行 `pnpm run dev` 时可从 `.dev.vars.example` 创建 `.dev.vars`，但必须替换示例占位值。云端部署使用 Worker secret，不使用 `.dev.vars`。

Owner 在本机控制台创建邀请、控制设备。已撤销的设备需要使用新邀请，以新设备身份接入。暂停保留身份，可以恢复。撤销邀请不会撤销已经通过它接入的设备；需要停止设备时，应使用设备控制。

## HTTP 合约

协议版本为 `pneuma.collector/v1`。控制请求体和响应使用 JSON，错误格式为 `{"error":"code"}`。认证后的响应带 `Cache-Control: no-store`。凭据不进入查询参数，也不提供浏览器 CORS 接口。

Owner 请求使用 `Authorization: Bearer <HOST_TOKEN>`：

| 方法与路径 | 请求／结果 |
| --- | --- |
| `GET /v1/health` | `{protocol,status:"ok"}` |
| `POST /v1/libraries/{library_id}/invitations` | `{label,policy}` → `{invitation_id,invite_token,expires_at}`，十分钟有效 |
| `GET /v1/libraries/{library_id}/invitations` | `{invitations:[{invitation_id,label,status,expires_at,device_id}]}`，不返回 token |
| `DELETE /v1/libraries/{library_id}/invitations/{invitation_id}` | 撤销邀请，返回其当前视图 |
| `GET /v1/libraries/{library_id}/devices` | `{devices:[{device_id,library_id,label,status,policy,enrolled_at,last_seen_at,last_snapshot_at}]}` |
| `PATCH /v1/libraries/{library_id}/devices/{device_id}` | `{status:"active"\|"paused"\|"revoked",policy?}` → 设备视图 |
| `GET /v1/libraries/{library_id}/snapshots?cursor=0&limit=100` | `{items:[manifest],next_cursor,has_more}` |
| `GET /v1/libraries/{library_id}/snapshots/{snapshot_id}?device_id={device_id}` | 原始快照 JSON 字节，带 `X-Content-SHA256` |

`library_id`、`device_id` 最长 128 个字符，仅包含 ASCII 字母、数字、`_`、`-`，以字母或数字开头。Owner 创建邀请时决定目标知识库；设备不能选择或更改目标库。设备 ID 和凭据哈希在一次部署内唯一。

邀请策略如下：

```json
{
  "processor_id": "agent-sessions",
  "scope": {
    "projects": ["all"],
    "harnesses": ["codex", "claude-code"],
    "since": null
  },
  "interval_seconds": 300,
  "exclude": ["/tmp/**"]
}
```

`projects` 为 `["all"]`，或显式的远程项目路径列表。路径在词法规范化后精确匹配；选择目录不会同时授权其子项目。`since` 为 null 或 ISO 日期时间，与共享扫描器一致，按最后一个保留的对话 turn 的时间判断。可选排除列表传给采集器的共享扫描器。云端还会在每次上传时检查上报的 harness、项目与历史范围。轮询间隔范围为 30–86400 秒；项目和排除列表各最多 100 项。

接入使用 `POST /v1/enroll`，无需 bearer 请求头：

```json
{
  "invite_token": "<一次性邀请>",
  "device_id": "<本地生成的 ID>",
  "device_secret": "<本地生成的随机密钥>",
  "label": "Laptop"
}
```

采集器必须先保存 ID 和随机密钥，再发送此请求。密钥长度为 32–256 个字符，只含 URL 安全的字母、数字、下划线或连字符。响应为设备视图，不返回密钥。设备保留 Owner 创建邀请时填写的名称；可选的客户端标签不会将它改名。领取邀请和创建设备在同一个 SQLite 事务中完成。同一设备 ID 和密钥的重试，即使邀请已到期也能取回接入的当前状态，除非邀请或设备已撤销。客户端主机名变化不改变设备身份。其他设备或冲突密钥收到 `409 invitation_already_claimed`；未使用且已过期的邀请返回 `410 invitation_expired`。

设备请求使用 `Authorization: Bearer <device_secret>`：

| 方法与路径 | 请求／结果 |
| --- | --- |
| `GET /v1/device/policy` | 当前设备状态与策略；暂停设备仍可轮询 |
| `POST /v1/device/snapshots` | 原始快照 JSON 加 `X-Content-SHA256`；返回清单和 `duplicate` |

快照使用 `schema: "pneuma.material.agent-session/v1"` 和 `converter_version: 3`，具体结构由共享 Python 解码器定义。`snapshot_id`、`material_id` 为小写 SHA-256 十六进制标识。传输摘要覆盖实际上传的完整 UTF-8 字节，包括来源信息；下载方必须在处理前重新校验。如果提供了 `origin.device_id`，必须与认证设备一致。服务端不会将设备自己上报的来源当成经过密码学验证的账号或仓库身份。

清单包含 `{snapshot_id,material_id,library_id,device_id,sha256,bytes,committed_at,sequence}`。分页使用提交后单调递增的序号，不使用对象名或上传时间戳。即使列表尾部为空，也总会返回 `next_cursor`；保存它，并用 `has_more` 判断是否立即继续翻页。本机应用只有在可靠接收投递后，才能推进本地持久检查点。

## 存储与失败行为

对象路径由认证得到的知识库和设备限定：

```text
libraries/{library_id}/devices/{device_id}/snapshots/{snapshot_id}/snapshot.json
libraries/{library_id}/devices/{device_id}/snapshots/{snapshot_id}/manifest.json
```

同一份标准化材料可以在多台设备出现，并带不同来源信息。每次设备观察都有自己的不可变对象；后续的材料／项目合并不会抹去设备来源。

写入 R2 前，快照 ID 会先绑定其确切摘要。两个对象都使用条件创建，不能通过本 API 覆盖已有对象。相同重试返回原投递结果（`duplicate:true`）；不同字节返回 `409 snapshot_conflict`。只有快照已经存在，才会写清单；只有两个 R2 对象都存在，SQLite 提交并分配序号后，投递才进入列表。因此，较慢上传不会落在已确认较快上传的游标之前而被遗漏。

最终提交前失败，可能留下未列出的 R2 对象或待完成预约。采集器保留 outbox 项，重试完全相同的字节，继续完成投递。这是可重试并去重的投递，不是 R2 与 SQLite 之间的原子事务，也不承诺本机恰好导入一次。部署备份需要同时包含登记状态和 R2。登记状态丢失后，目前不会自动从 R2 重建已提交列表。

凭据和邀请只存哈希。撤销会立即拒绝后续请求，并在进行中的上传提交前再次检查。暂停设备不能上传；已撤销设备不能轮询，也不能使用旧邀请重新接入。已经提交的快照仍对 Owner 可用。

首版单快照上限为 **8 MiB**，即使没有 `Content-Length`，也会在读取时累计字节；每次部署最多同时缓冲两次上传（`429 upload_busy` 可以重试）。`MAX_SNAPSHOT_BYTES` 可以降低上限。超大会话返回 `413 body_too_large`；采集器应保留并报告，不能截断内容或标记为已上传。更大会话的传输需要后续分段协议。控制请求上限为 16 KiB。Owner 的设备／邀请列表各最多显示 1000 条；快照列表支持完整分页。

## 本地端到端验证

`tests/dev-server.mjs` 在 loopback 地址启动生产 Worker，使用合成本地 binding 和已打包资产的冻结副本。通过环境提供合成 `HOST_TOKEN`，可选 `COLLECTOR_TEST_PORT`（默认 48738）。启动后输出就绪地址和实际 Worker bundle 的摘要，通过 SIGINT 或 SIGTERM 停止。它不导入真实知识库，也不部署到 Cloudflare。

实现依据：[Workers 最佳实践](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)、[SQLite Durable Object 事务](https://developers.cloudflare.com/durable-objects/api/sqlite-storage-api/)、[R2 条件操作](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)、[Request/Response 流式 RPC](https://developers.cloudflare.com/workers/runtime-apis/rpc/)。
