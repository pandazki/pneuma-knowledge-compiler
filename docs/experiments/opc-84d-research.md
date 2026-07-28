# OPC 84 天实验：研究来源与结构提炼

记录日期：2026-07-29

本文只记录可迁移的结构观察，不复制公开材料正文。合成数据中的人物、产品、话术和
业务均为原创虚构。

## 会议

### Zoom 官方：云录制转写

来源：https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0064927

观察：

- 云录制转写会产出独立 VTT；
- 转写按带时间戳的小段切开，可事后编辑；
- 自动转写原始形态不应像整理好的会议纪要；
- 同一说话人会因为停顿被切成许多短块。

### VCSum 中文真实会议数据集

来源：https://arxiv.org/abs/2305.05280

观察：

- 239 场真实会议、总计 230 小时以上；
- 单场 transcript 平均超过 14k token；
- 真实会议具有口语表达、话题切换、多人参与和长上下文；
- 关键信息分布在全程，不能只在开头摆几句“标准答案”；
- 每场平均有大量可判为重要的句子，但摘要仍需跨主题压缩；
- 会议适合同时保留 utterance、topic segment、headline、segment summary 和
  overall summary 层次。

这直接否定“十来句话就是一场真实会议”的旧样例。实验会议将以 60–180 个话轮为
常态，并让决定散布在中后段、复述、争论和修正之间。

### Zoom 公开 VTT 观察

来源：

- https://publicsafety.jhu.edu/assets/uploads/sites/9/2024/10/2024-10-16_Annual-Public-Meeting-Planning-Session_Transcript.pdf
- https://cdnsm5-ss16.sharpschool.com/UserFiles/Servers/Server_432258/File/District/Board%20of%20Education/05.25.21%20BOE%20Transcript.pdf

观察：

- 公开 Zoom transcript 常保留启动会议、认人、设备和议程定位等非业务段落；
- 机器转写会出现名字、专有词、标点和断句错误；
- 长发言被拆成连续编号的短字幕单元，而不是一条完整段落；
- 会中常有程序性发言和重复确认，它们占体量但不形成长期知识。

## IM

### Slack 官方数据导出说明

来源：https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports

观察：

- 导出按 channel/DM 目录与日期文件组织；
- 基本字段包含 message type、user、text、timestamp；
- 除普通消息外还有 bot、join/leave、topic change、file share、pin 等 subtype；
- edited/deleted 会保留前态或编辑信息，取决于保留策略；
- reactions、pinned、starred、attachments 和文件链接都是常见旁路信息；
- 导出文本未必天然区分 thread 与 channel flow，需要 thread timestamp 等关联；
- 文件本体可能不可用，只剩链接，因此“原文附件失效”应是可表达状态。

合成 IM 不会只包含整齐问答。它将包含机器人、表情、编辑、删除、线程错位、短确认、
部署流水和附件链接。

### Slack API：消息历史与线程

来源：

- https://api.slack.com/methods/conversations.history
- https://api.slack.com/messaging/retrieving

观察：

- 会话历史与 thread replies 是不同的读取动作；
- 游标分页、时间边界、权限和速率限制会影响导入；
- thread root、reply count 与参与者列表是保留上下文的重要元信息。

## 文档库

### Obsidian 官方与官方仓库

来源：

- https://obsidian.md/help/properties
- https://obsidian.md/help/plugins/daily-notes
- https://obsidian.md/help/plugins/templates
- https://github.com/obsidianmd/obsidian-importer
- https://github.com/obsidianmd/obsidian-api

观察：

- vault 是文件与文件夹层级，不是扁平文档列表；
- Markdown、frontmatter properties、tags、aliases、内部链接、嵌入、heading 和 block
  都是知识结构的一部分；
- daily note 与 template 会产生大量重复结构和半完成内容；
- 附件、图片和链接不保证本体始终可读；
- metadata cache 明确区分 headings、links、embeds、tags 和 blocks。

### 用户授权的本地测试 vault

位置：`/Users/pandazki/Tmp/obsidian-playground`

只做结构观察，未复制正文：

- 约 11 篇 Markdown、626 行；
- 同时存在 PARA 风格目录、研究笔记、项目收藏、偏好和 session；
- frontmatter 写法不一致，既有行内数组也有多行列表；
- 文档中有重复 YAML 分隔、双语标题、emoji、代码块、外链和 wiki link；
- 一些笔记接近完整研究，一些只是十几行 session；
- status 包含 `to-read`、`to-explore`、`completed` 等不同生命周期。

合成 vault 将保留这种长短不均、元信息不齐、模板残留和状态滞后的分布。

## 邮件

### Gmail conversation view

来源：https://support.google.com/mail/answer/5900?hl=en

观察：

- 回复通常按 subject 聚合，最新邮件位于 thread 后部；
- subject 改变或 thread 过长会断成新 conversation；
- 自动通知也可能被聚成同一 thread；
- 邮件 thread 不能只按参与者合并，Message-ID、In-Reply-To、References 和 subject
  都应参与关联。

### Stripe 订阅与 webhook

来源：

- https://docs.stripe.com/billing/subscriptions/webhooks
- https://docs.stripe.com/billing/invoices/subscription

观察：

- 经营邮件与 webhook 会形成异步状态序列，而非一次性“付款成功”；
- invoice created/finalized/paid/payment_failed/upcoming 等事件会重复出现；
- 首次失败、临时失败、需要额外认证和最终取消的语义不同；
- 自动重试、人工通知和客户回复会在邮件与 IM 中重复同一事件；
- 账单通知天然提供大量有格式但不一定值得进入长期知识的噪音。

## 开发与运营

### GitHub Issues 与 Pull Requests

来源：

- https://docs.github.com/en/issues/tracking-your-work-with-issues/learning-about-issues/about-issues
- https://docs.github.com/en/pull-requests/reference/pull-requests

观察：

- issue 可以同时表示 bug、想法、反馈和任务；
- label、milestone、sub-issue、dependency、assignee 形成结构化上下文；
- issue、PR、commit 之间会形成交叉引用和自动关闭；
- PR conversation、commit、review 是不同的时间面；
- 通知会重复已经存在于 issue/PR 的事实。

### 独立开发者公开复盘

来源：

- https://www.indiehackers.com/post/my-first-8-months-as-a-solo-founder-a72b52d661
- https://www.indiehackers.com/post/being-a-solo-founder-is-extremely-hard-f0db3287ff
- https://www.indiehackers.com/post/how-did-you-get-your-first-paying-customer-1ccf1f0ea7

观察：

- 开发、营销、访谈和支持经常在同一天切换；
- “产品能用”到“有人付费”可能相隔数周或数月；
- 首客更可能来自已有互动后的 1:1 外联，而不是一次大发布；
- 支付失败、合规材料和客户沟通会把一次交易拉成长事件链；
- 发布准备可能发生在周末，且常因“不够好”而拖延；
- 个人生病、疲惫、孤独和注意力偏移会直接打断业务节奏；
- 社区评论充满鼓励、推广、复述和短回应，是很自然的高比例噪音；
- OPC 的典型问题不是缺少事件，而是跨角色切换使事实散落在不同工具中。

## 对合成分布的约束

研究最终转化为以下硬约束：

1. 会议必须长、口语化、分段密集，不能像问答脚本；
2. IM 必须包含系统事件、短回应和 thread/编辑语义；
3. 文档库必须长短不均、层级化、带不一致元信息；
4. 邮件必须包含真实 thread header、quoted reply、签名和自动通知；
5. 主线事实必须跨来源重复，但表达方式和完整度不同；
6. 重要信息不能总出现在来源开头；
7. 付款、故障、发布和客户决定必须是跨数日的状态链；
8. 超过一半体量应来自真实工作必然产生、但不值得长期编译的内容。
