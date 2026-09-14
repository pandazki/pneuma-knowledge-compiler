import { defineMessages } from "./define";

/**
 * The structure lens (route `#/lens`): the report the service derives over the whole
 * canonical library, read, and the same report at two refs, subtracted.
 *
 * Two families of key live here and they are read differently.
 *
 * The `lens.<surface>.*` keys are ordinary view copy. The `lens.<lens id>.impact` /
 * `.action` keys are the PROMPT CATALOGUE's, keyed identically (docs/design/structure-lens.md
 * §3.2): a finding arrives carrying `{key, fields}`, and the console renders that key through
 * this table so the Chinese reader gets Chinese and the wording stays the console's. They are
 * looked up through `useTOr`, because the key is data at runtime — a lens id this console has
 * never heard of renders as the key and its fields rather than as a blank line.
 *
 * The impact and action sentences deliberately carry NO placeholders. Every concrete number,
 * path and quotation a finding has is already on the row beneath the sentence — its pages, its
 * targets, its evidence — and a sentence that interpolated a field this client guessed wrong
 * would read as a broken template. Interpolation still works if a future wording wants it.
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

    /* ------------------------------------------------- the catalogue · navigability */

    "lens.nav.dead_end.impact": "线索走到这页就停了：读完它的人没有下一处可去。",
    "lens.nav.dead_end.action": "把这页已经在谈的那一两个主体写成链接。",
    "lens.nav.arrival_blind.impact": "没有任何页链向它：只有已经知道它叫什么的人才找得到。",
    "lens.nav.arrival_blind.action": "在提到它的那几页里，把它的名字改成链接。",
    "lens.nav.dead_link.impact": "这条链接指向一篇不存在的文档，跟过去落在空处。",
    "lens.nav.dead_link.action": "改指到真实存在的路径，或删掉它；引用门禁从此拒收新的死链。",
    "lens.nav.hub_incomplete.impact": "族首页漏掉了自己名下的页：从入口进来的人看不见它们。",
    "lens.nav.hub_incomplete.action": "在族首页补上漏掉的那几页的链接。",
    "lens.nav.chronology_unlinked.impact":
      "编年页记着事情如何变化，却不通向它讲的那些特性与决策页。",
    "lens.nav.chronology_unlinked.action": "在相应的日期段落里，把它谈到的特性或决策写成链接。",
    "lens.nav.decision_unlinked.impact": "一条决策不指向它决定的任何东西，读者无从确认它落在了哪里。",
    "lens.nav.decision_unlinked.action": "链接这条决策影响的特性、编年或族首页。",
    "lens.nav.mention_unlinked.impact": "反复写着另一个主体的名字，却一次也没链过去。",
    "lens.nav.mention_unlinked.action": "把第一次提到的地方改成链接，其余保持原样。",
    "lens.nav.island.impact": "这个项目自成孤岛：与库里其他任何页都不相往来，只有直接打开才读得到。",
    "lens.nav.island.action": "裁定它该挂在哪里——并进某个族，或从一个现有入口页接上它。",

    /* ------------------------------------------------------ the catalogue · identity */

    "lens.id.title_duplicate.impact": "同一个标题落在两篇在世文档上：检索与链接有一半会指错。",
    "lens.id.title_duplicate.action": "裁定哪一篇是这个主体，另一篇改名或并入。",
    "lens.id.title_child_collision.impact": "这页和它名下的一页同名，父子在任何列表里都分不开。",
    "lens.id.title_child_collision.action": "用 retitle 给其中一页一个属于它自己的名字。",
    "lens.id.title_degenerate.impact": "标题只是一个角色词或路径名，没有说这页讲的是什么。",
    "lens.id.title_degenerate.action": "改成这页真正的主体名。",
    "lens.id.title_shared_with_hub.impact": "编年页与族首页同名，读者分不出哪一篇是入口。",
    "lens.id.title_shared_with_hub.action": "给编年页一个说明它是编年的名字。",

    /* ---------------------------------------------------------- the catalogue · form */

    "lens.form.collapsed_body.impact": "正文压成了一整行——换行被写成了字面的两个字符 \\n——读起来是一堵墙。",
    "lens.form.collapsed_body.action": "用真正的换行重写这一块；工具面从此拒收新的。",
    "lens.form.stray_heading.impact": "正文中间有一个一级标题，取标题的那一读会把它当成这页的名字。",
    "lens.form.stray_heading.action": "把它降级或删掉；页名用 retitle 改。",
    "lens.form.unanchored_citation.impact": "这条引用不挂在任何锚点上：从它回不到具体哪一条断言。",
    "lens.form.unanchored_citation.action": "把它并进它所属的断言块，或删掉。",
    "lens.form.overview_restates.impact": "概览原样抄了台账里的一条断言，这一格没有比下面多说任何东西。",
    "lens.form.overview_restates.action": "把这一格改写成它自己的话，或让它引用那条断言。",
    "lens.form.legacy_sections.impact": "概览头之下还留着旧版分节，同一件事写了两遍。",
    "lens.form.legacy_sections.action": "把还有用的内容并进概览四格，删掉剩下的分节。",
    "lens.form.definition_empty.impact": "定义格里只有引用和锚点，没有一句说明这是什么。",
    "lens.form.definition_empty.action": "补上那一句定义，或清空这一格。",
    "lens.form.unordered_chronology.impact": "编年页的日期不按时间排：它记下的是导入顺序，不是发生顺序。",
    "lens.form.unordered_chronology.action": "按日期重排这些段落，重复的日期并成一段。",

    /* ------------------------------------------- the catalogue · balance, corroboration */

    "lens.conc.catch_all.impact": "一个主体吞下了全库很大一块断言：命中它，跟命中整座库差不了多少。",
    "lens.conc.catch_all.action": "裁定它该拆成哪几个主体，交由一次 evolve 落实。",
    "lens.bal.family_heavy.impact": "一个族用很少的页扛着全库大部分断言：结构没跟上内容。",
    "lens.bal.family_heavy.action": "考虑给这个族增设路径模板，让它的页分得开。",
    "lens.bal.family_empty.impact": "一个申报的族一页都没有：要么还没到时候，要么它本来就不该在契约里。",
    "lens.bal.family_empty.action": "决定是给它写第一页，还是把这个模板从契约里去掉。",
    "lens.bal.session_shaped.impact":
      "这页大半的断言都是一条来源加一个日期：它更像会话流水，而不是一个主体的知识。",
    "lens.bal.session_shaped.action":
      "先回答它是主体还是日志；若是主体，把耐久的结论提上来，流水留给编年页。",
    "lens.corr.single_source.impact": "这页知道的一切都出自同一条来源，没有第二处印证它。",
    "lens.corr.single_source.action": "编译另一条谈同一主体的来源，或在页上写明目前只有这一条。",
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

    /* ------------------------------------------------- the catalogue · navigability */

    "lens.nav.dead_end.impact": "The thread stops here: a reader who finishes this page has nowhere to go next.",
    "lens.nav.dead_end.action": "Link the one or two subjects this page already talks about.",
    "lens.nav.arrival_blind.impact":
      "Nothing links here: it is findable only by someone who already knows its name.",
    "lens.nav.arrival_blind.action": "On the pages that already mention it, turn the name into a link.",
    "lens.nav.dead_link.impact": "This link points at a document that does not exist; following it lands nowhere.",
    "lens.nav.dead_link.action":
      "Repoint it at a path that exists, or remove it; the gate refuses new dead links from now on.",
    "lens.nav.hub_incomplete.impact":
      "The family's hub leaves out pages of its own subtree, so arriving at the entrance does not show them.",
    "lens.nav.hub_incomplete.action": "Add the missing pages to the hub.",
    "lens.nav.chronology_unlinked.impact":
      "The chronology records how things changed but never links the feature and decision pages it is about.",
    "lens.nav.chronology_unlinked.action":
      "Link the feature or decision page from the dated section that discusses it.",
    "lens.nav.decision_unlinked.impact":
      "A decision points at nothing it decided, so a reader cannot see where it landed.",
    "lens.nav.decision_unlinked.action": "Link the feature, chronology or hub this decision affects.",
    "lens.nav.mention_unlinked.impact": "It writes another subject's name again and again and never links to it.",
    "lens.nav.mention_unlinked.action": "Make the first mention a link and leave the rest as prose.",
    "lens.nav.island.impact":
      "This project is an island: nothing outside it links in or out, so it is reachable only by opening it directly.",
    "lens.nav.island.action":
      "Decide where it belongs: fold it into a family, or give it a way in from an existing page.",

    /* ------------------------------------------------------ the catalogue · identity */

    "lens.id.title_duplicate.impact":
      "One title on two live documents: retrieval and links reach the wrong one half the time.",
    "lens.id.title_duplicate.action": "Decide which page is the subject, and rename or merge the other.",
    "lens.id.title_child_collision.impact":
      "This page shares its title with a page beneath it, so parent and child are indistinguishable in any listing.",
    "lens.id.title_child_collision.action": "Give one of them a name of its own with retitle.",
    "lens.id.title_degenerate.impact": "The title is a role word or a path, and says nothing about what the page holds.",
    "lens.id.title_degenerate.action": "Rename it after the subject it actually holds.",
    "lens.id.title_shared_with_hub.impact":
      "The chronology carries the hub's title, so neither of them reads as the way in.",
    "lens.id.title_shared_with_hub.action": "Rename the chronology so that it says what it is.",

    /* ---------------------------------------------------------- the catalogue · form */

    "lens.form.collapsed_body.impact":
      "The body collapsed into one line — its breaks were written as the two characters \\n — and reads as a wall.",
    "lens.form.collapsed_body.action": "Rewrite the block with real line breaks; the tool face refuses new ones.",
    "lens.form.stray_heading.impact":
      "A top-level heading sits inside the body, where a title read takes it for the page's name.",
    "lens.form.stray_heading.action": "Demote or drop the heading; a page is renamed with retitle.",
    "lens.form.unanchored_citation.impact":
      "The citation hangs off no anchor, so there is no way back from it to a claim.",
    "lens.form.unanchored_citation.action": "Fold it into the claim block it belongs to, or remove it.",
    "lens.form.overview_restates.impact":
      "The overview repeats a ledger claim word for word, so the slot adds nothing to what is below it.",
    "lens.form.overview_restates.action": "Rewrite the slot in its own words, or have it cite the claim instead.",
    "lens.form.legacy_sections.impact":
      "Old-format sections still sit below the overview head, saying the same things twice.",
    "lens.form.legacy_sections.action":
      "Fold what is still useful into the four overview slots and drop the leftover sections.",
    "lens.form.definition_empty.impact":
      "The definition slot holds references and anchors but not one sentence saying what this is.",
    "lens.form.definition_empty.action": "Write the defining sentence, or clear the slot.",
    "lens.form.unordered_chronology.impact":
      "The dated sections are not in time order: they record the order things were ingested, not the order they happened.",
    "lens.form.unordered_chronology.action": "Reorder the sections by date and merge the repeated ones.",

    /* ------------------------------------------- the catalogue · balance, corroboration */

    "lens.conc.catch_all.impact":
      "One subject has swallowed a large part of the base: retrieving it is barely narrower than retrieving everything.",
    "lens.conc.catch_all.action": "Decide which subjects it should split into, and let an evolve carry it out.",
    "lens.bal.family_heavy.impact":
      "A family carries most of the base's claims on very few pages: the structure has not kept up with the content.",
    "lens.bal.family_heavy.action": "Consider new path templates for the family, so its pages can separate.",
    "lens.bal.family_empty.impact":
      "A declared family has never taken a page: either its time has not come, or it does not belong in the contract.",
    "lens.bal.family_empty.action": "Decide whether to write its first page or to drop the template from the contract.",
    "lens.bal.session_shaped.impact":
      "Most of its claims are one source and one date each: this reads as a log of sessions rather than as knowledge about a subject.",
    "lens.bal.session_shaped.action":
      "Answer first whether this is a subject or a log; if it is a subject, lift the durable conclusions out and leave the narration to the chronology.",
    "lens.corr.single_source.impact": "Everything this page knows comes from one source, and nothing corroborates it.",
    "lens.corr.single_source.action":
      "Compile another source that speaks to the same subject, or say on the page that one is all there is.",
  },
});
