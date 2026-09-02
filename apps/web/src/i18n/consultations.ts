import { defineMessages } from "./define";

/**
 * The use side: who is asking (`visitor.*`), what the readers have done with a page
 * (`access.*`), and the record of every answer this library gave (`consultations.*`).
 *
 * 「咨询」is the one rendering of *consultation* in this interface — the same word the
 * architecture and design pages use — and it is never spelled 问询 beside it. One word for
 * one thing, or a reader has to work out whether two names mean two records.
 *
 * `visitor.*` is now the LEDGER's vocabulary, not a control's: nothing beside a question
 * picks a class any more — the identity lens does (`nav.lens.*`, lib/lenses). What stays
 * here is what the records themselves are called when the owner reads them back, and
 * `audit` stays with them: no console lens writes an audit row, but an API caller does, and
 * a filter that cannot name a row the ledger holds is a filter with a blind spot.
 */
export const consultations = defineMessages({
  zh: {
    // --- who is asking -----------------------------------------------------------
    "visitor.business": "业务 · 留记录并计入热度",
    "visitor.audit": "审计 · 只留记录",
    "visitor.note":
      "记录方式只决定一次提问留下什么，不改变答案本身。「静默」不留任何痕迹，因此这份清单里没有它。在控制台上，记录方式由身份决定：所有者与访客都留记录并计入热度，无痕访客什么也不留；「审计」是 API 调用方的立场，不是坐在这台控制台前的人。",

    // --- the access card on a document -------------------------------------------
    "access.title": "访问情况",
    "access.note": "读取时从派生层联结出来，从不写进页面。",
    "access.lastAccessed": "最近访问",
    "access.hits7d": "7 天内",
    "access.hits30d": "30 天内",
    "access.heat": "热度",
    "access.hits": "{count} 次",
    "access.never": "尚无访问记录",
    "access.related": "查看相关咨询",
    "access.loading": "读取访问记录…",

    // --- the usage panel ---------------------------------------------------------
    "usage.title": "使用情况",
    "usage.window": "窗口 {since} 至 {until} · 热度每 {halfLife} 天减半",
    "usage.hotDocuments": "读得最多的页面",
    "usage.topMisses": "答不上来的问题",
    "usage.emptyHot": "这段窗口内没有页面被读到。",
    "usage.emptyMisses": "这段窗口内没有答不上来的问题。",
    "usage.spend": "这段窗口内记录了 {count} 次咨询，共花费",
    "usage.spendUnpriced": "（本部署未声明模型价格，只显示 token）",
    "usage.spendIncomplete":
      "（其中 {missing} 次没有报告用量，因此上面的 token 是下限，不给出金额）",
    "usage.missCount": "被问 {count} 次",
    "usage.missLastDay": "最近一次 {day}",
    "usage.days30": "近 30 天",
    "usage.days7": "近 7 天",
    "usage.days90": "近 90 天",
    "usage.daysAria": "选择统计窗口",

    // --- the consultations view ---------------------------------------------------
    "consultations.title": "咨询 Consultations",
    "consultations.ledger": "逐条记录",
    "consultations.description":
      "这座库每答一次的记录：问了什么、拿到哪一份库、摆到模型面前的每一个地址、答案，以及其中哪些被真正引用。逐字保留，绝不重新推导，也绝不是知识的权威。",
    "consultations.noUser.title": "先选一个画像",
    "consultations.noUser.description": "咨询记录按用户隔离，选定画像后才有可读的记录。",
    "consultations.empty.title": "还没有咨询记录",
    "consultations.empty.description":
      "以所有者或访客身份在检索或问答里问一个问题，这里就会出现它的记录。",
    "consultations.emptyFiltered.title": "没有符合筛选的咨询",
    "consultations.emptyFiltered.description": "换一个筛选条件，或清除当前的筛选。",
    "consultations.error.title": "读取咨询记录失败",
    "consultations.retry": "重试",

    "consultations.filter.lane": "通道",
    "consultations.filter.visitorClass": "记录方式",
    "consultations.filter.miss": "结果",
    "consultations.filter.all": "全部",
    "consultations.filter.missOnly": "只看落空",
    "consultations.filter.answeredOnly": "只看有据可答",
    "consultations.filter.target": "地址",
    "consultations.filter.targetClear": "清除地址筛选",
    "consultations.filter.clear": "清除全部筛选",

    "consultations.lane.fast": "fast",
    "consultations.lane.deep": "deep",
    "consultations.lane.briefing_ask": "briefing ask",
    "consultations.miss.badge": "落空",
    "consultations.total": "共 {count} 条",
    "consultations.loadMore": "加载更早的咨询",

    "consultations.detail.select": "选一条咨询来读它的证据链。",
    "consultations.detail.question": "问题",
    "consultations.detail.answer": "答案",
    "consultations.detail.noAnswer": "这次没有留下答案正文。",
    "consultations.detail.libraryRef": "回答所依据的库",
    "consultations.detail.asOf": "解析时点",
    "consultations.detail.evidence": "摆到模型面前的地址",
    "consultations.detail.cited": "被引用",
    "consultations.detail.handedOnly": "仅摆出",
    "consultations.detail.noEvidence": "这次没有任何地址进入模型。",
    "consultations.detail.evidenceNote":
      "引用是「摆出」的子集：只有解析后的地址确实在清单里，标记才会被采信。",
    "consultations.detail.degraded": "降级",
    "consultations.detail.openDocument": "打开这一页",
    "consultations.detail.openSpan": "打开原文",
    "consultations.detail.loading": "读取这条咨询…",
    "consultations.detail.error": "读取这条咨询失败",
  },
  en: {
    "visitor.business": "Business · recorded, counts as use",
    "visitor.audit": "Audit · recorded only",
    "visitor.note":
      "The class decides what a question leaves behind, never the answer itself. Silent leaves no trace at all, which is why it is not listed here. At this console the identity decides the class: owner and visitor are both recorded and count as use, a silent visitor leaves nothing, and audit is an API caller's stance rather than a person sitting here.",

    "access.title": "Access",
    "access.note": "Joined at read time out of the derived layer; never written into the page.",
    "access.lastAccessed": "Last read",
    "access.hits7d": "Last 7 days",
    "access.hits30d": "Last 30 days",
    "access.heat": "Heat",
    "access.hits": "{count} time{count||s}",
    "access.never": "No recorded access",
    "access.related": "Consultations that read this",
    "access.loading": "Reading access records…",

    "usage.title": "Use",
    "usage.window": "{since} to {until} · heat halves every {halfLife} day{halfLife||s}",
    "usage.hotDocuments": "Most-read pages",
    "usage.topMisses": "Questions answered with nothing",
    "usage.emptyHot": "No page was read in this window.",
    "usage.emptyMisses": "Nothing went unanswered in this window.",
    "usage.spend": "{count} recorded consultation{count||s} in this window, spending",
    "usage.spendUnpriced": "(this deployment declared no model prices — tokens only)",
    "usage.spendIncomplete":
      "({missing} of them reported no usage, so the tokens above are a floor and no amount is shown)",
    "usage.missCount": "asked {count} time{count||s}",
    "usage.missLastDay": "last on {day}",
    "usage.days30": "Last 30 days",
    "usage.days7": "Last 7 days",
    "usage.days90": "Last 90 days",
    "usage.daysAria": "Choose the window",

    "consultations.title": "Consultations",
    "consultations.ledger": "The records",
    "consultations.description":
      "One record per answer this library gave: the question, which library answered, every address the lane put in front of the model, the answer, and which of those it cited. Kept verbatim, never re-derived, and never an authority over knowledge.",
    "consultations.noUser.title": "Choose a profile first",
    "consultations.noUser.description":
      "Consultations are isolated per user; pick a profile to read its records.",
    "consultations.empty.title": "No consultations yet",
    "consultations.empty.description":
      "Ask something in Recall or Ask as the owner or a visitor, and its record appears here.",
    "consultations.emptyFiltered.title": "No consultation matches these filters",
    "consultations.emptyFiltered.description": "Change a filter, or clear them.",
    "consultations.error.title": "Could not read the consultations",
    "consultations.retry": "Retry",

    "consultations.filter.lane": "Lane",
    "consultations.filter.visitorClass": "Recorded as",
    "consultations.filter.miss": "Outcome",
    "consultations.filter.all": "All",
    "consultations.filter.missOnly": "Misses only",
    "consultations.filter.answeredOnly": "Answered only",
    "consultations.filter.target": "Address",
    "consultations.filter.targetClear": "Clear the address filter",
    "consultations.filter.clear": "Clear all filters",

    "consultations.lane.fast": "fast",
    "consultations.lane.deep": "deep",
    "consultations.lane.briefing_ask": "briefing ask",
    "consultations.miss.badge": "miss",
    "consultations.total": "{count} record{count||s}",
    "consultations.loadMore": "Load earlier consultations",

    "consultations.detail.select": "Pick a consultation to read its evidence chain.",
    "consultations.detail.question": "Question",
    "consultations.detail.answer": "Answer",
    "consultations.detail.noAnswer": "No answer text was recorded for this call.",
    "consultations.detail.libraryRef": "Library that answered",
    "consultations.detail.asOf": "Resolved against",
    "consultations.detail.evidence": "Addresses put in front of the model",
    "consultations.detail.cited": "cited",
    "consultations.detail.handedOnly": "handed over",
    "consultations.detail.noEvidence": "Nothing reached the model on this call.",
    "consultations.detail.evidenceNote":
      "Citations are a subset of what was handed over: a marker is admitted only when its resolved address is in the manifest.",
    "consultations.detail.degraded": "Degraded",
    "consultations.detail.openDocument": "Open this page",
    "consultations.detail.openSpan": "Open the source",
    "consultations.detail.loading": "Reading this consultation…",
    "consultations.detail.error": "Could not read this consultation",
  },
});
