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
    "call.open": "通话",
    "call.open.unavailable": "现在不能通话。",
    "call.back": "回到文字会话",
    "call.title": "和知识库通话",
    "call.description": "你说话，它听；需要查库时由引擎去查，查到什么都列在右边。",

    "call.phase.idle": "未开始",
    "call.phase.askingMic": "等待麦克风授权…",
    "call.phase.connecting": "接通中…",
    "call.phase.live": "通话中",
    "call.phase.ending": "挂断中…",
    "call.phase.ended": "通话已结束",
    "call.phase.failed": "没能接通",

    "call.start": "开始通话",
    "call.start.note": "需要麦克风权限；通话按分钟计费（约 $0.05/分钟），挂断即停。",
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
    "call.captions.unlinked": "未查库",
    "call.captions.unlinkedHint": "这段话不是知识库给出的内容，是语音模型自己说的。",

    "call.cards.title": "知识库的回答",
    "call.cards.empty": "问一个库里答得上来的问题，它查到什么都会列在这里。",
    "call.cards.hearing": "在听问题…",
    "call.cards.searching": "在库里查…",
    "call.cards.answering": "正在回答…",
    "call.cards.done": "用时 {seconds} 秒",
    "call.cards.unspoken": "已被新问题取代，未播报",
    "call.cards.claims": "依据断言（{count}）",
    "call.cards.said": "已交给语音的内容",
  },
  en: {
    "call.open": "Call",
    "call.open.unavailable": "Calling is not available right now.",
    "call.back": "Back to the text session",
    "call.title": "Call the library",
    "call.description":
      "You speak, it listens; when a question needs the library the engine looks it up, and whatever it found is listed on the right.",

    "call.phase.idle": "not started",
    "call.phase.askingMic": "waiting for microphone access…",
    "call.phase.connecting": "connecting…",
    "call.phase.live": "in a call",
    "call.phase.ending": "hanging up…",
    "call.phase.ended": "the call ended",
    "call.phase.failed": "the call did not connect",

    "call.start": "Start call",
    "call.start.note":
      "Needs microphone access; billed per minute (about $0.05/min) until you hang up.",
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
    "call.captions.unlinked": "not from the library",
    "call.captions.unlinkedHint":
      "The library did not supply this; the voice model said it on its own.",

    "call.cards.title": "What the library answered",
    "call.cards.empty":
      "Ask something the library can answer, and whatever it found is listed here.",
    "call.cards.hearing": "hearing the question…",
    "call.cards.searching": "searching the library…",
    "call.cards.answering": "answering…",
    "call.cards.done": "took {seconds}s",
    "call.cards.unspoken": "Superseded by a newer question; not spoken",
    "call.cards.claims": "Claims used ({count})",
    "call.cards.said": "handed to the voice",
  },
});
