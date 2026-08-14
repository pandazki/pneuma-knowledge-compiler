# {{PROJECT_NAME}} 的引擎

这个目录就是你的引擎。里面的一切——模型角色、材料怎么切、回答怎么写、库什么时候自查与重组、
编译契约、你的档案、以及任何提示词改写——决定了这个知识库拿你的材料做什么。

它是**一个独立的 git 仓库**，与你的数据、与机械件分开。每一次改动都是一个可回看、可回退的版本。
这里不放任何秘密：API key 和这台机器的端口留在 `../.env`，那个文件永不被版本化。

```
engine.yaml              模型角色：compile / recall / answer / deep / embedding
intake/intake.yaml       材料怎么切成语义单元
compile/contract.md      宪法——什么值得被记住、记在哪一页
compile/challenge.yaml   编译后的覆盖审计
evolve/evolve.yaml       库什么时候可以提出重组自己
recall/recall.yaml       回答怎么写，以及每个问题的检索预算
persona/profile.yaml     主人是谁
prompts/overlays.yaml    框架自身提示词用哪种语言，以及替换其中任意一条的措辞（通常为空）
```

## 动手改之前，有三件事值得先知道

**契约是一份文档，不是一堆开关。** `compile/contract.md` 教编译模型在**你的**领域里判断什么值得被
长期记住、该落在哪一页。这是判断力，只能用文字写——没有任何表单能装下它。完整的写法在框架仓库的
`docs/guides/compile-contract.zh-CN.md`。

**每一次改动都要说清自己的影响半径。** 你在这里做的任何事都不会回头重写已经记下的东西：

| 改什么 | 影响什么 |
|---|---|
| 回答风格、检索预算 | 你问的下一个问题 |
| 模型角色、提示词语言、提示词覆盖 | 下次启动之后 |
| 契约、challenge、evolve | 只管未来的编译——已记录的知识永不被回溯重写 |
| 切块策略 | 新材料立刻生效；已有材料要等派生层重建 |

`recall/recall.yaml` 把廉价的检索广度与最终模型上下文分开。`claim_candidate_cap` 与
`window_candidate_cap` 负责宽搜；`claim_cap`、`episode_summary_cap` 与 `window_cap` 分别准入三种
不同内容。episode 摘要是高密度的生成 L2 内容，会在明确的派生标签下展示，并带来源标题、发生时间、
章节和精确区间。它不会被冒充成逐字原文；较小的 raw 窗口预算仍是精确文本那一面。

`evidence_strategy` 决定怎样编排这些证据面。`ranked` 是直接、延迟最低的固定头部路径；`select`
在宽候选上增加一次有界的结构化 recall 模型调用，框架会验证返回坐标、保留高排名安全锚点，并把选中
的派生来源追到 L0。`answer_format` 与它独立：`text` 保留普通自由文本回答，`structured` 将回答类型、
干净正文和精确引用分开，使引用区间可以被验证。两项都可以针对一次 `ask` 覆盖。
API 会暴露 selector 在加入安全锚点前的实际入选数，让几乎没贡献证据的串行调用可见，而不是默认它有用。自动化使用干净的 `answer_text`；交互客户端渲染带引用的 `answer`。历史回放必须用 `--as-of` 显式传入提问时间；省略表示当前 UTC 时间。

**提示词语言是你的覆盖所叠在的那一层。** `prompts/overlays.yaml` 开头是 `language:`——`en` 是框架
默认的英文目录；`zh` 换成随框架发布的中文语言包，面向可读性与中文材料。两种情况下，你写在 `overlays:` 下的文案都在它**之后**生效、并盖过它。它不决定
这座文库用什么语言写：那取决于主人档案里声明的语言。

**任何一项都可以被环境变量为单次运行覆盖。** 顺序是：进程环境变量（`PNEUMA_KNOWLEDGE_*`）优先于
这个目录，这个目录优先于框架默认值。它支持一次性诊断——`PNEUMA_KNOWLEDGE_RECALL_WINDOW_CANDIDATE_CAP=80
./app.py ask '…'` 可以检查材料缺失是不是搜索深度问题，而不脏化被版本化的文件。长期运行决定要写进文件里。

## 怎么改

改完文件直接再跑 `./app.py …`——驱动每条命令都会重新读这个目录。满意了就提交：

```bash
cd engine && git add -A && git commit -m "把断言预算调高" && cd ..
git -C engine log --oneline        # 这台引擎的每一个版本
```

框架的引擎控制台（`/v1/engine/*`）就是同一件事外加一张图：它把这个目录渲染成它所配置的那条生命周期，
标出每个值的来源，并把每次 apply 带标签地提交到这里。
