# AGENTS.md

这是一个由 pneuma-knowledge-compiler scaffold 生成的知识库项目（不是框架仓库）。

**文件边界**：`contract.md`、`profile.yaml`、`.env`、`my-data/` 归用户，可以改；
`app.py`、`start.sh`、`docker-compose.yml` 是框架运行时的机器件——**不要改**，
要新版本就用框架仓库的 `scaffold/init.py` 重新生成。

**帮用户干活之前先读**（都在框架仓库 `{{FRAMEWORK_REPO}}`）：

- 陪用户建库/迭代库的完整流程：`scaffold/AGENT-GUIDE.zh-CN.md`
- 写编译契约的唯一权威：`docs/guides/compile-contract.zh-CN.md`

**红线**：用户数据与 key 永不写入任何会被 git 提交的位置；契约草稿必须经用户
过目才注册；不替用户虚构 profile 事实。

常用命令见 `README.md`。栈端口在 `.env`（生成时探测的空闲端口）。
