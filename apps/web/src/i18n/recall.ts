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
    "recall.empty.askDescription": "fast 基于 canonical claim 直接作答；deep 再对引用逐条核验。",
    "recall.empty.noHitsTitle": "无命中",
    "recall.empty.noHitsDescription": "换个查询词，或先去「导入 Ingest」入库更多材料。",

    "recall.hits.count": "{count} 条命中 · 点击脚注定位到原文",

    "recall.trail.title": "深查过程（{count} 步）",
    "recall.trail.live": "进行中…",
    "recall.trail.failed": "失败：{detail}",
    "recall.trail.hits": "{count} 命中",
    "recall.trail.chars": "{count} 字",

    "recall.answer.title": "答案",
    "recall.answer.blank": "（空）",
    "recall.usedClaims.title": "依据 claim（{count}）",
    "recall.windows.title": "原文摘录（{count}）",
    "recall.windows.description": "未编译为 claim 的原始内容，同样可定位回原文。",
  },
  en: {
    "recall.title": "Recall",
    "recall.description":
      "Run one query down all three lanes — rag / fast / deep — and compare: the hit ledger, a direct answer, a deep search with every citation verified.",
    "recall.descriptionShort": "Three retrieval lanes: rag / fast / deep.",

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
      "Try different terms, or file more material through Ingest first.",

    "recall.hits.count": "{count} hit{count||s} · click a footnote to open the original",

    "recall.trail.title": "Deep search ({count} step{count||s})",
    "recall.trail.live": "in progress…",
    "recall.trail.failed": "failed: {detail}",
    "recall.trail.hits": "{count} hit{count||s}",
    "recall.trail.chars": "{count} char{count||s}",

    "recall.answer.title": "Answer",
    "recall.answer.blank": "(empty)",
    "recall.usedClaims.title": "Claims used ({count})",
    "recall.windows.title": "Source excerpts ({count})",
    "recall.windows.description":
      "Raw content not compiled into claims; it still locates back to the original.",
  },
});
