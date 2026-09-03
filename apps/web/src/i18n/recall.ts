import { defineMessages } from "./define";

/**
 * The Recall view: one query, three lanes. The lane names (`rag` / `fast` / `deep`) are the
 * machine values AND the visible labels — they read the same in both languages, which is why
 * `recall.mode.*` carries identical strings rather than nothing at all: the label still goes
 * through the dictionary, so a future language can rename it without touching the call site.
 *
 * Answer bodies, hit snippets and trail errors arrive from the service and are data — only
 * the frame around them is translated.
 */
export const recall = defineMessages({
  zh: {
    "recall.title": "检索 Recall",
    "recall.description":
      "同一个查询可在 rag / fast / deep 三条 lane 上重跑对比：命中账、直接作答、带核验的深查。",
    "recall.descriptionShort": "rag / fast / deep 三条检索 lane。",
    // The reading room's own words for the same surface: a visitor asks a library, not a
    // retrieval pipeline. Same page, same lanes — only the frame changes with the lens.
    "recall.readingTitle": "问答",
    "recall.readingDescription": "向这座知识库提问——答案带着可核对的引用，可顺着读到原文。",

    "recall.noUser.title": "未选择用户",
    "recall.noUser.description": "在右上角选择一个 user_id 后，即可对其知识库做检索。",

    "recall.query.aria": "检索查询",
    "recall.query.placeholderRag": "查询词，如「发布 门禁」",
    "recall.query.placeholderAsk": "自然语言提问，如「发布前还缺什么」",

    "recall.mode.aria": "检索模式",
    "recall.mode.rag": "rag",
    "recall.mode.fast": "fast",
    "recall.mode.deep": "deep",

    "recall.action.search": "检索",
    "recall.action.ask": "提问",
    "recall.error.title": "检索失败",

    "recall.empty.ragTitle": "输入查询开始检索",
    "recall.empty.ragDescription": "rag 跑 L2 语义 + L1 词法双路，命中经 RRF 融合排序。",
    "recall.empty.askTitle": "提问开始作答",
    "recall.empty.askDescription": "fast 基于正本断言（claim）直接作答；deep 再对引用逐条核验。",
    "recall.empty.noHitsTitle": "无命中",
    "recall.empty.noHitsDescription": "换个查询词，或先去「导入 Ingest」入库更多来源。",

    "recall.hits.count": "{count} 条命中 · 点击脚注定位到原文",

    "recall.session.title": "本次会话的问答",
    "recall.session.note": "只留在这个浏览器标签页里，关掉就没有了。",
    "recall.session.reopen": "重新打开这条问答",

    "recall.trail.title": "深查过程（{count} 步）",
    "recall.trail.live": "进行中…",
    "recall.trail.failed": "失败：{detail}",
    "recall.trail.hits": "{count} 命中",
    "recall.trail.chars": "{count} 字",
    "recall.trail.result": "结果",

    "recall.answer.title": "答案",
    "recall.answer.blank": "（空）",
    "recall.answer.evidenceStrategy": "证据编排",
    "recall.answer.answerFormat": "回答格式",
    "recall.answer.degraded": "已降级",
    "recall.answer.deliberation": "思考",
    "recall.answer.selectorContribution":
      "selector 实选：claim {claims}/{claimCandidates} · episode {episodes}/{episodeCandidates} · 窗口 {windows}/{windowCandidates}",
    "recall.stages.title": "各阶段耗时",
    "recall.stages.description":
      "fast lane 的每一步实测墙钟：括号内是这次并发检索里各条路各自的耗时（它们同时在跑，相加不等于 retrieve），total 收口整条 lane。",
    "recall.stages.descriptionDeep":
      "这次深查每一步的实测墙钟，按发生顺序排列：turn:N 是一次模型思考，tool:X 是它调用的一件工具，finalize 表示预算耗尽后被迫收尾。total 收口整个 agentic 循环——循环之前的种子检索不算在内。",
    "recall.stages.descriptionRag":
      "rag lane 每一步的实测墙钟：embed 是问题向量，retrieve 里的 lexical 与 vector 是先后两次检索（顺序执行，相加即为 retrieve），fuse 是 RRF 融合，expand 是融合之后的重叠归并。这条 lane 不调用模型，所以没有作答阶段。",
    "recall.stages.skipped": "未执行",
    "recall.stages.pending": "待运行",
    "recall.stages.degraded": "降级：{reason}",
    "recall.stages.slowest": "最慢：{stage} {ms}",
    "recall.stages.explain": "这张图怎么读",
    "recall.stages.previewTitle": "{stage}：输入与结果",
    "recall.stages.previewOpen": "查看 {stage} 的输入与结果",
    "recall.stages.answering": "答案正在生成……",
    "recall.usedClaims.title": "依据断言（{count}）",
    "recall.components.title": "组件查询（{count}）",
    "recall.components.description":
      "路由选中的组件查询路：结构化查询、精确命中，自成一个证据面，不参与排序融合。",
    "recall.components.claims": "断言 {count}",
    "recall.components.windows": "原文摘录 {count}",
    "recall.components.dropped": "……另有 {count} 条超出该路上限",
    "recall.components.notShown": "……未展示：{detail}",
    "recall.components.alreadyShown": "有 {count} 条已在上面的排序证据里",
    "recall.components.via": "来自 {paths}",
    "recall.components.degraded": "降级：{reason}",
    "recall.components.empty": "这条路没有返回内容。",
    "recall.route.title": "组件路由",
    "recall.route.offered": "可选 {paths}",
    "recall.route.chosen": "选中 {paths}",
    "recall.route.none": "未选中任何路",
    "recall.route.degraded": "路由降级：{reason}",
    "recall.episodeSummaries.title": "派生 Episode 摘要（{count}）",
    "recall.episodeSummaries.description":
      "回答实际使用的高密度 L2 派生内容；不是逐字原文，每条都带原始来源位置。",
    "recall.episodeSummaries.derived": "派生摘要 · 非逐字",
    "recall.windows.title": "原文摘录（{count}）",
    "recall.windows.description": "未编译为断言的原始内容，同样可定位回原文。",
  },
  en: {
    "recall.title": "Recall",
    "recall.description":
      "Run one query down all three lanes — rag / fast / deep — and compare: the hit ledger, a direct answer, a deep search with every citation verified.",
    "recall.descriptionShort": "Three retrieval lanes: rag / fast / deep.",
    "recall.readingTitle": "Ask",
    "recall.readingDescription":
      "Ask this library a question — answers carry checkable citations that open into the sources.",

    "recall.noUser.title": "No user selected",
    "recall.noUser.description":
      "Choose a user_id in the top right to search that knowledge base.",

    "recall.query.aria": "Recall query",
    "recall.query.placeholderRag": "Search terms, e.g. “release gate”",
    "recall.query.placeholderAsk":
      "A question in plain language, e.g. “what is still missing before the release”",

    "recall.mode.aria": "Retrieval mode",
    "recall.mode.rag": "rag",
    "recall.mode.fast": "fast",
    "recall.mode.deep": "deep",

    "recall.action.search": "Search",
    "recall.action.ask": "Ask",
    "recall.error.title": "Recall failed",

    "recall.empty.ragTitle": "Type a query to search",
    "recall.empty.ragDescription":
      "rag runs both lanes — L2 semantic and L1 lexical — and fuses the hits with RRF.",
    "recall.empty.askTitle": "Ask a question to get an answer",
    "recall.empty.askDescription":
      "fast answers straight from canonical claims; deep then verifies each citation.",
    "recall.empty.noHitsTitle": "No hits",
    "recall.empty.noHitsDescription":
      "Try different terms, or file more sources through Ingest first.",

    "recall.hits.count": "{count} hit{count||s} · click a footnote to open the original",

    "recall.session.title": "This session's questions",
    "recall.session.note": "Kept in this browser tab only; closing it ends the list.",
    "recall.session.reopen": "Open this answer again",

    "recall.trail.title": "Deep search ({count} step{count||s})",
    "recall.trail.live": "in progress…",
    "recall.trail.failed": "failed: {detail}",
    "recall.trail.hits": "{count} hit{count||s}",
    "recall.trail.chars": "{count} char{count||s}",
    "recall.trail.result": "Result",

    "recall.answer.title": "Answer",
    "recall.answer.blank": "(empty)",
    "recall.answer.evidenceStrategy": "evidence",
    "recall.answer.answerFormat": "format",
    "recall.answer.degraded": "degraded",
    "recall.answer.deliberation": "deliberation",
    "recall.answer.selectorContribution":
      "selector chose claims {claims}/{claimCandidates} · episodes {episodes}/{episodeCandidates} · windows {windows}/{windowCandidates}",
    "recall.stages.title": "Stage timing",
    "recall.stages.description":
      "Measured wall-clock per step of the fast lane. The lanes in brackets ran concurrently inside one retrieval gather, so they add up to more than `retrieve`; `total` wraps the whole lane.",
    "recall.stages.descriptionDeep":
      "Measured wall-clock per step of this deep search, in the order it happened: `turn:N` is one model turn, `tool:X` a tool it reached for, `finalize` a closing call forced by the tool budget. `total` wraps the agentic loop — the seed retrieval before it is not a loop step.",
    "recall.stages.descriptionRag":
      "Measured wall-clock per step of the rag lane: `embed` is the question vector, `retrieve`'s `lexical` and `vector` are two lookups run one after the other (sequential, so they add up to `retrieve`), `fuse` is the RRF pass, `expand` the overlap merge that follows it. No model runs in this lane, so there is no answering step.",
    "recall.stages.skipped": "not run",
    "recall.stages.pending": "not yet",
    "recall.stages.degraded": "degraded: {reason}",
    "recall.stages.slowest": "slowest: {stage} {ms}",
    "recall.stages.explain": "How to read this diagram",
    "recall.stages.previewTitle": "{stage}: in and out",
    "recall.stages.previewOpen": "What {stage} was handed and produced",
    "recall.stages.answering": "The answer is being written…",
    "recall.usedClaims.title": "Claims used ({count})",
    "recall.components.title": "Component lookups ({count})",
    "recall.components.description":
      "The lookup paths routing chose: a structured query, exact hits, its own evidence face — never fused into the ranked pool.",
    "recall.components.claims": "{count} claim{count||s}",
    "recall.components.windows": "{count} excerpt{count||s}",
    "recall.components.dropped": "…and {count} more beyond this path's cap",
    "recall.components.notShown": "…not shown: {detail}",
    "recall.components.alreadyShown": "{count} already shown in the ranked evidence above",
    "recall.components.via": "via {paths}",
    "recall.components.degraded": "degraded: {reason}",
    "recall.components.empty": "This path returned nothing.",
    "recall.route.title": "Component routing",
    "recall.route.offered": "offered {paths}",
    "recall.route.chosen": "chose {paths}",
    "recall.route.none": "chose nothing",
    "recall.route.degraded": "routing degraded: {reason}",
    "recall.episodeSummaries.title": "Derived episode summaries ({count})",
    "recall.episodeSummaries.description":
      "Dense generated L2 content actually used for this answer; not verbatim, and every item locates back to its source.",
    "recall.episodeSummaries.derived": "derived summary · not verbatim",
    "recall.windows.title": "Source excerpts ({count})",
    "recall.windows.description":
      "Raw content not compiled into claims; it still locates back to the original.",
  },
});
