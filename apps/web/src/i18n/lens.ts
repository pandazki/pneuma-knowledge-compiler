import { defineMessages } from "./define";

/**
 * The structure lens (route `#/lens`): the report the service derives over the whole
 * canonical library, read, and the same report at two refs, subtracted.
 *
 * VIEW CHROME ONLY. The sentences a finding is made of — what it costs, what to do — are
 * NOT here and must never be added: the report carries each of them already rendered in
 * both packs (`impact.text.en` / `.zh`, docs/design/structure-lens.md §3.2), and the console
 * shows its locale's. One catalog, one wording, every face; a second copy in this file would
 * be the one that drifts, and it would silently override an application that reworded a key
 * through the overlay seam.
 *
 * The keys that ARE looked up by a runtime string — `lens.level.<level>`, its `.note`, and
 * `lens.actor.<actor>` — go through `useTOr`, so a level or actor this build has never heard
 * of renders as itself rather than as a blank.
 *
 * Document titles, paths, family templates and evidence strings are canonical data and render
 * as they come.
 */
export const lens = defineMessages({
  zh: {
    "lens.description": "从外面读整座知识库的形状：一份派生的、无模型的报告，以及两次读数之间的差。",

    "lens.tab.aria": "结构透镜",
    "lens.tab.reading": "本次读数",
    "lens.tab.compare": "时间对比",

    "lens.empty.title": "还没有结构可读",
    "lens.empty.description":
      "这个知识库尚未编译——先去「导入」添加来源并编译，结构随正本一起产出。",
    "lens.empty.action": "去导入",
    "lens.loading": "正在读取结构报告……",
    "lens.error.title": "读不到结构报告",

    "lens.score.label": "结构分",
    "lens.score.meaning":
      "没有任何未决发现点到的主体，占全部主体的比例。它不是成绩，只用来看两次读数之间的移动。",
    "lens.readAt": "读于 {time}",
    "lens.counts": "{files} 个文件归并为 {subjects} 个主体 · {claims} 条断言 · {edges} 条内链。",

    "lens.headline.title": "先做这三件事",
    "lens.headline.clean": "没有发现：这座库的形状眼下没有越线的地方。",
    "lens.headline.rest": "另有 {count} 条发现，按层级列在下面。",

    "lens.level.principle": "原则",
    "lens.level.drift": "漂移",
    "lens.level.shape": "形制",
    "lens.level.principle.note": "整体布局的问题，改哪一页都不解决——由 Owner 裁定。",
    "lens.level.drift.note": "某一页没有做到契约对它这一族的期待，一次编译就能补上。",
    "lens.level.shape.note": "写入机制本该拒收的形态；引用门禁从此拒收新的，存量列在这里等修。",

    "lens.actor.steward": "Steward",
    "lens.actor.owner": "Owner",
    "lens.actor.mechanism": "机制",
    "lens.actor.aria": "面向 {actor}",

    "lens.group.count": "{count} 条",
    "lens.group.empty": "这一层没有发现。",
    "lens.group.expand": "展开「{level}」的 {count} 条发现",
    "lens.group.collapse": "收起「{level}」",

    "lens.pages.label": "涉及页",
    "lens.pages.more": "另 {count} 条",
    "lens.pages.fewer": "收起",
    "lens.targets.label": "牵涉",
    "lens.evidence.label": "依据",
    "lens.openDocument": "打开这篇文档",
    "lens.decision": "Steward 已回绝 · {reason} · {date}",

    "lens.families.title": "族均衡",
    "lens.families.note": "族由契约申报的路径模板定义；申报了却零页的族也留在表里。",
    "lens.families.name": "族",
    "lens.families.pages": "页数",
    "lens.families.claims": "断言",
    "lens.families.share": "断言份额",
    "lens.families.empty": "这份报告没有带回族名单。",

    /* ----------------------------------------------------------------- compare */

    "lens.compare.note": "同一副透镜，在两个 ref 上各读一次，相减。",
    "lens.compare.before": "基准",
    "lens.compare.after": "对照",
    "lens.compare.head": "HEAD · 实时",
    "lens.compare.run": "对比",
    "lens.compare.same": "两侧选的是同一个 ref。",
    "lens.compare.none": "这个知识库还没有可比的快照。",
    "lens.compare.loading": "正在读取两侧的结构报告……",
    "lens.compare.error": "读取失败",
    "lens.compare.countsTitle": "读数差",
    "lens.compare.metric": "读数",
    "lens.compare.findingsTitle": "发现的去向",
    "lens.compare.resolved": "已解决 · {count}",
    "lens.compare.added": "新出现 · {count}",
    "lens.compare.stillOpen": "仍未决 · {count}",
    "lens.compare.noFindingChange": "两侧的发现完全一致。",
    "lens.compare.bucketEmpty": "没有。",
    "lens.compare.edgesTitle": "新增内链",
    "lens.compare.edgesNote": "一条新内链只有配上写下它的那句话才说明问题，而那句话在正本投影里——所以这一节按需读取。",
    "lens.compare.edgesLoad": "列出新增内链",
    "lens.compare.edgesLoading": "正在读取两侧的正本投影……",
    "lens.compare.edgesError": "读不到正本投影",
    "lens.compare.noNewEdges": "没有新增内链。",
    "lens.compare.newEdgeMore": "另有 {count} 条新增内链未列出。",

    "lens.metric.score": "结构分 · 无发现主体占比 %",
    "lens.metric.subjects": "主体",
    "lens.metric.files": "文件",
    "lens.metric.claims": "断言",
    "lens.metric.edges": "内链",
  },
  en: {
    "lens.description":
      "The shape of the whole library, read from outside: a derived, model-free report, and the difference between two readings.",

    "lens.tab.aria": "Structure lens",
    "lens.tab.reading": "Reading",
    "lens.tab.compare": "Compare",

    "lens.empty.title": "No structure to read yet",
    "lens.empty.description":
      "This knowledge base has not been compiled — add a source under Ingest and compile it; the structure comes out with the canon.",
    "lens.empty.action": "Go to Ingest",
    "lens.loading": "Reading the structure report…",
    "lens.error.title": "Could not read the structure report",

    "lens.score.label": "Structure score",
    "lens.score.meaning":
      "Subjects with nothing to fix, as a share of all subjects. Not a grade — a number to watch between two readings.",
    "lens.readAt": "Read at {time}",
    "lens.counts":
      "{files} file{files||s} folded into {subjects} subject{subjects||s} · {claims} claim{claims||s} · {edges} internal link{edges||s}.",

    "lens.headline.title": "Three things to do first",
    "lens.headline.clean": "Nothing found: as it stands, nothing about this library's shape is over the line.",
    "lens.headline.rest": "{count} further finding{count||s}, by level below.",

    "lens.level.principle": "Principle",
    "lens.level.drift": "Drift",
    "lens.level.shape": "Shape",
    "lens.level.principle.note":
      "The layout is wrong in a way no single page fixes — the Owner's decision.",
    "lens.level.drift.note":
      "A page falls short of what the contract expects of its family; one ordinary round fixes it.",
    "lens.level.shape.note":
      "A form the write mechanism should have refused. The gate refuses new ones; these are the instances already on disk.",

    "lens.actor.steward": "Steward",
    "lens.actor.owner": "Owner",
    "lens.actor.mechanism": "Mechanism",
    "lens.actor.aria": "Addressed to {actor}",

    "lens.group.count": "{count} finding{count||s}",
    "lens.group.empty": "Nothing at this level.",
    "lens.group.expand": "Show the {count} finding{count||s} under {level}",
    "lens.group.collapse": "Hide {level}",

    "lens.pages.label": "Pages",
    "lens.pages.more": "+{count} more",
    "lens.pages.fewer": "Show fewer",
    "lens.targets.label": "Also involved",
    "lens.evidence.label": "Evidence",
    "lens.openDocument": "Open the document",
    "lens.decision": "Steward declined · {reason} · {date}",

    "lens.families.title": "Family balance",
    "lens.families.note":
      "Families are the path templates the contract declares; a declared family with no page stays in the table.",
    "lens.families.name": "Family",
    "lens.families.pages": "Pages",
    "lens.families.claims": "Claims",
    "lens.families.share": "Claim share",
    "lens.families.empty": "This report carried no family roster.",

    /* ----------------------------------------------------------------- compare */

    "lens.compare.note": "One lens, read at two refs, subtracted.",
    "lens.compare.before": "Baseline",
    "lens.compare.after": "Against",
    "lens.compare.head": "HEAD · live",
    "lens.compare.run": "Compare",
    "lens.compare.same": "Both sides name the same ref.",
    "lens.compare.none": "This knowledge base has no snapshot to compare against yet.",
    "lens.compare.loading": "Reading the report at both refs…",
    "lens.compare.error": "Could not read a report",
    "lens.compare.countsTitle": "Difference",
    "lens.compare.metric": "Reading",
    "lens.compare.findingsTitle": "Where the findings went",
    "lens.compare.resolved": "Resolved · {count}",
    "lens.compare.added": "New · {count}",
    "lens.compare.stillOpen": "Still open · {count}",
    "lens.compare.noFindingChange": "Both sides hold exactly the same findings.",
    "lens.compare.bucketEmpty": "None.",
    "lens.compare.edgesTitle": "New internal links",
    "lens.compare.edgesNote":
      "A new link says nothing without the claim that wrote it, and that sentence lives in the canonical projection — so this section is read on request.",
    "lens.compare.edgesLoad": "List the new links",
    "lens.compare.edgesLoading": "Reading both canonical projections…",
    "lens.compare.edgesError": "Could not read a canonical projection",
    "lens.compare.noNewEdges": "No new internal links.",
    "lens.compare.newEdgeMore": "{count} further new link{count||s} not listed.",

    "lens.metric.score": "Structure score · clean subjects %",
    "lens.metric.subjects": "Subjects",
    "lens.metric.files": "Files",
    "lens.metric.claims": "Claims",
    "lens.metric.edges": "Internal links",
  },
});
