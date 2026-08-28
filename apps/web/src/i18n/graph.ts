import { defineMessages } from "./define";

/**
 * The structure lens (route `#/graph`): a health surface over the canonical structure, and a
 * difference table between two snapshots. Document titles, paths and family templates are
 * canonical data and render as they come.
 *
 * `graph.anomaly.concentration` reads its second clause in as `{ratio}` (empty when there is
 * no second subject to divide by) rather than assembling two sentences, so each language keeps
 * control of its own punctuation — the same shape the retired summary line used.
 */
export const graph = defineMessages({
  zh: {
    "graph.description": "正本结构的透镜：集中度、连通性、族均衡，以及两次快照之间的结构差。",

    "graph.tab.aria": "结构透镜",
    "graph.tab.health": "结构健康",
    "graph.tab.compare": "时间对比",

    "graph.empty.title": "还没有结构可读",
    "graph.empty.description":
      "这个知识库尚未编译——先去「导入」添加来源并编译，结构随正本一起产出。",
    "graph.empty.action": "去导入",

    /* ------------------------------------------------------------------ health */

    "graph.health.summary":
      "{files} 个文件归并为 {subjects} 个主体 · {claims} 条断言（claim）· {edges} 条内链。",
    "graph.health.headline": "最异常的 {count} 件事",
    "graph.health.clean": "没有越线的指标：没有单点集中，没有失衡族，也没有不可达的主体。",
    "graph.health.rest": "另有 {count} 项越线指标，见下面各节。",
    "graph.health.openDocument": "打开这篇文档",

    "graph.anomaly.concentration": "单个主体「{title}」独占全库 {share} 的断言{ratio}",
    "graph.anomaly.concentration.ratio": "，是第二名的 {ratio} 倍",
    "graph.anomaly.familyImbalance":
      "族 {family} 只有 {pages} 页，却装下 {share} 的断言——是它页数份额的 {factor} 倍",
    "graph.anomaly.zeroPageFamilies": "{count} 个申报族至今零页（共申报 {declared} 族）",
    "graph.anomaly.arrivalBlind": "{count} 个主体无入链（{share}）——只能靠已经知道名字才找得到",
    "graph.anomaly.deadEnd": "{count} 个主体断头（{share}）——线索走到这里就断了",
    "graph.anomaly.orphanClaims": "{count} 条断言落在无入链的主体里（{share}）",
    "graph.anomaly.deadLink": "{count} 条链接指向不存在的文档",

    "graph.concentration.title": "集中度",
    "graph.concentration.note":
      "按断言份额排序的主体；归档卷并入所属页计算，因为读者眼里那是同一个主体。",
    "graph.concentration.lead": "头名份额",
    "graph.concentration.ratio": "第一 / 第二",
    "graph.concentration.tail": "其余 {units} 个主体",
    "graph.concentration.claims": "{count} 条",
    "graph.concentration.volumes": "并入 {count} 卷归档",
    "graph.concentration.shareAria": "断言份额 {share}",

    "graph.connectivity.title": "连通性",
    "graph.connectivity.note":
      "口径与评测 D 组一致：无入链 = 没有任何文档链向它，断头 = 它不链向任何文档。",
    "graph.connectivity.arrivalBlind": "无入链主体",
    "graph.connectivity.deadEnd": "断头主体",
    "graph.connectivity.deadLinks": "死链",
    "graph.connectivity.orphanClaims": "孤立断言",
    "graph.connectivity.arrivalBlindList": "无入链 · 没有任何文档链向它们",
    "graph.connectivity.deadEndList": "断头 · 它们不链向任何文档",
    "graph.connectivity.isolated": "其中 {count} 个两头皆无。",
    "graph.connectivity.clean": "内链闭合：没有死链，每个主体都有入口也有去处。",

    "graph.families.title": "族均衡",
    "graph.families.note":
      "族由 skill 申报的路径模板定义。零页族是申报了却一直没用起来的归档位，所以它留在表里。",
    "graph.families.family": "族",
    "graph.families.pages": "页数",
    "graph.families.claims": "断言",
    "graph.families.claimShare": "断言份额",
    "graph.families.textShare": "篇幅份额",
    "graph.families.zeroPage": "零页族 · {count}",
    "graph.families.unowned": "{count} 个主体不属于任何申报族。",
    "graph.families.unavailable": "读不到 skill 申报的路径模板，族均衡这一节暂缺。",

    /* ----------------------------------------------------------------- compare */

    "graph.compare.note":
      "两次正本投影的差，读成表格与清单——两张读不懂的图并排只会更读不懂。",
    "graph.compare.before": "基准",
    "graph.compare.after": "对照",
    "graph.compare.head": "HEAD · 实时",
    "graph.compare.run": "对比",
    "graph.compare.same": "两侧选的是同一个快照。",
    "graph.compare.none": "这个知识库还没有可比的快照。",
    "graph.compare.loading": "正在读取两侧的正本投影……",
    "graph.compare.error": "读取快照失败",
    "graph.compare.deltaTitle": "指标差",
    "graph.compare.docsTitle": "主体增减",
    "graph.compare.edgesTitle": "新增内链",
    "graph.compare.metric": "指标",
    "graph.compare.added": "新增 · {count}",
    "graph.compare.removed": "消失 · {count}",
    "graph.compare.noDocChange": "两侧的主体集合完全一致。",
    "graph.compare.noNewEdges": "没有新增内链。",
    "graph.compare.newEdgeMore": "另有 {count} 条新增内链未列出。",

    "graph.metric.files": "文件",
    "graph.metric.subjects": "主体",
    "graph.metric.claims": "断言",
    "graph.metric.edges": "内链",
    "graph.metric.arrivalBlind": "无入链主体",
    "graph.metric.deadEnd": "断头主体",
    "graph.metric.orphanClaims": "孤立断言",
    "graph.metric.deadLinks": "死链",
    "graph.metric.leadShare": "头名份额 %",
    "graph.metric.leadRatio": "第一 / 第二",
  },
  en: {
    "graph.description":
      "A lens on the canonical structure: concentration, connectivity, family balance — and the structural difference between two snapshots.",

    "graph.tab.aria": "Structure lens",
    "graph.tab.health": "Structure health",
    "graph.tab.compare": "Compare in time",

    "graph.empty.title": "No structure to read yet",
    "graph.empty.description":
      "This knowledge base has not been compiled — add a source under Ingest and compile it; the structure comes out with the canon.",
    "graph.empty.action": "Go to Ingest",

    /* ------------------------------------------------------------------ health */

    "graph.health.summary":
      "{files} file{files||s} folded into {subjects} subject{subjects||s} · {claims} claim{claims||s} · {edges} internal link{edges||s}.",
    "graph.health.headline": "The {count} most abnormal thing{count||s}",
    "graph.health.clean":
      "Nothing over the line: no single-subject pile-up, no lopsided family, no unreachable subject.",
    "graph.health.rest": "{count} further reading{count||s} over the line — see the sections below.",
    "graph.health.openDocument": "Open the document",

    "graph.anomaly.concentration":
      "One subject, “{title}”, holds {share} of every claim in the base{ratio}",
    "graph.anomaly.concentration.ratio": " — {ratio}× the second-largest",
    "graph.anomaly.familyImbalance":
      "Family {family} has only {pages} page{pages||s} yet carries {share} of the claims — {factor}× its share of the pages",
    "graph.anomaly.zeroPageFamilies":
      "{count} declared famil{count|y|ies} have never taken a page ({declared} declared in all)",
    "graph.anomaly.arrivalBlind":
      "{count} subject{count||s} have nothing linking in ({share}) — findable only by already knowing the name",
    "graph.anomaly.deadEnd": "{count} subject{count||s} are dead ends ({share}) — the thread stops there",
    "graph.anomaly.orphanClaims": "{count} claim{count||s} sit behind a subject nothing links to ({share})",
    "graph.anomaly.deadLink": "{count} link{count||s} point at a document that does not exist",

    "graph.concentration.title": "Concentration",
    "graph.concentration.note":
      "Subjects by claim share; archive volumes count towards the page they belong to, because to a reader that is one subject.",
    "graph.concentration.lead": "Largest share",
    "graph.concentration.ratio": "First / second",
    "graph.concentration.tail": "The remaining {units} subject{units||s}",
    "graph.concentration.claims": "{count} claim{count||s}",
    "graph.concentration.volumes": "{count} archive volume{count||s} folded in",
    "graph.concentration.shareAria": "Claim share {share}",

    "graph.connectivity.title": "Connectivity",
    "graph.connectivity.note":
      "Same definitions as evaluation group D: arrival-blind = nothing links to it, dead end = it links to nothing.",
    "graph.connectivity.arrivalBlind": "Arrival-blind subjects",
    "graph.connectivity.deadEnd": "Dead-end subjects",
    "graph.connectivity.deadLinks": "Dead links",
    "graph.connectivity.orphanClaims": "Orphan claims",
    "graph.connectivity.arrivalBlindList": "Arrival-blind · no document links to these",
    "graph.connectivity.deadEndList": "Dead ends · these link to no document",
    "graph.connectivity.isolated": "{count} of them are both at once.",
    "graph.connectivity.clean":
      "The link structure closes: no dead links, and every subject has both a way in and a way on.",

    "graph.families.title": "Family balance",
    "graph.families.note":
      "Families are the path templates the skill declares. A family with no pages is a filing slot that was declared and never used, so it stays in the table.",
    "graph.families.family": "Family",
    "graph.families.pages": "Pages",
    "graph.families.claims": "Claims",
    "graph.families.claimShare": "Claim share",
    "graph.families.textShare": "Text share",
    "graph.families.zeroPage": "Families with no pages · {count}",
    "graph.families.unowned": "{count} subject{count||s} belong to no declared family.",
    "graph.families.unavailable":
      "The skill's declared path templates could not be read, so this section is unavailable.",

    /* ----------------------------------------------------------------- compare */

    "graph.compare.note":
      "The difference between two canonical projections, read as tables and lists — two illegible pictures side by side are only harder to read.",
    "graph.compare.before": "Baseline",
    "graph.compare.after": "Against",
    "graph.compare.head": "HEAD · live",
    "graph.compare.run": "Compare",
    "graph.compare.same": "Both sides name the same snapshot.",
    "graph.compare.none": "This knowledge base has no snapshot to compare against yet.",
    "graph.compare.loading": "Reading both canonical projections…",
    "graph.compare.error": "Could not read a snapshot",
    "graph.compare.deltaTitle": "Difference",
    "graph.compare.docsTitle": "Subjects gained and lost",
    "graph.compare.edgesTitle": "New internal links",
    "graph.compare.metric": "Metric",
    "graph.compare.added": "Gained · {count}",
    "graph.compare.removed": "Lost · {count}",
    "graph.compare.noDocChange": "Both sides hold exactly the same subjects.",
    "graph.compare.noNewEdges": "No new internal links.",
    "graph.compare.newEdgeMore": "{count} further new link{count||s} not listed.",

    "graph.metric.files": "Files",
    "graph.metric.subjects": "Subjects",
    "graph.metric.claims": "Claims",
    "graph.metric.edges": "Internal links",
    "graph.metric.arrivalBlind": "Arrival-blind subjects",
    "graph.metric.deadEnd": "Dead-end subjects",
    "graph.metric.orphanClaims": "Orphan claims",
    "graph.metric.deadLinks": "Dead links",
    "graph.metric.leadShare": "Largest share %",
    "graph.metric.leadRatio": "First / second",
  },
});
