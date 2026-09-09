---
name: pkc-steward
description: 通过 pkchome 与带引用闸门的 pkc 命令，为 Owner 维护个人知识库。
---

# 这是什么

知识库把 Owner 的材料——编码代理会话、文档、聊天——按契约编译成带引用的知识：L0 逐字原文与
canonical 库是权威，索引是派生视图，每条 claim 都引用来源块，闸门在写入时验证引用能解析。
库机械地确立的事（出处已验证、谁说的、何时最后改动、哪些 claim 已被接替、检索命中了多少已索引块）
读命令都会印出来；它没有确立的事（原文是否真的表达了 claim 的意思、日期换算是否正确、是否有
更新的材料涉及这一页）也写明了。判断是你的：需要核对就去读原文，问题复杂就交叉验证。
完整的设计与保证、按问题形状的最佳做法、每条工具的返回值，都在所选库的
`references/consume.md`（`pkchome library show` 的 `skill_dir` 下）。

# 回答 Owner 的问题（最常做的事）

一条常见的路，不是规定的流程：

1. `pkchome exec -- pkc outline` —— 完整地图，一页一行。没选库时它会拒绝并列出可用库，用 `--library NAME` 指定。
2. `pkchome exec -- pkc canonical read <path> [<path>…]` —— 一次读相关页面；头部和 `来源：` 索引写明最后改动、待处理或失败的编译作业、每个被引块是谁哪天说的。
3. 跨页或不知道在哪一页：`pkchome exec -- pkc recall <q> --evidence` 一次拿到多页的 claim 与原文窗口。
4. `pkc source fetch <sid> ¶a-b` 看原文；`pkc search <q> --lexical` 找名字、原句、最新会话，头部的计数说明匹配不可能在哪里。
5. 把这次使用交还给库：`pkc consult answer <handoff_id> --text-file -`（没跑 recall 时 `pkc consult record --question <q> --text-file -`，什么也没找到时加 `--kind no_record`）。问了什么、碰到哪些页面、引用了什么由此进入访问账本；不记，这次使用对库就不存在。

读命令彼此独立，输入已知时可同时发几条。长输出分页，页脚写明 `--page N`。

# 你在哪里

`pkchome status --json` 查看本机知识库、实时探测和已完成的初始化步骤——初始化和维护时用，回答问题时不需要。
未选择知识库时，`pkchome exec` 会拒绝执行并列出可用库。可用 `--library NAME`、
`PKC_LIBRARY=NAME`、目录绑定（`pkchome library bind NAME .`）或
`pkchome library use NAME` 设置的默认库来选择。

# 冷启动

空 home 用 Owner 的回答生成 YAML，再运行 `pkchome setup --answers <yaml>`。
字段为 `library`、`language`（en 或 zh）、`backend`（codex、claude-code 或 api）、
`semantic_retrieval`（on 或 off）和可选的 `embedding_key`。
优先通过 `pkchome credentials set KEY --from-stdin` 传入密钥；setup 也接受回答文件
中的密钥，但仅将它存入 home 的 credentials 文件。

档案的初稿来自宿主已经了解的 Owner：会话记忆、明确表达的偏好以及材料中的第一人称。
通过 `pkchome exec -- pkc profile set --field display_name=NAME --provenance inferred`
写入推断，其他字段按库内参考包的说明填写。向 Owner 展示：“我认为你是 X，从事 Y，
用 Z 写作——请纠正我”，然后逐字段用 `pkc profile confirm` 或 `pkc profile set`
确认或修正。实质知识仍通过来源与引用闸门进入知识库；档案只承载 Owner 的自我介绍。

先读已记录的检索选择。Owner 尚未选择时，询问是关闭语义检索运行，还是提供 embedding
服务商的密钥。用 `pkchome config set semantic_retrieval off --library NAME` 记录关闭，
或用 `pkchome credentials set KEY` 保存密钥，再将选择设为 `on`。保存密钥会自行重启运行中的引擎；
修改其他引擎设置后需重启。
为已有来源补齐语义检索，使用库提供的派生层重建操作。

# 继续维护已有库

`pkc outline` 是完整地图，一次会话通常从它开始；回答按 `references/consume.md` 的场景选路（`canonical read`、`recall --evidence`、`search`、`source fetch`）；仅当 outline 太长、难以扫读时才用有预算的 `glance`。
`pkc draft finish` 后，对每个写入过的族运行 `pkc outline --family <template>` 查看新页面的落点；在 agent 执行器下，API 通道是有密钥的控制台用来测试质量的工具。

运行 `pkchome library show NAME`。读取它给出的 `skill_dir` 那个包里的 `SKILL.md` 和
`references/`——包按 harness 自己的约定装在库目录里，因为那个目录就是项目。那里提供本库的
契约、编译指令、命令词汇和闸门说明。`entry` 字段指向那个包自己的 `scripts/pkc`，无人值守
轮次运行的就是它。你自己的会话改用 `pkchome exec -- pkc ...`：无论站在哪里，它都会带上这座
库的环境。修改契约或提示词后用 `pkchome library render NAME` 重新安装这个包。

在 `pkchome status` 里读这座库的 worker 姿态（`worker: unattended|attended`）。你自己在终端
手工排空它的队列时，先运行 `pkchome config set unattended off --library NAME`——否则 worker
会在你旁边对同一批编译作业拉起无人值守轮次——离开时再设回 on。

读取、导入、Owner 陈述和草稿轮次遵循库内生成的流程。Canonical 写入走 `pkc draft`。
Home 命令负责本机与库的选择；`pkchome console` 打开所选库的控制台。

# 记住了什么

`pkchome status` 给出基础设施、凭据、档案、技能和首次编译的步骤状态、技能新鲜度与最近
使用时间。`pkchome library show` 给出选择与绑定。已经记录的回答不再询问；实时探测失败
就修复对应步骤。

五个步骤中有三个由拥有它的 home 命令写下：`infra`（`pkchome up`）、`credentials`
（写入 home 的密钥）、`skill`（`pkchome library render`）。另外两个根本不作记录——
完成它们的命令属于库，而库写不了 home 的文件——因此 status 在读取时推导：
`pkc profile show --json` 报告档案已不是占位且没有任何字段仍标为 inferred 时，
`profile` 为 true；`first_compile` 取 canonical 仓库中最早一次 compile 提交的日期。
null 表示这次没有观察到，而不是步骤未完成：只有库的存储可达时才会去问档案。
密钥位于 home 的 credentials 文件，不会出现在状态文档和技能文本中。


# 引入编程代理会话

为所选库指定一次项目目录：

```sh
pkchome watch add <dir> --library NAME
pkchome watch ls --library NAME
pkchome sync --library NAME --dry-run
pkchome sync --library NAME
```

库的引擎运行时，常驻托盘默认每 15 分钟同步一次。Settings 可调整间隔和监视目录；
`pkchome watch rm <dir>` 停止监视。`pkchome sync` 手动执行一轮；`--dry-run` 展示
到期材料与 held 材料，不写文件、不导入。续接让长会话逐部分进入：先前项目页面加上
待处理增量，每条断言引用所属部分。Sync 只导入并报告入队内容，任务由引擎 worker
或 Steward 排空。

本全局包还携带 `scripts/agent_sessions.py`，它是 Python 3.12 标准库转换器，用于
选择特定会话及独立导出。使用本全局技能中与 `scripts/pkc` 并列的脚本；库渲染的技能包
提供编译流程。`list --project <dir>` 展示逐会话分流；`ingest --project <dir>` 与 sync
共用游标。

导入前展示 list 给出的逐会话判定与原因。`ingest` 的 `--library NAME` 显式选择库；
否则由 `pkchome library show` 解析既有选择。转换器在每条 `pkchome exec --library NAME
-- pkc ingest --contract agent-session/v1 --file …` 调用中固定这个选择。`--session-id ID`
选择列出的某条会话，可以重复。`--since` 接受带时区的 ISO 时间，保留活动达到该时刻的
会话会被纳入。`export --project <dir> --out <dir> [--owner-id ID] [--owner-name NAME]` 为每条准入会话写出一个
过滤后的 JSON，不导入。独立 export 的 `owner_id` 默认是 `owner`、不带 `owner_name`（库把 Owner 回合标为「用户：」）；ingest 默认使用
所选租户和库主档案里的名字，回合就读作「Pandazki：」。手动导入只索引的 export 时，需传 `--intake searchable`；分流元数据只
说明判定，本身不覆盖库的 intake。

`list`/`export` 的分流是机械的：Owner 文本少于 200 字符就跳过；否则至少三次 Owner 发言且项目目录匹配，
才成为编译候选。只有斜杠命令或已知单词确认语的会话只索引。阈值是
`--min-owner-chars 200`（0 关闭长度过滤）、`--min-owner-turns 3`（可调高）和
`--ack-max-words 1`。Claude Code 通过所选目录编码后的会话文件夹归属项目，Codex 使用
记录的 `cwd`。记录的目录冲突时跳过会话，包括编码名称碰撞。子代理任务提示、压缩
摘要、宿主注入上下文和工具结果被排除；没有真正
Owner 发言的转录被跳过。Owner 文本与代理叙述保留原话；同一消息的多个文本块用一个
换行连接。动作短句只保留工具名与路径或命令的可执行程序名，单行且最多 200 字符。
转换器按记录的时间戳稳定排序；发言时间缺失时继承前一个记录时间，没有时间或时间不带
时区则拒绝，不编造时刻。

研究或闲聊使用 `--purpose research` 或 `--purpose chat`；项目文件夹包含混合任务时，
配合选定的会话 ID。它们只索引。每条只索引判定都传入 `--intake searchable`：L0/L1
可达，L2 与 canonical 编译关闭。若其中有明确且持久的 Owner 观点，可按库内生成的流程，
在另行请求的草稿轮次中引用该 Owner 发言；研究或闲聊的叙述本身不获得页面。

默认项目契约的层次首先是项目概览、带日期的演进、关键功能和决策，其次是 Owner 本人的
观点，再是承载其他个人材料的人物与主题族。代理叙述支持报告的工作与项目状态；携带
`owner_voice: true` 的 `owner/views` 页面只能由 Owner 自己的发言支持。契约没有制作
过程族：文件修改、命令、暂时测试失败留作 L0/L1 证据。Canonical 写入走库的草稿闸门，
不把会话转录粘贴成页面。编译前读取实际选中库的契约。

Sync 与脚本的 `ingest` 共用所选库中与 `library.yaml` 并列的 `sync-state.json`。
待处理材料不足三次 Owner 发言或 200 个 Owner 文本字符时保持 HELD：导出游标不动，
直到增量同时达到两个阈值。转换器的阈值参数可提高次数下限或调整字符下限。字节前缀
不变就不重复导入，与修改时间无关。前缀变化或截断报告 `rewritten`；仅显式传入
`--rewritten reingest` 才导入替换内容。正常增长只导出未处理发言，携带 `continues`、
`from_turn` 与 `part` 元数据。先前 canonical 页面提供上下文，不重复送入旧转录原文。

旧 `ingested-sessions.json` 条目通过恢复精确的历史载荷，再经 ingest 去重取得来源 ID
完成迁移。无法证明旧哈希时报告 `rewritten`，绝不把今天的末尾当作旧游标。游标属于
本版状态，与库的队列和知识权威分开。不确定的导入结果保留本地载荷日志，以便精确
重试；游标保存成功后删除载荷。Dry run 不写载荷、锁或状态。
