# {{PROJECT_NAME}} —— 我的知识库

由 pneuma-knowledge-compiler 的 scaffold 生成的知识库项目。

## 哪些文件是你的，哪些别动

**你的（随便改）：**

| 文件 | 是什么 |
|---|---|
| `contract.md` | 编译契约——这座库的宪法：什么值得记、记到哪一页。{{CONTRACT_HINT}} |
| `profile.yaml` | 你的主体档案（称呼、职业、时区语言） |
| `.env` | 密钥、模型、端口。key 只进这里，永不提交 |
| `my-data/` | 你的材料（`.md`，frontmatter 带 `date:`） |

**机器件（别改，改了升级会丢）：** `app.py`、`start.sh`、`docker-compose.yml`。
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
./app.py glance              # 库的鸟瞰
./app.py evolve [action]     # 结构演进：list / run / show / adopt / drop 提案
./app.py status              # 栈与库的状态
./app.py down [--volumes]    # 停栈（--volumes 连数据卷一起删）
```

## 重置重来

```bash
./app.py down --volumes && rm -rf data/
```

改了契约想在空库上重编时用（删掉的主体族不会自动迁移，空库最干净）。

## 想深入

- 写好契约的完整实践：框架仓库 `docs/guides/compile-contract.zh-CN.md`
- 让 AI 陪你迭代这座库：框架仓库 `scaffold/AGENT-GUIDE.zh-CN.md`
- 底下的机器：框架仓库 `docs/architecture.zh-CN.md`

框架仓库：`{{FRAMEWORK_REPO}}`（`.env` 的 `PNEUMA_APP_FRAMEWORK_REPO`）。
