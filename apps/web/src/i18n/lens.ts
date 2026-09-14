import { defineMessages } from "./define";

/**
 * The structure lens (route `#/lens`): six dimensions read over the whole canonical library,
 * each with a band, a statement, a few metrics carrying their movement, and a direction.
 *
 * VIEW CHROME ONLY. The sentences a dimension is made of — its statement and its direction —
 * are NOT here and must never be added: the reading carries each of them already rendered in
 * both packs (`statement.text.en` / `.zh`, docs/design/structure-lens.md §5.2), and the console
 * shows its locale's. One wording, every face; a second copy in this file would be the one that
 * drifts, and it would silently override an application that reworded a key through the overlay
 * seam.
 *
 * What IS here is the console's own small vocabulary: the six dimension titles and the question
 * each one asks, the BAND words, and readable labels for the metric names. Those are chrome —
 * the word "thin" is how this console says a band id, not a sentence the lens wrote. All three
 * tables are looked up by a runtime string through `useTOr`, so a dimension, band or metric this
 * build has never heard of renders under its own name rather than as a blank.
 *
 * The thresholds that CHOOSE a band are constants of the lens module in core and are not
 * repeated here (§4.2) — a percentage spelled twice is a percentage that will disagree.
 *
 * Document titles, paths and evidence strings are canonical data and render as they come.
 */
export const lens = defineMessages({
  zh: {
    "lens.description":
      "从外面读这座库的整体：六个维度，各说它看见什么、这意味着什么、比上一次读数移动了多少。",

    "lens.loading": "正在读取结构读数……",
    "lens.error.title": "读不到结构读数",
    "lens.empty.title": "还没有结构可读",
    "lens.empty.description": "这座库尚未编译——先去「导入」添加来源并编译，结构随正本一起产出。",
    "lens.empty.action": "去导入",
    "lens.noDimensions": "这次读数没有带回任何维度。",

    "lens.readAt": "读于 {time}",
    "lens.counts": "{files} 个文件归并为 {subjects} 个主体 · {claims} 条断言 · {edges} 条内链。",
    "lens.against": "对照",
    "lens.againstNone": "没有可对照的上一次读数：以下是第一次读数。",

    "lens.previous.label": "对照读数",
    "lens.previous.auto": "上一次提交（默认）",
    "lens.previous.note": "默认由服务端取 HEAD 的父提交；也可以指定任一提交或冻结快照。",

    /* --------------------------------------------------------------- dimensions */

    "lens.dimension.walkability": "可走性",
    "lens.dimension.walkability.question": "这座库能走着读，还是只能按名字查？",
    "lens.dimension.shape": "堆积",
    "lens.dimension.shape.question": "知识在往哪里堆？",
    "lens.dimension.knowledge_vs_log": "知识与流水",
    "lens.dimension.knowledge_vs_log.question": "多少是关于主体的知识，多少只是会话流水？",
    "lens.dimension.liveness": "活性",
    "lens.dimension.liveness.question": "这座库会自我修正吗？",
    "lens.dimension.type_structure": "类型与结构",
    "lens.dimension.type_structure.question": "正在积累的是哪一类知识，它所暗示的结构存在了吗？",
    "lens.dimension.demand_supply": "供需",
    "lens.dimension.demand_supply.question": "它存着的，是别人向它问的吗？",

    /* -------------------------------------------------------------------- bands */

    "lens.band.aria": "读数 {band}",
    "lens.band.open": "通畅",
    "lens.band.thin": "稀疏",
    "lens.band.broken": "断裂",
    "lens.band.even": "均衡",
    "lens.band.leaning": "偏斜",
    "lens.band.collapsing": "塌陷",
    "lens.band.knowledge": "知识",
    "lens.band.mixed": "混杂",
    "lens.band.log": "流水",
    "lens.band.living": "活",
    "lens.band.settling": "沉降",
    "lens.band.still": "静",
    "lens.band.aligned": "对位",
    "lens.band.strained": "吃紧",
    "lens.band.misfiled": "错位",
    "lens.band.matched": "相称",
    "lens.band.skewed": "失衡",
    "lens.band.unread": "无人问",

    /* ------------------------------------------------------------------ metrics */

    "lens.metric.name": "指标",
    "lens.metric.value": "本次",
    "lens.metric.previous": "上次",
    "lens.metric.noPrevious": "没有上一次读数，这一列留空。",

    "lens.metric.edges_per_subject": "每主体内链数",
    "lens.metric.dead_end_share": "死胡同占比",
    "lens.metric.arrival_blind_share": "无人指向占比",
    "lens.metric.largest_component_share": "最大连通块占比",
    "lens.metric.islands": "孤岛",
    "lens.metric.lead_share": "首位主体占比",
    "lens.metric.lead_ratio": "首位主体倍率",
    "lens.metric.family_max_ratio": "族断言／页数最大倍率",
    "lens.metric.empty_families": "零页的族",
    "lens.metric.clusters": "簇数",
    "lens.metric.narration_share": "会话叙述断言占比",
    "lens.metric.narration_subject_share": "以叙述为主的主体占比",
    "lens.metric.untouched_share": "建成后未再写过的主体占比",
    "lens.metric.supersessions_per_100": "每百条断言的取代数",
    "lens.metric.edits_per_100": "每百条断言的修订数",
    "lens.metric.rollovers": "分卷次数",
    "lens.metric.overviews_rewritten": "重写过的概览",
    "lens.metric.median_days_since_write": "距上次写入天数中位数",
    "lens.metric.dated_outside_chronology": "编年族之外的带日期断言",
    "lens.metric.decisions_outside_family": "决策族之外的决策段落",
    "lens.metric.recurring_names": "反复出现却无人物页的名字",
    "lens.metric.families_with_pages": "有页的族",
    "lens.metric.families_without_pages": "无页的族",
    "lens.metric.consultations": "咨询次数",
    "lens.metric.consulted_subjects": "被问过的主体",
    "lens.metric.unconsulted_subjects": "从没被问过的主体",
    "lens.metric.gap_share": "无引用作答占比",

    "lens.evidence.label": "「{dimension}」的依据",
  },
  en: {
    "lens.description":
      "The whole library read from outside: six dimensions, each saying what it sees, what that means, and how far it moved since the previous reading.",

    "lens.loading": "Reading the structure lens…",
    "lens.error.title": "Could not read the structure lens",
    "lens.empty.title": "No structure to read yet",
    "lens.empty.description":
      "This knowledge base has not been compiled — add a source under Ingest and compile it; the structure comes out with the canon.",
    "lens.empty.action": "Go to Ingest",
    "lens.noDimensions": "This reading carried no dimension.",

    "lens.readAt": "Read at {time}",
    "lens.counts":
      "{files} file{files||s} folded into {subjects} subject{subjects||s} · {claims} claim{claims||s} · {edges} internal link{edges||s}.",
    "lens.against": "Against",
    "lens.againstNone": "No previous reading to stand against: this is the first one.",

    "lens.previous.label": "Previous reading",
    "lens.previous.auto": "The previous commit (default)",
    "lens.previous.note":
      "By default the service reads HEAD's parent; any commit or frozen snapshot can be named instead.",

    /* --------------------------------------------------------------- dimensions */

    "lens.dimension.walkability": "Walkability",
    "lens.dimension.walkability.question":
      "Can a reader walk this library, or only look things up by name?",
    "lens.dimension.shape": "Shape",
    "lens.dimension.shape.question": "Where is knowledge piling up?",
    "lens.dimension.knowledge_vs_log": "Knowledge vs log",
    "lens.dimension.knowledge_vs_log.question":
      "How much of this is knowledge about subjects, and how much a log of sessions?",
    "lens.dimension.liveness": "Liveness",
    "lens.dimension.liveness.question": "Does the library ever correct itself?",
    "lens.dimension.type_structure": "Type and structure",
    "lens.dimension.type_structure.question":
      "What kind of knowledge is accumulating, and does the structure it implies exist?",
    "lens.dimension.demand_supply": "Demand and supply",
    "lens.dimension.demand_supply.question": "Is what it holds what people ask it?",

    /* -------------------------------------------------------------------- bands */

    "lens.band.aria": "Reads {band}",
    "lens.band.open": "Open",
    "lens.band.thin": "Thin",
    "lens.band.broken": "Broken",
    "lens.band.even": "Even",
    "lens.band.leaning": "Leaning",
    "lens.band.collapsing": "Collapsing",
    "lens.band.knowledge": "Knowledge",
    "lens.band.mixed": "Mixed",
    "lens.band.log": "Log",
    "lens.band.living": "Living",
    "lens.band.settling": "Settling",
    "lens.band.still": "Still",
    "lens.band.aligned": "Aligned",
    "lens.band.strained": "Strained",
    "lens.band.misfiled": "Misfiled",
    "lens.band.matched": "Matched",
    "lens.band.skewed": "Skewed",
    "lens.band.unread": "Unread",

    /* ------------------------------------------------------------------ metrics */

    "lens.metric.name": "Metric",
    "lens.metric.value": "Now",
    "lens.metric.previous": "Before",
    "lens.metric.noPrevious": "No previous reading, so the movement columns stay empty.",

    "lens.metric.edges_per_subject": "Links per subject",
    "lens.metric.dead_end_share": "Dead-end share",
    "lens.metric.arrival_blind_share": "Arrival-blind share",
    "lens.metric.largest_component_share": "Largest connected component",
    "lens.metric.islands": "Islands",
    "lens.metric.lead_share": "Lead subject's share",
    "lens.metric.lead_ratio": "Lead subject's ratio",
    "lens.metric.family_max_ratio": "Widest family claim-to-page ratio",
    "lens.metric.empty_families": "Declared families with no page",
    "lens.metric.clusters": "Clusters",
    "lens.metric.narration_share": "Session-narration claims",
    "lens.metric.narration_subject_share": "Subjects mostly narration",
    "lens.metric.untouched_share": "Subjects never written since creation",
    "lens.metric.supersessions_per_100": "Supersessions per 100 claims",
    "lens.metric.edits_per_100": "Edits per 100 claims",
    "lens.metric.rollovers": "Rollovers",
    "lens.metric.overviews_rewritten": "Overviews rewritten",
    "lens.metric.median_days_since_write": "Median days since last write",
    "lens.metric.dated_outside_chronology": "Dated claims outside a chronology",
    "lens.metric.decisions_outside_family": "Decision sections outside the decisions family",
    "lens.metric.recurring_names": "Recurring names with no page",
    "lens.metric.families_with_pages": "Declared families with pages",
    "lens.metric.families_without_pages": "Declared families without pages",
    "lens.metric.consultations": "Consultations",
    "lens.metric.consulted_subjects": "Subjects consulted",
    "lens.metric.unconsulted_subjects": "Subjects never consulted",
    "lens.metric.gap_share": "Answers with no citation",

    "lens.evidence.label": "Evidence for {dimension}",
  },
});
