import { defineMessages } from "./define";

/**
 * The History view: one entry per patch, with the claim-level diff it carried. Everything the
 * compiler wrote or the store recorded — claim prose (`before` / `after`), document paths,
 * patch / job ids, refs, short shas, escalation notes — is data and renders untranslated.
 * Claim flag names come from the shared `common.flag.*` entries and the escalation label
 * fallback from `common.escalation.fallback`, so a flag badge here reads like one in Canonical.
 */
export const history = defineMessages({
  zh: {
    "history.title": "版本 History",
    "history.description": "查看知识库每一次可追溯的内容变化。",
    "history.descriptionCount":
      "{count} 个知识版本，按编译时间倒序。运行任务请前往「工序 Process」查看。",

    "history.noUser.title": "未选择用户",
    "history.noUser.description": "先在顶栏选择一个 user_id，再查看它的知识版本。",

    "history.heatmap.title": "版本编译密度",
    "history.heatmap.patch": "知识版本",

    "history.loadFailed": "加载知识变更失败",

    "history.empty.title": "还没有知识版本",
    "history.empty.description":
      "这个知识库尚未产生内容变化。导入原料并完成编译后，每次知识更新都会在这里留下可读的差异。",
    "history.empty.action": "去导入",

    "history.updateNoun": "次更新",
    "history.selectHint": "在左侧选择一次知识更新查看内容差异。",
    "history.row.counts": "{documents} 篇 · {claims} 条",

    "history.summary.empty": "本次更新没有留下可读的内容摘要",
    "history.brief.label": "编译简报 · 派生叙述",
    "history.patchTitle.addedRevised": "新增 {added} 条、修订 {revised} 条知识",
    "history.patchTitle.revised": "修订 {revised} 条知识",
    "history.patchTitle.added": "新增 {added} 条知识",
    "history.patchTitle.generic": "知识库更新",

    "history.stats.documents": "{count} 篇文档",
    "history.stats.added": "新增 {count}",
    "history.stats.revised": "修订 {count}",
    "history.stats.sources": "{count} 个来源",

    "history.section.diff": "内容差异",
    "history.section.sources": "依据来源",
    "history.section.review": "需复核",

    "history.unlocatedDocument": "未定位文档",
    "history.group.changes": "{count} 条变化",

    "history.claim.added": "新增",
    "history.claim.revised": "修订",
    "history.claim.changed": "变更",
    "history.claim.viewCurrent": "查看当前原文",
    "history.claim.before": "原",
    "history.claim.after": "现",
    "history.claim.noText": "未记录正文差异",

    "history.noPerClaim.title": "暂无逐条差异",
    "history.noPerClaim.body":
      "这个旧版本只记录了受影响的文档，没有保存知识条目的前后文本。",

    "history.source.index": "来源 {index}",
    "history.source.view": "查看原料",
    "history.source.empty": "未记录来源。",

    "history.escalation.fallbackBody": "这条变化需要人工复核。",

    "history.tech.summary": "技术记录",
    "history.tech.patch": "版本",
    "history.tech.job": "编译任务",
    "history.tech.baseCommit": "基于版本",
  },
  en: {
    "history.title": "History",
    "history.description": "Every traceable change to the knowledge base.",
    "history.descriptionCount":
      "{count} knowledge version{count||s}, newest compile first. Running jobs are shown under Process.",

    "history.noUser.title": "No user selected",
    "history.noUser.description":
      "Choose a user_id in the top bar to see its knowledge versions.",

    "history.heatmap.title": "Compile density",
    "history.heatmap.patch": "Knowledge version",

    "history.loadFailed": "Could not load the knowledge changes",

    "history.empty.title": "No knowledge versions yet",
    "history.empty.description":
      "This knowledge base has no content change yet. Once material is added and compiled, every knowledge update leaves a readable diff here.",
    "history.empty.action": "Go to Ingest",

    "history.updateNoun": "updates",
    "history.selectHint": "Choose an update on the left to read its diff.",
    "history.row.counts": "{documents} doc{documents||s} · {claims} claim{claims||s}",

    "history.summary.empty": "This update left no readable summary",
    "history.brief.label": "Compile brief · derived narration",
    "history.patchTitle.addedRevised": "{added} claim{added||s} added, {revised} revised",
    "history.patchTitle.revised": "{revised} claim{revised||s} revised",
    "history.patchTitle.added": "{added} claim{added||s} added",
    "history.patchTitle.generic": "Knowledge base update",

    "history.stats.documents": "{count} document{count||s}",
    "history.stats.added": "{count} added",
    "history.stats.revised": "{count} revised",
    "history.stats.sources": "{count} source{count||s}",

    "history.section.diff": "Content diff",
    "history.section.sources": "Supporting sources",
    "history.section.review": "Needs review",

    "history.unlocatedDocument": "Unlocated document",
    "history.group.changes": "{count} change{count||s}",

    "history.claim.added": "Added",
    "history.claim.revised": "Revised",
    "history.claim.changed": "Changed",
    "history.claim.viewCurrent": "View the current text",
    "history.claim.before": "Was",
    "history.claim.after": "Now",
    "history.claim.noText": "No prose diff recorded",

    "history.noPerClaim.title": "No per-claim diff",
    "history.noPerClaim.body":
      "This older version recorded only the documents it touched, not the before and after text of each claim.",

    "history.source.index": "Source {index}",
    "history.source.view": "View material",
    "history.source.empty": "No source recorded.",

    "history.escalation.fallbackBody": "This change needs a human review.",

    "history.tech.summary": "Technical record",
    "history.tech.patch": "Version",
    "history.tech.job": "Compile job",
    "history.tech.baseCommit": "Base version",
  },
});
