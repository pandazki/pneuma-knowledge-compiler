# {{PROJECT_NAME}}

由 Pneuma 生成、以来源为依据的知识库。
{{DEMO_SECTION}}
## 构建与检查

1. 亲自在编辑器中填写 `.env` 的模型凭据，不发给 agent，不放进命令文本。把输入放进
   `my-data/`，或使用生成时选择的外部目录。
2. 阅读 `engine/compile/contract.md`。{{CONTRACT_HINT}} `engine/persona/profile.yaml`
   中的拥有者资料是可选的，未知事实留空。
3. 运行普通构建，再对照来源检查知识库：

```bash
./start.sh                                  # 验证输入 → 启动 → 逐文件导入/编译
./app.py glance
./app.py ask '一个你实际需要答案的问题' --sources
./app.py status
```

构建成功表示材料导入与队列处理通过，不证明主张正确、概览忠实或有用事实没有遗漏。
`--sources` 会读取答案引用的精确 L0 段落，包括经由编译主张获得的引用。应检查原文是否
真正支持答案。回答或证据选择降级会明确显示。`data/run-reports/` 中的私有回执保留输入
哈希、来源 ID、engine 哈希、任务历史和回答细节；compile 模型 token 只是总成本的一部分。

## 材料格式

导入器先验证整个顶层目录，再按文件名顺序处理 `.json` 和 `.md`，忽略 `README.md`。
需要按时间回放时，请通过文件名排序表达；工具不会根据正文猜一个新顺序。

结构化导出使用框架 `docs/reference/source-contracts.zh-CN.md` 中的来源契约，每个 JSON
文件一份契约。身份、消息时间、线程、元数据和媒体放在各自字段中；一个 bundle 可以展开
为多个自然来源单元。不要为了符合契约而伪造精确时间戳或供应商身份。

Markdown 笔记可以携带 JSON 兼容的 frontmatter，它会保留为来源元数据：

```markdown
---
title: 发布决策
date: 2026-01-10
author: 产品团队
---
团队决定等无障碍审查完成后再发布。
```

简单对话可加 `type: conversation`，正文使用 `Speaker: text` 行。续行和消息内空行
需要缩进。没有说话者的开场文字、空消息会报错。这种有限语法不能表达任意参与者名字
或线程，遇到这些情况请用来源契约。只有日期就保留日期，不会补成当天中午。

## 命令与运行边界

| 命令 | 用途 |
|---|---|
| `./app.py build [dir]` | 与 `start.sh` 相同的普通构建 |
| `./app.py ingest [dir]` | 只导入，将索引与编译加入队列 |
| `./app.py compile` | 处理普通队列，对未解决 compile 任务追加一轮尝试 |
| `./app.py audit` | 只读审计整库出处与总览，发现问题时退出 1 |
| `./app.py ask '…' --sources` | 结构化 fast 回答及精确引用原文 |
| `./app.py ask '…' --deep` | agentic 检索/阅读循环，可能需要更多模型调用 |
| `./app.py ask '…' --as-of 2026-01-10T12:00:00Z` | 明确历史提问时间，省略表示现在 |
| `./app.py evolve step` | 创建结构调整提案，默认保留供审阅 |
| `./app.py evolve show/adopt/drop TASK_ID` | 查看或处理提案 |
| `./app.py up`、`init`、`glance`、`status`、`down` | 中间件、检测到的区域设置及知识库检查 |
| `./app.py restore` | 恢复随项目提供的 `prebuilt/` 演示库（若有） |

不要让 CLI 队列处理器和 console worker 同时运行。重试保留失败历史，反复调用 `compile`
会增加尝试次数，对比实验必须计入。`evolve step --policy adopt-clean` 明确启用机械检查
后自动采用，检查本身不替代对提案含义的审阅。

`status` 在中间件或知识库不可达时退出 1；退出 0 表示检查成功，不表示 pending/failed
数量为零。每次 CLI 处理队列前都会检查所有权，因为 console worker 可能在上一份输入后
启动。`audit` 也读取已结卷和归档，显示无关写入不必修复的历史缺陷；新增/改写内容及本轮
破坏的依赖仍会被拒绝。它不修改正本，机械审计通过也不证明语义忠实。

CLI 中断留下 claimed 任务时，先停止使用本中间件的所有 worker，再运行
`./app.py compile --recover`。恢复会重新排队本中间件中的 claimed 任务；普通构建不会
抢回可能仍由活跃 worker 执行的任务。

```bash
docker compose --profile console up -d --wait
# 浏览器界面：http://127.0.0.1:<.env 中的 PNEUMA_APP_WEB_PORT>
```

## 有意识地修改知识库

`engine/` 是独立 Git 仓库，保存策略、编译契约、可选资料和 prompt 覆写，入口是
`engine/README.md`。`.env` 保存凭据和本机端口，`my-data/` 保存输入，`data/` 保存私有
运行状态，这三者都不要提交到版本库。环境变量用于单次诊断，长期策略写入 `engine/`。

改契约只影响未来编译，重新导入相同材料通常会被去重；派生重建恢复索引，不会重新编译
正本。比较新契约时保留原库，在新项目构建，不要把删除知识库当作普通迭代步骤。
显式执行 `down --volumes` 会删除中间件数据。

运行机械层 `app.py`、`start.sh`、`server.py`、`worker.py`、`docker-compose.yml` 来自
框架模板。应改进模板，而非把策略藏进复制的代码；替换机械层时保留本项目的 engine 和数据。

框架：`{{FRAMEWORK_REPO}}`。验证流程见 `scaffold/AGENT-GUIDE.zh-CN.md`，契约设计见
`docs/guides/compile-contract.zh-CN.md`，内部机制见 `docs/architecture.zh-CN.md`。
