# 从原始材料建立知识库

[English](README.md) | **简体中文**

Pneuma 将原始材料编译成持续维护的主体与主张，并保留回到原文段落的引用。scaffold 生成
拥有材料、编译契约和运行环境的应用项目。作为框架使用者从这里开始即可，无需先读源码。

默认路径是：**保全来源 → 按主体编译 → 检查证据与用途**。L0 保存来源，L1/L2 支持检索，
L3 是持续维护的 canonical 正本。编译成功说明机械检查通过，不说明解释忠实或覆盖完整；
这两类验收应分开进行。

## 用自己的材料开始

准备 Python、`uv`、Docker 和模型 API key，在本目录运行：

```bash
./init.py                                  # 交互生成；默认创建空项目
./init.py --print-schema                    # 查看全部配置项
./init.py --answers answers.toml --target /path/to/my-kb
```

最小 `answers.toml`：

```toml
language = "zh"
project_name = "my-kb"
[data]
mode = "path"
path = "/absolute/path/to/material"
```

省略 `[data]`，之后把材料放进生成项目的 `my-data/`。拥有者资料是可选的。生成的
`engine/compile/contract.md` 已经可用，以 `subjects/{slug}.md` 为起点，每个独立演化的
主体一页。先读几份有代表性的材料，再根据未来用途具体化它。

在生成项目中运行：

```bash
$EDITOR .env                               # 凭据只放这里
./start.sh                                 # 验证 → 启动 → 逐文件导入并编译
./app.py glance
./app.py ask '一个关于这些材料的实际问题' --sources
```

输入按文件名排序处理，请用文件名表达回放顺序。材料有参与者身份、消息时间、线程或媒体时，
优先用[来源契约 JSON](../docs/reference/source-contracts.zh-CN.md)。Markdown 只是笔记和简单
对话的便捷适配器，不能替代这些结构字段。导入器先验证整批输入，再开始写入；保留 Markdown
frontmatter，不会把粗略日期补成虚构时刻。语法见生成项目的 README。

每次构建/导入、队列处理和回答都在 `data/run-reports/` 留下私有回执，可以查看输入哈希、
来源 ID、任务历史、失败和回答降级。compile 模型的 token 统计不等于索引、检索及回答的
总成本。

## 理解并改进结果

1. 把原文、主体页和引用段落放在一起读，检查归属、时间、限定条件、变化和遗漏。地址合法的
   引用仍可能对应错误主张。
2. 提出未来确实会问的问题。回答出错时，定位最早出现偏差的环节：导入、编译、检索、上下文
   选择，还是最终解释。
3. 修改对应层。改契约只影响未来编译，不会自动重编旧材料；重建派生索引也不会重写正本知识。

让 agent 协作时，从 [AGENT-GUIDE](AGENT-GUIDE.zh-CN.md) 开始。定制准入和页面边界时读
[契约指南](../docs/guides/compile-contract.zh-CN.md)，调整回答组装时读
[召回指南](../docs/guides/recall-strategies.zh-CN.md)，修改框架时再读
[架构](../docs/architecture.zh-CN.md)。

## 可选演示

```bash
./init.py --demo                            # 独立临时项目，带已编译的库，无需 key
./init.py --demo --target /path/to/demo --no-start
```

演示用于浏览已编译的示例。确定性向量支持无 key 展示，不是语义检索质量的基准。自己的库
请在独立项目中用真实 embedding 构建，无需先跑演示再清空数据。

## 生成项目的边界

| 路径 | 用途 |
|---|---|
| `engine/` | 可版本化的策略：契约、模型角色、摄入、召回、资料与 prompt 覆写 |
| `.env` | 凭据和本机隔离的中间件端口，不入版本库 |
| `my-data/` | 用户输入；也可使用生成时指定的外部目录 |
| `data/` | 私有运行状态和回执 |
| `README.md`、`AGENTS.md` | 项目使用说明与 agent 指引 |
| `app.py`、`start.sh`、`server.py`、`worker.py`、`docker-compose.yml` | 生成的运行机械层；改进它应修改框架模板 |

本目录包含生成器 `init.py`、`templates/`、可选的虚构示例 `example/` 与 agent 指南。
替换运行机械层时必须保留用户的 `engine/`、凭据与数据。
