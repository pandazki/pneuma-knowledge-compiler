# OPC 84 天 v2：研究台账

以下记录仅提供结构与约束，不提供可移植正文。所有虚构人物、公司、金额、产品名和表达均为原创；网页不会被复制、拼贴或近义改写进后续 corpus。

| ID | 页面标题与 URL | 访问日期 | source_type / authority | 提炼的结构性约束 | 虚构化使用边界 | 应用计划 ID |
|---|---|---|---|---|---|---|
| R01 | [Construction Management Software for Construction Projects](https://www.zoho.com/projects/construction-project-management.html) | 2026-07-29 | 供应商产品页 / 低：字段形状示例 | 变更记录可区分原因、范围、预算、责任人和状态。 | 只借字段关系；不作为室内设计行业统计或流程权威，不移植品牌术语。 | plan-G02–G10、plan-G19–G26 |
| R02 | [Using smart recording with AI](https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0061101) | 2026-07-29 | 官方产品文档 / 高 | 云录制、转写、时间定位和后处理层可以并存。 | 只约束合成 meeting 的时间定位和未整理感；不使用产品名或网页措辞。 | plan-G02、G10–G15、G19、G23–G25 |
| R03 | [How to read Slack data exports](https://slack.com/help/articles/220556107-How-to-read-Slack-data-exports) | 2026-07-29 | 官方产品文档 / 高（受保留设置条件） | 会话可按日期存放；线程、编辑、reaction 和文件链接是不同层；编辑/删除受导出条件限制。 | 只约束 IM 的时间、编辑和旁路元数据；不用真实产品名、用户或格式文本。 | plan-G03–G16、G21–G26 |
| R04 | [Obsidian Help source: Daily notes](https://raw.githubusercontent.com/obsidianmd/obsidian-help/master/en/Plugins/Daily%20notes.md) | 2026-07-29 | 官方文档源码镜像 / 高 | 按日期创建的笔记可使用模板、目录和日期属性。 | 只约束虚构 vault 的短日记、模板残留和路径差异；不引用页面文字。 | plan-G01–G02、G17、G20–G28 |
| R05 | [RFC 5322: Internet Message Format](https://www.rfc-editor.org/rfc/rfc5322.html) | 2026-07-29 | IETF 标准 / 高 | Message-ID、In-Reply-To、References 可表示邮件回复链。 | 只约束虚构 RFC822 headers 与 thread 关系；使用 example.test，不复写标准示例。 | plan-G03、G06–G09、G16–G20、G22、G27–G28 |
| R06 | [Subscription invoices](https://docs.stripe.com/billing/invoices/subscription?lang=curl) | 2026-07-29 | 官方产品文档 / 高（支付平台状态模型） | draft/open/paid 等状态与失败/重试不是同一事件。 | 只约束报价、发票、付款、失败分阶段；不用真实平台事件名或界面语句。 | plan-G16–G20、G27–G28 |
| R07 | [2026 年部分节假日安排](https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html) | 2026-07-29 | 国务院通知的政府转载 / 高 | 清明为 4 月 4–6 日，劳动节为 5 月 1–5 日，5 月 9 日上班。 | 只固定日历低谷与调休，不推断逐日天气或个人行程。 | plan-G12、G21–G23 |
| R08 | [Vehicle Maintenance](https://www.nhtsa.gov/sites/nhtsa.gov/files/documents/hs810732.pdf) | 2026-07-29 | 政府交通安全资料 / 高但范围受限 | 日常维护检查可涉及胎压、液体和制动。 | 只用于低风险保养颗粒度；不外推出事故、费用、修车时长或车型事实。 | plan-G05–G06、G10、G13 |
| R09 | [Steam Remote Play](https://store.steampowered.com/remoteplay?l=english) | 2026-07-29 | 官方产品说明 / 中 | 一名主机可邀请朋友一起游玩，并可能伴随语音和控制器协作。 | 只用于朋友间短邀请/爽约的日常形态；不出现真实平台、游戏名或产品语句。 | plan-G01、G03、G13、G18、G20、G26–G28 |

## 研究如何约束故事

研究限定记录结构、日历和日常颗粒度，而不提供剧情或句子。R01 和 R08 均有明确的低外推边界；R04 使用可直接读取的官方文档源码，先前无法稳定核验的季节页已排除。每个实际 group 后续必须把至少两条研究记录映射到稳定 authored ID；本轮的 plan-Gxx 仅是蓝图映射，不能替代正文阶段的 Gate 0.5 证据。
