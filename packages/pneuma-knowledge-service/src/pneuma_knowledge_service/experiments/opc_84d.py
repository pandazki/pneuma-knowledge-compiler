"""Deterministic 84-day OPC work-life corpus over the four official source contracts.

The corpus is intentionally not a neat demo.  A single, explicit business story runs
through twelve weekly import batches while most atomic content is ordinary work exhaust:
meeting setup, repeated context, bot events, draft notes, quoted mail, newsletters, and
plans that never become decisions.  A separate manifest labels that exhaust and carries
the truth set; the source payloads themselves never announce which lines are noise.

NOTE ON LANGUAGE.  The corpus strings below are Chinese by design: they are synthetic
SOURCE DATA fed into the compiler as L0 material (a fictional studio, invented people, an
invented product), not framework prose, and they are this repository's only end-to-end
coverage of a CJK knowledge base.  The framework's own model-visible prose lives in
`pneuma_knowledge_core.prompts.catalog` and is English and business-neutral; a deployment
overlays its own language there.  Keep new corpus content synthetic, and never introduce
real captured material.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections import Counter, defaultdict
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
            "联合走查固定在每周三 15:00，顾清和唐恬参加。",
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


MEETING_NOISE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "small_talk",
        (
            "先等一下，还有人正在进会议室。我刚从雨里回来，耳机上都是水。",
            "我今天换了个房间，窗外施工有点响；听不清就直接打断我。",
            "早上地铁临时限流，我是踩着点到的，先缓半分钟再开始。",
            "顾清那边还在接电话，我们不用干等，先把议程顺序对一下。",
        ),
    ),
    (
        "audio_check",
        (
            "我刚才选成显示器麦克风了，现在切回耳机，回声应该没了。",
            "你们能听见键盘声吗？如果太明显我就改成按键发言。",
            "刚才那十秒没有录进去，我把最后一句重新说一遍。",
            "唐恬的声音有点断，先关一下视频试试，内容不用从头重讲。",
        ),
    ),
    (
        "screen_navigation",
        (
            "我共享错窗口了，这个是本地日志，不是准备给大家看的流程图。",
            "等一下，我在两个相同标题的标签页之间切反了，右边那个才是最新版。",
            "页面还停在昨天的缓存，我强制刷新一下；先别按这个数字记录。",
            "我把侧栏收起来，不然表格最后两列被遮住了，你们现在能看到吗？",
        ),
    ),
    (
        "disfluency",
        (
            "嗯，我收回刚才的“已经完成”，准确说是主路径跑通，边界还没验。",
            "这句我说得太绝对了，应该改成目前样本里观察到，不是普遍规律。",
            "我换个说法：不是功能不能做，而是这轮没有证据支持优先做。",
            "刚才把原因和结果说反了，日志只证明发生顺序，还不能证明因果。",
        ),
    ),
    (
        "repeated_context",
        (
            "这个背景老成员听过，新加入的人没听过，我只补两句必要上下文。",
            "上次我们停在这个分歧上，今天不重放整段，只说后来多了什么证据。",
            "我先复述已确认部分，避免大家拿不同版本继续讨论。",
            "这里和前一场会有重叠，但今天的材料时间更晚，状态可能已经变化。",
        ),
    ),
    (
        "scheduling",
        (
            "周三的走查我可能晚十分钟，先不要动邀请，下午我再给确定答复。",
            "下一个会贴得太近了，这个议题如果超时就挪到异步，不临时延长。",
            "客户那边还没确认时区，日历里的时间先保留 tentative。",
            "周五下午我有一段离线时间，行动项别都压到那个窗口。",
        ),
    ),
    (
        "tangent",
        (
            "顺便记一下，文档站搜索今天变慢了，但它不属于本次验收范围。",
            "我看到社区里有人讨论另一套索引，先放停车场，不在这里换技术路线。",
            "刚才弹出的账单提醒和这个故障没有关系，我会后单独处理。",
            "有个命名问题一直悬着，不过它不影响今天验证引用是否能回放。",
        ),
    ),
    (
        "speculation",
        (
            "这可能是缓存，也可能是旧索引，我还没看日志，先不要写成根因。",
            "我怀疑是时区偏移，但只有一条样本，结论至少要等第二个来源。",
            "这个现象看起来像权限问题，只是外观相似，证据还不够。",
            "也许用户是没看到入口，也许是没有需求；现在只能把两种解释都留着。",
        ),
    ),
    (
        "transcript_error",
        (
            "转写刚把产品名拆成了两个英文词，原音没问题，校对时再统一。",
            "这里的“删除”被识别成“筛选”，后面讨论的是数据删除请求。",
            "说话人标签串了，上一句是顾清说的，不是沈砚。",
            "数字的小数点没有进转写，先以共享屏幕为准，别从字幕抄数。",
        ),
    ),
    (
        "acknowledgement",
        (
            "收到，我先记下，不在这个话题中间展开，等对应议题再回。",
            "我理解你的担心了，先让当前问题走完，避免两个线程互相覆盖。",
            "可以，这条先标成待核对；没有异议不等于大家已经同意。",
            "看到了，我会后把原文链接补上，现在先不凭记忆复述。",
        ),
    ),
    (
        "recap_without_decision",
        (
            "目前两种方案各有支持者，但维护成本数据没齐，今天不做选择。",
            "我们确认了问题存在，还没有确认哪一种修法值得进入排期。",
            "这轮只排除了一个明显不成立的解释，剩下的方向仍然是开放的。",
            "大家对目标基本一致，对实现顺序没有一致意见，纪要要把两层分开。",
        ),
    ),
    (
        "break",
        (
            "已经连续说了快一小时，先停两分钟，回来只收行动项。",
            "我去接杯水，录制先不停；这段静音不要当成会议结束。",
            "我们休息一下，回来不再新增议题，只处理刚才留下的三个问号。",
            "后面还有十分钟，先做一次时间检查，次要问题全部转异步。",
        ),
    ),
)

IM_NOISE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ack", ("收到，晚点细看。", "看到了，先挂在这里。", "好，我补完手头这段再回。", "记下了，别把这个表情当批准。")),
    ("reaction_only", ("👍 已阅", "👀 我在看", "先点个眼睛，稍后回复", "✅ 只表示收到，不表示验收通过")),
    (
        "bot_build",
        (
            "CI bot：preview 已完成，单元测试通过。",
            "CI bot：文档预览部署成功，链接十五分钟后过期。",
            "CI bot：构建取消，原因是同一分支已有更新提交。",
            "CI bot：缓存未命中，本轮比平时多用了两分钟。",
        ),
    ),
    (
        "bot_dependency",
        (
            "依赖机器人开了一个 patch 更新，尚未进入排期。",
            "安全扫描没有新增高危项，报告已归档。",
            "自动更新检查到锁文件变化，需要人工确认后再合并。",
            "许可证扫描完成，有一项元数据等待维护者复核。",
        ),
    ),
    (
        "reschedule",
        (
            "我前一个会拖延了，原定时间往后顺十分钟可以吗？",
            "客户临时改期，今天的同步先取消，材料照常留在 thread。",
            "明早那段我冲突了，下午三点或四点都可以。",
            "先别动日历，我等外部协作者回完再发新邀请。",
        ),
    ),
    (
        "link_only",
        (
            "先存一个还没读的链接：https://example.invalid/read-later",
            "这个文档可能相关，我只看了标题：https://example.invalid/draft",
            "把参考页放这，暂时不代表采用：https://example.invalid/reference",
            "稍后阅读：https://example.invalid/inbox ，目前没有摘要。",
        ),
    ),
    (
        "casual",
        (
            "咖啡机又提示缺水，我刚才还以为是监控告警。",
            "今天楼下施工有点吵，我下午换个地方开会。",
            "外面突然下雨，快递可能要晚一点到。",
            "午饭回来我会离线半小时，紧急事项电话找我。",
        ),
    ),
    (
        "thread_misalignment",
        (
            "回错 thread 了，这里讨论文档示例，不是线上事故。",
            "上一条应该发到采购串，我不在这里继续回复。",
            "这段上下文属于另一个客户，我撤回后重新贴。",
            "串线了；本条只纠正位置，不改变原来的决定。",
        ),
    ),
    (
        "edited",
        (
            "更正：我写成周四了，实际是周五下午。",
            "上条少了一个“不”字，我已经编辑，结论以新文本为准。",
            "刚才贴的是旧链接，已换成带日期的版本。",
            "名字拼错了，内容不变，我只修正显示名称。",
        ),
    ),
    (
        "status_churn",
        (
            "先从 doing 退回 todo，依赖没到，不是取消。",
            "这张卡暂时 blocked，等对方补样本后再开。",
            "我把优先级降一级，今天先处理引用回放故障。",
            "状态改回待确认；刚才的完成标记点早了。",
        ),
    ),
)

EMAIL_NOISE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "signature",
        (
            "此邮件从移动设备发出，排版可能与桌面版不同。",
            "我正在外出，只能先确认收到，详细意见稍后补。",
            "以下联系信息来自通用签名，不构成项目范围条款。",
            "邮件签名由客户端自动附加，请以正文中的明确回复为准。",
        ),
    ),
    (
        "quoted_reply",
        (
            "附上上周的历史回复供定位；其中的时间已经失效，请勿直接排期。",
            "下方引用来自旧线程，只用于解释前因后果，不代表当前批准。",
            "客户端自动带出了上一封全文，新的答复只有顶部两段。",
            "这段报价来自草稿版本，最终金额仍要看已签署文件。",
        ),
    ),
    (
        "calendar_update",
        (
            "日历系统已刷新视频链接，会议标题和参与人没有变化。",
            "一名参与人提议了新时间，邀请仍处于待确认状态。",
            "会议室发生冲突，线上链接保留，实体地点暂时移除。",
            "系统检测到时区差异，请在接受邀请前核对本地时间。",
        ),
    ),
    (
        "newsletter",
        (
            "本周产品通讯包含增长文章、模板下载和三场线上活动。",
            "社区周报汇总了热门讨论；它们没有经过本项目的证据审查。",
            "自动简报推荐了几篇定价文章，推荐不等于适用于当前客户。",
            "订阅摘要列出新工具发布，正文没有本周试点的状态更新。",
        ),
    ),
    (
        "delivery_notice",
        (
            "投递系统报告一名抄送人暂时不可达，其他收件人已接收。",
            "附件扫描仍在进行，正文已经投递，稍后会补发结果。",
            "邮件网关延迟了外部收件人队列，当前不需要重复发送。",
            "归档地址拒收了过大的附件，客户地址未受影响。",
        ),
    ),
    (
        "out_of_office",
        (
            "自动回复：我今天下午不在电脑前，紧急事项请走既有支持渠道。",
            "自动回复：本周出差，邮件会延迟处理，不会自动转发。",
            "休假提示：下周一恢复，期间请不要把未回复视为默认同意。",
            "外出提示：只能偶尔查看手机，审批事项将在返回后处理。",
        ),
    ),
    (
        "vendor_marketing",
        (
            "供应商邀请升级年度方案；该活动报价与现有试点采购无关。",
            "营销邮件提供额外额度，但没有包含迁移成本和退出条件。",
            "合作伙伴推荐了付费培训，这不是当前交付所需服务。",
            "限时折扣将在月底结束；采购决策仍需走现有评审。",
        ),
    ),
    (
        "legal_footer",
        (
            "本邮件可能包含保密信息；误收时请删除，不要继续转发。",
            "通用保密页脚不修改双方已经确认的范围和责任。",
            "附件版权归原作者所有，邮件转发不授予额外使用权。",
            "安全提示：请从既有渠道核验付款账户变更，不要只依赖邮件。",
        ),
    ),
)

MEETING_CONTEXT = (
    "这只是现场协调，不改变已经确认的范围。",
    "先让当前发言说完，待会儿再回到证据列表。",
    "纪要里保留这个插曲即可，不需要把它提升成行动项。",
    "如果会后没有新的书面确认，状态仍保持待核对。",
    "这段和客户交付无关，但能解释为什么中间停了几分钟。",
    "我先在停车场记一行，今天不为它切换主线。",
    "下一位先接着讲，不用重复刚才整段背景。",
    "等共享材料打开后再判断，现在不凭记忆补内容。",
    "这里没有形成结论，转写保留原话就够了。",
    "把事实、猜测和日程调整分开写，避免会后看成一件事。",
    "这场会只处理眼前的验收问题，旁支留到异步。",
    "暂时不更新任务状态，等对应负责人明确回复。",
)

IM_CONTEXT = (
    "跟{phase}的主决定无关，先留在{channel}里。",
    "{phase}阶段先在{weekday}再回来看；现在没有需要同步给客户的变化。",
    "等{person}补完{phase}的上下文，我再给完整回复。",
    "这条只说明{phase}期间{artifact}的处理进度，不代表范围更新。",
    "先放进收件箱，今天的主线仍是{milestone}。",
    "{phase}的会后再整理，当前不需要其他人停下手头工作。",
    "{phase}没有新的证据，状态继续保持待确认。",
    "这只是{phase}阶段的协作过程，别从短回复推断审批结果。",
    "如果今天没继续跟进，就顺延到{phase}的下一次集中处理。",
    "{phase}相关原文还没找到，先别把记忆里的版本转述给客户。",
    "我只处理了{phase}期间的通知，业务事项仍由原负责人确认。",
    "先把{phase}相关的链接和时间留住，是否采用要等正式讨论。",
)

DOCUMENT_LEADS = (
    "{day}早上清理收件箱时，",
    "为准备{phase}阶段的下一次走查，",
    "从{customer}最近提供的材料回看，",
    "午后重新打开这条记录时，",
    "在关闭编辑器之前，",
    "本周第二次整理这个主题时，",
    "从会议逐字稿回到文档后，",
    "把工作和个人收件箱分开以后，",
    "晚间复盘注意力切换时，",
    "准备把草稿移入归档前，",
    "对照上一版决定记录时，",
    "在没有新增证据的情况下，",
)

DOCUMENT_MIDDLES = {
    "process": (
        "我只补齐来源和待确认点，没有替缺失材料写结论。",
        "这次修改保留了原来的语气，推断仍放在单独位置。",
        "相同说法出现在不同渠道，但各自的时间与上下文仍需保留。",
        "当前能确认的是处理动作，不是客户已经接受结果。",
        "我把口头意见和可验收条件拆开，避免两者在摘要里粘连。",
        "旧版本没有被覆盖，而是作为已经失效的想法继续可回放。",
        "这条内容先进入待核对区，等会后邮件给出明确状态。",
        "正文没有增加新范围，只修正了一个容易误读的表达。",
    ),
    "clipping": (
        "原链接仍在待读区，标题和转述都不能充当证据。",
        "它看起来与当前产品相近，但样本、预算和客户类型都不同。",
        "我只记录了为什么收藏，没有把文章观点并入路线图。",
        "评论区很热闹，正文却没有能复核的数据口径。",
        "这个案例可能值得访谈追问，目前还不能改变优先级。",
        "作者省略了实施成本，因此这里继续标为未核验。",
        "它触发了一个问题，但没有给出可直接采用的答案。",
        "先保留出处；若后续没有客户材料支持，就在周末清理掉。",
    ),
    "daily": (
        "它没有改变今天的主任务，只造成了几次注意力切换。",
        "我当时只记了一句话，晚些时候也没有形成新的决定。",
        "这件事更像生活维护，不需要进入产品知识。",
        "处理完成后没有后续动作，留在日记里就足够了。",
        "情绪和疲劳影响了节奏，所以没有在晚上做范围判断。",
        "临时想法先经过一晚，第二天仍重要再进入项目文档。",
        "我关掉通知后继续工作，没有把忙碌误写成进展。",
        "今天的产出很小，但至少没有制造未经确认的承诺。",
    ),
}

DOCUMENT_CLOSINGS = (
    "下一次处理必须先回到原文，而不是沿用这次印象。",
    "如果状态变化，需要新的日期和明确责任人。",
    "这条记录到此结束，不自动生成后续任务。",
    "周末只决定是否继续关注，不改写它当时的不确定性。",
    "没有新的书面确认前，现状保持不变。",
    "后续若引用它，应同时带上来源位置和发生时间。",
    "这次整理的目的只是恢复上下文，不是增加材料体量。",
    "等真正进入排期时，再补验收条件和退出标准。",
    "即使它再次出现，也不会因为重复而增加证据强度。",
    "我把它留给未来的自己，而不是当作已经完成的工作。",
)

EMAIL_CONTEXT = (
    "该系统消息与{phase}同周出现，但不包含客户批准。",
    "若需要确认{milestone}，请回到原始客户线程。",
    "这封邮件只报告投递或日程状态，不改变项目范围。",
    "请不要因为自动邮件重复出现就提高它的证据权重。",
    "归档时保留 Message-ID 和时间，正文无需转成行动项。",
    "与{customer}有关的决定仍以明确书面答复为准。",
    "该内容可以帮助解释时间线，但不能证明交付完成。",
    "如果通知与人工回复冲突，先隔离并请求发件人确认。",
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
    used_noise_texts: set[str] = set()
    session_label = "客户周走查" if suffix == "main" else "发布与风险复盘"
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
                "对照原始材料后，目前可以稳定写下的是：",
                "这一条请保留发生时间，内容是：",
                "旧说法先不要覆盖；这次明确更新为：",
                "为了让下次走查可以直接回放，我记录为：",
            )
            closings = (
                "如果有人不同意，请现在指出具体来源。",
                "会后邮件只确认这句话，不顺带扩张范围。",
                "负责人和日期继续按行动项单独记录。",
                "这条进入纪要，其他讨论仍留在待核对区。",
                "后续若状态变化，需要新的书面记录。",
                "我会把引用位置补在同一句后面。",
            )
            text = (
                f"{speaker_names[speaker_id]}："
                f"{builder.rng.choice(prefixes)}{value}"
                f"{builder.rng.choice(closings)}"
            )
            is_noise = False
            noise_type = None
            signal_index += 1
        else:
            noise_type, variants = MEETING_NOISE[
                (index * 5 + week) % len(MEETING_NOISE)
            ]
            scope_variants = (
                f"在{arc.phase}阶段的{session_label}里，",
                f"今天主议题仍是{arc.objective}；",
                f"围绕“{arc.milestone}”这项里程碑，",
                f"在{arc.phase}阶段，就{arc.customer}这次{session_label}而言，",
            )
            for _ in range(40):
                candidate = (
                    f"{speaker_names[speaker_id]}：{builder.rng.choice(variants)}"
                    f"{builder.rng.choice(scope_variants)}"
                    f"{builder.rng.choice(MEETING_CONTEXT)}"
                )
                if candidate not in used_noise_texts:
                    text = candidate
                    used_noise_texts.add(candidate)
                    break
            else:  # combination space is intentionally much larger than one meeting
                raise RuntimeError(f"meeting noise variation exhausted for {meeting_id}")
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


def _expanded_paragraphs(
    builder: _Builder,
    lines: Iterable[str],
    *,
    rounds: int,
    mode: str,
    phase: str,
    customer: str,
    day: str,
) -> str:
    source = tuple(lines)
    paragraphs: list[str] = []
    used: set[str] = set()
    for index in range(rounds):
        value = source[index % len(source)]
        context = {"day": day, "phase": phase, "customer": customer}
        for _ in range(60):
            lead = builder.rng.choice(DOCUMENT_LEADS).format(**context)
            middle = builder.rng.choice(DOCUMENT_MIDDLES[mode])
            closing = builder.rng.choice(DOCUMENT_CLOSINGS)
            paragraph = f"{lead}{value.rstrip('。！？')}。{middle}{closing}"
            if paragraph not in used:
                used.add(paragraph)
                paragraphs.append(paragraph)
                break
        else:
            raise RuntimeError(f"document variation exhausted for {phase}/{mode}")
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
            builder,
            (
                "先把能直接回到原文的句子列出来，再将推断放到单独小节。",
                "同一个结论在会议、消息和邮件中出现时，保留各自时间与语气差异。",
                "没有明确确认的事项继续留在待验证区，不把重复出现当作事实。",
                "周末复盘只改变优先级，不回写或美化原始来源。",
            ),
            rounds=8 + week % 4,
            mode="process",
            phase=arc.phase,
            customer=arc.customer,
            day=base.date().isoformat(),
        )
    )
    clip_content = (
        f"# 未整理剪藏 · {arc.phase}\n\n"
        f"tags: #read-later #unverified\n\n"
        + _expanded_paragraphs(
            builder,
            (
                "有人说所有 B2B 产品都应该先做团队权限，但这篇帖子没有数据来源。",
                "收藏了一篇增长文章，只看了标题；里面的漏斗数字不适用于当前客户。",
                arc.negative_controls[0],
                "一段关于品牌命名的讨论很热闹，但没有任何设计合作客户参与。",
                "把三个可能的首页文案放在这里，顺序随机，暂时不选。",
                "外部案例声称一天获得上千注册，未核验渠道、预算或转化定义。",
            ),
            rounds=14 + week % 5,
            mode="clipping",
            phase=arc.phase,
            customer=arc.customer,
            day=base.date().isoformat(),
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
            builder,
            (
                "上午切换了太多窗口，几次忘记刚才为什么打开日志。",
                "想到一个功能名字又觉得太像别的产品，先不做任何设计。",
                "社区里有人推荐另一套技术栈，看起来有趣，但迁移成本完全没算。",
                "晚上状态一般，只修了两个小错误，没有形成需要长期保存的结论。",
            ),
            rounds=8 + (week * 2) % 5,
            mode="daily",
            phase=arc.phase,
            customer=arc.customer,
            day=base.date().isoformat(),
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
    used_noise_texts: set[str] = set()
    weekdays = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    artifacts = (
        "预览构建",
        "会议邀请",
        "导入样本",
        "引用清单",
        "问题列表",
        "支持收件箱",
        "依赖更新",
        "归档线程",
    )
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
                signal_openers = (
                    "把这条落成可核对记录：",
                    "对照今天的原文，我确认目前版本是：",
                    "这不是表情确认，完整状态写在这里：",
                    "为免下次从头追 thread，当前可以写成：",
                )
                signal_closings = (
                    "请在 thread 里指出来源或修改。",
                    "如果表述不准，直接引用原句纠正。",
                    "这条之外没有新增承诺。",
                    "后续变化另开带日期的回复。",
                )
                text = (
                    f"{builder.rng.choice(signal_openers)}{value}"
                    f"{builder.rng.choice(signal_closings)}"
                )
                sender = members[(index + week) % max(1, len(members) - 1)]
                is_noise = False
                noise_type = None
                signal_index += 2
            else:
                noise_type, variants = IM_NOISE[
                    (index * 3 + week + conv_index) % len(IM_NOISE)
                ]
                context = {
                    "phase": arc.phase,
                    "channel": title,
                    "weekday": weekdays[(index - 1) // 6 % len(weekdays)],
                    "person": users[(index + week) % 4]["display_name"],
                    "artifact": artifacts[(index * 3 + week) % len(artifacts)],
                    "milestone": arc.milestone,
                }
                for _ in range(40):
                    candidate = (
                        f"{builder.rng.choice(variants)} "
                        f"{builder.rng.choice(IM_CONTEXT).format(**context)}"
                    )
                    if candidate not in used_noise_texts:
                        text = candidate
                        used_noise_texts.add(candidate)
                        break
                else:
                    raise RuntimeError(f"IM noise variation exhausted for B{week:02d}")
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
    greetings = (
        "顾清，你好，",
        "沈砚，你好，",
        "各位好，",
        "你好，补充一条，",
        "收到上一封邮件，",
        "接着刚才的线程，",
    )
    evidence_notes = (
        "为方便回放，这封邮件只写可定位到原始材料的内容。",
        "会中猜测没有写进下面的确认项，避免它看起来像结论。",
        "如果正文与附件不一致，请直接回复差异位置。",
        "本次确认不覆盖旧邮件，后续仍可查看变化前的版本。",
        "请不要从未回复推断同意；需要明确的同意、修改或拒绝。",
        "引用位置会随归档一起保留，转述不能替代原文。",
    )
    signoffs = (
        "谢谢\n沈砚",
        "先到这里\n沈砚",
        "等你的明确回复\n沈砚",
        "祝好\n沈砚",
        "收到后请直接标注修改处\n沈砚",
        "会后见\n沈砚",
    )
    system_openings = (
        "您好，以下是本次自动状态摘要。",
        "系统通知：这是一封无需直接回复的状态邮件。",
        "收件箱提醒：以下信息由服务自动生成。",
        "归档通知：系统记录了一次投递或日程变化。",
        "服务摘要：请先核对时间，再决定是否需要人工处理。",
        "自动消息：本邮件用于解释收件箱里的状态变化。",
    )
    response_instructions = (
        "回复时请保留原主题，并明确写出同意、修改或拒绝。",
        "若有异议，请指出对应原文；没有回复不会被当作默认接受。",
        "请只确认你能够承诺的部分，其余内容继续标为待核对。",
        "如需调整，请同时给出新表述和可接受的完成时间。",
        "这次只收书面确认，不把会中口头倾向升级为决定。",
        "请在原线程中回复，避免脱离上下文转发一句结论。",
    )
    delivery_notes = (
        "若你已经处理，无需为了这封自动消息重复操作。",
        "该通知会随线程归档，回复不会发送给机器人。",
        "系统稍后可能再发状态更新，请以最新时间戳为准。",
        "需要人工判断时，请转到原项目线程，不在本邮件中审批。",
        "这条记录只用于解释收件箱时间线。",
        "无需转发；相关负责人已能在原系统看到状态。",
    )
    message_positions = ("首次来信", "第一次回复", "补充确认", "收尾回复")
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
            position = message_positions[index - 1]
            thread_label = "客户确认线程" if thread_index == 1 else "服务通知线程"
            at = base + timedelta(
                days=1 + index,
                hours=2 + thread_index * 2,
                minutes=index * 9,
            )
            if thread_index == 1 and index in {1, 3}:
                value = signal_values[index - 1]
                text = (
                    f"{builder.rng.choice(greetings)}这封{position}来自{arc.phase}阶段的"
                    f"{thread_label}，需要明确确认的是：{value}\n\n"
                    f"在这次{position}发出时，本周工作里程碑是{arc.milestone}。"
                    f"{builder.rng.choice(evidence_notes)}\n\n"
                    f"{builder.rng.choice(response_instructions)}"
                    f"这项{position}确认关系到{arc.customer}后续如何安排，"
                    "请不要脱离当前线程转述。"
                    f"\n{builder.rng.choice(signoffs)}"
                )
                is_noise = False
                noise_type = None
                from_ = owner if index == 1 else customer
                to = [customer if index == 1 else owner]
            else:
                noise_type, variants = EMAIL_NOISE[
                    (week + thread_index * 4 + index) % len(EMAIL_NOISE)
                ]
                _, secondary_variants = EMAIL_NOISE[
                    (week + thread_index * 2 + index + 3) % len(EMAIL_NOISE)
                ]
                context = builder.rng.choice(EMAIL_CONTEXT).format(
                    phase=arc.phase,
                    milestone=arc.milestone,
                    customer=arc.customer,
                )
                from_ = (
                    ops
                    if thread_index == 2
                    else (customer if index % 2 == 0 else owner)
                )
                opening = (
                    builder.rng.choice(system_openings)
                    if from_ == ops
                    else builder.rng.choice(greetings)
                )
                text = (
                    f"{opening}{builder.rng.choice(variants)}"
                    f"它是{arc.phase}阶段{thread_label}中的{position}，"
                    f"与当周正在推进的{arc.objective}并不是同一件事。\n\n"
                    f"{context}在这封{position}归档时，当前业务里程碑仍然是"
                    f"{arc.milestone}，"
                    f"若两边状态看起来冲突，应先回到{arc.customer}的人工往来核对。\n\n"
                    f"{builder.rng.choice(secondary_variants)}"
                    f"{builder.rng.choice(delivery_notes)}"
                    f"归档时把这封{position}保留为{arc.phase}期间的通信噪声，"
                    "不要从通知频率推断工作已经完成。"
                )
                is_noise = True
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


def _normalized_visible_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _template_shape(text: str) -> str:
    normalized = _normalized_visible_text(text).lower()
    normalized = re.sub(r"https?://\S+", "<url>", normalized)
    normalized = re.sub(r"[\w.+-]+@[\w.-]+", "<email>", normalized)
    normalized = re.sub(r"「[^」]*」", "「<topic>」", normalized)
    normalized = re.sub(
        r"\b(?:b|week|evt|doc|rf|im|mail)[-_]?\d[\w.-]*\b",
        "<id>",
        normalized,
    )
    return re.sub(r"\d+(?:[.:/-]\d+)*", "<n>", normalized)


def _source_repetition_metrics(
    batches: list[ExperimentBatch],
) -> dict[str, dict[str, float | int]]:
    fragments: dict[str, list[str]] = defaultdict(list)
    for batch in batches:
        for contract in batch.contracts:
            match contract["schema"]:
                case "pneuma.source.meeting/v1":
                    fragments["meeting"].extend(
                        segment["text"] for segment in contract["segments"]
                    )
                case "pneuma.source.document-library/v1":
                    for document in contract["documents"]:
                        fragments["document_library"].extend(
                            paragraph
                            for paragraph in re.split(
                                r"\n\s*\n", document["content"]
                            )
                            if _normalized_visible_text(paragraph)
                        )
                case "pneuma.source.im/v1":
                    for conversation in contract["conversations"]:
                        fragments["im"].extend(
                            message["text"] for message in conversation["messages"]
                        )
                case "pneuma.source.email/v1":
                    for thread in contract["threads"]:
                        for message in thread["messages"]:
                            fragments["email"].extend(
                                paragraph
                                for paragraph in re.split(
                                    r"\n\s*\n", message["text"]
                                )
                                if _normalized_visible_text(paragraph)
                            )

    metrics: dict[str, dict[str, float | int]] = {}
    for source_type, values in fragments.items():
        exact = Counter(_normalized_visible_text(value) for value in values)
        templates = Counter(_template_shape(value) for value in values)
        prose_values = (
            [
                value
                for value in values
                if not _normalized_visible_text(value).startswith("#")
                and not _normalized_visible_text(value).lower().startswith("tags:")
            ]
            if source_type == "document_library"
            else values
        )
        prose_exact = Counter(
            _normalized_visible_text(value) for value in prose_values
        )
        prose_templates = Counter(_template_shape(value) for value in prose_values)
        metrics[source_type] = {
            "fragments": len(values),
            "exact_duplicate_excess_ratio": sum(
                count - 1 for count in exact.values()
            )
            / len(values),
            "template_duplicate_excess_ratio": sum(
                count - 1 for count in templates.values()
            )
            / len(values),
            "prose_fragments": len(prose_values),
            "prose_exact_duplicate_excess_ratio": sum(
                count - 1 for count in prose_exact.values()
            )
            / len(prose_values),
            "prose_template_duplicate_excess_ratio": sum(
                count - 1 for count in prose_templates.values()
            )
            / len(prose_values),
        }
    return dict(sorted(metrics.items()))


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
        "visible_repetition": _source_repetition_metrics(batches),
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
