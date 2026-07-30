import { defineMessages } from "./define";

/**
 * The Canonical view: the compiled documents, set as proofs. Everything the compiler wrote —
 * document titles, frontmatter values, claim prose, the disputed / open-question rationales in
 * the margin — is data and renders untranslated. Claim flag names come from the shared
 * `common.flag.*` entries, so the badge here and the badge in Process read alike.
 */
export const library = defineMessages({
  zh: {
    "library.title": "正典 Canonical",
    "library.description": "{count} 篇文档 · 每个 claim 都能回到精确 source span。",
    "library.descriptionShort": "编译产出的 canonical 文档：serif 版样、claim 锚点、脚注引用。",

    "library.empty.title": "还没有正典",
    "library.empty.description":
      "这个知识库尚未编译出 canonical 文档——先去「导入 Ingest」添加原料，再在「工序 Process」里编译。",
    "library.empty.action": "去导入",

    "library.toc.aria": "文档目录",
    "library.toc.count": "目录 · {count} 篇",

    "library.noDoc.title": "没有文档",
    "library.noDoc.description": "documents 为空——编译尚未产出任何 canonical 文档。",

    "library.frontmatter.title": "版式信息",
    "library.body.title": "正文",
    "library.body.empty": "该文档没有可追溯 claim 块。",
    "library.citations.title": "出处",
    "library.patches.title": "版次轨迹",
    "library.patches.changed": "{count} 处变更",
  },
  en: {
    "library.title": "Canonical",
    "library.description":
      "{count} document{count||s} · every claim returns to an exact source span.",
    "library.descriptionShort":
      "The canonical documents the compiler produced: serif proofs, claim anchors, footnote citations.",

    "library.empty.title": "No canon yet",
    "library.empty.description":
      "This knowledge base has not compiled a canonical document yet — add material through Ingest, then compile it in Process.",
    "library.empty.action": "Go to Ingest",

    "library.toc.aria": "Document contents",
    "library.toc.count": "Contents · {count} document{count||s}",

    "library.noDoc.title": "No document",
    "library.noDoc.description":
      "documents is empty — the compile has produced no canonical document yet.",

    "library.frontmatter.title": "Frontmatter",
    "library.body.title": "Body",
    "library.body.empty": "This document has no traceable claim blocks.",
    "library.citations.title": "Sources",
    "library.patches.title": "Edition trail",
    "library.patches.changed": "{count} change{count||s}",
  },
});
