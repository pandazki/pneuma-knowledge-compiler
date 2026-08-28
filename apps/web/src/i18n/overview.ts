import { defineMessages } from "./define";

/**
 * Front matter: the editor's note, the production line, the four-layer definition table and
 * the reading guide. Every string here is UI prose — the page carries no server data at all
 * apart from the four live counts.
 *
 * The flow nodes and the guide entries are keyed by the view they open (`overview.flow.process`,
 * `overview.guide.ingest`), not by their printed number, so reordering the page is a code
 * change rather than a dictionary rewrite.
 */
export const overview = defineMessages({
  zh: {
    "overview.offline.title": "服务不可达",
    "overview.offline.body":
      "无法连接 pneuma-knowledge 服务（{detail}），下方实时计数暂不可用，翻阅指引仍可使用。",

    "overview.hero.title": "把持续产生的来源，编译成可追溯的知识。",
    "overview.hero.lede":
      "这是一台知识编译器：对话、文档与实验记录先落成可定位的来源（source），" +
      "经编译工序取证、合并、标注争议，产出带稳定锚点的正本，" +
      "再经检索、问答与主动提示三个取用面回到手边。每个断言（claim）都能回到" +
      "原文精确段，取用面受引用门禁约束——没有出处的内容不会被当作事实递出。",

    "overview.section.flow": "生产流程",
    "overview.section.layers": "四层结构",
    "overview.section.guide": "翻阅指引",

    "overview.flow.aria": "生产流程：来源、编译、正本、取用",
    "overview.flow.enter": "进入本篇",
    "overview.flow.countNote":
      "计数来自当前选中用户的实时数据；未选择用户或尚无数据时显示 —。取用是读取知识库的方式，本身没有可计数的对象，版次与快照的数目在「版次 History」。",

    "overview.flow.sources.name": "来源",
    "overview.flow.sources.caption": "source 按原貌入库，可定位",
    "overview.flow.sources.unit": "条 source",
    "overview.flow.process.name": "编译",
    "overview.flow.process.caption": "compile job 取证与合并",
    "overview.flow.process.unit": "个 job",
    "overview.flow.library.name": "正本",
    "overview.flow.library.caption": "正本文档与断言",
    "overview.flow.library.unit": "文档 + 断言",
    "overview.flow.recall.name": "取用",
    "overview.flow.recall.caption": "检索 / 问答 / 提示，带引用门禁",

    "overview.layer.l0":
      "原始来源。对话、文档、代码片段按原貌入库，每段都有可定位的 source_id 与 block 编号——证据层，不可伪造。",
    "overview.layer.l1":
      "词法索引。Meilisearch 低延迟字面检索；索引只是投影，随时可从 L0 重建，不反向定义事实。",
    "overview.layer.l2":
      "语义索引。向量召回与 L1 融合排序，补上字面之外的邻近；同为可重建投影。",
    "overview.layer.l3":
      "正本 Git 仓库。编译产物的唯一事实形态——文档、断言锚点与版次全部进 Git，可审阅、比较、回滚、快照。",

    "overview.guide.ingest.title": "导入一份来源",
    "overview.guide.ingest.body":
      "从粘贴文本、文件或一段会话开始，先看机械预览与编译计划，再确认入库。",
    "overview.guide.process.title": "看编译如何发生",
    "overview.guide.process.body":
      "每次 compile 都是一行账：来源、状态、耗时与模型 lineage，逐条可查。",
    "overview.guide.library.title": "读编译出的正本",
    "overview.guide.library.body":
      "每条断言带稳定锚点与脚注，随手一条都能回到原文精确段。",
    "overview.guide.recall.title": "试三个取用面",
    "overview.guide.recall.body":
      "同一句问题，对比检索、连续问答与主动提示——全都受引用门禁约束。",
    "overview.guide.history.title": "核对版次历史",
    "overview.guide.history.body":
      "快照、job 与版次在同一条 Git 时间线上，任何快照都可只读回看。",
    "overview.guide.evolve.title": "看 skill 如何演化",
    "overview.guide.evolve.body":
      "skill 演化的提案、对照与采纳 / 放弃，决定正本下一步怎么长。",

    "overview.synthetic.body":
      "演示数据全部可复现合成：用户画像、来源、正本与版次历史均由确定性生成器产出，" +
      "可在本地完整重放，不包含任何真实用户内容。",
  },
  en: {
    "overview.offline.title": "Service unreachable",
    "overview.offline.body":
      "Cannot reach the pneuma-knowledge service ({detail}); the live counts below are " +
      "unavailable, but the reading guide still works.",

    "overview.hero.title": "Compile the sources you keep producing into traceable knowledge.",
    "overview.hero.lede":
      "This is a knowledge compiler: conversations, documents and working notes first " +
      "land as addressable sources; the compile process gathers evidence, merges " +
      "it and marks disputes, producing a canonical body with stable anchors; three " +
      "retrieval surfaces — search, question answering and proactive prompts — bring it " +
      "back to hand. Every claim leads to an exact source span, and the retrieval surfaces " +
      "are bound by the citation gate: nothing without a provenance is handed out as fact.",

    "overview.section.flow": "Production line",
    "overview.section.layers": "Four layers",
    "overview.section.guide": "Reading guide",

    "overview.flow.aria": "Production line: sources, compile, canonical, retrieval",
    "overview.flow.enter": "Open this chapter",
    "overview.flow.countNote":
      "The counts are live for the selected user; a dash means no user is selected, or no data yet. Retrieval is a way of reading the base rather than a pile of things in it, so it carries no count — editions and snapshots are counted in History.",

    "overview.flow.sources.name": "Sources",
    "overview.flow.sources.caption": "sources filed as they are, addressable",
    "overview.flow.sources.unit": "sources",
    "overview.flow.process.name": "Compile",
    "overview.flow.process.caption": "compile jobs gather and merge",
    "overview.flow.process.unit": "jobs",
    "overview.flow.library.name": "Canonical",
    "overview.flow.library.caption": "canonical documents and claims",
    "overview.flow.library.unit": "documents + claims",
    "overview.flow.recall.name": "Retrieval",
    "overview.flow.recall.caption": "search / ask / prompts, gated",

    "overview.layer.l0":
      "Raw sources. Conversations, documents and code fragments are filed as they are, every span carrying an addressable source_id and block number — the evidence layer, and not forgeable.",
    "overview.layer.l1":
      "Lexical index. Low-latency literal search through Meilisearch; the index is only a projection, rebuildable from L0 at any time, and it never defines the facts.",
    "overview.layer.l2":
      "Semantic index. Vector recall fused with the L1 ranking, covering the adjacency literal search misses; likewise a rebuildable projection.",
    "overview.layer.l3":
      "The canonical Git repository. The one factual form of the compiled output — documents, claim anchors and editions all go into Git, to be reviewed, compared, rolled back, snapshotted.",

    "overview.guide.ingest.title": "Ingest a source",
    "overview.guide.ingest.body":
      "Start from pasted text, a file or a conversation; read the mechanical preview and the compile plan, then confirm.",
    "overview.guide.process.title": "Watch a compile happen",
    "overview.guide.process.body":
      "Each compile is one line of the ledger: source, status, duration and model lineage, all inspectable.",
    "overview.guide.library.title": "Read the compiled canonical knowledge",
    "overview.guide.library.body":
      "Every claim carries a stable anchor and a footnote; any one of them leads back to an exact source span.",
    "overview.guide.recall.title": "Try the three retrieval surfaces",
    "overview.guide.recall.body":
      "Put the same question to search, to a running conversation and to proactive prompts — all three bound by the citation gate.",
    "overview.guide.history.title": "Check the edition history",
    "overview.guide.history.body":
      "Snapshots, jobs and editions share one Git timeline; any snapshot can be revisited read-only.",
    "overview.guide.evolve.title": "See how a skill evolves",
    "overview.guide.evolve.body":
      "The skill-evolve proposals, their comparisons and the adopt / discard call decide how canonical grows next.",

    "overview.synthetic.body":
      "Every piece of demo data is reproducibly synthetic: profiles, sources, canonical output " +
      "and edition history all come from deterministic generators, replay in full locally, and " +
      "contain no real user content.",
  },
});
