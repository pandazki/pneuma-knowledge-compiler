import { defineMessages } from "./define";

/**
 * The check (route `#/review`): the page-level findings a Steward can repair in a round of its
 * own, and the act that enqueues that round (docs/design/structure-lens.md §3).
 *
 * VIEW CHROME ONLY. What a finding COSTS and what to DO about it are not here and must never
 * be added: the report carries both already rendered in both packs (`impact.text.en` / `.zh`,
 * §5.1), and the console shows its locale's. The finding ids are not here either — `nav.dead_link`
 * is the name the Steward and `pkc library review` use for that fault, and translating it would
 * give the console a private vocabulary for something everybody else spells one way.
 *
 * `review.kind.<kind>` is looked up by a runtime string through `useTOr`, so a kind this build
 * has never heard of renders under its own name rather than as a blank.
 */
export const review = defineMessages({
  zh: {
    "review.description":
      "站在页面上、对着契约能看出来的问题：每条都指名页面、依据、代价和修它的动作。",

    "review.loading": "正在读取质检报告……",
    "review.error.title": "读不到质检报告",
    "review.empty.title": "还没有可质检的正本",
    "review.empty.description": "这座库尚未编译——先去「导入」添加来源并编译。",
    "review.empty.action": "去导入",
    "review.clean": "这份报告没有发现：眼下没有哪一页越过了契约的期待。",

    "review.readAt": "读于 {time}",
    "review.counts.findings": "{count} 条发现",
    "review.counts.base": "{files} 个文件归并为 {subjects} 个主体 · {claims} 条断言 · {edges} 条内链。",

    "review.kind.legacy": "存量",
    "review.kind.judgement": "判断",
    "review.kind.aria": "类别 {kind}",

    "review.page.library": "整座库",
    "review.page.count": "{count} 条",
    "review.pages.label": "另涉及",
    "review.pages.more": "另 {count} 条",
    "review.pages.fewer": "收起",
    "review.targets.label": "牵涉",
    "review.evidence.label": "依据",
    "review.openDocument": "打开这篇文档",

    "review.round.action": "跑一轮质检",
    "review.round.hint": "把这份报告作为任务，交给 Steward 跑一轮：能改的当场改，改不了的在纪要里说明。",
    "review.round.readOnlyHint": "钉住历史快照时不能入队。",
    "review.round.enqueued": "质检轮次已入队",
    "review.round.noJobId": "（服务端没有回传作业号）",
    "review.round.openJob": "去工序看这个作业",
    "review.round.failed": "入队失败",
  },
  en: {
    "review.description":
      "What an insider can see standing at the page, against the contract: each finding names its page, its evidence, what it costs and the verb that repairs it.",

    "review.loading": "Reading the check report…",
    "review.error.title": "Could not read the check report",
    "review.empty.title": "Nothing to check yet",
    "review.empty.description":
      "This knowledge base has not been compiled — add a source under Ingest and compile it.",
    "review.empty.action": "Go to Ingest",
    "review.clean": "Nothing found: as it stands, no page falls short of what the contract expects.",

    "review.readAt": "Read at {time}",
    "review.counts.findings": "{count} finding{count||s}",
    "review.counts.base":
      "{files} file{files||s} folded into {subjects} subject{subjects||s} · {claims} claim{claims||s} · {edges} internal link{edges||s}.",

    "review.kind.legacy": "Legacy",
    "review.kind.judgement": "Judgement",
    "review.kind.aria": "Kind: {kind}",

    "review.page.library": "The library as a whole",
    "review.page.count": "{count} finding{count||s}",
    "review.pages.label": "Also on",
    "review.pages.more": "+{count} more",
    "review.pages.fewer": "Show fewer",
    "review.targets.label": "Also involved",
    "review.evidence.label": "Evidence",
    "review.openDocument": "Open the document",

    "review.round.action": "Run a review round",
    "review.round.hint":
      "Hand this report to the Steward as one round's task: repair what a round can repair, and say in the brief what it left.",
    "review.round.readOnlyHint": "Nothing can be enqueued while a historical snapshot is pinned.",
    "review.round.enqueued": "The review round is queued",
    "review.round.noJobId": "(the service returned no job id)",
    "review.round.openJob": "Open it under Process",
    "review.round.failed": "Could not enqueue the round",
  },
});
