# OPC——一座由代理建成的完整知识库

[English](README.md) | **简体中文**

这个目录就是 scaffold 流程跑完的样子：一个合成主人——林舟，独立开发变更证据链产品 Seamlog 的开发者——的知识库项目，190 份材料编译成 29 篇正本文档、754 条带引用的知识。库随项目一起发布，不用 API key，一分钟左右就能在浏览器里打开。

## 它是怎么来的

这座库由一个**自主代理**（跑在 Claude Code 里的 Claude Opus 5）建成：从一份全新的 [`scaffold/`](../../scaffold/) 拷贝出发，照着 [`AGENT-GUIDE.zh-CN.md`](../../scaffold/AGENT-GUIDE.zh-CN.md) 走，输入只有两样——`my-data/` 里的材料，和三句话的主人自述。它通读了全部 190 份材料、从中推导出 [`contract.md`](contract.md)、编译、按[验收环](../../docs/guides/compile-contract.zh-CN.md#8-验收环)自判，并在第一轮构建违反了材料自己声明的规矩时用掉了唯一一次修订机会。完整记录在 [`build-record/`](build-record/)：启动它的任务书逐字原文、它的构建日志、它的完整对话轨迹。

请把这次构建当作**参考线，不是天花板**：它是某一代代理在某一天的作品。拿更强的代理对着同一份数据走同一条指南，你的库很可能更好——契约的判断力正是代理之间拉开差距的地方。

## 上手

**1. 浏览——不需要 API key**

```bash
cp .env.example .env
./app.py up && ./bootstrap.py
docker compose --profile web up -d --build api web   # 首次构建镜像需要几分钟
```

打开 <http://127.0.0.1:24173>。处处可下钻：190 份原文逐字可查、170 个提交的编译历史、每条知识回链到原文精确段落，还有一卷构建过程中由轮转真实产出的冻结归档。

**2. 问答——需要 key**

在 `.env` 填入 OpenRouter key（`OPENROUTER_API_KEY`），然后从命令行问，或重启 api 容器让 Web 的检索面拿到 key：

```bash
./app.py ask '第一条证据链现在卡在什么条件上？' --sources
docker compose --profile web up -d api                # Web 问答生效
```

**3. 用你自己的参数重编译——需要 key，花真金白银**

改 `contract.md`（或换 `.env` 里的模型），从同一批材料重建。参考构建用 `gpt-5.6-luna` 花了约 2100 万 token：

```bash
./app.py down --volumes && rm -rf data/
./app.py up && ./app.py init
./app.py ingest my-data && ./app.py compile
```

`./demo.sh` 把三个阶段包成了交互式菜单。

## 这份语料

`my-data/` 是一个人 84 天的工作生活，完全合成（无真实人物、品牌或凭证）：18 场会议与 48 段 IM 对话是转写体，81 篇笔记与 43 条邮件线程是文档体。它最鲜明的性质——也是它适合考验这套框架的原因——是信息量的一半是**否定事实**：什么没获准、没签字、没确认、没查到。把「提议」压平成「决定」的编译器会把这份语料编成小说；随仓的契约存在的意义正是拦住这件事。

## 用你自己的代理复现它

这个示例的意义就在于可复现。把 scaffold、两份指南（[契约](../../docs/guides/compile-contract.zh-CN.md)、[AGENT-GUIDE](../../scaffold/AGENT-GUIDE.zh-CN.md)）和 `my-data/` 交给一个编码代理，让它走同一条路——`build-record/TASKBOOK.md` 就是参考构建的启动指令原文。预期得到形状相近的库，而不是完全相同的库：它推出的族与口径，就是它的判断力。

## 接下来

- 为**你的**领域写契约：[docs/guides/compile-contract.zh-CN.md](../../docs/guides/compile-contract.zh-CN.md)
- 用你自己的数据建自己的项目：[`scaffold/`](../../scaffold/README.zh-CN.md)
- 理解底下的机器：[docs/architecture.zh-CN.md](../../docs/architecture.zh-CN.md)

## 文件

| 文件 | 是什么 |
|---|---|
| `app.py`、`start.sh`、`docker-compose.yml`（中间件部分） | `scaffold/templates/` 的字节拷贝——重放叙事是字面事实 |
| `contract.md`、`profile.yaml` | 代理写的契约与主人档案 |
| `my-data/` | 合成语料，scaffold 摄入格式 |
| `prebuilt/canonical.bundle`、`prebuilt/l0.jsonl.gz` | 构建期的两个权威：编译好的正本文库（git bundle）与其引用所绑定的 L0 原始来源逐字行（source id 是系统分配的，重摄入不可能复现） |
| `bootstrap.py` | 无钥恢复：正本 bundle + L0 dump + 派生层重建 |
| `server.py`、compose 的 `web` profile（镜像用框架的 `docker/compose-web.Dockerfile`） | 浏览层——本示例与纯 scaffold 的唯一分叉 |
| `build-record/` | 任务书、构建日志、代理完整轨迹 |
