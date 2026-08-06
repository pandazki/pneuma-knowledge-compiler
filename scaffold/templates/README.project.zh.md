# {{PROJECT_NAME}} —— 我的知识库

由 pneuma-knowledge-compiler 的 scaffold 生成的知识库项目。
{{DEMO_SECTION}}
## 哪些文件是你的，哪些别动

**你的（随便改）：**

| 文件 | 是什么 |
|---|---|
| `engine/` | **这台引擎本身，你的，且被版本化**：模型角色、切块、回答风格、审计与演进的开关、编译契约、你的档案、提示词覆盖。它是一个独立的 git 仓库，每次改动都是一个可回看可回退的版本。先读 `engine/README.md` |
| `engine/compile/contract.md` | 编译契约——这座库的宪法：什么值得记、记到哪一页。{{CONTRACT_HINT}} |
| `engine/persona/profile.yaml` | 你的主体档案（称呼、职业、时区语言） |
| `.env` | 密钥与这台机器的基础设施（端口、compose 项目名）。key 只进这里，永不提交；策略一概不在这里 |
| `my-data/` | 你的材料（`.md`，frontmatter 带 `date:`） |

策略与密钥分开住，是因为 `engine/` 生来就是要被版本化、被分享、被回退的，而 `.env` 装着一份凭证，
永远不该被版本化。任何 `PNEUMA_KNOWLEDGE_*` 环境变量都能为单次运行盖过 `engine/` 里的同名设置——
那是给实验用的；长期有效的答案要写进文件。

**机器件（别改，改了升级会丢）：** `app.py`、`start.sh`、`docker-compose.yml`、`server.py`、`worker.py`。
它们是框架的运行时驱动，逻辑都在框架仓库里；想要新版本就用框架仓库里的
`scaffold/init.py` 重新生成一个项目，或从 `scaffold/templates/` 拷最新的过来。

## 命令

```bash
./start.sh                   # 一条命令端到端：起栈 → 检测环境 → 摄入 → 编译 → 问答演示
./app.py up                  # 启动中间件栈（端口在 .env，是生成时探测的空闲端口，启动后回显）
./app.py init                # 从系统检测时区/语言写回 profile.yaml
./app.py ingest [目录]       # 摄入材料（默认 my-data/）
./app.py compile             # 排空编译队列（真模型，花钱的一步）
./app.py ask '问题'          # 快通道问答（--sources 连引用原文一起打印；
                             #   --style concise|conversational|detailed 覆盖输出风格）
./app.py glance              # 库的鸟瞰（不需要 key）
./app.py evolve [action]     # 结构演进：list / run / show / adopt / drop 提案
./app.py status              # 栈与库的状态（不需要 key）
./app.py restore             # 恢复本项目自带的预编译库（只在有 prebuilt/ 时可用，不需要 key）
./app.py down [--volumes]    # 停栈（--volumes 连数据卷一起删）
```

## 在浏览器里看

一条命令起浏览层（框架 API + 编译 worker + Web 界面），三者都从 `.env` 指定的框架仓库构建：

```bash
docker compose --profile console up -d --wait    # 首次构建镜像要几分钟
# 然后打开 http://127.0.0.1:<.env 里的 PNEUMA_APP_WEB_PORT>
```

界面里能做的三件事：翻文库（每条结论都能点回原文那一段）、看流程（材料怎么变成结论）、
开**引擎控制台**——`engine/` 目录的投影：改一个配置、看清它的影响范围、apply 一次，
时间线上就多一个版本。没有 key 也能看：库、原料、引用全部可读，只有问答和编译需要 key。

## 重置重来

```bash
./app.py down --volumes && rm -rf data/
```

改了契约想在空库上重编时用（删掉的主体族不会自动迁移，空库最干净）。`engine/` 不受影响：
它是你的引擎，不是数据。

## 想深入

- 写好契约的完整实践：框架仓库 `docs/guides/compile-contract.zh-CN.md`
- 让 AI 陪你迭代这座库：框架仓库 `scaffold/AGENT-GUIDE.zh-CN.md`
- 底下的机器：框架仓库 `docs/architecture.zh-CN.md`

框架仓库：`{{FRAMEWORK_REPO}}`（`.env` 的 `PNEUMA_APP_FRAMEWORK_REPO`）。
