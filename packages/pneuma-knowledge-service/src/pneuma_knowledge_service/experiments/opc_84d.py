"""Deterministic 84-day OPC work-life corpus over the four official source contracts.

The corpus is intentionally not a neat demo.  A single, explicit business story runs
through twelve weekly import batches while most atomic content is ordinary work exhaust:
meeting setup, repeated context, bot events, draft notes, quoted mail, newsletters, and
plans that never become decisions.  A separate manifest labels that exhaust and carries
the truth set; the source payloads themselves never announce which lines are noise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

SHANGHAI = timezone(timedelta(hours=8))
START = datetime(2026, 3, 2, 8, 30, tzinfo=SHANGHAI)
DEFAULT_SEED = 20260729


@dataclass(frozen=True)
class ExperimentBatch:
    batch_id: str
    started_at: str
    ended_at: str
    contracts: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "contracts": list(self.contracts),
        }


@dataclass(frozen=True)
class Opc84dDataset:
    seed: int
    manifest: dict[str, Any]
    batches: tuple[ExperimentBatch, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "manifest": self.manifest,
            "batches": [batch.as_dict() for batch in self.batches],
        }


@dataclass(frozen=True)
class WeekArc:
    phase: str
    objective: str
    milestone: str
    customer: str
    facts: tuple[str, str, str]
    old_decision: str
    current_decision: str
    guard_decision: str
    commitments: tuple[str, str]
    constraints: tuple[str, str]
    negative_controls: tuple[str, str, str]


WEEK_ARCS: tuple[WeekArc, ...] = (
    WeekArc(
        phase="问题发现",
        objective="验证小型咨询团队是否真的缺少可回到原文的决策记录",
        milestone="完成首轮五次访谈并留下三个待验证假设",
        customer="北辰咨询",
        facts=(
            "RelayForge 面向十人以内的咨询与产品工作室，而不是大型企业协作平台。",
            "北辰咨询当前把客户结论散落在视频会议、Slack 和项目邮件里。",
            "沈砚是试验周期内唯一全职开发与运营者。",
        ),
        old_decision="先做一套自动生成漂亮会议摘要的通用工具。",
        current_decision="第一版先证明决定能够回到原始片段，摘要美观不是首要目标。",
        guard_decision="访谈阶段不接触客户生产数据，只使用对方提供的脱敏样例。",
        commitments=(
            "沈砚在周五前完成五次问题访谈并整理逐条证据。",
            "顾清在周四前提供两份脱敏会议纪要和一个项目频道导出。",
        ),
        constraints=(
            "验证预算上限为人民币三千元，不购买年度 SaaS。",
            "任何演示数据都不得包含客户姓名、邮箱或合同金额原文。",
        ),
        negative_controls=(
            "下周把产品改名为 SolarMemo。",
            "办公室绿萝应该换到靠窗的位置。",
            "午饭试试新开的海南鸡饭。",
        ),
    ),
    WeekArc(
        phase="客户访谈",
        objective="从访谈中识别最痛的可验证工作，而不是收集功能愿望",
        milestone="否定自动总结优先，确认跨来源决定追踪优先",
        customer="北辰咨询",
        facts=(
            "五名访谈对象都能找到会议纪要，但四人无法快速定位决定的原始证据。",
            "北辰咨询每周约有六场客户会议，项目频道消息量远高于邮件。",
            "客户愿意为减少验收争议付费，而不是为更长的摘要付费。",
        ),
        old_decision="把实时转写和会议摘要作为首页唯一入口。",
        current_decision="把跨来源决定、承诺和引用回放作为 MVP 的核心路径。",
        guard_decision="对没有来源支撑的回答必须明确显示证据不足。",
        commitments=(
            "沈砚在周三前交付一张跨来源证据流程图。",
            "唐恬在周五前给出十个真实但脱敏的验收问题。",
        ),
        constraints=(
            "一次检索结果必须在三秒内先给出可读反馈。",
            "引用必须落到稳定 source id 和块区间，不能只链接摘要。",
        ),
        negative_controls=(
            "所有访谈对象都强烈要求语音克隆。",
            "首页背景可以换成紫色渐变。",
            "先买一台新的机械键盘再继续开发。",
        ),
    ),
    WeekArc(
        phase="MVP 定界",
        objective="把两周能交付的范围写成可以拒绝需求的边界",
        milestone="冻结四类输入、引用检索和决定时间线",
        customer="北辰咨询",
        facts=(
            "MVP 的官方输入固定为 meeting、document library、IM 和 email 四类。",
            "Canonical 文档是派生层，原始来源保持不可变并可重建。",
            "试点成功以二十个问题至少十九个能回到正确原文为硬指标。",
        ),
        old_decision="试点同时交付团队权限、自动写回和移动端。",
        current_decision="试点只交付四类导入、带引用检索和决定时间线。",
        guard_decision="自动写回、团队权限和长期运维明确列入不做清单。",
        commitments=(
            "沈砚在周四发出试点范围说明和风险清单。",
            "顾清在周五确认二十个验收问题的最终版本。",
        ),
        constraints=(
            "试点周期固定两周，参与者最多十二人。",
            "客户原始附件不离开本地试点环境。",
        ),
        negative_controls=(
            "第二周就上线企业单点登录。",
            "把所有历史消息永久保存更省事。",
            "演示时顺便做一个完整 CRM。",
        ),
    ),
    WeekArc(
        phase="设计合作",
        objective="把北辰咨询的试点变成双方都能验收的交付",
        milestone="确认试点日期、数据边界和联合走查节奏",
        customer="北辰咨询",
        facts=(
            "北辰咨询的试点项目代号为 Cedar，持续十四天。",
            "联合走查固定在每周三十五点，顾清和唐恬参加。",
            "试点使用十二名研究员的脱敏样例，不接入生产 workspace。",
        ),
        old_decision="试点期间每天自动向客户频道推送编译结果。",
        current_decision="试点只在联合走查中展示结果，不自动向外部频道发消息。",
        guard_decision="每次导入保留来源、采集时间、稳定 ID 和适配器版本。",
        commitments=(
            "沈砚在下周一中午前准备首批四类数据导入。",
            "顾清在周四前完成十二名参与者的脱敏映射。",
        ),
        constraints=(
            "删除请求必须在二十四小时内覆盖 L0、索引和 canonical 派生层。",
            "任何模型输出不得替代客户审批或代表客户发送消息。",
        ),
        negative_controls=(
            "顾清已经批准把生产 Slack 全量接进来。",
            "联合走查改到每周五晚上九点。",
            "试点参与者临时增加到四十人。",
        ),
    ),
    WeekArc(
        phase="首次导入",
        objective="跑通脱敏数据的真实导入并记录不整齐的边界情况",
        milestone="四类来源均可读取，暴露重复、附件失效和时区偏移",
        customer="北辰咨询",
        facts=(
            "首批数据包含三场 Zoom 会议、一个 Obsidian vault、两个 Slack 频道和八个邮件线程。",
            "Slack 导出中有重复 thread reply，必须按 provider message id 去重。",
            "两封旧邮件只保留附件链接，附件本体已经不可用。",
        ),
        old_decision="统一把所有没有时区的时间当作 UTC。",
        current_decision="缺失时区的旧材料先隔离并请求来源时区，不静默猜测。",
        guard_decision="去重以用户、provider 和稳定外部 ID 为边界，不跨用户合并。",
        commitments=(
            "沈砚在周三走查前修复 Slack thread 去重。",
            "唐恬在周四前确认历史会议的 Asia/Shanghai 时区。",
        ),
        constraints=(
            "附件失效必须显示为可解释状态，不能伪造正文。",
            "同一来源重跑必须幂等且不增加 source 数。",
        ),
        negative_controls=(
            "附件打不开就用模型补一份大概内容。",
            "所有历史时间显然都是北京时间。",
            "重复消息越多越能提高召回。",
        ),
    ),
    WeekArc(
        phase="事故与修复",
        objective="处理一次错误实体合并并证明系统可以回滚和重建",
        milestone="回滚错误快照、修复实体边界、发布事故复盘",
        customer="北辰咨询",
        facts=(
            "Cedar 第一次走查把同姓的顾清和顾青错误合并为一个人。",
            "错误只影响 canonical 和派生索引，L0 原始来源未被改写。",
            "回滚后重新投影恢复了正确的两个实体和各自引用。",
        ),
        old_decision="在姓名相似时自动合并实体，减少客户确认步骤。",
        current_decision="姓名相似只产生候选关系，未经稳定标识或人工确认不得合并。",
        guard_decision="事故修复顺序固定为冻结写入、保存证据、回滚、重建、回放验证。",
        commitments=(
            "沈砚在事故后四小时内完成回滚和影响范围说明。",
            "顾清在次日中午前复核二十个验收问题的引用。",
        ),
        constraints=(
            "回滚不能删除 L0，也不能复用错误快照的 claim 投影。",
            "事故报告只写确认事实，不猜测客户侧影响。",
        ),
        negative_controls=(
            "顾青其实是顾清在社区里使用的昵称。",
            "事故没有客户看到，所以不用记录。",
            "索引坏了直接清空原始数据最快。",
        ),
    ),
    WeekArc(
        phase="采购与安全",
        objective="用小团队能维护的方式回答客户采购与隐私问题",
        milestone="完成保留、删除、子处理方和访问边界说明",
        customer="北辰咨询",
        facts=(
            "Cedar 试点默认保留原始来源三十天，客户可提前删除。",
            "子处理方清单包括托管数据库、对象存储和模型 API 提供方。",
            "访问日志按用户隔离，管理员界面不显示跨用户内容。",
        ),
        old_decision="为了便于调试，试点数据默认保留一年。",
        current_decision="试点原始数据默认保留三十天，派生索引随删除请求重建。",
        guard_decision="供应商变化必须先更新子处理方清单再处理新数据。",
        commitments=(
            "许言在周三前审阅数据处理附录。",
            "沈砚在周五前补齐删除演练和恢复演练记录。",
        ),
        constraints=(
            "日志不得记录原始正文、API key 或完整邮箱地址。",
            "开源演示数据与客户试点索引必须使用不同用户和命名空间。",
        ),
        negative_controls=(
            "客户口头同意后就可以跳过数据处理附录。",
            "日志里保留完整 prompt 方便以后排错。",
            "开源 demo 可以复用试点的向量集合。",
        ),
    ),
    WeekArc(
        phase="定价与回款",
        objective="把试点价值转换成一个客户能批准、自己能交付的报价",
        milestone="签下首个付费月度方案并恢复一次失败付款",
        customer="北辰咨询",
        facts=(
            "北辰咨询接受每月人民币四千八百元的设计合作方案。",
            "方案含每月两次联合走查和二十万字符新增材料。",
            "首笔付款因 3DS 验证未完成失败，次日由客户重新认证后成功。",
        ),
        old_decision="按席位每人每月收费并设置三个复杂套餐。",
        current_decision="设计合作期采用单一月费，按新增材料设柔性使用边界。",
        guard_decision="支付失败不立即删除数据，先通知并保留七天人工恢复窗口。",
        commitments=(
            "沈砚在周二发出正式报价和发票。",
            "顾清在周四完成支付认证并回传采购编号。",
        ),
        constraints=(
            "设计合作期不承诺 7x24 支持，严重事故响应目标为四小时。",
            "月费不包含定制模型训练和客户侧系统改造。",
        ),
        negative_controls=(
            "首笔付款已经在第一次尝试时成功。",
            "方案价格是每席位每月四百八十元。",
            "付款失败意味着客户已经决定取消。",
        ),
    ),
    WeekArc(
        phase="发布准备",
        objective="准备一次可回退的小范围公开发布，而不是追求首日声量",
        milestone="完成文档、迁移说明、演示和发布门禁",
        customer="原点工作室",
        facts=(
            "公开预览面向最多五十名申请者，默认仍是单用户工作区。",
            "发布门禁包括许可证扫描、生产构建、无密钥 E2E 和删除演练。",
            "原点工作室同意作为第二个设计合作候选，不承诺本周采购。",
        ),
        old_decision="周一直接公开发布并同步开放自助付费。",
        current_decision="先邀请制公开预览，观察激活和引用回放后再开放自助付费。",
        guard_decision="门禁有一项失败就延期，不为营销日期跳过验证。",
        commitments=(
            "沈砚在周四前录制八分钟演示并补齐迁移说明。",
            "程野在周五前提供六个用于预览验收的问题。",
        ),
        constraints=(
            "公开预览不接入客户生产 Slack OAuth。",
            "演示必须使用独立合成用户且不得引用 Cedar 数据。",
        ),
        negative_controls=(
            "Product Hunt 已经确认把产品设为当日推荐。",
            "公开预览当天一定能获得一千个注册。",
            "门禁失败可以先发版后补测试。",
        ),
    ),
    WeekArc(
        phase="小范围发布",
        objective="观察真实激活而不是沉迷访问量",
        milestone="邀请制发布带来注册增长，也暴露首次成功路径过长",
        customer="原点工作室",
        facts=(
            "公开预览首周有四十七个注册，十二个完成四类来源中的至少一种导入。",
            "七名用户完成带引用问答，首次成功中位时间为二十八分钟。",
            "支持问题主要集中在导入格式、处理进度和附件失效说明。",
        ),
        old_decision="注册数达到四十就立即扩展到团队协作功能。",
        current_decision="先把首次成功时间压到十五分钟以内，再考虑团队协作。",
        guard_decision="发布周只修复阻断激活或破坏引用的缺陷。",
        commitments=(
            "沈砚在周三前发布导入检查器和三份错误示例。",
            "罗屿在周五前完成首次导入空状态和进度状态设计。",
        ),
        constraints=(
            "支持回复不得承诺未排期功能的日期。",
            "公开指标同时报告注册、激活和引用回放，不只展示访问量。",
        ),
        negative_controls=(
            "四十七个注册全部已经成为付费用户。",
            "用户最想要的是头像动画。",
            "发布周没有收到任何支持请求。",
        ),
    ),
    WeekArc(
        phase="留存修复",
        objective="根据使用证据减少首次导入后的迷路与等待",
        milestone="取消低价值功能，缩短首个可引用答案的路径",
        customer="北辰咨询",
        facts=(
            "完成首次引用问答的用户次周返回率明显高于只完成注册的用户。",
            "自动生成周报的使用率很低，却制造了最多的格式支持问题。",
            "导入检查器将常见格式错误在上传前暴露，支持量随之下降。",
        ),
        old_decision="继续打磨自动周报模板，把它放到首页主入口。",
        current_decision="暂停自动周报，把工程时间用于导入检查和首次引用问答。",
        guard_decision="留存优化以真实行为漏斗为准，不以访谈中的功能好感代替。",
        commitments=(
            "沈砚在周四前移除首页周报入口并迁移已有链接。",
            "唐恬在周五前完成新版首次成功路径的五人可用性测试。",
        ),
        constraints=(
            "迁移不能让已有 briefing 链接失效。",
            "任何自动提示都必须允许关闭且不阻断主任务。",
        ),
        negative_controls=(
            "自动周报是留存最高的功能。",
            "首页入口越多越能帮助新用户理解产品。",
            "可用性测试已经覆盖五百名用户。",
        ),
    ),
    WeekArc(
        phase="周期复盘",
        objective="根据十二周证据决定继续什么、停止什么、延后什么",
        milestone="确认下一周期继续聚焦设计合作客户",
        customer="北辰咨询",
        facts=(
            "周期结束时有一个付费客户、一个设计合作候选和七名稳定周活跃预览用户。",
            "最稳定价值是跨来源决定与引用回放，不是通用摘要或自动周报。",
            "当前单人维护能力适合两到三个高接触客户，不适合同时做通用平台。",
        ),
        old_decision="下一周期扩张为包含任务、聊天和 CRM 的通用协作平台。",
        current_decision="下一周期继续聚焦两到三个设计合作客户和引用可靠性。",
        guard_decision="团队权限、自助付费和移动端延后到首次成功时间达标之后。",
        commitments=(
            "沈砚在周期结束后三天内发出客户复盘和下一阶段范围。",
            "顾清在下周三前确认是否续签第二个月。",
        ),
        constraints=(
            "下一周期基础设施预算维持每月人民币两千元以内。",
            "任何新增来源类型必须先有真实客户材料和官方 contract。",
        ),
        negative_controls=(
            "下个月马上招聘五名全职员工。",
            "产品已经具备完整 CRM 能力。",
            "所有预览用户都要求移动端。",
        ),
    ),
)


EVENT_SHAPES: tuple[tuple[int, int, str, str], ...] = (
    (0, 9, "main", "weekly_plan"),
    (0, 16, "operations", "inbox_triage"),
    (1, 10, "main", "customer_call"),
    (1, 21, "personal", "late_note"),
    (2, 11, "main", "implementation"),
    (2, 16, "growth", "follow_up"),
    (3, 9, "operations", "service_check"),
    (3, 18, "open_source", "maintainer_work"),
    (4, 10, "main", "decision_update"),
    (4, 17, "growth", "content_attempt"),
    (5, 14, "personal", "recovery"),
    (6, 19, "main", "weekly_review"),
)


MEETING_NOISE: tuple[tuple[str, str], ...] = (
    ("small_talk", "先等一下，顾清还在进会议室。昨晚雨挺大，我这边地铁也慢了十来分钟。"),
    ("audio_check", "能听见吗？我刚才麦克风选错了。现在这个音量如果还有回声你们提醒我一下。"),
    ("screen_navigation", "我共享的是不是浏览器窗口？等一下，我翻错标签页了，应该是左边第三个，不是这个监控面板。"),
    ("disfluency", "嗯，我重新说一下，刚才那句话不准确。我的意思不是已经做完，而是今天先把能验证的那一段跑通。"),
    ("repeated_context", "这个背景上周其实讲过一遍，我还是快速重复一下，主要怕今天新进来的同学不知道前因后果。"),
    ("scheduling", "周三那个时间我可能会晚十分钟，日历先别急着改，等下午另一个会议确认后我再回消息。"),
    ("tangent", "顺便说一句，新的文档站搜索好像变慢了，不过和今天的验收范围没直接关系，先记在停车场。"),
    ("speculation", "这里我只是猜测，也可能是浏览器缓存，不要把这句当结论，待会儿看完日志再说。"),
    ("transcript_error", "刚才转写把 RelayForge 写成了 railway force，后面看到这个词都按产品名理解，不影响实际数据。"),
    ("acknowledgement", "好，收到。这个我先不展开，等轮到对应议题再一起看，避免来回跳。"),
    ("recap_without_decision", "目前有人倾向方案一，也有人觉得方案二维护简单，但我们还没有足够证据，今天先不定。"),
    ("break", "我们已经连续四十五分钟了，先停两分钟。回来以后只看剩下三个问题，不再开新话题。"),
)

IM_NOISE: tuple[tuple[str, str], ...] = (
    ("ack", "收到，我先把这条标一下，晚一点集中回复，不在这里展开。"),
    ("reaction_only", "👍 我看到了，等手头这个构建结束再切回来。"),
    ("bot_build", "CI bot：preview 构建完成，缓存命中 87%，本条通知无需操作。"),
    ("bot_dependency", "Dependabot：发现一个 patch 版本更新，当前测试通过，尚未安排合并。"),
    ("reschedule", "我前一个会拖了十分钟，原定时间先顺延；如果你不方便我们明早再约。"),
    ("link_only", "先丢个链接在这：https://example.invalid/read-later ，我还没读，不代表采用里面的方案。"),
    ("casual", "今天咖啡豆好像磨得太细了，机器一直报警，和线上监控那声还挺像。"),
    ("thread_misalignment", "这条回错 thread 了，讨论的是文档示例，不是线上事故；我复制到正确的串里。"),
    ("edited", "更正：我刚写的是周四，其实是周五下午；上条已编辑，日历邀请还没发。"),
    ("status_churn", "状态先从 doing 改回 todo，依赖还没到位；这不是取消，只是今天不继续。"),
)

EMAIL_NOISE: tuple[tuple[str, str], ...] = (
    ("signature", "此邮件由移动设备发送。签名中的职位和地址仅供联系，不构成项目范围承诺。"),
    ("quoted_reply", "以下为历史邮件引用，内容可能已经过期：\n> 我们先按旧时间讨论\n> 是否上线仍待确认\n> 请勿据此安排生产变更"),
    ("calendar_update", "日历系统通知：会议标题未变，视频链接已刷新。若您已接受邀请，无需回复本邮件。"),
    ("newsletter", "本周产品通讯汇总了十二条增长建议、七个模板和三场线上活动。这是一封自动订阅邮件。"),
    ("delivery_notice", "自动投递报告：一名抄送人地址暂时不可达，系统将在稍后重试；其他收件人已接收。"),
    ("out_of_office", "自动回复：我今天下午不在电脑前，紧急事项请走既有支持渠道；本邮箱不会自动转发。"),
    ("vendor_marketing", "供应商活动邀请：升级年度方案可获得额外额度。该报价与现有试点采购无关。"),
    ("legal_footer", "本邮件及附件可能包含保密信息。如误收请删除。此通用页脚不改变双方已签署文件。"),
)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _event_id(week: int, index: int) -> str:
    return f"evt-{week:02d}-{index:02d}"


def _truth_id(kind: str, week: int, index: int) -> str:
    return f"{kind}-{week:02d}-{index:02d}"


def _make_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for week, arc in enumerate(WEEK_ARCS, start=1):
        base = START + timedelta(days=(week - 1) * 7)
        summaries = (
            f"整理「{arc.objective}」的本周计划，把未知项与对外承诺分开。",
            f"清理积压通知和上周未关闭的小任务，为「{arc.phase}」腾出连续工作块。",
            f"与{arc.customer}推进「{arc.objective}」，记录异议、证据与待确认项。",
            f"深夜补记白天遗漏的上下文；只留下草稿，不在疲劳状态下做范围决定。",
            f"实现并验证本周里程碑：{arc.milestone}。",
            f"发出客户跟进，要求对方明确确认而不是把沉默视为同意。",
            "检查托管、模型、邮件和索引运行状态，区分告警与真正故障。",
            "处理开源 issue、依赖更新和文档反馈，不让维护工作吞掉客户交付。",
            f"根据新证据更新决定：{arc.current_decision}",
            "发布一则过程记录并回复社区评论，接受低互动而不临时改产品方向。",
            "安排半天离线恢复，仍有零散想法进入收件箱，但不把它们伪装成进展。",
            f"周复盘确认里程碑「{arc.milestone}」，列出继续、停止和延后事项。",
        )
        for index, ((day, hour, thread, kind), summary) in enumerate(
            zip(EVENT_SHAPES, summaries), start=1
        ):
            at = base + timedelta(days=day, hours=hour - 8, minutes=(index * 7) % 53)
            events.append(
                {
                    "event_id": _event_id(week, index),
                    "batch_id": f"B{week:02d}",
                    "occurred_at": _iso(at),
                    "thread": thread,
                    "kind": kind,
                    "phase": arc.phase,
                    "summary": summary,
                    "mainline": thread == "main",
                }
            )
    return events


def _truth_set() -> dict[str, list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    supersessions: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    retrieval: list[dict[str, Any]] = []

    for week, arc in enumerate(WEEK_ARCS, start=1):
        effective = START + timedelta(days=(week - 1) * 7 + 4, hours=2)
        fact_ids: list[str] = []
        for index, value in enumerate(arc.facts, start=1):
            truth_id = _truth_id("fact", week, index)
            fact_ids.append(truth_id)
            facts.append(
                {
                    "truth_id": truth_id,
                    "value": value,
                    "effective_from": _iso(effective - timedelta(days=2 - index)),
                    "status": "current",
                    "source_types": ["meeting", "document_library", "im"],
                }
            )
        old_id = _truth_id("decision", week, 1)
        current_id = _truth_id("decision", week, 2)
        guard_id = _truth_id("decision", week, 3)
        decisions.extend(
            [
                {
                    "truth_id": old_id,
                    "value": arc.old_decision,
                    "effective_from": _iso(effective - timedelta(days=3)),
                    "status": "superseded",
                    "source_types": ["meeting", "document_library"],
                },
                {
                    "truth_id": current_id,
                    "value": arc.current_decision,
                    "effective_from": _iso(effective),
                    "status": "current",
                    "source_types": ["meeting", "im", "email"],
                },
                {
                    "truth_id": guard_id,
                    "value": arc.guard_decision,
                    "effective_from": _iso(effective + timedelta(hours=2)),
                    "status": "current",
                    "source_types": ["document_library", "im", "email"],
                },
            ]
        )
        for index, value in enumerate(arc.commitments, start=1):
            commitments.append(
                {
                    "truth_id": _truth_id("commitment", week, index),
                    "value": value,
                    "owner": "沈砚" if index == 1 else arc.customer,
                    "due_at": _iso(effective + timedelta(days=index)),
                    "status": "open" if week == len(WEEK_ARCS) else "done",
                    "source_types": ["meeting", "im", "email"],
                }
            )
        for index, value in enumerate(arc.constraints, start=1):
            constraints.append(
                {
                    "truth_id": _truth_id("constraint", week, index),
                    "value": value,
                    "effective_from": _iso(effective),
                    "status": "current",
                    "source_types": ["document_library", "meeting", "email"],
                }
            )
        supersessions.append(
            {
                "supersession_id": f"sup-{week:02d}",
                "before_truth_id": old_id,
                "after_truth_id": current_id,
                "effective_at": _iso(effective),
                "reason": f"{arc.phase}阶段的新证据改变了优先级。",
            }
        )
        for index, value in enumerate(arc.negative_controls, start=1):
            negatives.append(
                {
                    "truth_id": _truth_id("negative", week, index),
                    "value": value,
                    "reason": "只在草稿、猜测或闲聊中出现，不应进入 canonical。",
                    "source_types": ["meeting", "document_library", "im", "email"][
                        : 1 + (index % 4)
                    ],
                }
            )
        retrieval.extend(
            [
                {
                    "case_id": f"rq-{week:02d}-01",
                    "question": f"{arc.phase}阶段最后采用了什么决定，替代了哪个旧想法？",
                    "expected_truth_ids": [current_id, old_id],
                    "as_of": _iso(effective + timedelta(hours=3)),
                },
                {
                    "case_id": f"rq-{week:02d}-02",
                    "question": f"{arc.customer}在本周确认了哪些事实与交付？",
                    "expected_truth_ids": [fact_ids[0], _truth_id("commitment", week, 2)],
                    "as_of": None,
                },
                {
                    "case_id": f"rq-{week:02d}-03",
                    "question": f"{arc.phase}阶段有哪些不能突破的边界？",
                    "expected_truth_ids": [
                        guard_id,
                        _truth_id("constraint", week, 1),
                        _truth_id("constraint", week, 2),
                    ],
                    "as_of": None,
                },
            ]
        )
    return {
        "durable_facts": facts,
        "decisions": decisions,
        "commitments": commitments,
        "constraints": constraints,
        "supersessions": supersessions,
        "negative_controls": negatives,
        "retrieval_cases": retrieval,
    }


class _Builder:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.atoms: list[dict[str, Any]] = []

    def atom(
        self,
        *,
        source_type: str,
        source_ref: str,
        text: str,
        is_noise: bool,
        noise_type: str | None,
        event_id: str,
        occurred_at: datetime,
    ) -> None:
        self.atoms.append(
            {
                "source_ref": f"{source_type}:{source_ref}",
                "source_type": source_type,
                "event_id": event_id,
                "occurred_at": _iso(occurred_at),
                "char_count": len(text),
                "is_noise": is_noise,
                "noise_type": noise_type,
            }
        )


def _signal_values(arc: WeekArc) -> tuple[str, ...]:
    return (
        *arc.facts,
        arc.old_decision,
        arc.current_decision,
        arc.guard_decision,
        *arc.commitments,
        *arc.constraints,
    )


def _meeting(
    builder: _Builder,
    *,
    week: int,
    suffix: str,
    arc: WeekArc,
    count: int,
    started_at: datetime,
) -> dict[str, Any]:
    meeting_id = f"rf-b{week:02d}-{suffix}"
    participants = [
        {"participant_id": "p-owner", "display_name": "沈砚", "email": "yan@relayforge.dev"},
        {"participant_id": "p-gu", "display_name": "顾清", "email": "gu@beichen.example"},
        {"participant_id": "p-tang", "display_name": "唐恬", "email": "tang@beichen.example"},
        {"participant_id": "p-luo", "display_name": "罗屿", "email": "luo@studio.example"},
    ]
    speakers = [item["participant_id"] for item in participants]
    speaker_names = {item["participant_id"]: item["display_name"] for item in participants}
    signals = _signal_values(arc)
    signal_positions = {
        8,
        13,
        19,
        27,
        34,
        41,
        49,
        58,
        66,
        73,
        81,
        88,
        max(1, count - 9),
        max(1, count - 3),
    }
    segments: list[dict[str, Any]] = []
    cursor = started_at
    signal_index = 0
    for index in range(1, count + 1):
        segment_id = f"{meeting_id}-s{index:03d}"
        speaker_id = speakers[(index + week + (1 if suffix != "main" else 0)) % len(speakers)]
        if index in signal_positions:
            value = signals[signal_index % len(signals)]
            prefixes = (
                "我把刚才的讨论落成一句可以验收的话：",
                "这里请大家明确确认，当前有效版本是：",
                "先区分事实和猜测，已经有材料支撑的是：",
                "这个要写进会后行动项，不是口头建议：",
            )
            text = f"{speaker_names[speaker_id]}：{prefixes[signal_index % len(prefixes)]}{value}"
            is_noise = False
            noise_type = None
            signal_index += 1
        else:
            noise_type, raw = MEETING_NOISE[(index * 5 + week) % len(MEETING_NOISE)]
            elaboration = (
                f"今天讨论的是「{arc.objective}」，但这段只是在整理现场，不新增决定。"
                if index % 3 == 0
                else "如果后面有正式结论，请以会后确认邮件和决定记录为准。"
            )
            text = (
                f"{speaker_names[speaker_id]}：{raw}{elaboration}"
                "我先把现场话保留下来，里面的停顿、重复和临时判断都不要自动抹平，"
                "否则复盘时会误以为当时已经达成一致。"
            )
            is_noise = True
        duration = 11 + (index * 7 + week) % 21
        ended = cursor + timedelta(seconds=duration)
        segments.append(
            {
                "segment_id": segment_id,
                "speaker_id": speaker_id,
                "started_at": _iso(cursor),
                "ended_at": _iso(ended),
                "text": text,
            }
        )
        builder.atom(
            source_type="meeting",
            source_ref=segment_id,
            text=text,
            is_noise=is_noise,
            noise_type=noise_type,
            event_id=_event_id(week, 3 if index < count // 2 else 9),
            occurred_at=cursor,
        )
        cursor = ended + timedelta(seconds=(index * 3) % 5)
    return {
        "schema": "pneuma.source.meeting/v1",
        "provider": "mock",
        "meeting_id": meeting_id,
        "title": (
            f"{arc.phase} · {arc.customer} 周走查"
            if suffix == "main"
            else f"{arc.phase} · 发布与风险复盘"
        ),
        "started_at": _iso(started_at),
        "ended_at": _iso(cursor),
        "timezone": "Asia/Shanghai",
        "owner_participant_ids": ["p-owner"],
        "participants": participants,
        "agenda": [arc.objective, arc.milestone, "风险、证据与下一步"],
        "segments": segments,
        "metadata": {
            "batch_id": f"B{week:02d}",
            "synthetic": True,
            "transcript_style": "zoom-vtt-like",
        },
    }


def _expanded_paragraphs(lines: Iterable[str], *, rounds: int) -> str:
    source = tuple(lines)
    paragraphs: list[str] = []
    for index in range(rounds):
        value = source[index % len(source)]
        paragraphs.append(
            f"{value} 这段记录保留当时的上下文和未决状态；后续若有明确确认，"
            f"以带日期的决定记录为准。记录序号 {index + 1:02d}。"
        )
    return "\n\n".join(paragraphs)


def _documents(
    builder: _Builder, *, week: int, arc: WeekArc, base: datetime
) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    signal_content = (
        f"# {arc.phase}周决定与证据\n\n"
        f"> [!summary] 本周目标\n> {arc.objective}\n\n"
        "## 已确认事实\n\n"
        + "\n".join(f"- {item}" for item in arc.facts)
        + "\n\n## 决定变化\n\n"
        f"- 旧设想（已失效）：{arc.old_decision}\n"
        f"- 当前决定：{arc.current_decision}\n"
        f"- 执行护栏：{arc.guard_decision}\n\n"
        "## 承诺\n\n"
        + "\n".join(f"- [ ] {item}" for item in arc.commitments)
        + "\n\n## 约束\n\n"
        + "\n".join(f"- {item}" for item in arc.constraints)
        + "\n\n## 证据导航\n\n"
        f"- 会议：[[02-Meetings/B{week:02d}-{arc.phase}走查]]\n"
        f"- 客户：[[01-Projects/RelayForge/Customers/{arc.customer}]]\n"
        "\n## 工作过程\n\n"
        + _expanded_paragraphs(
            (
                "先把能直接回到原文的句子列出来，再将推断放到单独小节。",
                "同一个结论在会议、消息和邮件中出现时，保留各自时间与语气差异。",
                "没有明确确认的事项继续留在待验证区，不把重复出现当作事实。",
                "周末复盘只改变优先级，不回写或美化原始来源。",
            ),
            rounds=20,
        )
    )
    clip_content = (
        f"# 未整理剪藏 · {arc.phase}\n\n"
        f"tags: #read-later #unverified\n\n"
        + _expanded_paragraphs(
            (
                "有人说所有 B2B 产品都应该先做团队权限，但这篇帖子没有数据来源。",
                "收藏了一篇增长文章，只看了标题；里面的漏斗数字不适用于当前客户。",
                arc.negative_controls[0],
                "一段关于品牌命名的讨论很热闹，但没有任何设计合作客户参与。",
                "把三个可能的首页文案放在这里，顺序随机，暂时不选。",
                "外部案例声称一天获得上千注册，未核验渠道、预算或转化定义。",
            ),
            rounds=45,
        )
    )
    daily_content = (
        f"# {base.date().isoformat()} 日记\n\n"
        "## Inbox\n\n"
        + "\n".join(
            [
                f"- [ ] {arc.negative_controls[1]}",
                "- [ ] 回一个不紧急的社区私信",
                "- [x] 把昨天的临时截图移到归档",
                "- [ ] 检查咖啡机滤芯，和产品没有关系",
                f"- [ ] {arc.negative_controls[2]}",
            ]
        )
        + "\n\n## 随手记\n\n"
        + _expanded_paragraphs(
            (
                "上午切换了太多窗口，几次忘记刚才为什么打开日志。",
                "想到一个功能名字又觉得太像别的产品，先不做任何设计。",
                "社区里有人推荐另一套技术栈，看起来有趣，但迁移成本完全没算。",
                "晚上状态一般，只修了两个小错误，没有形成需要长期保存的结论。",
            ),
            rounds=30,
        )
    )
    specs = (
        (
            f"doc-b{week:02d}-decision",
            f"01-Projects/RelayForge/Weeks/B{week:02d}-{arc.phase}.md",
            f"{arc.phase}周决定与证据",
            signal_content,
            False,
            None,
            ["relayforge", "decision", f"week-{week:02d}"],
            9,
        ),
        (
            f"doc-b{week:02d}-clip",
            f"00-Inbox/Clippings/B{week:02d}-未整理剪藏.md",
            f"未整理剪藏 · {arc.phase}",
            clip_content,
            True,
            "unread_clipping",
            ["read-later", "unverified"],
            2,
        ),
        (
            f"doc-b{week:02d}-daily",
            f"03-Daily/{base.date().isoformat()}.md",
            f"{base.date().isoformat()} 日记",
            daily_content,
            True,
            "daily_scratch",
            ["daily", "inbox"],
            12,
        ),
    )
    for doc_id, path, title, content, noise, noise_type, tags, event_index in specs:
        at = base + timedelta(days=event_index % 7, hours=event_index)
        docs.append(
            {
                "document_id": doc_id,
                "path": path,
                "title": title,
                "content": content,
                "frontmatter": {
                    "title": title,
                    "created": _iso(at),
                    "status": "current" if not noise else "unprocessed",
                    "week": week,
                    "synthetic": True,
                },
                "tags": tags,
                "links": [
                    {
                        "target": f"01-Projects/RelayForge/Weeks/B{max(1, week - 1):02d}",
                        "label": "上周",
                        "embedded": False,
                    }
                ],
                "created_at": _iso(at),
                "modified_at": _iso(at + timedelta(hours=3)),
                "metadata": {"batch_id": f"B{week:02d}"},
            }
        )
        builder.atom(
            source_type="document_library",
            source_ref=doc_id,
            text=content,
            is_noise=noise,
            noise_type=noise_type,
            event_id=_event_id(week, event_index),
            occurred_at=at,
        )
    return {
        "schema": "pneuma.source.document-library/v1",
        "provider": "mock",
        "library_id": f"relayforge-vault-b{week:02d}",
        "title": f"RelayForge Vault · B{week:02d}",
        "documents": docs,
        "metadata": {"batch_id": f"B{week:02d}", "note_count": len(docs)},
    }


def _im_source(
    builder: _Builder, *, week: int, arc: WeekArc, base: datetime
) -> dict[str, Any]:
    users = [
        {"user_id": "u-owner", "display_name": "沈砚", "email": "yan@relayforge.dev", "is_bot": False},
        {"user_id": "u-gu", "display_name": "顾清", "email": "gu@beichen.example", "is_bot": False},
        {"user_id": "u-tang", "display_name": "唐恬", "email": "tang@beichen.example", "is_bot": False},
        {"user_id": "u-luo", "display_name": "罗屿", "email": "luo@studio.example", "is_bot": False},
        {"user_id": "u-ci", "display_name": "CI Bot", "email": None, "is_bot": True},
        {"user_id": "u-billing", "display_name": "Billing Bot", "email": None, "is_bot": True},
    ]
    conversations: list[dict[str, Any]] = []
    signals = _signal_values(arc)
    for conv_index, (title, kind, members) in enumerate(
        (
            (
                f"cedar-week-{week:02d}",
                "channel",
                ["u-owner", "u-gu", "u-tang", "u-ci"],
            ),
            (
                f"relayforge-ops-{week:02d}",
                "group_dm",
                ["u-owner", "u-luo", "u-ci", "u-billing"],
            ),
        ),
        start=1,
    ):
        conversation_id = f"im-b{week:02d}-c{conv_index:02d}"
        messages: list[dict[str, Any]] = []
        signal_positions = {5, 11, 18, 25, 31} if conv_index == 1 else {8, 22, 33}
        signal_index = conv_index - 1
        thread_root = f"{conversation_id}-m005"
        for index in range(1, 35):
            message_id = f"{conversation_id}-m{index:03d}"
            at = base + timedelta(
                days=(index - 1) // 6,
                hours=1 + (index * 3 + conv_index) % 11,
                minutes=(index * 11) % 59,
            )
            if index in signal_positions:
                value = signals[signal_index % len(signals)]
                text = (
                    f"把这条落成可核对记录：{value}"
                    " 请在 thread 里指出来源或修改，不用只回一个表情。"
                )
                sender = members[(index + week) % max(1, len(members) - 1)]
                is_noise = False
                noise_type = None
                signal_index += 2
            else:
                noise_type, raw = IM_NOISE[(index * 3 + week + conv_index) % len(IM_NOISE)]
                text = (
                    f"{raw} 当前频道主题是「{arc.phase}」，"
                    "但这条消息没有形成新的范围、承诺或客户事实。"
                    "保留它是为了还原真实协作流：人们会确认、跑题、等待和改期，"
                    "并不是每次敲回车都在创造值得长期保存的知识。"
                )
                sender = (
                    "u-ci"
                    if noise_type.startswith("bot_")
                    else members[(index + conv_index) % len(members)]
                )
                is_noise = True
            message: dict[str, Any] = {
                "message_id": message_id,
                "sender_id": sender,
                "sent_at": _iso(at),
                "text": text,
                "thread_id": thread_root if index > 5 and index % 4 == 0 else None,
                "edited_at": _iso(at + timedelta(minutes=4)) if noise_type == "edited" else None,
                "reactions": (
                    [{"name": "eyes", "count": 2}]
                    if index % 9 == 0
                    else ([{"name": "white_check_mark", "count": 1}] if not is_noise else [])
                ),
                "metadata": {
                    "subtype": "bot_message" if sender in {"u-ci", "u-billing"} else "message"
                },
            }
            messages.append(message)
            builder.atom(
                source_type="im",
                source_ref=message_id,
                text=text,
                is_noise=is_noise,
                noise_type=noise_type,
                event_id=_event_id(week, 2 + ((index - 1) % 10)),
                occurred_at=at,
            )
        conversations.append(
            {
                "conversation_id": conversation_id,
                "conversation_type": kind,
                "title": title,
                "member_ids": members,
                "messages": messages,
                "metadata": {
                    "batch_id": f"B{week:02d}",
                    "purpose": arc.objective,
                },
            }
        )
    return {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": f"relayforge-im-b{week:02d}",
        "owner_user_ids": ["u-owner"],
        "users": users,
        "conversations": conversations,
        "metadata": {"batch_id": f"B{week:02d}", "provider_shape": "slack-export"},
    }


def _address(address: str, name: str) -> dict[str, str]:
    return {"address": address, "display_name": name}


def _email_source(
    builder: _Builder, *, week: int, arc: WeekArc, base: datetime
) -> dict[str, Any]:
    owner = _address("yan@relayforge.dev", "沈砚")
    customer = _address("gu@beichen.example", "顾清")
    ops = _address("notify@service.example", "Service Notifications")
    threads: list[dict[str, Any]] = []
    signal_values = (
        arc.current_decision,
        arc.guard_decision,
        arc.commitments[0],
        arc.constraints[0],
    )
    for thread_index in range(1, 3):
        thread_id = f"mail-b{week:02d}-t{thread_index:02d}"
        subject = (
            f"{arc.phase}：范围、证据与本周确认"
            if thread_index == 1
            else f"[自动通知] B{week:02d} 账单、日历与服务摘要"
        )
        messages: list[dict[str, Any]] = []
        previous: str | None = None
        references: list[str] = []
        for index in range(1, 5):
            message_id = f"<{thread_id}-m{index:02d}@relayforge.example>"
            at = base + timedelta(
                days=1 + index,
                hours=2 + thread_index * 2,
                minutes=index * 9,
            )
            if thread_index == 1 and index in {1, 3}:
                value = signal_values[index - 1]
                text = (
                    f"你好，\n\n本次需要明确确认的是：{value}\n\n"
                    f"本周里程碑为「{arc.milestone}」。请直接回复同意、修改或拒绝，"
                    "沉默不会被视为批准。\n\n"
                    "为方便回放，本邮件只引用稳定业务事实，不把会中猜测写成结论。\n\n"
                    "沈砚\nRelayForge"
                )
                is_noise = False
                noise_type = None
                from_ = owner if index == 1 else customer
                to = [customer if index == 1 else owner]
            else:
                noise_type, raw = EMAIL_NOISE[
                    (week + thread_index * 4 + index) % len(EMAIL_NOISE)
                ]
                repeated = "\n\n".join(
                    f"{raw}\n通知批次 {copy + 1}；若已处理请忽略，不需要回复。"
                    for copy in range(6)
                )
                text = (
                    f"您好，\n\n{repeated}\n\n"
                    f"当前邮件主题与「{arc.phase}」同周出现，但自动内容不代表客户决定。\n\n"
                    f"{EMAIL_NOISE[(index + 3) % len(EMAIL_NOISE)][1]}"
                )
                is_noise = True
                from_ = ops if thread_index == 2 else (customer if index % 2 == 0 else owner)
                to = [owner] if from_ == ops or from_ == customer else [customer]
            message = {
                "message_id": message_id,
                "sent_at": _iso(at),
                "from": from_,
                "to": to,
                "cc": [_address("archive@relayforge.dev", "Project Archive")]
                if index == 3
                else [],
                "subject": subject if index == 1 else f"Re: {subject}",
                "text": text,
                "in_reply_to": previous,
                "references": list(references),
                "attachments": (
                    [
                        {
                            "filename": f"B{week:02d}-scope.pdf",
                            "content_type": "application/pdf",
                            "size_bytes": 48231 + week,
                            "content_id": f"attach-b{week:02d}",
                        }
                    ]
                    if thread_index == 1 and index == 1
                    else []
                ),
                "metadata": {
                    "automated": thread_index == 2,
                    "batch_id": f"B{week:02d}",
                },
            }
            messages.append(message)
            builder.atom(
                source_type="email",
                source_ref=message_id,
                text=text,
                is_noise=is_noise,
                noise_type=noise_type,
                event_id=_event_id(week, 6 if thread_index == 1 else 7),
                occurred_at=at,
            )
            previous = message_id
            references.append(message_id)
        threads.append(
            {
                "thread_id": thread_id,
                "subject": subject,
                "messages": messages,
                "metadata": {
                    "batch_id": f"B{week:02d}",
                    "category": "customer" if thread_index == 1 else "automated",
                },
            }
        )
    return {
        "schema": "pneuma.source.email/v1",
        "provider": "mock",
        "archive_id": f"relayforge-mail-b{week:02d}",
        "owner_addresses": ["yan@relayforge.dev"],
        "threads": threads,
        "metadata": {"batch_id": f"B{week:02d}", "provider_shape": "rfc822"},
    }


def _stats(
    batches: list[ExperimentBatch], events: list[dict[str, Any]], atoms: list[dict[str, Any]]
) -> dict[str, Any]:
    meetings = documents = conversations = threads = messages = segments = 0
    for batch in batches:
        for contract in batch.contracts:
            match contract["schema"]:
                case "pneuma.source.meeting/v1":
                    meetings += 1
                    segments += len(contract["segments"])
                case "pneuma.source.document-library/v1":
                    documents += len(contract["documents"])
                case "pneuma.source.im/v1":
                    conversations += len(contract["conversations"])
                    messages += sum(
                        len(item["messages"]) for item in contract["conversations"]
                    )
                case "pneuma.source.email/v1":
                    threads += len(contract["threads"])
                    messages += sum(len(item["messages"]) for item in contract["threads"])
    chars = sum(item["char_count"] for item in atoms)
    noise_chars = sum(item["char_count"] for item in atoms if item["is_noise"])
    return {
        "day_count": 84,
        "batch_count": len(batches),
        "event_count": len(events),
        "normalized_source_units": meetings + documents + conversations + threads,
        "meetings": meetings,
        "meeting_segments": segments,
        "documents": documents,
        "im_conversations": conversations,
        "email_threads": threads,
        "messages": messages,
        "source_chars": chars,
        "atom_count": len(atoms),
        "noise_atoms": sum(item["is_noise"] for item in atoms),
        "noise_atom_ratio": sum(item["is_noise"] for item in atoms) / len(atoms),
        "noise_chars": noise_chars,
        "noise_char_ratio": noise_chars / chars,
    }


def build_opc_84d_dataset(seed: int = DEFAULT_SEED) -> Opc84dDataset:
    """Build the byte-stable dataset and its out-of-band quality/truth manifest."""

    builder = _Builder(seed)
    events = _make_events()
    batches: list[ExperimentBatch] = []
    for week, arc in enumerate(WEEK_ARCS, start=1):
        base = START + timedelta(days=(week - 1) * 7)
        contracts: list[dict[str, Any]] = [
            _meeting(
                builder,
                week=week,
                suffix="main",
                arc=arc,
                count=92 if week != 10 else 128,
                started_at=base + timedelta(days=1, hours=1, minutes=30),
            ),
            _documents(builder, week=week, arc=arc, base=base),
            _im_source(builder, week=week, arc=arc, base=base),
            _email_source(builder, week=week, arc=arc, base=base),
        ]
        if week in {4, 10}:
            contracts.insert(
                1,
                _meeting(
                    builder,
                    week=week,
                    suffix="risk",
                    arc=arc,
                    count=68 if week == 4 else 124,
                    started_at=base + timedelta(days=4, hours=7),
                ),
            )
        batches.append(
            ExperimentBatch(
                batch_id=f"B{week:02d}",
                started_at=_iso(base),
                ended_at=_iso(base + timedelta(days=6, hours=15, minutes=29)),
                contracts=tuple(contracts),
            )
        )

    ended = START + timedelta(days=83, hours=15, minutes=29)
    stats = _stats(batches, events, builder.atoms)
    manifest = {
        "schema": "pneuma.experiment.opc-84d/v1",
        "experiment_id": "opc-84d-relayforge",
        "user_id": "u-opc-ninghe",
        "display_name": "沈砚",
        "timezone": "Asia/Shanghai",
        "seed": seed,
        "started_at": _iso(START),
        "ended_at": _iso(ended),
        "story": {
            "product": "RelayForge",
            "mainline": "从问题验证到首个付费设计合作客户、邀请制发布与首月留存复盘。",
            "side_threads": ["open_source", "growth", "operations", "personal"],
            "week_phases": [arc.phase for arc in WEEK_ARCS],
        },
        "events": events,
        "atoms": builder.atoms,
        "truth": _truth_set(),
        "stats": stats,
    }
    return Opc84dDataset(seed=seed, manifest=manifest, batches=tuple(batches))
