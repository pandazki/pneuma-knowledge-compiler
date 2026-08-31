import { defineMessages } from "./define";

/**
 * Live Context: the config strip, the chat surface, the suggestion bubble and its two tabs,
 * and the synthetic preset workstreams.
 *
 * Two families of text are deliberately absent:
 *   - the closed vocabularies (`focus`, suggestion `kind`) live in ./enums, keyed by the
 *     stable key the API serves, and are rendered through `tOr` with the served label as the
 *     fallback;
 *   - a suggestion's `title` / `body` / `trigger` / citations are server payload — data, not
 *     copy — and are rendered verbatim.
 *
 * Wire-level names (`focus`, `min_confidence`, `turn_window`, `quiet_period`, `stats`,
 * `already_shown`, `want_more`, `flush`, `seq`, `confidence`) stay in code in both languages:
 * they are the protocol's own identifiers, and the bench exists to show them.
 */
export const liveContext = defineMessages({
  zh: {
    "liveContext.description":
      "持续接收工作流片段，自动检索相关证据并融合为可引用的上下文提示；没有足够证据时保持静默。",
    "liveContext.descriptionShort":
      "持续接收工作流片段，自动检索相关证据并融合为可引用的上下文提示。",
    "liveContext.noUser.title": "未选择用户",
    "liveContext.noUser.description":
      "在右上角选择一个 user_id。上下文提示只会引用该用户知识库里的真实来源；没有可靠证据时保持静默。",
    "liveContext.vocabError": "focus 词表拉取失败：{detail}",

    // ------------------------------------------------------------------ config strip
    "liveContext.config.title": "评估设置",
    "liveContext.config.mode": "投递方式",
    "liveContext.config.clearTurns": "清空对话",
    "liveContext.config.quietPeriod.label": "quiet_period（秒）",
    "liveContext.density.label": "提示密度",
    "liveContext.density.eager.label": "积极",
    "liveContext.density.eager.hint": "更多、更广的提示：门槛更低，看得更勤，反应更快。",
    "liveContext.density.balanced.label": "平衡",
    "liveContext.density.balanced.hint": "默认：既不抢话，也不错过明显值得说的东西。",
    "liveContext.density.quiet.label": "克制",
    "liveContext.density.quiet.hint": "更准、更少打扰：只在把握较大时才出声。",
    "liveContext.density.custom.label": "自定义",
    "liveContext.density.custom.hint": "当前这组数值不属于任何一档，原样保留——不会被就近吸附。",
    "liveContext.density.summary": "confidence {confidence} · 静默 {quiet}s · 待处理 {turns} 轮",
    "liveContext.card.evidence": "知识库原文",
    "liveContext.card.evidenceWeb": "网页原文",
    "liveContext.debug.intent": "意图：{intent}",
    "liveContext.skip.delivered": "已下发",
    "liveContext.skip.small_talk": "跳过·闲聊",
    "liveContext.skip.already_mined": "跳过·已挖掘",
    "liveContext.skip.nothing_new": "跳过·无新内容",
    "liveContext.skip.low_worth": "跳过·价值不足",
    "liveContext.skip.no_plan": "跳过·无检索计划",
    "liveContext.skip.no_candidates": "跳过·无候选",
    "liveContext.skip.no_coverage": "跳过·库里没有",
    "liveContext.skip.none_chosen": "跳过·一张都不选",
    "liveContext.skip.low_confidence": "跳过·置信不足",
    "liveContext.skip.uncited": "跳过·无引用",
    "liveContext.skip.duplicate": "跳过·同主体重复",
    "liveContext.skip.unparsed": "跳过·输出无法解析",
    "liveContext.skip.pick_failed": "跳过·挑选失败",
    "liveContext.skip.briefing_empty": "跳过·简报无卡",
    "liveContext.config.webSearch.label": "允许互联网搜索作为补充",
    "liveContext.config.webSearch.hint":
      "开启后，发现阶段可以多规划一路 web 查询；知识库一张候选都没给出时也会自动补一次。搜索结果与知识库候选同池，由同一次挑选决定选不选它，引用的是网页而不是来源块。按次计费。",
    "liveContext.config.webSearch.refused": "本部署没有开启互联网搜索，这一路仍然是关的。",
    "liveContext.card.webBadge": "互联网 Web",
    "liveContext.card.webNoExpand": "这张卡出自互联网搜索，展开请直接点下面的来源链接。",
    "liveContext.web.tier.off": "未走互联网",
    "liveContext.web.tier.planned": "互联网·计划内",
    "liveContext.web.tier.fallback": "互联网·库空兜底",
    "liveContext.web.line": "{tier} · 搜索 {searches} 次 · 引用 {pages} 页 · ${cost}",
    "liveContext.web.nopages": "这次搜索没有点名任何网页，答案因此被拒绝，没有成为候选。",
    "liveContext.config.stats.label": "stats 帧",
    "liveContext.config.stats.hint": "开启后每次评估都回一帧引用门禁账，包括一张卡都没下发的评估。",
    "liveContext.config.flush": "立即评估（flush）",
    "liveContext.config.flushTitle": "立即评估，跳过静默期",

    "liveContext.mode.oneshot": "一次性（SSE）",
    "liveContext.mode.stream": "长连接（WS）",
    "liveContext.mode.oneshotHint": "整段窗口攒好，按「评估一次」一并送出；每次都是全量重发。",
    "liveContext.mode.streamHint": "每发一条就推给服务端；何时评估由服务端的静默期决定。",

    "liveContext.summary.oneshot": "一次性",
    "liveContext.summary.acked": "策略已回执",
    "liveContext.summary.notAcked": "策略未回执",
    "liveContext.transport.open": "已连接",
    "liveContext.transport.connecting": "连接中…",
    "liveContext.transport.closed": "未连接",

    "liveContext.focus.label": "focus（注意力指向）",
    "liveContext.focus.option": "{label}（{key}）",
    "liveContext.focus.loading": "载入词表…",

    // ------------------------------------------------------------------------- roles
    "liveContext.role.owner": "本人",
    "liveContext.role.other": "对方",
    "liveContext.roles.add": "新增角色",
    "liveContext.roles.addTitle": "新增一个说话人",
    "liveContext.roles.cancel": "取消",
    "liveContext.roles.confirm": "确定",
    "liveContext.roles.nameLabel": "角色名",
    "liveContext.roles.namePlaceholder": "角色名…",
    "liveContext.roles.ownerNote": "知识主体：引用门禁会区别对待本人说的话，因此这个角色不可删除。",
    "liveContext.roles.ownerTitle": "知识主体（本人）",
    "liveContext.roles.pillTitle": "以「{name}」的身份说话",
    "liveContext.roles.remove": "删除该角色",
    "liveContext.roles.rename": "重命名",
    "liveContext.roles.colour": "改成{colour}",

    "liveContext.colour.slate": "青灰",
    "liveContext.colour.amber": "琥珀",
    "liveContext.colour.violet": "紫罗兰",
    "liveContext.colour.teal": "松绿",
    "liveContext.colour.rose": "玫红",
    "liveContext.colour.lime": "橄榄",

    // -------------------------------------------------------------------- the chat
    "liveContext.chat.title": "对话",
    "liveContext.chat.count": "{count} 轮",
    "liveContext.chat.empty": "还没有内容。选一个说话人，输入一条工作流片段。",
    "liveContext.chat.unknownRole": "未知说话人",
    "liveContext.chat.sent": "已发送",
    "liveContext.chat.edit": "编辑该轮",
    "liveContext.chat.saveEdit": "保存",
    "liveContext.chat.cancelEdit": "取消编辑",
    "liveContext.turn.text": "工作流片段",
    "liveContext.turn.remove": "删除该片段",

    "liveContext.compose.placeholder": "以「{role}」的身份说…",
    "liveContext.compose.send": "发送",
    "liveContext.compose.sendTitle": "立即推给服务端（长连接是追加式的，推出去就不能再改）",
    "liveContext.compose.add": "加入窗口",
    "liveContext.compose.addTitle": "加入本地窗口；按「评估一次」才会送出",
    "liveContext.compose.evaluate": "评估一次",
    "liveContext.compose.evaluateHint": "把整段窗口送去评估一次。",
    "liveContext.compose.streamHint": "长连接：每条发出即推送，服务端在静默期后自行评估。",

    // --------------------------------------------------------------- the suggestion
    "liveContext.bubble.emptyTitle": "还没有上下文提示",
    "liveContext.bubble.emptyDescription":
      "静默是正常工作状态：绝大多数对话根本不值得检索，一拍在发现阶段就会跳过，连索引都不碰。「处理状态」逐拍记下是哪一道门关上的，以及每一段花了多少毫秒。",
    "liveContext.bubble.countdownTitle": "{seconds} 秒后自动收起",
    "liveContext.bubble.pinnedTitle": "已固定，不会自动收起",
    "liveContext.bubble.queuedTitle": "还有 {count} 条排队，不会被覆盖",
    "liveContext.bubble.dismiss": "收起",
    "liveContext.bubble.dismissTitle": "收起这条，换下一条",
    "liveContext.bubble.wantMore": "想看更多",
    "liveContext.bubble.wantMoreTitle": "固定这条并走 want_more：取回引用原文再展开",
    "liveContext.bubble.expanding": "展开中…",
    "liveContext.bubble.pinnedNote": "已固定：收起前不会消失。",
    "liveContext.bubble.pinnedNoSocket": "已固定。展开需要长连接。",

    "liveContext.card.trigger": "触发：「{trigger}」",
    "liveContext.card.wantMoreDisabled": "want_more 只在长连接打开时可用",
    "liveContext.card.expandFailed": "展开失败：{detail}",
    "liveContext.card.detailEmpty": "（空）",

    "liveContext.deliveredCount": "下发 {count} 张",

    // ---------------------------------------------------------------------- the tabs
    "liveContext.tabs.aria": "提示记录与处理状态",
    "liveContext.tabs.history": "历史提示（{count}）",
    "liveContext.tabs.debug": "处理状态",
    "liveContext.history.empty": "还没有收起或过期的提示。",
    "liveContext.fate.expired": "已过期",
    "liveContext.fate.dismissed": "已收起",
    "liveContext.fate.pinned": "曾固定",

    "liveContext.debug.counts": "计数",
    "liveContext.debug.turnsSent": "已推送 {count} 轮",
    "liveContext.debug.evaluations": "评估 {count} 次",
    "liveContext.debug.suggestions": "收到 {count} 张",
    "liveContext.debug.deduped": "去重挡下 {count} 张",
    "liveContext.debug.queued": "排队 {count} 张",
    "liveContext.debug.readyEcho": "生效策略（服务端回执）",
    "liveContext.debug.gate": "逐拍记录",
    "liveContext.debug.gateEmpty": "还没有评估。开启 stats 后每次评估都会回一帧——包括零下发的那些。",
    "liveContext.debug.frames": "传输帧",
    "liveContext.debug.framesEmpty": "还没有收发记录。",

    // Synthetic, business-neutral bench material written in the front end.
    "liveContext.preset.speaker.owner": "本人",
    "liveContext.preset.speaker.collaborator": "协作者",
    "liveContext.preset.speaker.friend": "朋友",

    "liveContext.preset.releaseLicense.label": "开源许可",
    "liveContext.preset.releaseLicense.summary":
      "讨论里出现一个许可证概念，本人没有追问，系统应主动补充它的含义",
    "liveContext.preset.releaseLicense.expect": "期望 concept 卡（概念解释）",
    "liveContext.preset.releaseLicense.turn1":
      "发布前还要确认依赖许可证兼容性，特别是 copyleft 的传递范围。",
    "liveContext.preset.releaseLicense.turn2": "我先把依赖清单和生成代码的归属整理出来。",
    "liveContext.preset.releaseLicense.turn3":
      "README 里也最好解释一下 permissive license 和 copyleft 的区别。",

    "liveContext.preset.releaseProgress.label": "发布进度",
    "liveContext.preset.releaseProgress.summary":
      "讨论里出现一个知识库能直接回答的发布问题，系统应把事实递上来",
    "liveContext.preset.releaseProgress.expect": "期望 fact 卡（事实问答）",
    "liveContext.preset.releaseProgress.turn1": "当前项目的公开预览版推进到哪一步了？",
    "liveContext.preset.releaseProgress.turn2":
      "我记得已经跑过本地导出，但具体还缺哪一道发布检查一时想不起来。",
    "liveContext.preset.releaseProgress.turn3":
      "那你确认一下知识库里记录的引用门禁，别把未脱敏的实验记录打进公开包。",

    "liveContext.preset.smalltalk.label": "闲聊（对照组）",
    "liveContext.preset.smalltalk.summary": "没有任何值得补充的上下文——引用门禁的四道检查应当把一切挡掉",
    "liveContext.preset.smalltalk.expect": "期望 0 张卡：沉默是正常工作状态，不是故障",
    "liveContext.preset.smalltalk.turn1": "今天风挺大，出门走一圈比坐着舒服。",
    "liveContext.preset.smalltalk.turn2": "是啊，我准备工作告一段落就去散会儿步。",
    "liveContext.preset.smalltalk.turn3": "回来吃什么？楼下那家新开的还没试过。",
  },
  en: {
    "liveContext.description":
      "Takes in workstream fragments as they arrive, retrieves the relevant evidence and fuses it into citable context suggestions; stays silent when the evidence is not enough.",
    "liveContext.descriptionShort":
      "Takes in workstream fragments as they arrive, retrieves the relevant evidence and fuses it into citable context suggestions.",
    "liveContext.noUser.title": "No user selected",
    "liveContext.noUser.description":
      "Choose a user_id in the top right. A context suggestion only ever cites real sources from that user's knowledge base; without dependable evidence it stays silent.",
    "liveContext.vocabError": "Could not load the focus vocabulary: {detail}",

    // ------------------------------------------------------------------ config strip
    "liveContext.config.title": "Evaluation settings",
    "liveContext.config.mode": "Delivery",
    "liveContext.config.clearTurns": "Clear the conversation",
    "liveContext.config.quietPeriod.label": "quiet_period (seconds)",
    "liveContext.density.label": "Suggestion density",
    "liveContext.density.eager.label": "Eager",
    "liveContext.density.eager.hint":
      "More suggestions, and broader ones: a lower bar, a shorter look-again, a faster reaction.",
    "liveContext.density.balanced.label": "Balanced",
    "liveContext.density.balanced.hint":
      "The default: neither interrupting nor missing the obviously worth saying.",
    "liveContext.density.quiet.label": "Quiet",
    "liveContext.density.quiet.hint":
      "Sharper and less interrupting: it speaks only when it is fairly sure.",
    "liveContext.density.custom.label": "Custom",
    "liveContext.density.custom.hint":
      "These numbers match no preset, and they are kept as they are — never snapped to the nearest one.",
    "liveContext.density.summary":
      "confidence {confidence} · quiet {quiet}s · pending {turns} turns",
    "liveContext.card.evidence": "What the library says",
    "liveContext.card.evidenceWeb": "What the page says",
    "liveContext.debug.intent": "Intent: {intent}",
    "liveContext.skip.delivered": "delivered",
    "liveContext.skip.small_talk": "skipped · small talk",
    "liveContext.skip.already_mined": "skipped · already mined",
    "liveContext.skip.nothing_new": "skipped · nothing new",
    "liveContext.skip.low_worth": "skipped · not worth retrieving",
    "liveContext.skip.no_plan": "skipped · no lookup planned",
    "liveContext.skip.no_candidates": "skipped · nothing found",
    "liveContext.skip.no_coverage": "skipped · the library holds nothing",
    "liveContext.skip.none_chosen": "skipped · none chosen",
    "liveContext.skip.low_confidence": "skipped · under the floor",
    "liveContext.skip.uncited": "skipped · nothing carried it",
    "liveContext.skip.duplicate": "skipped · same subject again",
    "liveContext.skip.unparsed": "skipped · unparsable output",
    "liveContext.skip.pick_failed": "skipped · pick failed",
    "liveContext.skip.briefing_empty": "skipped · briefing had none",
    "liveContext.config.webSearch.label": "Allow internet search as a supplement",
    "liveContext.config.webSearch.hint":
      "With this on, the discover stage may plan a web lookup as well — and one runs anyway when the library returns no candidate at all. A web result joins the same candidate pool, is chosen or not by the same pick call, and cites pages rather than source blocks. Billed per search.",
    "liveContext.config.webSearch.refused":
      "This deployment has not enabled internet search, so the path stays off.",
    "liveContext.card.webBadge": "Web",
    "liveContext.card.webNoExpand":
      "This card came from an internet search — follow the source links below to read more.",
    "liveContext.web.tier.off": "no web lookup",
    "liveContext.web.tier.planned": "web · planned",
    "liveContext.web.tier.fallback": "web · library was empty",
    "liveContext.web.line": "{tier} · {searches} searches · {pages} pages · ${cost}",
    "liveContext.web.nopages": "This search named no page, so its answer was refused and never became a candidate.",
    "liveContext.config.stats.label": "stats frames",
    "liveContext.config.stats.hint":
      "With this on, every evaluation returns a citation gate ledger frame — including the evaluations that delivered nothing.",
    "liveContext.config.flush": "Evaluate now (flush)",
    "liveContext.config.flushTitle": "Evaluate immediately, skipping the quiet period",

    "liveContext.mode.oneshot": "One-shot (SSE)",
    "liveContext.mode.stream": "Long-lived (WS)",
    "liveContext.mode.oneshotHint":
      "Build the window up, then send it whole with “Evaluate once”. Every evaluation re-sends all of it.",
    "liveContext.mode.streamHint":
      "Each turn is pushed as it is sent; the server decides when to evaluate, after its quiet period.",

    "liveContext.summary.oneshot": "One-shot",
    "liveContext.summary.acked": "policy acknowledged",
    "liveContext.summary.notAcked": "policy not acknowledged",
    "liveContext.transport.open": "Connected",
    "liveContext.transport.connecting": "Connecting…",
    "liveContext.transport.closed": "Not connected",

    "liveContext.focus.label": "focus (where attention points)",
    "liveContext.focus.option": "{label} ({key})",
    "liveContext.focus.loading": "Loading the vocabulary…",

    // ------------------------------------------------------------------------- roles
    "liveContext.role.owner": "Owner",
    "liveContext.role.other": "Them",
    "liveContext.roles.add": "Add a speaker",
    "liveContext.roles.addTitle": "Add a speaker",
    "liveContext.roles.cancel": "Cancel",
    "liveContext.roles.confirm": "Confirm",
    "liveContext.roles.nameLabel": "Speaker name",
    "liveContext.roles.namePlaceholder": "Speaker name…",
    "liveContext.roles.ownerNote":
      "The knowledge subject: the citation gate treats the owner's own words differently, so this speaker cannot be removed.",
    "liveContext.roles.ownerTitle": "The knowledge subject (owner)",
    "liveContext.roles.pillTitle": "Speak as “{name}”",
    "liveContext.roles.remove": "Remove this speaker",
    "liveContext.roles.rename": "Rename",
    "liveContext.roles.colour": "Change to {colour}",

    "liveContext.colour.slate": "slate",
    "liveContext.colour.amber": "amber",
    "liveContext.colour.violet": "violet",
    "liveContext.colour.teal": "teal",
    "liveContext.colour.rose": "rose",
    "liveContext.colour.lime": "olive",

    // -------------------------------------------------------------------- the chat
    "liveContext.chat.title": "Conversation",
    "liveContext.chat.count": "{count} turn{count||s}",
    "liveContext.chat.empty":
      "Nothing here yet. Pick a speaker and type one workstream fragment.",
    "liveContext.chat.unknownRole": "Unknown speaker",
    "liveContext.chat.sent": "sent",
    "liveContext.chat.edit": "Edit this turn",
    "liveContext.chat.saveEdit": "Save",
    "liveContext.chat.cancelEdit": "Cancel the edit",
    "liveContext.turn.text": "Workstream fragment",
    "liveContext.turn.remove": "Delete this fragment",

    "liveContext.compose.placeholder": "Speak as “{role}”…",
    "liveContext.compose.send": "Send",
    "liveContext.compose.sendTitle":
      "Push to the server now. The long connection is append-only: once pushed, a turn cannot be changed",
    "liveContext.compose.add": "Add to the window",
    "liveContext.compose.addTitle": "Add to the local window; nothing is sent until you evaluate",
    "liveContext.compose.evaluate": "Evaluate once",
    "liveContext.compose.evaluateHint": "Sends the whole window for one evaluation.",
    "liveContext.compose.streamHint":
      "Long-lived: each turn is pushed as it is sent, and the server evaluates after its quiet period.",

    // --------------------------------------------------------------- the suggestion
    "liveContext.bubble.emptyTitle": "No context suggestions yet",
    "liveContext.bubble.emptyDescription":
      "Silence is the normal working state: most of what a conversation says is not worth a lookup, and a tick that decides so at the discover stage never touches an index at all. “Processing” records which door closed on every tick, and what each stage spent.",
    "liveContext.bubble.countdownTitle": "Closes on its own in {seconds}s",
    "liveContext.bubble.pinnedTitle": "Pinned — it will not close on its own",
    "liveContext.bubble.queuedTitle": "{count} more waiting; none will be overwritten",
    "liveContext.bubble.dismiss": "Dismiss",
    "liveContext.bubble.dismissTitle": "Dismiss this one and show the next",
    "liveContext.bubble.wantMore": "Want more",
    "liveContext.bubble.wantMoreTitle":
      "Pins this card and sends want_more: fetches the originals behind its citations and expands",
    "liveContext.bubble.expanding": "Expanding…",
    "liveContext.bubble.pinnedNote": "Pinned: it stays until you dismiss it.",
    "liveContext.bubble.pinnedNoSocket": "Pinned. Expanding needs the long connection.",

    "liveContext.card.trigger": "Trigger: “{trigger}”",
    "liveContext.card.wantMoreDisabled":
      "want_more is only available while the long connection is open",
    "liveContext.card.expandFailed": "Expansion failed: {detail}",
    "liveContext.card.detailEmpty": "(empty)",

    "liveContext.deliveredCount": "{count} delivered",

    // ---------------------------------------------------------------------- the tabs
    "liveContext.tabs.aria": "Suggestion history and processing state",
    "liveContext.tabs.history": "History ({count})",
    "liveContext.tabs.debug": "Processing",
    "liveContext.history.empty": "No dismissed or expired suggestions yet.",
    "liveContext.fate.expired": "expired",
    "liveContext.fate.dismissed": "dismissed",
    "liveContext.fate.pinned": "was pinned",

    "liveContext.debug.counts": "Counts",
    "liveContext.debug.turnsSent": "{count} turn{count||s} pushed",
    "liveContext.debug.evaluations": "{count} evaluation{count||s}",
    "liveContext.debug.suggestions": "{count} received",
    "liveContext.debug.deduped": "{count} held back as duplicates",
    "liveContext.debug.queued": "{count} queued",
    "liveContext.debug.readyEcho": "Policy in force (the server's echo)",
    "liveContext.debug.gate": "Per-tick record",
    "liveContext.debug.gateEmpty":
      "No evaluations yet. With stats on, every evaluation returns one — including those that delivered nothing.",
    "liveContext.debug.frames": "Transport frames",
    "liveContext.debug.framesEmpty": "Nothing sent or received yet.",

    // Synthetic, business-neutral bench material written in the front end.
    "liveContext.preset.speaker.owner": "Owner",
    "liveContext.preset.speaker.collaborator": "Collaborator",
    "liveContext.preset.speaker.friend": "Friend",

    "liveContext.preset.releaseLicense.label": "Open-source licensing",
    "liveContext.preset.releaseLicense.summary":
      "a licence concept surfaces and the owner never asks about it; the system should supply what it means",
    "liveContext.preset.releaseLicense.expect": "expect a concept card (an explanation)",
    "liveContext.preset.releaseLicense.turn1":
      "Before the release we still need to confirm the dependency licences are compatible, especially how far copyleft carries.",
    "liveContext.preset.releaseLicense.turn2":
      "I will start with the dependency list and the attribution for generated code.",
    "liveContext.preset.releaseLicense.turn3":
      "The README had better explain the difference between a permissive licence and copyleft as well.",

    "liveContext.preset.releaseProgress.label": "Release progress",
    "liveContext.preset.releaseProgress.summary":
      "a release question the knowledge base can answer directly surfaces; the system should hand the fact over",
    "liveContext.preset.releaseProgress.expect": "expect a fact card (a direct answer)",
    "liveContext.preset.releaseProgress.turn1": "How far has the current project's public preview got?",
    "liveContext.preset.releaseProgress.turn2":
      "I remember running the local export, but I cannot recall which release check is still outstanding.",
    "liveContext.preset.releaseProgress.turn3":
      "Then check the citation gates recorded in the knowledge base, and keep unredacted experiment notes out of the public package.",

    "liveContext.preset.smalltalk.label": "Small talk (the control)",
    "liveContext.preset.smalltalk.summary":
      "nothing here is worth adding — all four citation-gate checks should hold",
    "liveContext.preset.smalltalk.expect":
      "expect zero cards: silence is the normal working state, not a fault",
    "liveContext.preset.smalltalk.turn1":
      "Windy today — a walk outside beats sitting at a desk.",
    "liveContext.preset.smalltalk.turn2":
      "It is, I will go out for a bit once this stretch of work is done.",
    "liveContext.preset.smalltalk.turn3":
      "And afterwards? Neither of us has tried the new place downstairs.",
  },
});
