# pneuma-knowledge scaffold —— 项目生成器

[English](README.md) | **简体中文**

scaffold 是一个**生成器**：一个入口脚本，问你几个问题（或者用一个文件一次性给全），
然后在你指定的目录里生成一个完整、自洽的知识库项目——你的数据、你的契约、
一套探测空闲端口自动配好的独立中间件栈。

```bash
./init.py --demo                           # 零交互零 key：直接给你一个「已经编好库」的项目并起好
./init.py                                  # 交互式：一步步引导，每个岔路都可用内置演示数据
./init.py --answers my.toml --target DIR   # 单命令：给编码代理和 CI 用
./init.py --print-schema                   # 打印带注释的 answers 文件模板
```

**只想先看看一座编好的知识库长什么样？** `./init.py --demo` 会在一个新建临时目录里生成一个
真实项目，起好中间件与浏览层，并把 [`examples/opc`](../examples/opc/README.zh-CN.md) 的库装进去
——191 份来源、28 篇正本文档、每条结论都能点回原文的那一段——**完全不需要 API key**
（`--target DIR` 指定目录，`--no-start` 只生成不启动）。它就是一个普通的生成项目，只是自带
一座库；你在里面学到的东西，直接适用于你自己的库。

两种模式跑的是同一个生成器；交互流只是把 answers 文件里的答案逐个问出来。
流程里没有任何问题需要前置知识：每一步先讲清这个东西是干什么的，给一个合理的
默认值（回车即接受），选完回显确认。端口、compose 项目名、租户 id——所有新手
不会有意见的东西——全部自动决定并回显，从来不问。

想让 AI 陪你建库？把 `AGENT-GUIDE.zh-CN.md` 交给你的编码代理（Claude Code / Codex /
Cursor 都行），把这句话粘给它：

```
请阅读 scaffold/AGENT-GUIDE.zh-CN.md 并按它引导我，用我自己的数据建一个知识库。我是新手，请一步步来。
```

## 生成出来的项目长什么样

```
my-kb/
  engine/            # 你的 —— 引擎本身，自带一个 git 仓库：模型角色、切块、回答风格、
                     #   编译契约、主体档案、prompt 覆盖
  .env               # 你的 —— key 与这台机器的基础设施（已 gitignore）
  my-data/           # 你的 —— 材料（.md；选了演示数据的话已经填好）
  README.md          # 按你选的语言生成，写明上述边界
  AGENTS.md          # 告诉任何编码代理同样的边界 + 指南在哪
  app.py             # 机器件 —— 运行时驱动（别改）
  start.sh           # 机器件 —— 端到端演示（别改）
  docker-compose.yml # 机器件 —— 本项目专属中间件栈（别改）
  server.py          # 机器件 —— 浏览层的 API 入口（别改）
  worker.py          # 机器件 —— 浏览层的编译 worker（别改）
```

机器件是 `templates/` 的字节拷贝——升级它们就是重新生成一个项目（或拷最新模板
过来）；你写的东西全部在机器件之外。

然后在生成的项目里：

```bash
cd my-kb
$EDITOR .env       # 填 OPENROUTER_API_KEY（交互时输过就不用了）
./start.sh         # 起栈 → 摄入 → 编译 → 带引用的演示问答 → 库的鸟瞰

docker compose --profile console up -d --wait   # 想在浏览器里干活：文库、原料、引擎控制台
```

## 这个目录里有什么

| 路径 | 是什么 |
|---|---|
| `init.py` | 生成器——唯一入口 |
| `templates/` | 原样拷贝的机器件 + 分语言模板（契约骨架、档案、项目 README/AGENTS） |
| `example/` | 内置演示数据集（一位虚构独立开发者的两周）、配套演示契约、演示问题 |
| `AGENT-GUIDE.zh-CN.md` | 编码代理陪用户建库的完整流程 |

## 判断力写在哪

编译模型的全部判断依据都写在生成项目的 `engine/compile/contract.md` 里。写好一份契约的完整实践
——类型→隐含用法的推导、主体粒度、验收环——在
[docs/guides/compile-contract.zh-CN.md](../docs/guides/compile-contract.zh-CN.md)，
那是这件事的唯一权威。
