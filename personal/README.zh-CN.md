# PKC personal

[English](README.md)

> 安装 pkc 个人知识库：运行
> `curl -fsSL https://raw.githubusercontent.com/pandazki/pneuma-knowledge-compiler/main/personal/install.sh | sh`，
> 然后遵循它最后打印的指引。

这句话写给编程代理，不是写给终端：把它贴进 Codex 或 Claude Code，代理会安装本版、读取
随之安装的技能，并从那里继续。

在一台机器上维护一个人的多个带引用知识库。`pkchome` 管理 home（默认 `~/.pkc`，
可用 `PKC_HOME` 修改）、共用的 Docker 中间件和明确选定的库。
安装的库提供 `pkc`，所有 canonical 写入都通过其草稿闸门。

## 安装脚本做什么

`install.sh` 幂等，随时可重跑。顺序如下：

1. **`uv`** —— 缺失时用官方脚本安装；本次运行会把 `~/.local/bin` 加入 PATH。
2. **`pkc-personal`** —— 从固定的发布版做 `uv tool install --force`。`PKC_RELEASE=<ref>`
   安装其他 ref；`PKC_SOURCE=<dir>` 从本地检出安装。
3. **`pkc` 启动器** —— 写在 `pkchome` 同一个 bin 目录下（内容为
   `exec pkchome exec -- pkc "$@"`）。该处已有的非本版 `pkc` 会被拒绝，绝不覆盖。
4. **技能** —— 对每个存在的宿主目录（`~/.codex`、`~/.claude`）执行
   `pkchome skill install --force`。
5. **Docker** —— 探测 `docker info`。失败时说明 Docker Desktop 或 OrbStack 从哪里获取，
   并以退出码 3 停止；此前完成的步骤不会回滚，重跑即可继续。
6. **控制台页面** —— 执行 `pkchome console install`。只有在本仓库内构建的 wheel 才自带
   已构建页面，否则从 `personal-console-v<version>` 发布下载，并在写入任何文件之前校验
   随发布公布的 sha256。此步绝不致命：机器离线时上面各步的成果照旧保留，首次打开
   `pkchome console` 时再取。
7. **桌面应用** —— 发布构建后配合 `PKC_DESKTOP=1` 下载；否则只打印一行，说明
   `pkchome tray` 会告知从哪里获取。

每一步打印一行 `ok:` 或 `skip:`，最后几行给出已安装的 `SKILL.md` 与接下来要运行的两条
命令。`--quiet` 只输出错误和这个末尾块。

## 命令

```
pkchome setup [--answers <file>] [--non-interactive] [--no-skill]
pkchome up | down | restart | console [install] | tray
pkchome status [--json] [--library <name>]
pkchome onboarding [--library <name>]
pkchome library create <name> [--from <name>] [--language en|zh] [--contract personal-projects|personal-knowledge|<path>] [--backend …]
pkchome library ls | show [<name>] | use <name> | bind <name> [<dir>] | unbind [<dir>] | render [<name>]
pkchome config get|set <key> [<value>] [--library <name>]
pkchome credentials set KEY [--from-stdin] [--no-verify]
pkchome env [--export] [--library <name>]
pkchome exec [--library <name>] -- <command…>
pkchome skill install [--backend codex|claude-code|all] [--force]
```

`register` 与 `forget` 是 v2 占位命令。`down` 保留中间件数据。

可选的 [PKC 桌面托盘](desktop/README.zh-CN.md) 显示机器与知识库状态、提供带引用的搜索，
并通过 `pkchome` 修改设置。将 `PKC.app` 安装到 `~/Applications` 或 `/Applications`，
然后运行 `pkchome tray`；未安装时，该命令会打印发布页面。开发时运行
`cd personal/desktop && pnpm install`，再运行 `pnpm tauri dev`；使用 `pnpm tauri build`
构建安装包。即使引擎未运行，托盘仍会独立探测 home；详细健康信息来自各运行中引擎的
`/home/status`。

Setup 回答字段：`library: notes`、`language: en`、`backend: codex`、
`semantic_retrieval: off`；可选的 `embedding_key` 只进入凭据文件；可选的 `owner:` 映射
写明 Owner 已经给出的档案字段（`display_name`、`occupation`、`role`、`industry`、`bio`
等 `pkc profile` 的任意字段），按“Owner 亲述”写入。配置的 embedding
服务商的密钥在写入前会先向该服务商验证一次——被拒绝的密钥不改变任何东西（不写文件、
不重启引擎、保留原密钥），离线时可用 `--no-verify` 跳过验证直接保存。Setup 需要终端或
`--answers`；`--no-skill` 跳过向检测到的宿主目录安装技能。

Setup 不会把档案留成空白。它读取这台机器已经说明的 Owner 信息——账户全名、系统时区、
界面语言（`language` 回答优先于它）——并以 `inferred` 出处写入；在 Owner 逐项确认之前，
`pkchome status` 不会把这样的档案算作已完成。`pkchome onboarding` 打印剩下要做的事：
带值的推断字段与确认或更正它们的命令、尚未回答的注册问题（用 Owner 自己的语言提问），
以及仍未决定时的检索选择。Setup 会打印同一段内容；这条命令是留给之后才到场的 Steward 的——
setup 未能写入推断字段时，`onboarding` 会自行补写，并在首行报告 `seeded: <字段>`，
清单里因此不会缺掉确认这一步。

`config get|set` 读写每个库（不带 `--library` 时则是 home 的默认值）记录下来的一项选择：
`backend`、`language`、`semantic_retrieval`、`embedding`、`unattended`，以及
`model` / `reasoning_effort`——这个库的编译与演进轮跑哪个模型、想多深，而不是继承你自己
全局 harness 配置里的那一套。Codex 两者都认（`reasoning_effort` 取 `minimal`、`low`、
`medium`、`high`、`xhigh` 之一）；Claude Code 只认模型，因为它的 CLI 没有推理强度开关。
留空即各自交给 harness。改动其中任何一个都会重启该库的引擎，因为启动器只在启动时读一次设置。

知识库选择优先级依次是 `--library`、`PKC_LIBRARY`、当前目录或祖先中最近的 `.pkc`
文件，以及 home 的当前库。未选择时以退出码 2 拒绝执行。`env` 为用户自己的 shell
有意输出密钥；状态文档不会输出。

## 项目与编程代理会话

新库使用双语 `personal-projects` 契约：项目概览、带日期的演进、关键功能和决策，然后
是 Owner 本人的观点，人物与主题承载其他个人材料。使用
`pkchome library create notes --contract personal-knowledge` 选择之前的契约，也可传入
自定义契约路径。`--from NAME` 仍继承该库的契约，除非 `--contract` 显式覆盖。

说明一次库的范围；库的引擎运行时，托盘会同步范围内的 Claude Code 与 Codex 会话：

```sh
pkchome watch add /path/to/momo --library notes
pkchome watch add ~/Codes --recursive --library notes
pkchome watch add --all --library notes
pkchome watch ls --library notes
pkchome sync --library notes --dry-run
pkchome sync --library notes --json
pkchome watch rm /path/to/momo --library notes
pkchome watch rm --all --library notes
pkchome config set sync.interval_minutes 15
pkchome config set sync.enabled on
pkchome config set sync.exclude '/private/tmp/**,~/scratch/**'
pkchome config get sync.exclude
pkchome config set sync.min_owner_turns 5
pkchome config set sync.min_owner_chars 200
pkchome config set sync.ack_max_words 1
pkchome config set sync.max_part_chars 400000
```

Setup answers 可包含 `watch: [/path/to/momo]`。每库在 `library.yaml` 中保存自己的
`watch: [{path, recursive, harnesses: [claude-code, codex], since?}]`。`watch add` 接受
`--harnesses codex claude-code` 和带时区的 `--since`，选择保留活动达到该时刻的会话。

一条记录有三种范围形式。给出目录即精确的单个项目，与此前相同。`--recursive` 使它成为
前缀：该目录及其下的每个项目，按路径分段比较，因此 `/a/b` 绝不会收入 `/a/bc`。`--all`
记录字面量 `all`：两种宿主留有会话的每个项目，直接从宿主根目录枚举得到，而不依赖一份
目录清单——把库开放给四百个项目应当是一项配置，而不是四百次 `watch add`。
`watch rm <dir>` 与 `watch rm --all` 按同一个键移除。

这样宽的范围也会触及成千上万个已废弃的临时目录，因此 `sync.exclude` 保存一组 glob
模式，与解析后的项目目录匹配，默认为 `/private/tmp/**`、`/tmp/**`、`/private/var/**`
和 `/var/folders/**`。`config set sync.exclude` 追加一个模式或逗号分隔的列表；传入空值
则全部清空。有两项排除是机制而非 Owner 可以移除的模式：home 本身，以及每个库自己的
目录——它的 engine、canonical 仓库与渲染出的技能包。目录已不存在的项目计入
`project_missing`，不逐条列出，因为在 `all` 下它们数以千计。

Steward 自己的会话被整体跳过，既不索引也不编译。运行过 `pkc` 或 `pkchome` 的会话，或
处在 home 与库目录之中的会话，都是对库本身的维护工作；库若把它收进来，就是在编译自己
的产物。它们计入 `skipped_steward`。

托盘默认间隔为 15 分钟；Settings 可修改间隔、开关与目录列表。
Dashboard 展示上次同步和 held 数量，并提供 “Sync now” 按钮。

Sync 只通过 `pkchome exec --library NAME -- pkc ingest` 送入新部分，自身不编译：
ingest 将普通 index/compile 任务入队，由引擎 worker 或 Steward 排空。报告包含
scanned、new、increments、held、unchanged、rewritten、ingested、skipped、
skipped_steward、project_missing 和逐会话细节。Held 数量与库的队列分开；未变化的
held 会话同时计入这两个字段。

全局技能还携带标准库 `scripts/agent_sessions.py`：`list --project <dir>` 展示整会话
分流，`export --project <dir> --out <dir> [--owner-id ID]` 写出过滤后的 JSON，
`ingest --project <dir> [--library NAME]` 与 sync 共用增量游标。`--session-id ID`
选择特定会话；`--purpose research|chat` 将它们设为只索引。Export 的 Owner 身份默认
为 `owner`；ingest 使用所选租户。手动导入只索引的 export 时需要 `--intake searchable`，
元数据本身不设置 intake。

每份待处理增量默认要求三次 Owner 发言和 200 个 Owner 文本字符；`sync.min_owner_turns`
（下限 3）、`sync.min_owner_chars` 和 `sync.ack_max_words` 说明这台机器实际要求多少。
任一阈值不足都保持 HELD，不推进导出游标，后续增长继续累积。

`sync.max_part_chars`（默认 400,000，下限 1,000）是另一种界：一个入库分片最多携带多少
Owner 与代理文本。它是关于**一轮编译的上下文**的事实，而不是对材料的评判——真实的一次四月
会话有 24,439 次发言、180 万字符，它让每一次启动都死掉，且没有留下 worker 读得懂的话。
更长的增量只在 Owner 发言处切成连续的分片（一次 Owner 发言连同其后的代理发言是一个单位，
切口绝不落在一次发言内部），每个分片在同一次同步里按顺序作为普通的增长分片入库——
`continues`、`from_turn`、`part`——于是按用户串行的队列按顺序编译它们，每一片都以前一片写下
的页面为上下文。每个分片按上面的阈值各自分流。游标逐片推进（`sync-state.json` 里的
`split_turns` 记下字节边界之后已入库的发言数），所以在分片之间中断的一次同步会从下一片
接着来。报告以 `split_parts` 计数；单个超过界限的交换会整片入库，并记在 `oversized_parts` 下。转换器的 `--min-owner-turns`、`--min-owner-chars`
和 `--ack-max-words` 仍可配置其手动分流（次数下限 3、字符下限 0，确认语默认限 1 词）。
数值阈值满足后，仅命令/已知确认语和显式研究/闲聊只索引。子代理和目录冲突被排除。
Owner 原话与代理叙述逐字保留；工具缩为有长度上限的动作短句，排除参数、结果、思考
与宿主注入上下文。`list`/`export` 保持整会话规则：字符不足跳过，次数不足只索引。

`library.yaml` 旁的 `sync-state.json` 保存来源 ID、导出发言游标和已验证文件前缀。
字节未变化时，mtime 不会触发再次导入。正常增长只送入新发言，携带 `continues`、
`from_turn`、`part` 元数据；先前 canonical 页面提供上下文，断言引用所属部分。
前缀变化或截断报告 `rewritten`；显式使用 `pkchome sync --rewritten reingest` 才准入
替换内容。旧 `ingested-sessions.json` 条目通过恢复精确历史载荷、经 ingest 去重取得
来源 ID 完成迁移；无法证明的哈希会报告，绝不默认为今天的末尾。待处理载荷写入日志，
用于崩溃或响应丢失后的精确重试。`--dry-run` 不写任何内容，也不创建锁或载荷日志。
这些都属于本版状态；canonical 仍只通过库的草稿闸门改变。

## 东西放在哪里

```
~/.pkc/                     home（可用 PKC_HOME 迁移）
  config.yaml               安装信息、中间件端口、默认值
  credentials               KEY=value，权限 0600 —— 状态与技能文本都不会回显
  current                   未做其他选择时会话落入的库
  infra/、run/、data/        生成的 compose 文件、引擎 pid 与日志、数据卷
  libraries/<name>/         library.yaml、engine/、canonical/、skill/
~/.local/bin/               pkchome（uv tool）与并列的 pkc 启动器
~/.codex/skills/pkc-steward/、~/.claude/skills/pkc-steward/    全局技能
```

一座库自己的技能包在 setup 中**最后**渲染——排在主体档案之后，因为包里就写着主体；
无人值守的每一轮开跑前，worker 都会校验它，发现漂移就地重渲，让宿主读到的措辞始终是
这套部署今天渲染出的措辞。

## 卸载

```sh
pkchome down                 # 先停中间件；数据卷保留
uv tool uninstall pkc-personal
rm -f ~/.local/bin/pkc
rm -rf ~/.codex/skills/pkc-steward ~/.claude/skills/pkc-steward
rm -rf ~/.pkc                # 只有确实要连库一起删除时才执行
```

## 开发

在所在工作树根目录使用 `uv run --project personal` 运行：

```sh
uv run --project personal pkchome setup --answers answers.yaml --no-skill
uv run --project personal pkchome library create notes --language en --backend codex
uv run --project personal pkchome exec -- pkc jobs
uv run --project personal pytest personal/tests -q
```

这是独立的 uv 项目，有自己的环境和随代码提交的锁文件。运行时仅依赖 core、service
两个库发行包；本版的契约和全局技能文本作为自有资源随包分发。

控制台页面始终是构建产物而非源码：引擎按顺序从 wheel 自带的 `pkc_personal/console/dist`、
`PKC_CONSOLE_DIST`（本地构建，供开发）、或 `~/.pkc/console/<version>/dist`（由
`pkchome console install` 从 `personal-console-v<version>` 发布下载、并按公布的 sha256
校验的副本）中取用。在本仓库内，`scripts/personal_console_dist.sh` 构建该目录，
`scripts/personal_console_release.sh` 将其发布为某一版本的发布资产。
`pkchome status` 会说明本机用的是哪一种。

当前接口限制：缺少 worker 租户过滤的库版本会被拒绝启动引擎；检索选择会被记录，但需要
库暴露 `semantic_retrieval` 后才生效；引擎在启动时决定是否提供控制台页面，因此引擎启动
之后才取到的页面要等下一次 `pkchome restart` 才会被提供。
