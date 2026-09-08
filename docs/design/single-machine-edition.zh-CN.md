# 个人版——库之上的一个应用

[English](single-machine-edition.md) | **简体中文**

状态：设计稿。建立在 [coding-agent-mode.zh-CN.md](coding-agent-mode.zh-CN.md)（门、skill、backend）
与 [steward-owner-visitor.zh-CN.md](steward-owner-visitor.zh-CN.md)（角色）之上。

## 1. 库与它的应用

Pneuma Knowledge Compiler 是一个**库**：`pneuma-knowledge-core` 与 `pneuma-knowledge-service`——领域、
四层、门、gate、API 应用、worker 循环、`pkc` 命令和各适配器。把它装起来、给它一张脸的一切，都是
**应用**。此前有两个：scaffold 项目（自己的栈、自己的 `.env`、自己的进程）和控制台 web（`apps/web`，
API 之上的 SPA，由项目 compose 的 `console` profile 拉起）。

本页增加第三个：**个人版**——一个人、一台机器、一个 coding agent 作为全部界面、一个托盘图标作为一瞥、
需要时打开控制台 web。它和另外两个一样是严格意义上的应用，也采用应用的严格形态：

| | scaffold 项目 | 控制台 web | 个人版 |
|---|---|---|---|
| 住在哪 | `init.py` 写到哪 | `apps/web/` | `personal/`（未来独立成仓） |
| 对库的依赖形式 | workspace 路径或框架仓库 | HTTP 之上的 API | 一行：`pneuma-knowledge-service @ git+…@<tag>` |
| 基础设施 | 每个项目一套栈 | 自己没有 | 每台机器一套栈，在 `~/.pkc` 下 |
| 库 | 一座 | URL 指到哪个租户 | 任意多座，同一套栈上的租户 |
| agent 的入口 | 装进项目的 skill | — | 装进 harness 的一份 skill |
| 进程 | `app.py up`、`server.py`、`worker.py` | nginx | `pkchome up`：中间件加一个引擎进程 |
| 分发 | 生成 | Docker 镜像 / 一份 `dist` | git release：一个包和一个桌面应用 |

原则：**库是一样东西，应用是另一样东西，个人版永远只是库的消费者。** 它只 import 两个包，不读框架
仓库的任何文件，不从 `scaffold/` 拷任何模板，不 fork `apps/web` 的任何源码。它需要而库尚未提供的
东西，作为库的功能加进库（§11），从不走私有路径。

## 2. 角色与动机（新增部分）

角色是框架的。本版增加一条关于安装的所有者动机、一条关于一瞥的，并保留 coding-agent 页引入的三条
冷启动动机：

| | 动机 |
|---|---|
| O13 | **只开一次头，永远接着用。** 机器只设置一次——基础设施、一个 key、一个名字——之后任何会话、任何目录都不再回答同一个问题 |
| O14 | **一句话安装。** 所有者已经有一个 coding agent；把一句话贴进去就是全部安装，剩下的 agent 来做 |
| O15 | **不用问就看得见。** 库在不在、上次编译落没落、key 是否过期——从菜单栏一眼看到，也从那里修好 |
| S10 | **知道这里已经有什么。** 在任何地方启动的 Steward 找到这台机器上的库，检查哪些还能用，接着对的那一座干，而不是提议再建一座 |
| S11 | **带着它已经知道的来。** Steward 跑在所有者用了几个月的 harness 里；它对所有者的记忆就是 profile 的初稿，所有者只需纠正而不是从头填 |

## 3. 用户故事

- **3.1 一句话（v1）。** 所有者有 Codex（或 Claude Code）和 Docker。把 README 的那句话贴进 harness。
  agent 跑安装脚本；脚本装 `uv`（缺则装）、按 release tag 装个人版包、给发现的每个 harness 装
  harness 级 skill、探 Docker，最后打印 agent 的下一步。agent 读 skill，跑 `pkchome status`——空——
  然后 `pkchome setup`：探测端口、写 `~/.pkc/config.yaml`、拉起中间件和引擎、建第一座库
  （`pkchome library create notes`），问冷启动仅有的两个问题（所有者是谁，以*"我认为你是 X，做 Y，用 Z
  写作——请纠正我"*的形式；不用语义检索跑还是给一个 key）。十分钟，两个问题，只打了一句话。
- **3.2 几周后，另一个目录（v1）。** *"把这些会议记录加进我的库。"* `pkchome status` 列出 `notes`
  （栈在跑、引擎在跑、key 在、skill 新鲜、上次用是周二）；Steward 摄入进去。不设置，不提问。
- **3.3 两座库（v1）。** *"客户的东西单独放。"* `pkchome library create acme --from notes` 复制引擎
  契约作起点；`pkchome library use acme` 设为当前，或 `pkchome library bind acme .` 绑到这个目录，在
  这里打开的会话就落在它里面。租户在同一套栈上靠 I1 隔离。
- **3.4 栈没了（v1）。** Docker 重启、端口挪了、机器睡了。托盘图标先于任何人的提问变成琥珀色：它自己
  的探针说 Docker 不在或某个端口黑了，不需要引擎回答。`pkchome status` 说清哪一项探测失败；
  `pkchome up` 按配置重建；数据卷原样回来。
- **3.5 初始化被记住（v1）。** setup 完成的每一步——栈、key、profile、skill、首次编译——按库记录；
  发现某步已完成的 Steward 不重做，也不再问它的问题。
- **3.6 引擎在，控制台就在（v1）。** `pkchome up` 启动每座库的引擎进程，每个引擎都在自己的端口上
  服务控制台 web；`pkchome console` 用浏览器打开当前库的那个。控制台顶栏按名字切换库、显示家的健康度；所有者视角的 Steward
  视图在库的目录里运行。
- **3.7 从托盘到页面（v1）。** 所有者在托盘面板里打一个问题。fast lane 带引用作答；点一条引用，
  控制台打开在那篇文档上。引擎不在时，面板给的是"启动"而不是空结果。
- **3.8 不开终端也能设置（v1）。** 托盘的设置页切换当前库、粘贴 embedding key（从不回显）、开关语义
  检索、选 backend、设开机自启。每个控件底下都是一条 `pkchome` 命令。
- **3.9 项目加入家（v2）。** scaffold 项目可以 `pkchome register <dir>`，`pkchome status` 就把它列在
  家自己的库旁边并探测；它保留自己的栈和 `.env`。

## 4. 裁定

1. **个人版是一个应用，在 `personal/`。** 目录按它将来要成为的仓库根来布局：自己的 `pyproject.toml`、
   自己的 `README`、自己的测试，桌面应用在包旁边。它的依赖规则是一条测试而不是一句话：`personal/`
   下的 Python 只 import `pneuma_knowledge_core`、`pneuma_knowledge_service` 和第三方；`personal/` 下
   没有任何文件写着指向 `scaffold/`、`apps/`、`examples/` 或 `packages/` 的路径
   （`tests/test_open_source_hygiene.py`）。
2. **`pkc` 是库的；`pkchome` 是个人版的。** Steward 的词汇——门、读面、`owner say`、`ingest`、
   `profile`、`archive`、`skill`——是库的命令，这里不加一个字。只有个人机器才需要的，另起第二条命令
   `pkchome`：setup、up、down、status、library、config、credentials、harness 级 skill、控制台、托盘。
   个人版的包不声明自己的 `pkc` 脚本——安装环境里唯一的 `pkc` 就是库的。个人版加的是进去的路：
   `pkchome exec -- <命令…>` 在从家装配出的环境（§4.5）下运行任何命令，安装脚本在 `pkchome` 旁边写一个
   `pkc` 启动器，内容就是 `pkchome exec -- pkc "$@"`；全局 skill 的 shim 也是同一行。`pkc` 零子命令、
   零旗标；skill 教的文字就是库的文字。
3. **每台机器一个家，`~/.pkc`（`PKC_HOME`）。** 它持有状态和配置——从不是来源、claim 或记录。第二台
   机器从空的家开始；靠复制目录搬走的库没有家也是完整的。库不知道家的存在：这个变量是个人版的，
   不是一个 `PNEUMA_KNOWLEDGE_*` 设置。
4. **每台机器一套基础设施，N 个租户。** Postgres、Qdrant、Meilisearch、RustFS 只跑一份，由 `pkchome up`
   从 `config.yaml` 生成的 compose 文件拉起；数据卷在 `~/.pkc/data/` 下。一座库是那套栈上的一个租户，
   像所有租户一样靠 I1 隔离；它的正本仓库在 `~/.pkc/libraries/<name>/canonical/`。
5. **个人版装配环境；库只读环境。** 优先级从低到高：框架默认 → `~/.pkc/config.yaml` → 库的引擎
   目录 → `~/.pkc/credentials`（引擎不得持有的 key）→ 进程环境。一个函数 `home_environment(library)`
   产出 `PNEUMA_KNOWLEDGE_*` 变量（以及 `PNEUMA_KNOWLEDGE_TENANT`、`PNEUMA_KNOWLEDGE_ENGINE_DIR`），
   `pkc` 入口、引擎进程和每库的 skill 渲染都用它。库的 `get_settings` 看到的只是一个进程环境，
   和在项目里完全一样。
6. **凭据只提供一次，从不复制。** `~/.pkc/credentials`（0600）存 `KEY=value`；任何库目录和引擎都
   不会拿到 key。进程环境里的 key 对那一个进程优先。
7. **选择被记录，记录过的选择不再问。** 每座库：`semantic_retrieval`、embedding 规格、backend；每个
   家：新库继承的默认值。Steward 开口之前先从 `pkchome status` 读它们。
8. **库是选出来的，不是猜出来的。** 租户解析：`pkchome` 上的 `--library` 或 `pkc` 上的 `--user` →
   环境里的 `PKC_LIBRARY` → 工作目录或祖先目录里的 `.pkc` 绑定 → `~/.pkc/current`。一个都没有时
   `pkchome exec` 在库的 `pkc` 运行之前就拒绝并列出库；它从不替所有者挑。
9. **skill 是全局的，契约不是。** harness 级的 `pkc-steward` skill 是个人版自己的文字
   （`personal/skill/`，中英）：你在哪、冷启动、怎么在一座库里继续、什么已被记住。它不提任何契约，
   因为它服务这台机器上的每一座库。每座库自己的包——契约、编译指令、CLI、gate，同一个哈希盖成
   `Executor-Skill`——由库自己的 `pkc skill install` 按 harness 的约定装进**库目录**
   （Codex 是 `.agents/skills/pkc-steward`，Claude Code 是 `.claude/skills/pkc-steward`，
   `pkc:start` 路由块落在旁边的 `AGENTS.md` / `CLAUDE.md`）。装在那里而不是装进个人版自己起名的
   目录，是因为**库目录就是 harness 为这座库站进去的那个项目**：引擎进程在那里启动，无人值守的
   worker 把那个目录当作轮次的项目交出去，轮次的任务把 shim 写成
   `<project_dir>/<manifest.skill_dir>/scripts/pkc`。渲染到别处的包，就是轮次手里没有的那条路径，
   轮次于是空转。全局 skill 进入一座库的第一步仍是读 `pkchome library show` 指出的那个包。
10. **每座库一个引擎进程。** 库的进程模型是一个进程一个引擎目录：它注册的契约、引擎目录写明的模型和
    措辞，都是进程级的。所以 `pkchome up` 先把中间件起一次，再按库各起一个进程，把这座库的 API 应用和
    worker 循环跑在一起（pid 和日志在 `~/.pkc/run/<name>.*`，端口记在 `library.yaml`），在那个端口上
    服务控制台 web。它的 worker 只消化自己的租户（§11.7），同一个 Postgres 上的两个引擎不会用错的
    契约编译对方的作业。agent 执行器下 worker 把编译作业留给 `pkc draft open`，除非库的无人值守姿态
    打开。`pkchome down` 只停 `pkchome up` 启动的东西。把 N 座库折进一个进程是以后的库功能
    （每租户的引擎目录），不是个人版的把戏。
11. **托盘是客户端，且自己会观测。** 桌面应用读 `~/.pkc` 和引擎的 API；自己不持有状态，除窗口几何
    外什么都不写。它自己做浅探针——Docker 守护进程、四个端口、引擎 pid——所以引擎死了是图标上的一种
    颜色而不是一片空白；引擎应答时再叠上深状态（队列、失败、每库健康）。它提供的每个动作都是以子进程
    跑一条 `pkchome` 命令，路径由 `config.yaml` 记录的安装位置给出。它渲染的状态就是
    `pkchome status --json`，和 Steward、控制台读的是同一份文档。
12. **控制台是被服务的，不是被 fork 的。** 引擎进程服务控制台 web 的构建产物 `dist`——作为产物取得
    （在本仓库里由 `apps/web` 构建，个人版独立成仓后从 release 下载），从不作为源码引入。控制台关于
    家需要知道的一切（按名字列库、健康页）是控制台自己的功能，藏在一个可选端点 `/home/status` 后面：
    宿主应答它，顶栏就出现切换器和健康页；没有宿主，控制台逐字节如今日。
13. **默认契约是个人版的资产。** 不带 `--contract` 建的库拿到 `personal-knowledge`，一份放在
    `personal/contracts/` 下、为一个人的笔记、会议、聊天和邮件写的契约。它从库的同名参考策略播种
    一次，此后就是个人版自己的：个人版运行时从不读 `pneuma-knowledge-strategies`，两者允许分叉。

## 5. 家

```
~/.pkc/
  config.yaml            install: {pkchome, pkc, version}; infra: {compose_project, data_dir, ports: {postgres, qdrant, meili, rustfs}};
                         defaults: {backend, language, semantic_retrieval, embedding}
  credentials            KEY=value，0600（OPENROUTER_API_KEY …）
  current                没有别的选择时会话落入的库名
  registry.json          （v2）用 `pkchome register` 登记的 scaffold 项目
  infra/
    docker-compose.yml   `pkchome up` 从 config.yaml 生成；配置变了就重新生成
  run/                   每座库引擎的 <name>.pid、<name>.log
  data/                  postgres、qdrant、meili、rustfs 数据卷
  libraries/<name>/
    library.yaml         租户 id、创建时间、引擎端口、选择 {semantic_retrieval, embedding, backend}、
                         步骤 {infra, credentials, profile, skill, first_compile}、last_used、绑定
    engine/              引擎目录（自己的 git 仓库），来自库的模板
    canonical/           正本 git 仓库
    .agents/skills/      按所选 harness 的约定装好的包（Claude Code 下是 `.claude/skills/`）：
                         pkc-steward/{SKILL.md, references/, scripts/pkc}，skill-version.json 在它旁边
    AGENTS.md            `pkc:start` 路由块（Claude Code 下是 CLAUDE.md）——库目录就是那个项目
```

`library.yaml` 就是框架要的初始化状态：一步由拥有它的命令完成时写下（`pkchome up` → `infra`；key 进
`credentials` → `credentials`；`pkc profile confirm` → `profile`；`pkchome library render` → `skill`；
第一次 `pkc draft finish` → `first_compile`），`pkchome status` 把它们和每项的实时探测一起读回。

## 6. 命令

```
pkchome setup [--non-interactive --answers <f>]   config.yaml、探测端口、拉起基础设施与引擎、第一座库、两个问题
pkchome up | down | restart                       全机的中间件与引擎进程
pkchome status [--json] [--library <name>]        逐项探测：docker、四个服务、引擎、队列；每座库：key、引擎目录、正本、skill 新鲜度、已完成步骤、上次使用
pkchome library create <name> [--from <name>] [--language …] [--contract <path>]
pkchome library ls | show [<name>] | use <name> | bind <name> [<dir>] | unbind [<dir>] | render [<name>]
pkchome config get|set <key> [<value>] [--library <name>]   家的默认值或某座库的选择（semantic_retrieval、backend、embedding）
pkchome credentials set KEY [--from-stdin]        写 ~/.pkc/credentials（0600）；从不回显
pkchome env [--library <name>]                    装配好的环境，给 shell 或脚本用
pkchome exec [--library <name>] -- <命令…>        在那个环境下运行一条命令；`pkc` 解析为库的那个
pkchome skill install [--backend codex|claude-code|all] [--force]   harness 级 skill；自动检测在场的 harness
pkchome console                                   用浏览器打开引擎的控制台
pkchome tray                                      已安装则启动桌面应用，否则说去哪拿
pkchome register <dir> | forget <dir>             （v2）
```

`pkc <任何子命令>` 是库的命令，经个人版的启动器运行（§4.2）。`pkchome setup` 是唯一的交互命令，且只在
接了终端时交互；Steward 用 `--answers` 把所有者说的话带进去跑它。

`pkchome status --json` 是三个读者共用的契约——Steward、控制台的健康页、托盘。形状：`home`（路径、
版本）、`docker`（可达否）、`services`（四个，各 `{port, up}`）、`libraries`（各 `{name, current, engine: {pid, up, port, uptime}, queue: {pending, failed,
last_compile_at}, key, engine_dir, canonical_head, skill_fresh, steps, last_used}`）。

## 7. 全局 skill

`pkc-steward`，装进 `~/.codex/skills/pkc-steward/` 或 `~/.claude/skills/pkc-steward/`（盖 marker、
`--force` 守卫，用库的安装器装个人版的包）。文字是个人版自己的，在 `personal/skill/`（中英），
不含契约。它的几节：

- **你在哪。** 先 `pkchome status`，靠机制而不是靠叮嘱：没选库时 `pkchome exec` 会拒绝并列出库，跳过
  status 的会话会撞上这个拒绝。
- **冷启动。** 两个问题，以及 Steward 自己怎么回答第一个：用它已经知道的写 profile
  （`pkc profile set … --provenance inferred`，coding-agent-mode §5.8），请所有者逐项纠正；把所有者
  的检索选择记下（`pkchome config set semantic_retrieval …` 或 `pkchome credentials set`，
  coding-agent-mode §5.9）。
- **在一座库里继续。** 读这座库自己的包（`pkchome library show` 给路径）；从那里起，一轮、门和姿态
  就是库渲染出的文字。
- **什么已被记住。** 步骤和选择；`pkchome status` 已回答的，Steward 不再问。

每库的包就是项目 skill 的 `references/` 加一页把它们按名字绑到这座库的 `SKILL.md`——同一个渲染器，
和项目里的 Steward 带的是同一个 `Executor-Skill` 哈希。

## 8. 那一句话

README 只放一句话，给 agent 而不是给人：

> 安装 pkc 个人知识库：运行 `curl -fsSL <release-url>/install.sh | sh`，然后按它最后打印的指引继续。

`install.sh` 是这句话触发的机制。它幂等，依次做：`uv`（缺则装）→ 按 release tag `uv tool install`
个人版包 → 对目录存在的每个 harness（`~/.codex`、`~/.claude`）跑 `pkchome skill install` → 探
Docker（`docker info`；失败则打印 Docker Desktop 或 OrbStack 从哪来并停下，不假装成功）→ 可选地从
同一个 release 拿桌面应用。它最后几行是写给读它的 agent 的：装了哪个 `SKILL.md`、去跑 `pkchome
status`、下一条命令是 setup。这几行存在的理由：跑安装脚本的那个 harness 未必会在同一个会话里重新
加载 skill。

## 9. 托盘

`personal/desktop/` 下的一个 Tauri 2 应用，随同一个 release 出 `dmg` / `exe`。它是客户端（§4.11），
以手感论成败：

- **是 popover，不是窗口。** macOS 上是锚在菜单栏图标下的面板（`NSPanel`），无标题栏，失焦即收；
  Windows 与 Linux 上是定位到托盘的无边框窗口。面板 UI 随应用打包、从磁盘加载；打开它不花一次网络
  往返。
- **先显状态，再更新。** Rust 侧一个轮询器从启动起就跑：读 `~/.pkc`，探 Docker、四个端口和引擎 pid，
  引擎应答时问 `/home/status`。面板打开的一瞬间渲染上一次已知状态，之后以事件接收变化。打开时转圈
  是缺陷。
- **没有引擎也能观测。** 图标颜色来自浅探针，所以引擎死了图标会变。深状态（队列、失败、每库健康）
  可用时作为一层叠加。
- **三块面板。** 看板（状态文档、最近几次编译、失败作业的重试）；搜索（fast lane 带引用，每条打开
  控制台的那篇文档；引擎不在时是一个启动按钮）；设置（当前库、经密文框输入的 embedding key、语义
  检索、backend、开机自启——每项都是一条 `pkchome` 命令）。
- **动作即 `pkchome`。** 启动、停止、重启、切换、设置——应用跑 `config.yaml` 记录的那条命令，失败时
  展示它的输出。它从不直接碰 `~/.pkc`。
- 可选：搜索的全局快捷键（Tauri 的 global-shortcut 插件）；经 autostart 插件开机自启。

## 10. 家之上的控制台

一座库的引擎进程是一个 FastAPI 应用：库的 `create_app(settings)` 加个人版的路由——`/home/status`
（整个家的状态文档）、`/home/libraries`（每座库及其引擎端口，切换即跳转）、`/home/actions/*`
（托盘用的那些 `pkchome` 动词）——再把控制台的 `dist` 挂在 `/`，带 SPA 回退。控制台那一侧很小、很通用：一个探 `/home/status` 的
`useHome()`，应答时把裸 user id 切换器换成按名字列的库、并加一页健康页；`apps/web` 把这当自己的
功能加上，项目形态不受影响。

## 11. 库要开的口子

每一条都是库的功能，在项目形态下也有自己的用处，加进库是为了个人版永远不需要私有路径：

1. **从显式环境装配设置。** `get_settings` 已经读进程环境和引擎目录；个人版只需要一条有文档的
   路径在装配好的环境下运行它（§4.5）。确认 `PNEUMA_KNOWLEDGE_ENV_FILE` 未设时工作目录里的 `.env`
   不会漏进来。
2. **单进程引擎。** `create_app(settings)` 和 worker 的 `run_forever()` 能在同一个事件循环里跑、能
   干净地停；worker 从同一个对象取设置。
3. **模板作为包数据。** scaffold 从 `scaffold/templates/` 读的引擎、profile、契约模板挪进 service 包
   （`engine/templates/`），scaffold 改从那里读；scaffold 的 `init.py` 算的 compose 生成变成一个库
   函数，两边都调它。
4. **每库的 skill 包。** `render_skill_package` 已按（契约 × 措辞 × 组件 × backend）渲染；个人版
   需要一条 `pkc skill render --out <dir>`，只写出包、不装进项目，`Executor-Skill` 哈希不变。
5. **检索旋钮与 profile 出处。** coding-agent-mode §5.8 与 §5.9，照那里写的做；两者都是项目形态也
   要的库行为。
6. **静态挂载缝。** `create_app` 接受一个可选的静态目录来放控制台 `dist`（项目形态仍用 nginx；
   个人版用这个）。
7. **worker 的租户过滤。** `PNEUMA_KNOWLEDGE_WORKER_TENANTS`（逗号分隔；空即所有租户，也就是今天的
   行为）：worker 只认领这些租户的作业。同一个 Postgres 上的两个引擎就是两个互不碰对方队列的 worker。

## 12. 不变量

- **I1。** 库即租户；每条命令运行前都解析出一个租户，拒绝而不默认。worker 照旧按租户消化。
- **I2 / I7。** 家不持有权威也不持有记录：正本仓库和 L0 在原处；skill 包是派生的、可重渲染。
- **I3–I6。** 不动。
- **依赖方向单向且有测试。** `personal/` → 两个库包和控制台的产物；`packages/`、`apps/`、`scaffold/`
  里没有任何东西 import 或读 `personal/`，`personal/` 也不读它们的任何东西。
- **机制优于说服。** "先选库"是一次拒绝，不是 skill 里的一句话；"别再问"是完成那步的命令记下的
  一个步骤；依赖规则是一条 hygiene 测试。
- **机密。** `credentials` 是 0600，在任何 git 仓库之外（引擎是仓库，家不是），从不复制进库，从不进
  渲染出的 skill，从不进托盘的状态。

## 13. 实施顺序

1. **库的口子**（§11.1–11.4、11.6、11.7）：确认只读环境的设置装配、单进程引擎、模板作为包数据并让
   scaffold 改用它、`pkc skill render --out`、静态挂载。
2. **个人版的包**：`personal/` 与 `pyproject.toml`、`home_environment`、租户解析与带拒绝的 `pkchome exec`；`pkchome library …`、`library.yaml`；`pkchome up|down|restart|status` 与生成的 compose、
   引擎进程；`pkchome config|credentials|env`；`pkchome setup`；默认契约；hygiene 测试。
3. **库里的检索旋钮与 profile 出处**（§11.5）。
4. **全局 skill** 与 `pkchome skill install`；`library create` 时渲染每库的包。
5. **安装脚本**（`install.sh`）与 README 那句话；在这台机器上用 Codex 做一次真实冷启动：从空的家到
   第一次编译，像验收那样记录下来。
6. **家之上的控制台**：`/home/*` 路由、挂载的 `dist`、控制台的 `useHome()` 切换器与健康页。
7. **托盘**：Tauri 应用、轮询器、三块面板、release 构建。
8. 端到端：在干净的家上从那一句话开始，经托盘，到控制台的一个页面。

## 14. 边界

- 一台机器。跨机器共享一个家或一套栈，未设计。
- 家不是备份：`pkchome down` 保留数据，但这里没有任何东西把它复制到别处。
- Docker 仍是前提；更轻的适配器组成的无 Docker 栈是以后的一页。
- 跑不了命令行的 AI（聊天应用）在这里没有脸；只读的 MCP 面是以后的一页。
- Kimi、evolve 门、单次角色跑在 agent 上，仍停在 coding-agent-mode 留下的位置。

## 15. 编程代理会话作为材料

Owner 的裁定按主体排列知识：首先是**项目本身**——用途、受众、顶层设计、演进、关键
功能与里程碑；其次是 **Owner 如何思考这些项目**，证据来自 Owner 自己的输入；最后
才是具体制作过程。编程代理转录的大部分是代理输出。有些会话是研究、闲聊或其他任务，
并非项目工作。文件夹或转录不会原样进入编译器。

三个机制落实这个顺序：

1. **来源契约与正规化器。** 库拥有 `pneuma.source.agent-session/v1`：身份明确的 Owner
   `say` 发言、代理 `narrative` 叙述与有界 `action` 短句，附项目归属及带时区、不递减的
   时间戳。至少需要一条非空 Owner 发言。工具输入输出不是来源文本；动作只是一行
   最多 200 字符的说明，不是命令结果或成功证明。
2. **导入前分流。** 本版转换器仅在项目匹配且至少三次 Owner 发言时提供编译候选。
   默认值是 `--min-owner-turns 3`、`--min-owner-chars 200` 和 `--ack-max-words 1`。
   Owner 文本不足 200 字符就**跳过**，即使其他条件满足；0 关闭长度过滤。发言阈值
   可提高，不能低于库的三次下限。发言次数不足、项目不匹配，或只有斜杠命令／已知
   确认语的会话请求 `canonical_treatment: none`。现有 CLI 用 `--intake searchable`
   表达它，因此同时请求不建 L2；准入会话的 L0/L1 仍无条件可达。子代理任务提示被
   排除，不归到 Owner 名下；过滤后没有 Owner 发言的转录被跳过。用
   `--purpose research|chat` 选中的研究／闲聊会话接受同样的只索引处理。这些是机械
   准入条件，不代表语义上判定了每条候选会话都含值得编译的知识。
3. **编译契约与 Owner 声音页面。** 新库以 `personal-projects` 更新 §4.13 所述的默认
   契约。本版自有的双语契约依次组织 `projects/{slug}/overview.md`、`evolution.md`、
   `features/{slug}.md`、`decisions/{slug}.md`，然后是 `owner/views/{slug}.md`，再是
   `memory/people/{slug}.md` 与 `memory/topics/{slug}.md`。概览定义与摘要解释项目，
   演进条目携带日期。`owner/views/{slug}.md` 路径模板以 `path`／`owner_voice` 映射
   声明 `owner_voice: true`，创建模板也携带该标记；库的闸门落实路径声明，并核验
   引用来自 Owner 本人发言。代理叙述支持报告的工作与项目状态，不能支持 Owner 的
   观点。制作过程没有 canonical 文档族：修改、命令与暂时测试失败留在 L0/L1，供
   主体页面下检索与引用。研究／闲聊不产生 canonical 页面，除非 Owner 表达持久
   观点；这类发言可在另行请求的草稿轮次中支持观点。`--contract personal-knowledge`
   仍是随包提供的备选，`--contract <path>` 仍接受自定义契约。

提供方转换器留在 **PKC 库之外**。它是 Steward 的工具，位于
`personal/skill/scripts/agent_sessions.py`，随本版全局技能安装，只使用 Python 3.12
标准库。Owner 指定目录；Steward 运行 `list --project <dir>`，展示逐会话判定，然后运行
`ingest --project <dir>`。`--session-id` 从混合项目文件夹中选择特定会话；`--since` 按
保留活动是否达到带时区的指定时刻过滤。`export --project <dir> --out <dir> [--owner-id …]`
为每条准入会话写出一个过滤后的契约载荷。Export 的 Owner id 默认是 `owner`；ingest
在未覆盖时使用所选库租户。Claude Code 由 `~/.claude/projects` 下编码的项目目录归属；
Codex 由 `~/.codex/sessions` 下 rollout 的 `cwd` 归属。记录的目录冲突时跳过会话，
包括编码名称碰撞。手动导入只索引的 export 时需要 `--intake searchable`；分流元数据
本身不覆盖库的 intake。

转换器逐字保留 Owner 原话与代理叙述，同一消息的文本块用一个换行连接，丢弃工具结果、
思考过程、压缩摘要和宿主注入上下文，并将动作缩为工具名加路径或命令的可执行程序名
（省略参数）。它稳定排序已有时间戳，不改变其代表的时刻；发言时间缺失时继承前一个
记录时间，没有可用时间则报错。它不扫描项目源码，也不把完整转录送入导入接口。测试
只使用合成的提供方记录。

Ingest 解析本版既有的库选择，在每次 `pkchome exec --library <name> -- pkc ingest
--contract agent-session/v1 --file …` 中固定它，并仅将成功导入的载荷哈希与会话身份
记到 `~/.pkc/libraries/<name>/ingested-sessions.json`（遵循 `PKC_HOME`）。这是可丢弃的
**本版状态**，不是权威或保留的知识记录。原子写入与每库导入锁保护它。重跑跳过未变化
载荷，变化的会话成为新的不可变来源材料，失败导入仍可重试。`ingest --dry-run` 不改变
来源或该状态。转换器的任何操作都不写 canonical。

## 16. 应用负责的增量与常驻同步

Owner 的裁定是：外部材料持续增长属于个人版的问题。长时间运行的编程会话必须基于
先前结果和待处理增量进入知识库；不能因文件修改时间变化，就把完整会话再次当作新材料。
库不知道监视目录、转录游标或托盘调度，只看到传给 `pkc ingest` 的 `agent-session/v1`
载荷。本节以共用的增量机制替代 §15 的整载荷导入跟踪，转换器手动 `ingest` 也使用它。

`library.yaml` 保存 `watch: [{path, harnesses: [claude-code, codex], since?}]`。
路径解析为绝对目录，按 §15 精确选择；`since` 是可选、含端点且带时区的保留活动下限，
只用于会话首次导入，不从已准入会话或待处理增量中丢弃发言。`pkchome watch add <dir>
[--library NAME] [--harnesses codex claude-code] [--since ISO]`、`watch ls` 和
`watch rm <dir>` 维护列表；移除目录仍保留游标。Setup answers 可包含 `watch: [dirs]`。
即使目录相同，各库的监视列表和游标也相互独立。

`~/.pkc/libraries/<name>/sync-state.json` 按会话保存 `{provider, session_id, file,
source_ids, exported_turns, last_turn_id, last_at, prefix_hash, held}`。会话键包含提供方、
会话身份和项目；同一文件的会话身份变化也算重写。`file_size` 界定最近观察的 SHA-256
前缀，`exported_bytes` 记录最后成功导出的字节边界；有 held 材料时两个边界不同。
状态不保存转录原文。游标规则由机械逻辑执行：

- 完整文件的大小与前缀哈希相同：unchanged，不导入，与 mtime 无关。未变化的 held
  会话仍报告其 held 数量。计数有意重叠：`unchanged` 表示观察是否变化，`held` 表示
  仍在等待足够输入的会话数。
- 文件增长且旧前缀完整：将保留发言与已验证的导出前缀比较，包含之前 held 的材料。
  Reader 排除事件镜像及非准入材料；多重集相减保留真实的重复发言，并处理延迟时间戳，
  不丢失也不重复早先发言。新部分的发言 ID 接续已导出数量，载荷内仍按时间排序。
  JSONL 最后一条记录未完成时等待写完；有效的末尾记录无需换行。本机制不读取 mtime。
- 未达到任一分流阈值：记录 `held: {owner_turns, chars}` 和观察前缀，保持
  `exported_turns`、`exported_bytes`、`last_turn_id`、`last_at`、`source_ids` 不动。
  每份待处理增量默认要求三次 Owner 发言和 200 个 Owner 文本字符；转换器手动
  `ingest` 仍接受原有阈值参数。两个数值阈值都满足后，同一分流逻辑判定完整编译资格
  或只索引（仅命令/确认语，或显式研究/闲聊）。子代理与目录冲突被排除。目录缺失及
  解析/导入错误报告为 skipped/error 行；失败导入仍可重试。
- 达到阈值：只将新发言导出为新的不可变来源。`metadata` 携带 `from_turn`（首条
  保留发言 ID）、`part`（从 1 开始），续接时还携带 `continues`（紧邻的上一来源 ID）。
  只有 ingest 返回一个来源 ID 后才推进导出游标。应用契约要求先读早先部分形成的
  canonical 页面，不重读旧转录；断言引用实际所属部分。
- 观察前缀变化、截断或已保留历史变化：报告 `rewritten`，不替换游标。显式传入
  `--rewritten reingest` 才在满足资格时导入替换内容；重新开始发言游标，保留来源 ID
  历史，标记 `rewritten` 而不声明 `continues`。

旧 `ingested-sessions.json` 条目被一次性吸收：恢复转换后载荷与记录哈希精确相同的
完整历史文件前缀，再经普通 ingest 去重取得既有来源 ID。来源仍存在时不会创建新来源
或任务。长文件的一次性搜索可能较贵。旧哈希无法复现（转录被重写、旧转换选项或
Owner ID 未知）时报告 `rewritten`；迁移绝不猜测今天的末尾就是旧末尾。原有旧记录
保留，已迁移键从新状态的 legacy 映射中移除。

`pkchome sync [--library NAME] [--dry-run] [--json] [--rewritten report|reingest]`
执行一轮，报告 `{scanned, new, increments, held, unchanged, rewritten, ingested,
skipped}` 及逐会话结果。文本模式列出来源 ID 与入队的编译任务。紧接着重跑不会新增
入队。`run/<name>.sync.lock` 的 advisory lock 拒绝并发写入进程，进程死亡时释放。
Dry run 不创建文件、不更新游标、不调用 ingest，迁移显示为待执行。每次 ingest 前，
精确载荷先原子写到 `sync-pending/`，哈希和拟提交游标写入 sync 状态。崩溃或响应丢失
时，先经库去重重放相同字节，再处理新增长；即使监视已移除也如此。只有返回的来源 ID
和游标保存成功后才删除载荷日志。

托盘仍是客户端（§4.11）。Rust poller 分别为每座有监视目录、引擎运行、间隔到期且无
sync 运行中的库请求 `/home/actions/sync`。`config.yaml` 保存
`sync: {interval_minutes: 15, enabled: true}`；`pkchome config set sync.interval_minutes N`
及 `sync.enabled on|off` 修改全 home 配置。引擎 action 脱离当前进程会话启动
`pkchome sync --library <this> --json`，固定到自身 home 和库。`/home/status` 包含每库
的 `sync` 观察，顶层 `sync` 对应该引擎服务的库：`{last_run_at, last_result, watching,
next_due}`，另有 `running`、当前 `held` 数及供调度使用的数值 `next_due_ms`，客户端
无需解析日期。到期时间由记录的上一轮和当前间隔计算；从未运行的监视立即到期。
Poller 也按间隔限制 action 尝试，避免陈旧状态或启动失败使每次健康轮询都触发重试。
Settings 通过 `pkchome watch` 提供间隔、开关和监视目录；Dashboard 显示
“watching N dirs · last sync … · held M” 和 “Sync now”。托盘绝不打开转录。

Sync **不编译**。Ingest 写 L0，并将普通 index/compile 任务加入库的队列，由无人值守
引擎 worker 或 Steward 经现有闸门排空。框架自身的队列计数是另一件事：`held` 是
尚未进入库的外部材料，`ingested` 是本轮收到成功响应的来源部分数，两者都不是任务数，
也不意味着编译完成。该机制不涉及库 package、控制台应用或 scaffold 修改。
