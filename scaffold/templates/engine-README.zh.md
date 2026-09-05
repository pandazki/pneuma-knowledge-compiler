# {{PROJECT_NAME}} 的引擎

此目录保存知识库可版本化的策略。API key 和本机端口在 `../.env`，来源与运行状态放在
此 Git 仓库之外。

| 文件 | 决策 |
|---|---|
| `compile/contract.md` | 用途、主体边界、准入、权威和时间 |
| `engine.yaml` | 模型角色、工具/调用限制、概览边界和索引组件 |
| `intake/intake.yaml` | 新来源的切分方式 |
| `recall/recall.yaml` | 检索广度、证据上下文、回答格式和风格 |
| `persona/profile.yaml` | 可选的拥有者声明资料与区域设置来源 |
| `compile/challenge.yaml` | 可选的覆盖探测与补偿 |
| `evolve/evolve.yaml` | 结构提案触发条件和草稿期限 |
| `prompts/overlays.yaml` | 框架提示词语言及整条覆写 |

从契约和实际产物开始，再决定是否调其他参数。起始契约区分独立主体，在账本保留有用细节，
概览是对这些知识的简洁解读。任何契约都无法让合法引用自动证明解释正确，应结合原文、
页面和实际问题一起验收。

## 默认值与有意调整

`ranked` 广泛检索，给回答端有界的主张、派生 episode 摘要和原文窗口。`structured`
区分答案正文/类型/引用，报告被拒绝的返回引用。`ask --sources` 读取精确的 L0 引用段落。
`select` 多一次有界选择调用；`all` 在字符上限内把候选交给回答端。先在代表性问题上
单次覆盖，再改默认值。fast 有一次最终回答调用，规划、glance、组件、选择或失败回退
可能增加调用；deep 可以反复搜索和阅读。

领域尚不支持时，保持 `components` 为空。`people` 需要匹配的人物族与身份证据，`time`
增加来源时间查询，`attention` 观察 business consultation；CLI 的直接 recall 不留下
consultation 记录。覆盖 challenge 和自动 evolution 默认关闭，因为会增加工作和调用；
覆盖探测通过仍是模型判断。`evolve step` 默认保留草稿，采用是单独动作。

| 修改 | 影响 |
|---|---|
| 召回预算、风格、证据策略 | 下一次调用/提问 |
| 模型角色、提示词覆写 | 下一次 CLI 调用；常驻服务需要重启 |
| 编译契约、challenge 策略 | 未来编译，旧主张不会重编 |
| Evolve 策略 | 未来提案调度；采用提案会改变正本结构 |
| 切分策略 | 新索引；派生重建回放已保留的语义边界 |
| Embedding 模型 | 重建受影响向量；维度和向量空间都必须一致 |

相同来源重新导入通常会去重。比较完整编译时，在新项目中使用相同来源清单，不要把抹掉
原库当作修改契约的常规方法。派生重建从权威数据恢复索引，不会重新进行 L3 判断。
相同向量维度不意味着不同 embedding 模型可以混用。

系统检测到的区域设置标为 `deployment_default`，不是拥有者的声明。只有本人声明时才把
对应字段的 provenance 改成 `profile`。空的背景、名字和日期保持未声明。prompt 的
`language` 控制框架措辞，与来源语言和回答语言偏好分开。

每次 CLI 调用重新读文件，优先级是：进程环境 → engine 文件 → 框架默认值。用环境变量
做诊断，长期策略写入文件。在项目根目录执行：

```bash
git -C engine diff
git -C engine add -A
git -C engine commit -m '描述实际策略改动'
```

Engine Console 配置的也是这个目录。进一步阅读框架的
`docs/guides/compile-contract.zh-CN.md`、`docs/guides/recall-strategies.zh-CN.md` 与
`scaffold/AGENT-GUIDE.zh-CN.md`。
