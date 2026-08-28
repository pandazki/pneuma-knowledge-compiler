import { defineMessages } from "./define";

/**
 * The Canonical view: the compiled documents, set as proofs. Everything the compiler wrote —
 * document titles, frontmatter values, claim prose, the disputed / open-question rationales in
 * the margin — is data and renders untranslated. Claim flag names come from the shared
 * `common.flag.*` entries, so the badge here and the badge in Process read alike.
 */
export const library = defineMessages({
  zh: {
    "library.title": "正本",
    "library.description": "{count} 篇文档 · 每个断言（claim）都能回到原文精确段。",
    "library.descriptionShort": "编译产出的正本文档：版样、断言（claim）锚点、脚注引用。",

    "library.empty.title": "还没有正本",
    "library.empty.description":
      "这个知识库尚未编译出正本文档——先去「导入」添加来源，再在「工序」里编译。",
    "library.empty.action": "去导入",

    "library.toc.aria": "文档目录",
    "library.toc.count": "目录 · {count} 篇",
    "library.toc.expandDir": "展开 {name} · {count} 篇",
    "library.toc.collapseDir": "折叠 {name} · {count} 篇",

    "library.noDoc.title": "没有文档",
    "library.noDoc.description": "文档列表为空——编译尚未产出任何正本文档。",

    "library.volumes.aria": "本主题的各卷",
    "library.volumes.label": "卷",
    "library.volumes.main": "主卷",

    "library.neighborhood.title": "邻域",
    "library.neighborhood.note": "双向脉络索引：每一行都带上写出这条链接的那句断言。",
    "library.neighborhood.out": "出向 · {count}",
    "library.neighborhood.in": "入向 · {count}",
    "library.neighborhood.emptyOut": "这篇不链向任何文档。",
    "library.neighborhood.emptyIn": "没有文档链向这篇。",
    "library.neighborhood.more": "同向另有 {count} 句",
    "library.neighborhood.volume": "写在归档卷 {name}",

    "library.overview.title": "总览与信息",
    "library.overview.note":
      "这份文档当前的画像：由编译整体重写，每一句都落在下面账本里的断言上。",
    "library.overview.definition": "定义",
    "library.overview.summary": "现状",
    "library.overview.introduction": "背景",
    "library.overview.connections": "关联",

    "library.frontmatter.title": "版式信息",
    "library.body.title": "正文",

    "library.supersession.aria": "正文视图：当前 / 历史",
    "library.supersession.current": "当前",
    "library.supersession.history": "历史",
    "library.supersession.currentNote": "已隐去 {count} 条被取代的旧状态；切到「历史」可看到完整的取代链。",
    "library.supersession.historyNote":
      "含被取代的旧状态：旧状态原样保留，只是不再是当前事实。",
    "library.supersession.superseded": "已被取代",
    "library.supersession.supersededBy": "被 c:{anchor} 取代",
    "library.supersession.supersedes": "取代 c:{anchor}",
    "library.supersession.elsewhere": "在 {path}",
    "library.supersession.jump": "跳到 c:{anchor}",
    "library.body.empty": "该文档没有可追溯断言。",
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

    "library.empty.title": "No canonical knowledge yet",
    "library.empty.description":
      "This knowledge base has not compiled a canonical document yet — add a source through Ingest, then compile it in Process.",
    "library.empty.action": "Go to Ingest",

    "library.toc.aria": "Document contents",
    "library.toc.count": "Contents · {count} document{count||s}",
    "library.toc.expandDir": "Expand {name} · {count} document{count||s}",
    "library.toc.collapseDir": "Collapse {name} · {count} document{count||s}",

    "library.noDoc.title": "No document",
    "library.noDoc.description":
      "The document list is empty — the compile has produced no canonical document yet.",

    "library.volumes.aria": "Volumes of this subject",
    "library.volumes.label": "Volumes",
    "library.volumes.main": "Main",

    "library.neighborhood.title": "Neighbourhood",
    "library.neighborhood.note":
      "A two-way index of the thread: every row carries the claim that wrote the link.",
    "library.neighborhood.out": "Out · {count}",
    "library.neighborhood.in": "In · {count}",
    "library.neighborhood.emptyOut": "This document links to nothing.",
    "library.neighborhood.emptyIn": "No document links here.",
    "library.neighborhood.more": "{count} further sentence{count||s} the same way",
    "library.neighborhood.volume": "written in archive volume {name}",

    "library.overview.title": "Overview & facts",
    "library.overview.note":
      "The document's current picture, rewritten whole by a compile — every sentence rests on a claim in the ledger below.",
    "library.overview.definition": "Definition",
    "library.overview.summary": "Summary",
    "library.overview.introduction": "Introduction",
    "library.overview.connections": "Connections",

    "library.frontmatter.title": "Frontmatter",
    "library.body.title": "Body",

    "library.supersession.aria": "Body view: current or history",
    "library.supersession.current": "Current",
    "library.supersession.history": "History",
    "library.supersession.currentNote":
      "{count} superseded state{count||s} hidden; switch to History to read the whole chain.",
    "library.supersession.historyNote":
      "Superseded states included: the old state is kept exactly as written, it simply no longer holds.",
    "library.supersession.superseded": "superseded",
    "library.supersession.supersededBy": "superseded by c:{anchor}",
    "library.supersession.supersedes": "supersedes c:{anchor}",
    "library.supersession.elsewhere": "in {path}",
    "library.supersession.jump": "Go to c:{anchor}",
    "library.body.empty": "This document has no traceable claim blocks.",
    "library.citations.title": "Sources",
    "library.patches.title": "Edition trail",
    "library.patches.changed": "{count} change{count||s}",
  },
});
