# AGENTS.md

这是一个由 pneuma-knowledge-compiler scaffold 生成的知识库项目（不是框架仓库）。

**文件边界**：`engine/`（这台引擎：策略、`compile/contract.md`、`persona/profile.yaml`、
提示词覆盖——它是一个独立的 git 仓库，每次改动一个提交）、`.env`（密钥与本机端口，永不被版本化）、
`my-data/` 归用户，可以改；`app.py`、`start.sh`、`docker-compose.yml`、`server.py`、`worker.py` 是框架运行时的机器件——
**不要改**，要新版本就用框架仓库的 `scaffold/init.py` 重新生成。

**策略住在哪**：`engine/`，不在 `.env`。迭代这座库就是改那里的文件并提交，这样每条业务规则都有一个
可查看、可回退的版本。各文件的影响半径写在 `engine/README.md`。任何 `PNEUMA_KNOWLEDGE_*` 变量
都能为单次运行盖过引擎里的同名设置——那是临时诊断或运维用的缝，不是记长期决定的地方。

**帮用户干活之前先读**（都在框架仓库 `{{FRAMEWORK_REPO}}`）：

- 陪用户建库/迭代库的完整流程：`scaffold/AGENT-GUIDE.zh-CN.md`
- 写编译契约的唯一权威：`docs/guides/compile-contract.zh-CN.md`

**红线**：用户数据与 key 永不写入任何会被 git 提交的位置；契约草稿必须经用户
过目才注册；不替用户虚构 profile 事实。

常用命令见 `README.md`。栈端口在 `.env`（生成时探测的空闲端口）。
