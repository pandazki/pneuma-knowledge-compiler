import { defineMessages } from "./define";

/**
 * The Sources chapter: the material catalogue, the four kind-specific readers (meeting /
 * document library / instant messages / email) and the compiler galley behind the second tab.
 *
 * Two notes on what is NOT here:
 *   - the names of the closed server vocabularies a catalogue row carries — kind, class and
 *     origin — all live in `enums.ts`, keyed by the wire value, so the chips, the readers and
 *     the density tooltip say the same word and an unknown value degrades to the wire value
 *     instead of to a blank.
 *   - the prefixes the readers parse out of normalised block text ("Owner (…)",
 *     "Attachments:") are NOT copy — they are the backend textualizer's wire format and stay
 *     in `views/sources/sourcePresentation.ts`.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
 */
export const sources = defineMessages({
  zh: {
    "sources.description":
      "浏览会议、文档库、即时消息与邮件的来源原貌；切换到编译校样可审计 intake plan、结构与 block 落点。",
    "sources.descriptionShort": "编译的输入：每条 source 的校样与消化态。",

    "sources.empty.noUser.title": "未选择用户",
    "sources.empty.noUser.description": "先在顶栏选择一个 user_id，再查看它的原料目录。",
    "sources.empty.none.title": "还没有原料",
    "sources.empty.none.description":
      "去「导入 Ingest」添加第一条 source，再回来查看它的校样页。",
    "sources.empty.none.action": "去导入",
    "sources.error.list": "加载原料目录失败",
    "sources.error.detail": "加载 source 详情失败",

    "sources.heatmap.title": "来源密度",
    "sources.heatmap.hint": "点一格只看当天",

    "sources.filter.aria": "原料过滤",
    "sources.filter.searchPlaceholder": "按标题搜索…",
    "sources.filter.searchAria": "按标题搜索原料目录",
    "sources.filter.count": "目录 · {total} 条",
    "sources.filter.narrowed": "目录 · {total} → {shown} 条",
    "sources.filter.clear": "清除过滤",
    "sources.filter.dimension.kind": "类型",
    "sources.filter.dimension.source_class": "性质",
    "sources.filter.dimension.origin": "来路",
    "sources.filter.chipAria": "{dimension}：{value}，{count} 条",
    "sources.filter.range": "时间",
    "sources.filter.rangeFrom": "起始日期",
    "sources.filter.rangeTo": "截止日期",
    "sources.filter.loading": "正在载入目录 · {loaded} / {total}",
    "sources.filter.noHits.title": "没有命中的原料",
    "sources.filter.noHits.description": "放宽关键词、类型或时间范围，或清除全部过滤。",

    "sources.list.aria": "原料目录",
    "sources.list.more": "再显示 {count} 条",
    "sources.list.shown": "已显示 {shown} / {hits} 条",
    "sources.list.openAria": "打开《{title}》的校样",

    "sources.timeline.occurred": "语料时间",
    "sources.timeline.ingested": "入库时间",
    "sources.timeline.ingestedHint": "这条原料没有语料时间，按入库日归位",

    "sources.detail.title": "来源校样",
    "sources.directory.digested": "已消化",
    "sources.directory.undigested": "未消化",

    "sources.exactSpan.title": "b{block} · 原文精确段",
    "sources.tabs.aria": "来源详情视图",
    "sources.tabs.source": "来源视图",
    "sources.tabs.compiler": "编译校样",

    "sources.compiler.plan": "编译计划",
    "sources.compiler.confirmTerm": "确认状态",
    "sources.compiler.confirmed": "用户已确认",
    "sources.compiler.proposed": "系统提案（未人工确认）",
    "sources.compiler.structure": "结构地图",
    "sources.compiler.blocks": "归一化原文 · {count} blocks",
    "sources.compiler.blocksHint": "点击块号取原文精确段",

    "sources.block.fetchAria": "取 block {index} 的原文精确段",
    "sources.block.fetchTitle": "取原文精确段",
    "sources.blockCount": "{count} blocks",
    "sources.owner": "本人",

    "sources.meeting.overview": "会议概览",
    "sources.meeting.date": "日期",
    "sources.meeting.window": "时段",
    "sources.meeting.minutes": "{count} 分钟",
    "sources.meeting.participants": "参与者",
    "sources.meeting.participantCount": "{count} 人",
    "sources.meeting.transcript": "转写",
    "sources.meeting.segmentCount": "{count} 段",
    "sources.meeting.attendees": "与会者",
    "sources.meeting.noParticipants": "未提供参与者元信息",
    "sources.meeting.agenda": "议程",
    "sources.meeting.noAgenda": "未提供会议议程",
    "sources.meeting.verbatim": "逐字稿",
    "sources.meeting.blockHint": "点击 block 编号取原文精确段",

    "sources.document.location": "Vault 定位",
    "sources.document.libraryFallback": "文档库",
    "sources.document.created": "创建 {time}",
    "sources.document.modified": "更新 {time}",
    "sources.document.noFrontmatter": "这篇文档没有 frontmatter",
    "sources.document.tags": "标签",
    "sources.document.noTags": "无标签",
    "sources.document.links": "双链",
    "sources.document.noLinks": "无出链",
    "sources.document.body": "文档正文",

    "sources.im.type.channel": "频道",
    "sources.im.type.dm": "私聊",
    "sources.im.type.group_dm": "多人私聊",
    "sources.im.type.other": "会话",
    "sources.im.context": "会话语境",
    "sources.im.summary": "{type} · {count} 条消息",
    "sources.im.log": "消息记录",
    "sources.im.threadHint": "线程回复保留缩进",
    "sources.im.unknownDate": "日期未知",
    "sources.im.edited": "已编辑",
    "sources.im.threadReply": "线程回复",

    "sources.email.thread": "邮件线程",
    "sources.email.countTerm": "邮件",
    "sources.email.count": "{count} 封",
    "sources.email.correspondents": "通信方",
    "sources.email.addressCount": "{count} 个地址",
    "sources.email.messages": "往来邮件",
    "sources.email.ordinal": "第 {index} 封",
    "sources.email.from": "发件人",
    "sources.email.to": "收件人",
    "sources.email.cc": "抄送",
    "sources.email.sentAt": "时间",
    "sources.email.addressSeparator": "，",

    "sources.generic.body": "原文",

    "sources.summary.meeting": "{participants} 位参与者 · {segments} 段转写",
    "sources.summary.document": "{count} 个正文块",
    "sources.summary.im": "{messages} 条消息 · {members} 位成员",
    "sources.summary.email": "{count} 封邮件",
    "sources.summary.generic": "{count} 个原文块",
  },
  en: {
    "sources.description":
      "Browse meetings, document libraries, instant messages and email as they arrived; switch to the compiler galley to audit the intake plan, the structure and where each block landed.",
    "sources.descriptionShort":
      "The compiler's input: the galley page and digest state of every source.",

    "sources.empty.noUser.title": "No user selected",
    "sources.empty.noUser.description":
      "Pick a user_id in the top bar to see its material catalogue.",
    "sources.empty.none.title": "No material yet",
    "sources.empty.none.description":
      "Add your first source under Ingest, then come back for its galley page.",
    "sources.empty.none.action": "Go to Ingest",
    "sources.error.list": "Could not load the material catalogue",
    "sources.error.detail": "Could not load the source detail",

    "sources.heatmap.title": "Source density",
    "sources.heatmap.hint": "Click a day to see only that day",

    "sources.filter.aria": "Catalogue filters",
    "sources.filter.searchPlaceholder": "Search titles…",
    "sources.filter.searchAria": "Search the source catalogue by title",
    "sources.filter.count": "Catalogue · {total}",
    "sources.filter.narrowed": "Catalogue · {total} → {shown}",
    "sources.filter.clear": "Clear filters",
    "sources.filter.dimension.kind": "Kind",
    "sources.filter.dimension.source_class": "Class",
    "sources.filter.dimension.origin": "Origin",
    "sources.filter.chipAria": "{dimension}: {value}, {count} item{count||s}",
    "sources.filter.range": "Time",
    "sources.filter.rangeFrom": "From date",
    "sources.filter.rangeTo": "To date",
    "sources.filter.loading": "Loading the catalogue · {loaded} / {total}",
    "sources.filter.noHits.title": "Nothing in the catalogue matches",
    "sources.filter.noHits.description":
      "Loosen the terms, the chips or the range — or clear the filter.",

    "sources.list.aria": "Source catalogue",
    "sources.list.more": "Show {count} more",
    "sources.list.shown": "Showing {shown} of {hits}",
    "sources.list.openAria": "Open the galley for {title}",

    "sources.timeline.occurred": "Corpus time",
    "sources.timeline.ingested": "Ingest time",
    "sources.timeline.ingestedHint":
      "This source carries no corpus time — it is placed by its import day",

    "sources.detail.title": "Source galley",
    "sources.directory.digested": "Digested",
    "sources.directory.undigested": "Not digested",

    "sources.exactSpan.title": "b{block} · exact source span",
    "sources.tabs.aria": "Source detail views",
    "sources.tabs.source": "Source view",
    "sources.tabs.compiler": "Compiler galley",

    "sources.compiler.plan": "Compile plan",
    "sources.compiler.confirmTerm": "Confirmation",
    "sources.compiler.confirmed": "Confirmed by the user",
    "sources.compiler.proposed": "System proposal (not confirmed by hand)",
    "sources.compiler.structure": "Structure map",
    "sources.compiler.blocks": "Normalised text · {count} block{count||s}",
    "sources.compiler.blocksHint": "Click a block number for its exact source span",

    "sources.block.fetchAria": "Fetch the exact source span for block {index}",
    "sources.block.fetchTitle": "Fetch the exact source span",
    "sources.blockCount": "{count} block{count||s}",
    "sources.owner": "owner",

    "sources.meeting.overview": "Meeting overview",
    "sources.meeting.date": "Date",
    "sources.meeting.window": "Window",
    "sources.meeting.minutes": "{count} min",
    "sources.meeting.participants": "Participants",
    "sources.meeting.participantCount": "{count} {count|person|people}",
    "sources.meeting.transcript": "Transcript",
    "sources.meeting.segmentCount": "{count} segment{count||s}",
    "sources.meeting.attendees": "Attendees",
    "sources.meeting.noParticipants": "No participant metadata provided",
    "sources.meeting.agenda": "Agenda",
    "sources.meeting.noAgenda": "No agenda provided",
    "sources.meeting.verbatim": "Verbatim transcript",
    "sources.meeting.blockHint": "Click a block number for its exact source span",

    "sources.document.location": "Vault location",
    "sources.document.libraryFallback": "Document library",
    "sources.document.created": "Created {time}",
    "sources.document.modified": "Updated {time}",
    "sources.document.noFrontmatter": "This document has no frontmatter",
    "sources.document.tags": "Tags",
    "sources.document.noTags": "No tags",
    "sources.document.links": "Wikilinks",
    "sources.document.noLinks": "No outgoing links",
    "sources.document.body": "Document body",

    "sources.im.type.channel": "Channel",
    "sources.im.type.dm": "Direct message",
    "sources.im.type.group_dm": "Group message",
    "sources.im.type.other": "Conversation",
    "sources.im.context": "Conversation context",
    "sources.im.summary": "{type} · {count} message{count||s}",
    "sources.im.log": "Message log",
    "sources.im.threadHint": "Thread replies keep their indent",
    "sources.im.unknownDate": "Date unknown",
    "sources.im.edited": "Edited",
    "sources.im.threadReply": "Thread reply",

    "sources.email.thread": "Email thread",
    "sources.email.countTerm": "Emails",
    "sources.email.count": "{count} message{count||s}",
    "sources.email.correspondents": "Correspondents",
    "sources.email.addressCount": "{count} address{count||es}",
    "sources.email.messages": "Correspondence",
    "sources.email.ordinal": "Message {index}",
    "sources.email.from": "From",
    "sources.email.to": "To",
    "sources.email.cc": "Cc",
    "sources.email.sentAt": "Sent",
    "sources.email.addressSeparator": ", ",

    "sources.generic.body": "Original text",

    "sources.summary.meeting":
      "{participants} participant{participants||s} · {segments} transcript segment{segments||s}",
    "sources.summary.document": "{count} body block{count||s}",
    "sources.summary.im": "{messages} message{messages||s} · {members} member{members||s}",
    "sources.summary.email": "{count} email{count||s}",
    "sources.summary.generic": "{count} source block{count||s}",
  },
});
