import { defineMessages } from "./define";

/**
 * The Live Context bench: the one-shot SSE panel, the long-lived WS panel, the suggestion
 * card, and the synthetic preset workstreams.
 *
 * Two families of text are deliberately absent:
 *   - the closed vocabularies (`focus`, suggestion `kind`) live in ./enums, keyed by the
 *     stable key the API serves, and are rendered through `tOr` with the served label as the
 *     fallback;
 *   - a suggestion's `title` / `body` / `trigger` / citations are server payload — data, not
 *     copy — and are rendered verbatim.
 *
 * Wire-level names (`focus`, `min_confidence`, `turn_window`, `quiet_period`, `stats`,
 * `already_shown`, `want_more`, `flush`, `as_of`, `seq`, `confidence`) stay in code in both
 * languages: they are the protocol's own identifiers, and the bench exists to show them.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
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
    "liveContext.transportAria": "实时上下文传输",
    "liveContext.tab.sse": "一次性 SSE",
    "liveContext.tab.ws": "长连接 WS",

    "liveContext.role.owner": "本人",
    "liveContext.role.other": "参与者",
    "liveContext.role.unknown": "未知",

    "liveContext.turn.speaker": "说话人",
    "liveContext.turn.role": "角色",
    "liveContext.turn.text": "工作流片段",
    "liveContext.turn.textPlaceholder": "输入一条工作流片段…",
    "liveContext.turn.remove": "删除该片段",

    "liveContext.focus.label": "focus（注意力指向）",
    "liveContext.focus.option": "{label}（{key}）",
    "liveContext.focus.loading": "载入词表…",

    "liveContext.cards.emptyTitle": "还没有上下文提示",
    "liveContext.cards.clear": "清空提示",
    "liveContext.gate.title": "门禁账",
    "liveContext.deliveredCount": "下发 {count} 张",

    "liveContext.sse.window.title": "工作流窗口",
    "liveContext.sse.window.add": "追加片段",
    "liveContext.sse.window.hint":
      "逐条录入会议、消息或协作片段，整段窗口一次性送入评估；focus 只改变注意力指向，不过滤上下文。",
    "liveContext.sse.params.title": "评估参数",
    "liveContext.sse.minConfidence.label": "min_confidence（服务端闸门）",
    "liveContext.sse.minConfidence.hint":
      "低于该置信度的卡片不会下发，计入丢弃原因 low_confidence。",
    "liveContext.sse.run": "送整段评估一次",
    "liveContext.sse.errorTitle": "评估失败",
    "liveContext.sse.cards.title": "上下文提示（{visible} / 已生成 {total}）",
    "liveContext.sse.cards.emptyDescription":
      "输入工作流片段并运行评估；解析失败、无引用、低置信或超限时都会保持静默，门禁账会记录原因。",
    "liveContext.sse.threshold.label": "本地再过滤阈值（software filter）",
    "liveContext.sse.threshold.hint":
      "纯前端过滤：confidence ≥ 阈值的已生成提示保留，不发任何请求。",
    "liveContext.sse.threshold.hidden": "本地阈值挡下 {count} 张（未重新请求）。",
    "liveContext.sse.streaming": "评估中，提示逐一到达…",

    "liveContext.ws.connection.title": "连接",
    "liveContext.ws.connect": "连接",
    "liveContext.ws.disconnect": "断开",
    "liveContext.ws.reconnect": "重连（回放）",
    "liveContext.ws.reconnectTitle":
      "断开后重连，并在 config 里回放窗口与已展示卡片（客户端是去重权威）",
    "liveContext.ws.status.open": "已连接",
    "liveContext.ws.status.connecting": "连接中…",
    "liveContext.ws.status.closed": "已断开",
    "liveContext.ws.closedNotice":
      "连接已断开。客户端是去重权威：重连时在 config 里回放已推送的 turns 与已下发卡片 already_shown，服务端跨断线不记任何事。",
    "liveContext.ws.config.title": "生效策略（config）",
    "liveContext.ws.quietPeriod.label": "quiet_period（秒）",
    "liveContext.ws.stats.label": "stats 帧",
    "liveContext.ws.stats.hint": "开启后每次评估都回一帧门禁账，包括一张卡都没下发的评估。",
    "liveContext.ws.config.liveNote": "连接打开时，改动实时推送 config。",
    "liveContext.ws.turns.title": "工作流片段",
    "liveContext.ws.flush": "立即评估（flush）",
    "liveContext.ws.flushTitle": "立即评估，跳过静默期",
    "liveContext.ws.send": "发送",
    "liveContext.ws.sentCount": "已推送 {count} 轮。",
    "liveContext.ws.defaultSpeaker": "对方",
    "liveContext.ws.cards.title": "上下文提示（{count}）",
    "liveContext.ws.cards.emptyDescription":
      "长连接的稳态是静默：服务端维护窗口、静默期与单在途合并；没有足够相关且可引用的证据时不会发送提示。开启 stats 后可查看门禁账。",
    "liveContext.ws.statsLog.title": "评估账（stats 历史）",
    "liveContext.ws.statsLog.empty":
      "还没有评估帧。stats 开启后每次评估都会回一帧——包括零下发的那些。",

    "liveContext.card.trigger": "触发：「{trigger}」",
    "liveContext.card.wantMore": "展开（want_more）",
    "liveContext.card.wantMoreRetry": "重试展开（want_more）",
    "liveContext.card.wantMoreTitle": "走 WS 的 want_more，基于本卡引用取原文再展开",
    "liveContext.card.wantMoreDisabled": "want_more 只在连接打开时可用",
    "liveContext.card.expandFailed": "展开失败：{detail}",
    "liveContext.card.detailEmpty": "（空）",

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
      "那你确认一下知识库里记录的门禁，别把未脱敏的实验材料打进公开包。",

    "liveContext.preset.smalltalk.label": "闲聊（对照组）",
    "liveContext.preset.smalltalk.summary": "没有任何值得补充的上下文——四道闸门应当把一切挡掉",
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
    "liveContext.transportAria": "Live context transport",
    "liveContext.tab.sse": "One-shot SSE",
    "liveContext.tab.ws": "Long-lived WS",

    "liveContext.role.owner": "Owner",
    "liveContext.role.other": "Participant",
    "liveContext.role.unknown": "Unknown",

    "liveContext.turn.speaker": "Speaker",
    "liveContext.turn.role": "Role",
    "liveContext.turn.text": "Workstream fragment",
    "liveContext.turn.textPlaceholder": "Type one workstream fragment…",
    "liveContext.turn.remove": "Delete this fragment",

    "liveContext.focus.label": "focus (where attention points)",
    "liveContext.focus.option": "{label} ({key})",
    "liveContext.focus.loading": "Loading the vocabulary…",

    "liveContext.cards.emptyTitle": "No context suggestions yet",
    "liveContext.cards.clear": "Clear suggestions",
    "liveContext.gate.title": "Gate ledger",
    "liveContext.deliveredCount": "{count} delivered",

    "liveContext.sse.window.title": "Workstream window",
    "liveContext.sse.window.add": "Add fragment",
    "liveContext.sse.window.hint":
      "Enter meeting, message or collaboration fragments one at a time; the whole window goes into a single evaluation. focus only redirects attention — it does not filter the context.",
    "liveContext.sse.params.title": "Evaluation parameters",
    "liveContext.sse.minConfidence.label": "min_confidence (the server-side gate)",
    "liveContext.sse.minConfidence.hint":
      "A card below this confidence is never delivered; it counts towards dropped.low_confidence.",
    "liveContext.sse.run": "Evaluate the window once",
    "liveContext.sse.errorTitle": "Evaluation failed",
    "liveContext.sse.cards.title": "Context suggestions ({visible} of {total} generated)",
    "liveContext.sse.cards.emptyDescription":
      "Enter workstream fragments and run an evaluation. Unparsed, uncited, low-confidence and capped output all end in silence, and the gate ledger records which one it was.",
    "liveContext.sse.threshold.label": "Local re-filter threshold (software filter)",
    "liveContext.sse.threshold.hint":
      "Client-side only: generated suggestions with confidence ≥ the threshold stay, and no request is sent.",
    "liveContext.sse.threshold.hidden": "The local threshold holds back {count} (nothing was re-requested).",
    "liveContext.sse.streaming": "Evaluating; suggestions arrive one at a time…",

    "liveContext.ws.connection.title": "Connection",
    "liveContext.ws.connect": "Connect",
    "liveContext.ws.disconnect": "Disconnect",
    "liveContext.ws.reconnect": "Reconnect (with replay)",
    "liveContext.ws.reconnectTitle":
      "Close and open again, replaying the window and the cards already shown in config (the client is the deduplication authority)",
    "liveContext.ws.status.open": "Connected",
    "liveContext.ws.status.connecting": "Connecting…",
    "liveContext.ws.status.closed": "Disconnected",
    "liveContext.ws.closedNotice":
      "The connection is closed. The client is the deduplication authority: on reconnect, config replays the turns already pushed and the cards already delivered as already_shown — the server remembers nothing across a disconnect.",
    "liveContext.ws.config.title": "Policy in force (config)",
    "liveContext.ws.quietPeriod.label": "quiet_period (seconds)",
    "liveContext.ws.stats.label": "stats frames",
    "liveContext.ws.stats.hint":
      "With this on, every evaluation returns a gate ledger frame — including the evaluations that delivered nothing.",
    "liveContext.ws.config.liveNote": "While the connection is open, a change pushes config straight away.",
    "liveContext.ws.turns.title": "Workstream fragments",
    "liveContext.ws.flush": "Evaluate now (flush)",
    "liveContext.ws.flushTitle": "Evaluate immediately, skipping the quiet period",
    "liveContext.ws.send": "Send",
    "liveContext.ws.sentCount": "{count} turn{count||s} pushed.",
    "liveContext.ws.defaultSpeaker": "Them",
    "liveContext.ws.cards.title": "Context suggestions ({count})",
    "liveContext.ws.cards.emptyDescription":
      "Silence is the steady state of a long-lived connection: the server keeps the window, the quiet period and single-in-flight coalescing, and sends nothing until the evidence is both relevant and citable. Turn stats on to read the gate ledger.",
    "liveContext.ws.statsLog.title": "Evaluation ledger (stats history)",
    "liveContext.ws.statsLog.empty":
      "No evaluation frames yet. With stats on, every evaluation returns one — including those that delivered nothing.",

    "liveContext.card.trigger": "Trigger: “{trigger}”",
    "liveContext.card.wantMore": "Expand (want_more)",
    "liveContext.card.wantMoreRetry": "Retry the expansion (want_more)",
    "liveContext.card.wantMoreTitle":
      "Sends want_more over the WS: fetches the originals behind this card's citations and expands",
    "liveContext.card.wantMoreDisabled": "want_more is only available while the connection is open",
    "liveContext.card.expandFailed": "Expansion failed: {detail}",
    "liveContext.card.detailEmpty": "(empty)",

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
      "Then check the gates recorded in the knowledge base, and keep unredacted experiment material out of the public package.",

    "liveContext.preset.smalltalk.label": "Small talk (the control)",
    "liveContext.preset.smalltalk.summary":
      "nothing here is worth adding — all four gates should hold",
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
