# pneuma-knowledge-strategies

[English](README.md) | **简体中文**

内置策略：几份**已经写好的领域编译契约**，以数据形式随包发布，外加一个只做两件事的加载器——列出有哪些、读出其中一份的原文。

## 这是起点，不是答案

本项目的立场写在 [`docs/guides/compile-contract.zh-CN.md`](../../docs/guides/compile-contract.zh-CN.md)：契约应当从你自己的数据里推导出来——先看真实材料，再说什么值得记、记到哪里去。别人替你写好的契约不可能知道你的领域里什么算高价值、什么算噪声。

那为什么还要内置？因为冷启动时「面对空文件」是最贵的一步。一份可运行、结构完整的契约，能让你**先跑起来看见它**，再照着自己的材料逐段改写。它是脚手架，用完就该被替换掉；把它原样留在生产里，等于把别人的领域判断当成了自己的。

**这个包不是框架的一部分。** 它不 import `pneuma_knowledge_core`，将来也不会；框架侧（core / service）也不 import 它。哪份契约生效，由**应用**在启动时显式注册决定。

## 已收录

| 目录 | skill_id | 版本 | 说明 |
| --- | --- | --- | --- |
| `strategies/personal-knowledge/` | `personal-knowledge` | `v1` | 最初的个人知识参考策略：证据分级、正反例、冻结历史卷、一等公民的起点、收尾自检。 |
| `strategies/personal-knowledge/` | `personal-knowledge` | `v2` | `v1` 之上多两条判断：IM 图片与带标签的 caption/OCR 共用一个可引用 L0 块，其他原生媒体明确尚未支持；以及所有者对话是所有者在谈这座库本身，它对某条已有 claim 说的话就是关于那条 claim 的证据，应当订正或取代它，而不是在旁边另立一条。 |

刻意保持一个领域一份契约。**要服务另一类用户，就新增一个策略（一个新目录），而不是给现有策略堆版本。** 只有契约自身的判断被修订时才升版本。

## API

数据 + 加载器，没有别的：

```python
from pneuma_knowledge_strategies import list_strategies, get_strategy, load_strategy_text

for s in list_strategies():
    print(s.skill_id, s.version, s.domain, s.summary)

s = get_strategy("personal-knowledge", "v2")
body = s.read_text()          # 契约正文（原文，逐字节）
s.path_templates              # 这份契约的落盘路径模板
s.contract_rules              # 附加的写契约条款（prompt catalog key）
text = load_strategy_text("personal-knowledge", "v2")   # 等价捷径
```

`Strategy` 同时带 `skill_id` / `version` / `path_templates` / `contract_rules`，因为这四项和正文一起构成契约的身份：消费方要用它们算出 `Skill-Content-Hash` 并盖进 canonical commit trailer。让调用方自己重敲一遍，就是 provenance 哈希悄悄对不上的开始。

## 怎么在应用里用起来

框架不会替你选契约。应用在启动时把一份策略转成 `SkillVersion` 并注册：

```python
from pneuma_knowledge_core.skill import SkillVersion, register_skill_base
from pneuma_knowledge_strategies import get_strategy

s = get_strategy("personal-knowledge", "v2")
register_skill_base(
    s.version,
    SkillVersion.from_parts(
        skill_id=s.skill_id,
        version=s.version,
        instructions=s.read_text(),
        path_templates=s.path_templates,
        contract_rules=s.contract_rules,
    ),
)
```
