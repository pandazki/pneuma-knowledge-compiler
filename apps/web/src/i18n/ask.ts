import { defineMessages } from "./define";

/**
 * The Ask view: build a briefing (a frozen knowledge pack), then keep questioning it.
 *
 * `scope.query` / `scope.source_ids` / `budget_chars` / `briefing_id` / `verbatim_fetches`
 * stay in place as written — they are the request and response field names, not copy. The
 * source-kind filter carries its OWN labels rather than reusing `enum.sourceKind.*`, because
 * the original Chinese here is the bilingual short form ("会议 Meeting"), which the Sources
 * readers do not use.
 */
export const ask = defineMessages({
  zh: {
    "ask.title": "问答 Ask",
    "ask.description":
      "把一批断言（claim）冻结成 briefing 知识包，再对它连续提问——每轮答案都带引用脚注与 token 账。",
    "ask.descriptionShort": "构建 briefing，然后连续提问。",

    "ask.noUser.title": "未选择用户",
    "ask.noUser.description": "在右上角选择一个 user_id 后，即可构建 briefing 并连续提问。",

    "ask.blank": "（空）",

    "ask.build.title": "构建 briefing",
    "ask.build.queryLabel": "scope.query（检索范围）",
    "ask.build.queryPlaceholder": "可选：一句检索意图",
    "ask.build.queryHint": "query 与来源多选至少填一项。",
    "ask.build.sourcesLabel": "scope.source_ids（锚定原始来源）",
    "ask.build.selectedLabel": "已选",
    "ask.build.matchLabel": "当前结果",
    "ask.build.searchAria": "搜索来源",
    "ask.build.searchPlaceholder": "按来源标题搜索",
    "ask.build.kindAria": "筛选来源类型",
    "ask.build.kind.all": "全部类型",
    "ask.build.kind.meeting": "会议 Meeting",
    "ask.build.kind.documentLibrary": "文档库 Document",
    "ask.build.kind.im": "即时消息 IM",
    "ask.build.kind.email": "邮件 Email",
    "ask.build.selectedSummary": "已选来源 ·",
    "ask.build.remove": "移除",
    "ask.build.sourcesError": "来源列表拉取失败",
    "ask.build.noMatch": "当前筛选没有匹配来源；可清空搜索或切换来源类型。",
    "ask.build.noSources": "（无来源——可只靠 query 构建；或先去「导入 Ingest」入库来源）",
    "ask.build.sourceNoun": "条 source",
    "ask.build.budgetLabel": "budget_chars（字符预算）",
    "ask.build.snapshotLabel": "快照：",
    "ask.build.snapshotReadOnly": "（历史只读）",
    "ask.build.snapshotHead": "当前 HEAD",
    "ask.build.error": "构建失败",
    "ask.build.action": "构建 briefing",

    "ask.history.title": "历史 briefing",
    "ask.history.error": "历史拉取失败",
    "ask.history.empty": "还没有构建过 briefing。",
    "ask.history.noTime": "（无时间）",
    "ask.history.chars": "{count} 字",
    "ask.history.hint": "选中一条即可在它的知识包上继续提问。",

    "ask.text.show": "查看详情",
    "ask.text.hide": "收起详情",
    "ask.text.error": "briefing 正文拉取失败",
    "ask.text.empty": "（这份 briefing 正文为空）",
    "ask.text.metrics": "{chars} 字 · {lines} 行",

    "ask.stages.buildDescription":
      "构建这份 briefing 每一步的实测墙钟：retrieve 是检索（括号内为断言与正文两次查询，它们先后执行，相加即为 retrieve），expand 是把命中扩成带出处的证据（上下文窗口、来源卡、引用反查、L0 原文），pack 是按预算拼装。整个构建没有模型调用；标为「未执行」的那一半，是这次 scope 里根本没有的那一半。",
    "ask.stages.askDescription":
      "这一轮提问每一步的实测墙钟，按发生顺序排列：turn:N 是一次模型思考，tool:X 是它调用的一件工具，finalize 表示预算耗尽后被迫收尾。total 只收口这一轮的循环——知识包是早先构建的，不计在内。",

    "ask.build.disabledHint": "先写一句检索问题，或在上面勾选至少一条来源。",

    "ask.current.title": "当前 briefing",
    "ask.current.rebuild": "重新构建 briefing",
    "ask.current.anchoredSources": "锚定来源",
    "ask.current.chars": "字符",

    "ask.thread.title": "连续问答",
    "ask.thread.emptyTitle": "还没有提问",
    "ask.thread.emptyDescription":
      "在下方输入问题——briefing 问法复用冻结的知识包，每轮答案都带引用脚注。",
    "ask.thread.noCitations": "本轮没有返回 source 引用；答案可阅读，但尚未完成证据绑定。",
    "ask.thread.verbatim": "verbatim_fetches（{count}）",
    "ask.thread.error": "提问失败",
    "ask.thread.placeholder": "对当前 briefing 提问",
    "ask.thread.aria": "提问",
    "ask.thread.action": "提问",
  },
  en: {
    "ask.title": "Ask",
    "ask.description":
      "Freeze a set of claims into a briefing, then keep questioning it — every answer carries citation footnotes and a token ledger.",
    "ask.descriptionShort": "Build a briefing, then keep asking.",

    "ask.noUser.title": "No user selected",
    "ask.noUser.description":
      "Choose a user_id in the top right to build a briefing and start asking.",

    "ask.blank": "(empty)",

    "ask.build.title": "Build a briefing",
    "ask.build.queryLabel": "scope.query (retrieval scope)",
    "ask.build.queryPlaceholder": "Optional: one line of search intent",
    "ask.build.queryHint": "Give a query, pick sources, or both — at least one.",
    "ask.build.sourcesLabel": "scope.source_ids (anchored to raw sources)",
    "ask.build.selectedLabel": "Selected",
    "ask.build.matchLabel": "found",
    "ask.build.searchAria": "Search sources",
    "ask.build.searchPlaceholder": "Search by source title",
    "ask.build.kindAria": "Filter by source kind",
    "ask.build.kind.all": "All kinds",
    "ask.build.kind.meeting": "Meeting",
    "ask.build.kind.documentLibrary": "Document library",
    "ask.build.kind.im": "Instant messages",
    "ask.build.kind.email": "Email",
    "ask.build.selectedSummary": "Selected sources ·",
    "ask.build.remove": "Remove",
    "ask.build.sourcesError": "Could not load the source list",
    "ask.build.noMatch":
      "No source matches the current filter; clear the search or switch the kind.",
    "ask.build.noSources":
      "(no sources — a query alone is enough to build, or file a source through Ingest first)",
    "ask.build.sourceNoun": "sources",
    "ask.build.budgetLabel": "budget_chars (character budget)",
    "ask.build.snapshotLabel": "Snapshot: ",
    "ask.build.snapshotReadOnly": " (historical, read-only)",
    "ask.build.snapshotHead": "current HEAD",
    "ask.build.error": "Build failed",
    "ask.build.action": "Build briefing",

    "ask.history.title": "Past briefings",
    "ask.history.error": "Could not load the history",
    "ask.history.empty": "No briefing built yet.",
    "ask.history.noTime": "(no timestamp)",
    "ask.history.chars": "{count} char{count||s}",
    "ask.history.hint": "Pick one to carry on asking against its knowledge pack.",

    "ask.text.show": "View text",
    "ask.text.hide": "Hide text",
    "ask.text.error": "Could not load the briefing text",
    "ask.text.empty": "(this briefing's text is empty)",
    "ask.text.metrics": "{chars} char{chars||s} · {lines} line{lines||s}",

    "ask.stages.buildDescription":
      "Measured wall-clock per step of building this briefing: `retrieve` is the lookups (in brackets, the claim face and the body face — they run in sequence here, so they add up to `retrieve`), `expand` turns hits and anchored sources into evidence with provenance (context windows, source cards, the citation reverse lookup, L0 text), `pack` is the budgeted assembly. No model runs in a build; a stage marked \"not run\" is a half this scope simply did not have.",
    "ask.stages.askDescription":
      "Measured wall-clock per step of this question, in the order it happened: `turn:N` is one model turn, `tool:X` a tool it reached for, `finalize` a closing call forced by the tool budget. `total` wraps this round's loop only — the knowledge pack was built earlier and is not inside it.",

    "ask.build.disabledHint":
      "Write a gathering query, or tick at least one source above.",

    "ask.current.title": "Current briefing",
    "ask.current.rebuild": "Build another briefing",
    "ask.current.anchoredSources": "anchored sources",
    "ask.current.chars": "characters",

    "ask.thread.title": "Ongoing questions",
    "ask.thread.emptyTitle": "No questions yet",
    "ask.thread.emptyDescription":
      "Type a question below — the briefing lane reuses the frozen knowledge pack, and every answer carries citation footnotes.",
    "ask.thread.noCitations":
      "This round returned no source citations; the answer is readable, but its evidence is not yet bound.",
    "ask.thread.verbatim": "verbatim_fetches ({count})",
    "ask.thread.error": "Asking failed",
    "ask.thread.placeholder": "Ask the current briefing",
    "ask.thread.aria": "Question",
    "ask.thread.action": "Ask",
  },
});
