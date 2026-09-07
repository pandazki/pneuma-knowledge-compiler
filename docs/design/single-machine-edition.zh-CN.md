# 单机版——`pkc` 与 `~/.pkc`

[English](single-machine-edition.md) | **简体中文**

状态：设计稿。建立在 [coding-agent-mode.zh-CN.md](coding-agent-mode.zh-CN.md)（门、skill、backend）
与 [steward-owner-visitor.zh-CN.md](steward-owner-visitor.zh-CN.md)（角色）之上。

## 1. 同一个框架的两种形态

到目前为止一套部署只有一种形态：**项目目录**——由 scaffold 生成，带自己的中间件栈、自己的 `.env`、
自己的引擎、自己的 API 和 worker。这种形态保留：它适合把框架嵌进应用的场景、适合多座库各占一套栈
的团队，也是每一条测试的形态。

本页增加第二种，给一个人在一台机器上用：**`pkc` 加 `~/.pkc`**。一套共享的基础设施，启动一次、一直
在；任意多座库作为它上面的租户；一个 coding agent——Codex、Claude Code——作为全部界面，由一份放进
这个人已经在用的 harness 里的 skill 教导；控制台可选。库本身在两种形态之间一处未变：同样的四层、
同样的门、同样的 gate、同样的引擎目录。变的是机器住在哪、由谁启动。

| | 项目形态 | 单机版 |
|---|---|---|
| 基础设施 | 每个项目一套栈，在项目的 compose 文件里 | 每台机器一套栈，在 `~/.pkc/infra` 下，启动一次 |
| 一座库 | 就是项目 | 一个有名字的租户：`~/.pkc/libraries/<name>/` |
| 配置 | 项目的 `.env` | `~/.pkc/config.yaml` + `credentials`，加每座库自己的引擎 |
| 进程 | 每个项目自己的 `app.py up`、`server.py`、`worker.py` | `pkc up`：全机的中间件和一个 worker 守护进程；需要时 `pkc console` |
| agent 的入口 | 装进项目的 skill | 装进 harness 用户级 skill 目录的 skill |
| 所有者站在哪 | `cd` 进项目 | 任何地方；库选一次，或绑定到某个目录 |
| 隔离 | 按栈 | 按租户（I1），同一套栈 |

拆分背后的原则：**框架是同一份代码加两种设置装配。** 项目的 `.env` 和家的 `config.yaml` 都解析成
同一个 `Settings`；`pkc`、API 和 worker 从不知道自己跑在哪种形态里。

## 2. 角色与动机（新增部分）

角色是框架的。本版增加一条所有者动机和两条 Steward 动机，正是 harness 解决的冷启动：

| | 动机 |
|---|---|
| O13 | **只开一次头，永远接着用。** 机器只设置一次——基础设施、一个 key、一个名字——之后任何会话、任何目录都不再回答同一个问题 |
| S10 | **知道这里已经有什么。** 在任何地方启动的 Steward 找到这台机器上的库，检查哪些还能用，接着对的那一座干，而不是提议再建一座 |
| S11 | **带着它已经知道的来。** Steward 跑在所有者用了几个月的 harness 里；它对所有者的记忆就是 profile 的初稿，所有者只需纠正而不是从头填 |

## 3. 用户故事

- **3.1 第一次（v1）。** 所有者有 Codex 和 Docker。装一次 skill（`pkc skill install --global
  --backend codex`，或 README 给的一行命令），在任何地方打开 Codex：*"帮我建知识库。"* Steward 跑
  `pkc home status`——空——然后 `pkc setup`：探测空闲端口写 `~/.pkc/config.yaml`，启动中间件
  （`pkc up`），问冷启动仅有的两个问题（所有者是谁，以*"我认为你是 X，做 Y，用 Z 写作——请纠正我"*的
  形式；不用语义检索跑还是给一个 key），建第一座库（`pkc library create notes`），说材料放哪。十分钟，
  两个问题。
- **3.2 几周后，另一个目录（v1）。** *"把这些会议记录加进我的库。"* `pkc home status` 列出 `notes`
  （栈在跑、key 在、skill 新鲜、上次用是周二）；Steward 摄入进去。不设置，不提问。
- **3.3 两座库（v1）。** *"客户的东西单独放。"* `pkc library create acme --from notes` 复制引擎契约
  作起点；`pkc library use acme` 设为当前，或 `pkc library bind acme .` 绑到这个目录，在这里打开的
  会话就落在它里面。租户在同一套栈上靠 I1 隔离。
- **3.4 栈没了（v1）。** Docker 重启、端口挪了，或者是台新机器。`pkc home status` 说清哪一项探测
  失败；`pkc up` 按配置重建；库的数据在家的数据目录里，原样回来。
- **3.5 初始化被记住（v1）。** setup 完成的每一步——栈、key、profile、skill、首次编译——按库记录；
  发现某步已完成的 Steward 不重做，也不再问它的问题。
- **3.6 需要时才有控制台（v1）。** `pkc console` 启动 API 并在家之上服务 web 控制台；所有者视角的
  Steward 视图在库的目录里运行。
- **3.7 项目加入家（v1）。** scaffold 项目可以 `pkc home register <dir>`，`home status` 就把它列在家
  自己的库旁边并探测；它保留自己的栈和 `.env`。

## 4. 裁定

1. **每台机器一个家，`~/.pkc`（`PNEUMA_KNOWLEDGE_HOME`）。** 它持有状态和配置——从不是来源、claim
   或记录。第二台机器从空的家开始；靠复制目录搬走的库没有家也是完整的。
2. **每台机器一套基础设施，N 个租户。** Postgres、Qdrant、Meilisearch、RustFS 只跑一份，由 `pkc up`
   从 `config.yaml` 生成的 compose 文件拉起；数据卷在 `~/.pkc/data/` 下。一座库是那套栈上的一个租户，
   像所有租户一样靠 I1 隔离；它的正本仓库在 `~/.pkc/libraries/<name>/canonical/`。
3. **设置从家装配，和从项目装配完全一样。** 优先级从低到高：框架默认 → `~/.pkc/config.yaml` → 库的
   引擎目录 → `~/.pkc/credentials`（引擎不得持有的 key）→ 进程环境。`pkc`、API 和 worker 读同一个
   `Settings`，从不读家的路径。
4. **凭据只提供一次，从不复制。** `~/.pkc/credentials`（0600）存 `KEY=value`；任何库目录和引擎都
   不会拿到 key。环境里的 key 对那一个进程优先。
5. **选择被记录，记录过的选择不再问。** 每座库：`semantic_retrieval`、embedding 规格、backend；每个
   家：新库继承的默认值。Steward 开口之前先从 `pkc home status` 读它们。
6. **库是选出来的，不是猜出来的。** 租户解析：命令上的 `--user`/`--library` → 环境里的
   `PNEUMA_KNOWLEDGE_TENANT` → 工作目录或祖先目录里的 `.pkc` 绑定 → `~/.pkc/current`。一个都没有时
   `pkc` 拒绝并列出库；它从不替所有者挑。
7. **skill 是全局的，契约不是。** harness 级的 `pkc-steward` skill 教门、一轮、姿态和家；它不提任何
   契约，因为它服务这台机器上的每一座库。每座库在 `~/.pkc/libraries/<name>/skill/` 下渲染自己的参考包
   （契约、编译指令、CLI、gate——同一个生成器，同一个哈希盖成 `Executor-Skill`），全局 skill 进入一座库
   的第一步是读 `pkc library show` 指出的那个包。
8. **worker 是机器的，一轮是 agent 的。** `pkc up` 启动一个 worker 守护进程（pid 文件在
   `~/.pkc/run/`），为每个租户消化索引、投影、重建作业；agent 执行器下它把编译作业留给 `pkc draft
   open`，除非库的无人值守姿态打开，那时它像项目形态一样拉起 harness。`pkc down` 只停 `pkc up` 启动
   的东西。

## 5. 家

```
~/.pkc/
  config.yaml            framework: {repo | package}; infra: {compose_project, data_dir, ports: {postgres, qdrant, meili, rustfs}};
                         defaults: {backend, language, semantic_retrieval, embedding}; console: {port}
  credentials            KEY=value，0600（OPENROUTER_API_KEY …）
  current                没有别的选择时会话落入的库名
  registry.json          用 `pkc home register` 登记的 scaffold 项目（路径、上次探测）
  infra/
    docker-compose.yml   `pkc up` 从 config.yaml 生成；配置变了就重新生成
  run/                   worker 与控制台的 pid 文件和日志
  data/                  postgres、qdrant、meili、rustfs 数据卷
  libraries/<name>/
    library.yaml         租户 id、创建时间、选择 {semantic_retrieval, embedding, backend}、
                         步骤 {infra, credentials, profile, skill, first_compile}、last_used、绑定
    engine/              引擎目录（自己的 git 仓库），来自框架的模板
    canonical/           正本 git 仓库
    skill/               渲染出的参考包：SKILL.md（指向本库）、references/、skill-version.json
```

`library.yaml` 就是框架要的初始化状态：一步由拥有它的命令完成时写下（`pkc up` → `infra`；key 进
`credentials` → `credentials`；`pkc profile confirm` → `profile`；`pkc skill render` → `skill`；
第一次 `pkc draft finish` → `first_compile`），`pkc home status` 把它们和每项的实时探测一起读回。

## 6. 命令

```
pkc setup [--non-interactive --answers <f>]     config.yaml、探测端口、拉起基础设施、第一座库、两个问题
pkc up | down | status                          全机的中间件与 worker；`status` 探测每个服务
pkc home status [--json]                        库与登记的项目，逐一探测：基础设施、key、引擎、正本、skill 新鲜度、已完成步骤
pkc home register <dir> | forget <dir>
pkc library create <name> [--from <name>] [--language …] [--contract <template>]
pkc library ls | show [<name>] | use <name> | bind <name> [<dir>] | unbind [<dir>]
pkc config get|set <key> <value> [--library <name>]   家的默认值或某座库的选择（semantic_retrieval、backend、embedding）
pkc credentials set KEY [--from-stdin]           写 ~/.pkc/credentials（0600）；从不回显
pkc skill install --global --backend codex|claude-code|all    harness 级 skill；`pkc skill render [--library]` 渲染每库的参考包
pkc console [--port]                             在家之上跑 API 与 web 控制台
```

其他所有 `pkc` 命令——`ingest`、`draft`、`owner say`、`profile`、`archive`、各读命令——不变，作用于
选中的库。`pkc setup` 是唯一的交互命令，且只在接了终端时交互；Steward 用 `--answers` 把所有者说的
话带进去跑它。

## 7. 全局 skill

`pkc-steward`，装进 `~/.codex/skills/pkc-steward/` 或 `~/.claude/skills/pkc-steward/`（盖 marker、
`--force` 守卫，和项目 skill 同一个安装器）。由 catalog 渲染（`steward.home.*`，中英），不含契约文本。
它的几节：

- **你在哪。** 先 `pkc home status`，靠机制而不是靠叮嘱：没选库时其他每条 `pkc` 命令都会拒绝并列出
  库，跳过 status 的会话会撞上这个拒绝。
- **冷启动。** 两个问题，以及 Steward 自己怎么回答第一个：用它已经知道的写 profile
  （`pkc profile set … --provenance inferred`），请所有者逐项纠正；把所有者的检索选择记下
  （`pkc config set semantic_retrieval …` 或 `pkc credentials set`）。
- **在一座库里继续。** 读这座库自己的包（`pkc library show` 给路径）；从那里起，一轮、门和姿态就是
  项目 skill 的文字，按库渲染。
- **什么已被记住。** 步骤和选择；`home status` 已回答的，Steward 不再问。

`~/.pkc/libraries/<name>/skill/` 下的每库包，就是项目 skill 的 `references/` 加一页把它们按名字绑到
这座库的 `SKILL.md`——所以 Steward 在库里读到的文字与项目里的 Steward 读到的相同，`Executor-Skill`
盖的也是同一个哈希。

## 8. 项目形态保留什么、什么挪走

`scaffold/init.py` 和项目形态的行为不变。三样东西挪进框架包让两种形态共用：引擎与 profile 模板
（scaffold 从包里读而不是自己的 `templates/`）、compose 生成（端口、项目名、数据路径——scaffold 的
`init.py` 已经在算，改为调共享函数）、设置装配的家这一层。scaffold 项目可以把自己登记进家
（`pkc home register`），在 `home status` 里带着自己的栈一起被探测。

## 9. 不变量

- **I1。** 库即租户；每条命令运行前都解析出一个租户，拒绝而不默认。worker 照旧按租户消化。
- **I2 / I7。** 家不持有权威也不持有记录：正本仓库和 L0 在原处；skill 包是派生的、可重渲染。
- **I3–I6。** 不动。
- **机制优于说服。** "先选库"是一次拒绝，不是 skill 里的一句话；"别再问"是完成那步的命令记下的
  一个步骤。
- **机密。** `credentials` 是 0600，在任何 git 仓库之外（引擎是仓库，家不是），从不复制进库，从不进
  渲染出的 skill。

## 10. 实施顺序

1. 设置：家这一层（`PNEUMA_KNOWLEDGE_HOME`、`config.yaml`、`credentials`、优先级）与租户解析
   （`--library`、绑定、`current`、拒绝）。
2. `pkc library create|ls|show|use|bind`，带步骤和选择的 `library.yaml`；模板挪进包；每库的
   `pkc skill render`。
3. `pkc up|down|status`、生成的 compose、worker 守护进程、`pkc home status` 探测、`pkc home register`。
4. `pkc setup`、`pkc credentials set`、`pkc config get|set`；`semantic_retrieval` 作为引擎旋钮，被
   intake、索引和每条 lane 尊重（coding-agent-mode §5.9）。
5. `pkc profile` 的出处与"先推断"流程（coding-agent-mode §5.8）。
6. 全局 skill 与其安装器；每库的包。
7. `pkc console`；scaffold 的 `init.py` 改用共享函数；`home register`。
8. 在这台机器上用 Codex 做一次真实冷启动：从空的家到第一次编译，像验收那样记录下来。

## 11. 边界

- 一台机器。跨机器共享一个家或一套栈，未设计。
- 家不是备份：`pkc down` 保留数据，但这里没有任何东西把它复制到别处。
- Kimi、evolve 门、单次角色跑在 agent 上，仍停在 coding-agent-mode 留下的位置。
