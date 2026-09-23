import { defineMessages } from "./define";

/**
 * The call: a voice conversation with the library, inside the Steward view.
 *
 * The copy has one job the other surfaces do not: a reader must be able to tell the LIBRARY's
 * answer from the voice model's paraphrase of it. So the two sides are named differently
 * throughout — the cards are 「知识库的回答」, and a stretch of speech the library did not
 * supply carries 「未查库」 — and nothing here ever calls the voice's words an answer.
 */
export const call = defineMessages({
  zh: {
    "call.details": "通话详情",
    "call.readyToTalk": "已接通，可以说话了。",
    "call.micOn": "麦克风已开启",
    "call.cancel": "取消",
    "call.error.micDenied": "请在浏览器中允许麦克风访问，然后重试。",
    "call.error.noMicrophone": "没有找到麦克风，请连接后重试。",

    "call.trace.title": "委托时间线与回写原文",
    "call.trace.first": "首段局部发现（保留原文）",
    "call.trace.note": "时间以收到委托为零点。回执仅表示估计的上下文注入，不代表已经播报。",
    "call.trace.ack": "收到回执 +{time} 秒 · 通话注入区间 {start}–{end} 秒",
    "call.trace.speech": "同期 Live 转写（按时间展示，不代表逐条回写已播报）",
    "call.trace.change": "主人修正 / 取消检查",
    "call.trace.export": "导出本次委托记录",
    "call.trace.sent": "已发送，等待回执",
    "call.trace.acknowledged": "已回执",
    "call.trace.rejected": "被拒绝",
    "call.trace.sending": "发送中",

    "call.open": "通话",
    "call.open.unavailable": "现在不能通话。",
    "call.back": "返回管家",
    "call.leave": "结束并返回",
    "call.title": "和知识库通话",
    "call.description": "直接提问，一起查阅你的知识库。",

    "call.phase.idle": "未开始",
    "call.phase.askingMic": "等待麦克风授权…",
    "call.phase.connecting": "接通中…",
    "call.phase.live": "通话中",
    "call.phase.ending": "挂断中…",
    "call.phase.ended": "通话已结束",
    "call.phase.failed": "没能接通",

    "call.start": "开始通话",
    "call.start.note": "约 $0.05/分钟 · 开始后请求麦克风权限",
    "call.again": "再打一次",
    "call.end": "挂断",
    "call.mute": "静音",
    "call.unmute": "取消静音",
    "call.muted": "麦克风已静音",
    "call.elapsed": "已通话 {time}",
    "call.cost": "约 {cost}",
    "call.context": "上下文 {percent}%",
    "call.model": "{model} · {voice}",
    "call.audioBlocked": "点这里听声音",
    "call.error": "出错了：{detail}",
    "call.closed": "结束原因：{reason}",

    "call.captions.title": "字幕",
    "call.captions.empty": "说点什么，字幕会出现在这里。",
    "call.captions.owner": "你",
    "call.captions.voice": "语音",
    "call.captions.latest": "回到最新",
    "call.captions.linked": "来自第 {index} 条知识库回答",
    "call.captions.unlinked": "未关联回写",
    "call.captions.unlinkedHint": "这段转写未按时间关联到本次查库回写；这不能证明它没有使用此前的知识库内容。",

    "call.cards.title": "知识库的回答",
    "call.cards.empty": "查到的资料与出处会显示在这里。",
    "call.cards.hearing": "在听问题…",
    "call.cards.searching": "在库里查…",
    "call.cards.answering": "正在回答…",
    "call.cards.done": "已查到资料",
    "call.cards.unspoken": "已被新问题取代，未播报",
    "call.cards.claims": "依据断言（{count}）",
    "call.cards.said": "已交给语音的内容",
  },
  en: {
    "call.details": "Call details",
    "call.readyToTalk": "Connected. You can speak now.",
    "call.micOn": "Microphone on",
    "call.cancel": "Cancel",
    "call.error.micDenied": "Allow microphone access in your browser, then try again.",
    "call.error.noMicrophone": "Connect a microphone, then try again.",

    "call.trace.title": "Delegation timeline and exact updates",
    "call.trace.first": "Preliminary finding (preserved)",
    "call.trace.note": "Times start at delegation receipt. Acknowledgment estimates context injection, not playback.",
    "call.trace.ack": "Acknowledged +{time}s · session injection interval {start}–{end}s",
    "call.trace.speech": "Concurrent Live transcript (time association, not per-update playback proof)",
    "call.trace.change": "Owner correction / cancellation checks",
    "call.trace.export": "Export this delegation",
    "call.trace.sent": "Sent, awaiting acknowledgment",
    "call.trace.acknowledged": "Acknowledged",
    "call.trace.rejected": "Rejected",
    "call.trace.sending": "Sending",

    "call.open": "Call",
    "call.open.unavailable": "Calling is not available right now.",
    "call.back": "Back to Steward",
    "call.leave": "End and return",
    "call.title": "Call the library",
    "call.description":
      "Ask out loud. Explore what your library knows.",

    "call.phase.idle": "not started",
    "call.phase.askingMic": "waiting for microphone access…",
    "call.phase.connecting": "connecting…",
    "call.phase.live": "in a call",
    "call.phase.ending": "hanging up…",
    "call.phase.ended": "the call ended",
    "call.phase.failed": "the call did not connect",

    "call.start": "Start call",
    "call.start.note":
      "About $0.05/min · Microphone access requested on start",
    "call.again": "Call again",
    "call.end": "Hang up",
    "call.mute": "Mute",
    "call.unmute": "Unmute",
    "call.muted": "Microphone muted",
    "call.elapsed": "{time} elapsed",
    "call.cost": "about {cost}",
    "call.context": "context {percent}%",
    "call.model": "{model} · {voice}",
    "call.audioBlocked": "Click to hear",
    "call.error": "Something went wrong: {detail}",
    "call.closed": "Ended: {reason}",

    "call.captions.title": "Captions",
    "call.captions.empty": "Say something and the captions appear here.",
    "call.captions.owner": "You",
    "call.captions.voice": "Voice",
    "call.captions.latest": "Jump to latest",
    "call.captions.linked": "From library answer {index}",
    "call.captions.unlinked": "no linked update",
    "call.captions.unlinkedHint":
      "No library update was linked by timing; this does not prove the voice ignored earlier library context.",

    "call.cards.title": "What the library answered",
    "call.cards.empty":
      "Retrieved information and sources will appear here.",
    "call.cards.hearing": "hearing the question…",
    "call.cards.searching": "searching the library…",
    "call.cards.answering": "answering…",
    "call.cards.done": "Retrieved from the library",
    "call.cards.unspoken": "Superseded by a newer question; not spoken",
    "call.cards.claims": "Claims used ({count})",
    "call.cards.said": "handed to the voice",
  },
});
