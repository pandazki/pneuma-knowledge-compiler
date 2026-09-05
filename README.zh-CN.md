# Pneuma Knowledge Compiler

[English](README.md) | **简体中文**

把你领域里的原始材料——会议、文档、聊天、邮件——编译成可演进、带引用的知识库。让知识持续积累、随主体变化，并能追查到原始材料。

### 面向领域的知识库建模

领域概念不一致、使用场景不一致，构建知识库的方式就应该不一致。记什么、记成什么结构，由你的编译契约定义；框架只提供领域无关的索引与检索底座。

### 知识库模型可演进

没有任何业务一成不变。预先建模会随数据量、数据分布和业务本身的变化逐渐失效。框架为此提供一套演进的底层基础设施——演进提案、diff 评审、数据迁移——由业务按需驱动模型迭代。

### 框架级溯源约束

新增和改写的知识必须有通向依据的出处链，变更不能悄悄破坏原本有效的依赖。原始材料始终可达，断言保留稳定身份，结构演进通过 diff 审阅。这些保证让知识库可检查、可维护。引用检查确定证据在哪里，编译契约、模型和审阅判断证据是否支持主张。精确保证及历史缺陷的处理见[写入机制](docs/architecture.zh-CN.md#5-正本写入机制)。

### 它不是什么

> 这不是 Agent 记忆系统。知识库和记忆是两码事。Agent 的记忆应该记住的是「我有一个怎样的知识库」——它的构建哲学、顶层概览、检索方式与维护方法——而不是把知识库本身当作记忆。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/history-dark.png">
  <img alt="编译历史：提交时间线、逐条知识的前后差异及其依据来源" src="docs/assets/history-light.png">
</picture>

## 三分钟看见它

不需要 API key，也不需要回答任何问题。一条命令生成一个「已经编好库」的真实项目（191 份合成来源、1188 条知识），起好，并告诉你去哪看：

```bash
cd scaffold && ./init.py --demo      # 落在一个新建临时目录；用 --target DIR 自己指定
```

它会打印一个 `http://127.0.0.1:<端口>`。在浏览器里走完整条流水线：原始材料、编译历史、带逐条引用的正本文库（还有一卷真实的已结卷）、各检索面，以及**引擎控制台**——在那里改一个策略配置、看清它的影响范围，然后作为一个版本 apply 出去。以上都不需要 key；问答需要。

它自带的那座库来自 [`examples/opc`](examples/opc/README.zh-CN.md)——一个由代理建成的示例，也可以就地跑（`cd examples/opc && ./demo.sh`）。

## 用你自己的数据建库

`scaffold/` 是一个项目生成器——交互式引导（或用一个 answers 文件单命令），把一个完整的知识库项目生成到你指定的目录，中间件端口自动探测、互不冲突：

```bash
cd scaffold && ./init.py     # 交互式：默认空项目与可运行的起始契约
cd ~/my-kb && ./start.sh     # 验证材料、启动中间件、导入并编译
```

然后检查它：运行 `./app.py glance`，用 `./app.py ask "…" --sources` 提出实际问题并追查引用。建模判断写在 `engine/compile/contract.md`；`engine/persona/profile.yaml` 的个人资料可选。改契约只影响未来编译，不会重新编译已有知识。

想有人带着走？把 `scaffold/AGENT-GUIDE.md` 交给你的 coding agent，它会一步步陪你用自己的数据建完。

## 它怎么工作

原始材料逐字保存，四层同时可达：L0 原文直取、L1 词法检索、L2 语义检索、L3 正本知识。权威的只有两样——原始材料本身，和存放正本的每用户 Git 仓库：每次编译是一个 commit，每条知识带着引用。它们旁边是第三类持久物：被保留的记录——一份分块 manifest、一次编译事件、一次答复调用的记录——一份存下来的观察，重建只重放它，绝不改写它。其余（索引、投影）都是派生物，各自从声明的底随时可重建。什么能成为正本，由你的编译契约决定；写入闸门在提交时机械校验每条引用，解析不回原文的一律拒绝。

原生媒体从窄而完整的边界起步：IM 消息可以携带 JPEG、PNG、WebP 或 GIF 原图。原图进入私有 S3 兼容 L0（本地使用 RustFS），以带标签的 caption/OCR 或真实图片块交给编译模型，经消息原有的块级引用解析，并在正文阅读器与引用视图中展示。其他媒体类型目前没有声明为已支持。

## 演进怎么发生

编译器会记下每次编译发生了什么。框架从这些痕迹里起草 schema 修改——新的文档族、调整的路径模板、重组的页面——在独立分支上完成，把 diff 摆在你面前。采纳，机械对账合入；丢弃，一切如旧。单独修改契约不会重写旧主张；采用结构提案可以改变正本知识，所以既要审阅机械有效性，也要审阅它改变了什么含义。

## 仓库布局

```
packages/pneuma-knowledge-core        # 领域逻辑 + 异步端口（仅依赖 pydantic 与 langchain）
packages/pneuma-knowledge-service     # FastAPI 服务、适配器（Postgres/Qdrant/Meilisearch/S3/Git）、worker
packages/pneuma-knowledge-strategies  # 参考编译契约（纯数据包；框架永不 import）
packages/pneuma-knowledge-eval        # 判断质量度量
apps/web                              # 双语 Web 界面
scaffold/                             # 拷出去就归你的知识库应用模板
examples/                             # opc：一个由代理建成的完整示例项目，附预编译库
infra/                                # 本地开发栈（Postgres、Qdrant、Meilisearch、RustFS）
```


## 致谢

Web 阅读面内嵌霞鹜文楷屏幕阅读版（OFL 1.1）。阅读层排版纪律借鉴 [kami](https://github.com/tw93/kami)——其默认中文字体仓耳今楷 02 仅限个人免费使用、商用需另行授权，本项目因此改用 OFL 字体。语义分块的边界检测哲学受 [nemori](https://github.com/nemori-ai/nemori) 启发。

## License

[MIT](LICENSE)
