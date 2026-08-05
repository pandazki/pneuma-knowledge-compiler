# Pneuma Knowledge Compiler

[English](README.md) | **简体中文**

把你领域里的原始材料——会议、文档、聊天、邮件——编译成可演进、带引用、不可编造的知识库。

### 面向领域的知识库建模

领域概念不一致、使用场景不一致，构建知识库的方式就应该不一致。记什么、记成什么结构，由你的编译契约定义；框架只提供领域无关的索引与检索底座。

### 知识库模型可演进

没有任何业务一成不变。预先建模会随数据量、数据分布和业务本身的变化逐渐失效。框架为此提供一套演进的底层基础设施——演进提案、diff 评审、数据迁移——由业务按需驱动模型迭代。

### 框架级溯源约束

每条知识必须携带指向原文段落的引用，写入时由框架机械校验，不满足即拒绝。溯源不是提示词约定，而是写入层的强制约束：无法编造，也无法丢失出处。

### 它不是什么

> 这不是 Agent 记忆系统。知识库和记忆是两码事。Agent 的记忆应该记住的是「我有一个怎样的知识库」——它的构建哲学、顶层概览、检索方式与维护方法——而不是把知识库本身当作记忆。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/history-dark.png">
  <img alt="编译历史：提交时间线、逐条知识的前后差异及其依据来源" src="docs/assets/history-light.png">
</picture>

## 三分钟看见它

不需要任何 API key——`examples/opc` 随仓附带一座真实的、由代理建成的库（190 份合成材料、754 条知识），本地一分钟左右即可恢复：

```bash
cd examples/opc && cp .env.example .env
./app.py up && ./bootstrap.py
docker compose --profile web up -d --build api web   # 首次构建镜像需要几分钟
```

打开 <http://127.0.0.1:24173>，在浏览器里走完整条流水线：原始材料、编译历史、带逐条引用的正本文库（还有一卷真实的冻结归档）、以及各检索面。浏览零成本；问答需要在 `.env` 里填 OpenRouter key。

## 用你自己的数据建库

`scaffold/` 是一个项目生成器——交互式引导（或用一个 answers 文件单命令），把一个完整的知识库项目生成到你指定的目录，中间件端口自动探测、互不冲突：

```bash
cd scaffold && ./init.py     # 交互式：每一步给默认值，可先用内置演示数据体验
cd ~/my-kb && ./start.sh     # 起栈、摄入、编译、带引用的问答演示，一条命令
```

然后换成你自己的：把 `.md` 材料交给 `./app.py ingest <目录>`，改 `contract.md`（什么值得记）和 `profile.yaml`（这座库属于谁），重编验收。

想有人带着走？把 `scaffold/AGENT-GUIDE.md` 交给你的 coding agent，它会一步步陪你用自己的数据建完。

## 它怎么工作

原始材料逐字保存，四层同时可达：L0 原文直取、L1 词法检索、L2 语义检索、L3 正本知识。权威的只有两样——原始材料本身，和存放正本的每用户 Git 仓库：每次编译是一个 commit，每条知识带着引用。其余（索引、投影）都是派生物，随时可重建。什么能成为正本，由你的编译契约决定；写入闸门在提交时机械校验每条引用，解析不回原文的一律拒绝。

## 演进怎么发生

编译器会记下每次编译发生了什么。框架从这些痕迹里起草 schema 修改——新的文档族、调整的路径模板、重组的页面——在独立分支上完成，把 diff 摆在你面前。采纳，机械对账合入；丢弃，一切如旧。升级从不改写已有的知识：演进的是模型，不是事实。

## 仓库布局

```
packages/pneuma-knowledge-core        # 领域逻辑 + 异步端口（仅依赖 pydantic 与 langchain）
packages/pneuma-knowledge-service     # FastAPI 服务、适配器（Postgres/Qdrant/Meilisearch/Git）、worker
packages/pneuma-knowledge-strategies  # 参考编译契约（纯数据包；框架永不 import）
packages/pneuma-knowledge-eval        # 判断质量度量
apps/web                              # 双语 Web 界面
scaffold/                             # 拷出去就归你的知识库应用模板
examples/                             # opc：一个由代理建成的完整示例项目，附预编译库
infra/                                # 本地开发栈（Postgres、Qdrant、Meilisearch）
```

完整文档正沿本 README 的主轴重建，将落在 `docs/`。

## 致谢

Web 阅读面内嵌霞鹜文楷屏幕阅读版（OFL 1.1）。阅读层排版纪律借鉴 [kami](https://github.com/tw93/kami)——其默认中文字体仓耳今楷 02 仅限个人免费使用、商用需另行授权，本项目因此改用 OFL 字体。语义分块的边界检测哲学受 [nemori](https://github.com/nemori-ai/nemori) 启发。

## License

[MIT](LICENSE)
