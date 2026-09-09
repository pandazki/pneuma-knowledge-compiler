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
6. **桌面应用** —— 发布构建后配合 `PKC_DESKTOP=1` 下载；否则只打印一行，说明
   `pkchome tray` 会告知从哪里获取。

每一步打印一行 `ok:` 或 `skip:`，最后几行给出已安装的 `SKILL.md` 与接下来要运行的两条
命令。`--quiet` 只输出错误和这个末尾块。

## 命令

```
pkchome setup [--answers <file>] [--non-interactive] [--no-skill]
pkchome up | down | restart | console | tray
pkchome status [--json] [--library <name>]
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
`semantic_retrieval: off`；可选的 `embedding_key` 只进入凭据文件。配置的 embedding
服务商的密钥在写入前会先向该服务商验证一次——被拒绝的密钥不改变任何东西（不写文件、
不重启引擎、保留原密钥），离线时可用 `--no-verify` 跳过验证直接保存。Setup 需要终端或
`--answers`；`--no-skill` 跳过向检测到的宿主目录安装技能。

知识库选择优先级依次是 `--library`、`PKC_LIBRARY`、当前目录或祖先中最近的 `.pkc`
文件，以及 home 的当前库。未选择时以退出码 2 拒绝执行。`env` 为用户自己的 shell
有意输出密钥；状态文档不会输出。

## 项目与编程代理会话

新库使用双语 `personal-projects` 契约：项目概览、带日期的演进、关键功能和决策，然后
是 Owner 本人的观点，人物与主题承载其他个人材料。使用
`pkchome library create notes --contract personal-knowledge` 选择之前的契约，也可传入
自定义契约路径。`--from NAME` 仍继承该库的契约，除非 `--contract` 显式覆盖。

指定一次项目目录；库的引擎运行时，托盘会同步其中的 Claude Code 与 Codex 会话：

```sh
pkchome watch add /path/to/momo --library notes
pkchome watch ls --library notes
pkchome sync --library notes --dry-run
pkchome sync --library notes --json
pkchome watch rm /path/to/momo --library notes
pkchome config set sync.interval_minutes 15
pkchome config set sync.enabled on
```

Setup answers 可包含 `watch: [/path/to/momo]`。每库在 `library.yaml` 中保存自己的
`watch: [{path, harnesses: [claude-code, codex], since?}]`。`watch add` 接受
`--harnesses codex claude-code` 和带时区的 `--since`，选择保留活动达到该时刻的会话。
路径精确选择项目。托盘默认间隔为 15 分钟；Settings 可修改间隔、开关与目录列表。
Dashboard 展示上次同步和 held 数量，并提供 “Sync now” 按钮。

Sync 只通过 `pkchome exec --library NAME -- pkc ingest` 送入新部分，自身不编译：
ingest 将普通 index/compile 任务入队，由引擎 worker 或 Steward 排空。报告包含
scanned、new、increments、held、unchanged、rewritten、ingested、skipped 和逐会话
细节。Held 数量与库的队列分开；未变化的 held 会话同时计入这两个字段。

全局技能还携带标准库 `scripts/agent_sessions.py`：`list --project <dir>` 展示整会话
分流，`export --project <dir> --out <dir> [--owner-id ID]` 写出过滤后的 JSON，
`ingest --project <dir> [--library NAME]` 与 sync 共用增量游标。`--session-id ID`
选择特定会话；`--purpose research|chat` 将它们设为只索引。Export 的 Owner 身份默认
为 `owner`；ingest 使用所选租户。手动导入只索引的 export 时需要 `--intake searchable`，
元数据本身不设置 intake。

每份待处理增量要求三次 Owner 发言和 200 个 Owner 文本字符。任一阈值不足都保持 HELD，
不推进导出游标，后续增长继续累积。转换器的 `--min-owner-turns`、`--min-owner-chars`
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

当前接口限制：缺少 worker 租户过滤的库版本会被拒绝启动引擎；检索选择会被记录，但需要
库暴露 `semantic_retrieval` 后才生效；只有安装 `pkc_personal/console/dist` 构建产物后
才提供控制台页面。
