import { defineMessages } from "./define";

/**
 * Evolve (DESIGN.md §5): the evolution timeline, the draft review bench, and the schema
 * accumulation axis.
 *
 * Two things deliberately live here rather than in the components:
 *   - the evolution STATUS vocabulary, because `lib/evolve.ts` is transpiled standalone by
 *     tests/evolve.test.mjs and therefore cannot import a translator — it returns keys,
 *     the views render them (an unknown status degrades to the raw status via `tOr`);
 *   - `evolve.listSeparator`, because the drift / proposal callouts join family names, and
 *     the separator is copy too (「、」 in Chinese, a comma in English).
 *
 * The zh column is the original hand-tuned copy, moved verbatim.
 */
export const evolve = defineMessages({
  zh: {
    "evolve.title": "演化 Evolve",
    "evolve.description": "演化时间线 · 审阅重组如何搬移断言（claim）、归属族与路径模板。",
    "evolve.descriptionShort": "演化提案的评审台与归属族累积轴。",
    "evolve.trigger": "触发演化",
    "evolve.readOnlyHint": "历史快照为只读",
    "evolve.listSeparator": "、",
    "evolve.evolutionOrdinal": "第 {n} 次演化",
    "evolve.decided": "决定 {at}",

    "evolve.tabs.aria": "演化视图",
    "evolve.tab.timeline": "时间线",
    "evolve.tab.timelineAwaiting": "时间线 · {count} 待审",
    "evolve.tab.schema": "Schema 快照轴",

    "evolve.noUser.title": "未选择用户",
    "evolve.noUser.description":
      "在右上角选择一个 user_id，以查看它的演化时间线与量身定制 skill。",

    "evolve.notice.queued": "已入队演化任务——worker 跑完后草案会出现在时间线顶端。",
    "evolve.notice.triggerFailed": "触发失败：{detail}",

    "evolve.status.draft": "草案待审",
    "evolve.status.adopted": "已采用",
    "evolve.status.dropped": "已放弃",
    "evolve.status.expired": "已过期",
    "evolve.status.aborted": "已中止",
    "evolve.status.no_change": "无变化",

    "evolve.ttl.expired": "已超评审窗口",
    "evolve.ttl.hoursMinutes": "剩约 {h}h{m}m",
    "evolve.ttl.minutes": "剩约 {m}m",
    "evolve.ttl.tooltip":
      "评审窗口 {hours}h，客户端按 created_at 推算（advisory），实际过期以服务端为准",

    "evolve.skill.loadFailed": "skill 加载失败",
    "evolve.timeline.loadFailed": "演化时间线加载失败",
    "evolve.timeline.empty.title": "暂无演化任务",
    "evolve.timeline.empty.description":
      "点右上角「触发演化」发起一次演化提案；草案会停在这里等待你的裁决。",
    "evolve.timeline.counts": "共 {total} 次 · 待审 {awaiting} · 已采用 {adopted} · 已否决 {declined}",
    "evolve.timeline.countsNoChange": "无变化 {count}",
    "evolve.timeline.noNewFamily": "未提出新 family",

    "evolve.scale.newDocuments": "新建 {count} 篇",
    "evolve.scale.moved": "搬移 {count} 条",
    "evolve.scale.merged": "合并 {count} 条",
    "evolve.scale.none": "无机械规模摘要",

    "evolve.detail.pickHint": "在左侧时间线选中一次演化查看详情。",
    "evolve.detail.loadFailed": "任务加载失败",
    "evolve.detail.title": "演化任务",
    "evolve.detail.created": "创建 {at}",
    "evolve.detail.proposedFamilies": "本次提议新增归属 family：",

    "evolve.action.adopt": "采用",
    "evolve.action.drop": "放弃",
    "evolve.action.cancel": "取消",
    "evolve.action.hint": "采用会把这次演化并回主线并重建 L3；放弃会删掉演化分支。",
    "evolve.action.adoptFailed": "采用失败：{detail}",
    "evolve.action.dropFailed": "放弃失败：{detail}",

    "evolve.section.rationale": "提案理由",
    "evolve.section.packs": "pack 草案 · {count}",
    "evolve.section.dropped": "消失的锚 · {count}",
    "evolve.section.summary": "机械摘要",
    "evolve.section.changedFiles": "变更文件 · {count}",

    "evolve.rationale.empty": "本任务没有留下提案自述。",

    "evolve.packs.empty": "本任务没有 pack 草案（无变化提案，或提案未通过模板校验）。",
    "evolve.packs.noInstructions": "未附 instructions。",
    "evolve.packs.noTemplates": "未附路径模板。",

    "evolve.dropped.awaiting": "待你裁决",
    "evolve.dropped.allKept": "锚全部保留",
    "evolve.dropped.empty":
      "这次演化没有让任何断言锚点消失——每一条都带原锚点搬到了新归属族。",
    "evolve.dropped.calloutTitle": "这是本次评审的重点",
    "evolve.dropped.calloutBody":
      "下面 {count} 条断言的锚点在新库里已找不到（被合并或删除）。锚点消失意味着 L3、事件与版次追溯中的引用链在这里断开，采用前请逐条确认这是你要的结果。",

    "evolve.stat.newDocuments": "新建文档",
    "evolve.stat.movedClaims": "搬移断言",
    "evolve.stat.mergedClaims": "合并断言",
    "evolve.summary.empty": "本任务无机械摘要。",
    "evolve.summary.adoptedCount": "收编 {count} 条",

    "evolve.files.emptyDraft": "本草案无文件级差异，或分支暂不可读。",
    "evolve.files.emptyDecided": "任务已决定、分支已回收——仅保留上方机械摘要。",
    "evolve.files.expand": "展开",
    "evolve.files.collapse": "收起",
    "evolve.file.created": "新建",
    "evolve.file.deleted": "删除",
    "evolve.file.modified": "改写",

    "evolve.technical": "技术记录",
    "evolve.drop.confirmTitle": "放弃这份草案？",
    "evolve.drop.confirmDescription": "将删除该演化分支并记为已放弃，操作不可撤销。",
    "evolve.drop.confirmAction": "确认放弃",
    "evolve.drop.confirmBody.before": "任务",
    "evolve.drop.confirmBody.after": "的草案与其分支将被丢弃。",

    "evolve.axis.station.base": "基线 skill",
    "evolve.axis.station.baseVersion": "基线 skill {version}",
    "evolve.axis.station.packs": "注册期定制 pack",
    "evolve.axis.station.pending": "第 {n} 次演化 · 待你裁决",

    "evolve.axis.currentSkill": "当前生效 skill",
    "evolve.axis.familyCount": "共 {total} 个，其中 {evolved} 个由演化加入",
    "evolve.axis.claimLabels": "断言标签词表 · {count}",
    "evolve.axis.labelAria": "{name}：{description}",

    "evolve.axis.stationsTitle": "累积轴 · {count} 刻度",
    "evolve.axis.notEnrolled": "尚未入册",
    "evolve.axis.driftedCount": "{count} 项已漂移",
    "evolve.axis.openTask": "查看这次演化",
    "evolve.axis.noNewFamily": "未新增 family。",
    "evolve.axis.driftedTitle": "当前 skill 里已找不到这个 family",
    "evolve.axis.driftTitle": "schema 漂移",
    "evolve.axis.driftBody":
      "这些 family 曾被采纳、但当前 skill 里已经查不到：{families}。轴上以删除线标出，未做任何补齐。",

    "evolve.axis.familiesTitle": "当前全量 family · {count}",
    "evolve.axis.noTemplates": "当前 skill 未声明任何路径模板——无法推导 family 一览。",
    "evolve.axis.groupCount": "{count} 个",
    "evolve.axis.proposedTitle": "待你裁决",
    "evolve.axis.proposedBody":
      "{families} 已被提议，但要等你在时间线上采用后才会进入 schema。",

    "evolve.origin.base": "基线",
    "evolve.origin.pack": "注册期 pack",
    "evolve.origin.evolved": "演化加入",
    "evolve.axis.originOrdinal": "第 {n} 次",
    "evolve.axis.originLink": "来源",
  },
  en: {
    "evolve.title": "Evolve",
    "evolve.description":
      "The evolution timeline · draft review (adopt / drop) · how families and path templates accumulate.",
    "evolve.descriptionShort":
      "The review bench for evolve proposals, and the family accumulation axis.",
    "evolve.trigger": "Trigger an evolution",
    "evolve.readOnlyHint": "A historical snapshot is read-only",
    "evolve.listSeparator": ", ",
    "evolve.evolutionOrdinal": "Evolution #{n}",
    "evolve.decided": "decided {at}",

    "evolve.tabs.aria": "Evolve views",
    "evolve.tab.timeline": "Timeline",
    "evolve.tab.timelineAwaiting": "Timeline · {count} awaiting",
    "evolve.tab.schema": "Schema axis",

    "evolve.noUser.title": "No user selected",
    "evolve.noUser.description":
      "Pick a user_id in the top right to see its evolution timeline and tailored skill.",

    "evolve.notice.queued":
      "Evolution task queued — once the worker finishes, the draft appears at the top of the timeline.",
    "evolve.notice.triggerFailed": "Trigger failed: {detail}",

    "evolve.status.draft": "Awaiting review",
    "evolve.status.adopted": "Adopted",
    "evolve.status.dropped": "Dropped",
    "evolve.status.expired": "Expired",
    "evolve.status.aborted": "Aborted",
    "evolve.status.no_change": "No change",

    "evolve.ttl.expired": "Past the review window",
    "evolve.ttl.hoursMinutes": "about {h}h{m}m left",
    "evolve.ttl.minutes": "about {m}m left",
    "evolve.ttl.tooltip":
      "A {hours}h review window; the client derives this from created_at (advisory) — actual expiry is the service's call",

    "evolve.skill.loadFailed": "Could not load the skill",
    "evolve.timeline.loadFailed": "Could not load the evolution timeline",
    "evolve.timeline.empty.title": "No evolution tasks yet",
    "evolve.timeline.empty.description":
      "Use “Trigger an evolution” in the top right to raise an evolve proposal; the draft waits here for your decision.",
    "evolve.timeline.counts":
      "{total} in all · {awaiting} awaiting · {adopted} adopted · {declined} declined",
    "evolve.timeline.countsNoChange": "{count} no change",
    "evolve.timeline.noNewFamily": "No new family proposed",

    "evolve.scale.newDocuments": "{count} document{count||s} created",
    "evolve.scale.moved": "{count} claim{count||s} moved",
    "evolve.scale.merged": "{count} claim{count||s} merged",
    "evolve.scale.none": "No mechanical scale summary",

    "evolve.detail.pickHint": "Select an evolution on the timeline to read its detail.",
    "evolve.detail.loadFailed": "Could not load the task",
    "evolve.detail.title": "Evolution task",
    "evolve.detail.created": "created {at}",
    "evolve.detail.proposedFamilies": "Filing families proposed here:",

    "evolve.action.adopt": "Adopt",
    "evolve.action.drop": "Drop",
    "evolve.action.cancel": "Cancel",
    "evolve.action.hint":
      "Adopting merges this evolution back into the mainline and rebuilds L3; dropping deletes the evolution branch.",
    "evolve.action.adoptFailed": "Adopt failed: {detail}",
    "evolve.action.dropFailed": "Drop failed: {detail}",

    "evolve.section.rationale": "Why this proposal",
    "evolve.section.packs": "Pack drafts · {count}",
    "evolve.section.dropped": "Anchors lost · {count}",
    "evolve.section.summary": "Mechanical summary",
    "evolve.section.changedFiles": "Changed files · {count}",

    "evolve.rationale.empty": "This task left no proposal statement.",

    "evolve.packs.empty":
      "This task has no pack draft (a no-change proposal, or one that failed template validation).",
    "evolve.packs.noInstructions": "No instructions attached.",
    "evolve.packs.noTemplates": "No path templates attached.",

    "evolve.dropped.awaiting": "Awaiting your call",
    "evolve.dropped.allKept": "Every anchor kept",
    "evolve.dropped.empty":
      "This evolution lost no claim anchor — every claim moved to its new family carrying its original anchor.",
    "evolve.dropped.calloutTitle": "This is what the review turns on",
    "evolve.dropped.calloutBody":
      "The anchors of the {count} claim{count||s} below are gone from the new library (merged or deleted). A lost anchor means the reference chain in L3, the journal and git blame breaks here; confirm one by one that this is what you want before adopting.",

    "evolve.stat.newDocuments": "New documents",
    "evolve.stat.movedClaims": "Claims moved",
    "evolve.stat.mergedClaims": "Claims merged",
    "evolve.summary.empty": "This task has no mechanical summary.",
    "evolve.summary.adoptedCount": "{count} taken in",

    "evolve.files.emptyDraft":
      "This draft has no file-level difference, or its branch is not readable right now.",
    "evolve.files.emptyDecided":
      "The task is decided and its branch reclaimed — only the mechanical summary above remains.",
    "evolve.files.expand": "Expand",
    "evolve.files.collapse": "Collapse",
    "evolve.file.created": "Created",
    "evolve.file.deleted": "Deleted",
    "evolve.file.modified": "Rewritten",

    "evolve.technical": "Technical record",
    "evolve.drop.confirmTitle": "Drop this draft?",
    "evolve.drop.confirmDescription":
      "The evolution branch will be deleted and the task recorded as dropped. This cannot be undone.",
    "evolve.drop.confirmAction": "Drop it",
    "evolve.drop.confirmBody.before": "The draft for task",
    "evolve.drop.confirmBody.after": "and its branch will be discarded.",

    "evolve.axis.station.base": "Baseline skill",
    "evolve.axis.station.baseVersion": "Baseline skill {version}",
    "evolve.axis.station.packs": "Registration-time packs",
    "evolve.axis.station.pending": "Evolution #{n} · awaiting your call",

    "evolve.axis.currentSkill": "Skill in force",
    "evolve.axis.familyCount": "{total} in all, {evolved} of them added by evolution",
    "evolve.axis.claimLabels": "Claim label vocabulary · {count}",
    "evolve.axis.labelAria": "{name}: {description}",

    "evolve.axis.stationsTitle": "Accumulation axis · {count} station{count||s}",
    "evolve.axis.notEnrolled": "Not yet enrolled",
    "evolve.axis.driftedCount": "{count} drifted",
    "evolve.axis.openTask": "Open this evolution",
    "evolve.axis.noNewFamily": "No family added.",
    "evolve.axis.driftedTitle": "The current skill no longer declares this family",
    "evolve.axis.driftTitle": "Schema drift",
    "evolve.axis.driftBody":
      "These families were adopted once, but the current skill no longer declares them: {families}. They are struck through on the axis; nothing has been filled in.",

    "evolve.axis.familiesTitle": "Families in force · {count}",
    "evolve.axis.noTemplates":
      "The current skill declares no path template — there is no family roster to derive.",
    "evolve.axis.groupCount": "{count} famil{count|y|ies}",
    "evolve.axis.proposedTitle": "Awaiting your call",
    "evolve.axis.proposedBody":
      "{families} have been proposed, but they only enter the schema once you adopt them on the timeline.",

    "evolve.origin.base": "Baseline",
    "evolve.origin.pack": "Registration pack",
    "evolve.origin.evolved": "Added by evolution",
    "evolve.axis.originOrdinal": "#{n}",
    "evolve.axis.originLink": "Source",
  },
});
