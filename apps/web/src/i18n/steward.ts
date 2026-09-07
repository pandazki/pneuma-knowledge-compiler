import { defineMessages } from "./define";

/**
 * The Steward view: one conversation with the coding agent that compiles this library.
 *
 * The copy has one job the other views do not: it must never suggest that the console did
 * anything. Every step on the page is the agent's own command, and the wording says so —
 * 「它跑了」, "it ran" — because the console adds nothing the agent did not do and hides
 * nothing it did (docs/design/coding-agent-mode.md §5.6).
 */
export const steward = defineMessages({
  zh: {
    "steward.title": "管家 Steward",
    "steward.description": "和编译这座知识库的编码代理对话。它跑的每一条命令都在这里，连同结果。",

    "steward.status.live": "会话进行中",
    "steward.status.idle": "尚未开始",
    "steward.status.exited": "会话已结束",
    "steward.status.connecting": "连接中…",
    "steward.status.closed": "连接已断开",
    "steward.status.backend": "{label} · {protocol}",
    "steward.status.session": "会话 {id}",

    "steward.compose.placeholder": "跟管家说点什么，比如「这周进来了什么，招标那块有没有互相矛盾的地方？」",
    "steward.compose.send": "发送",
    "steward.compose.busy": "它正在做事——现在发出的消息会排队，等这一轮结束再送进去。",
    "steward.compose.hint": "Enter 发送，Shift+Enter 换行",

    "steward.item.owner": "你",
    "steward.item.queued": "已排队 · 等当前这一轮结束",
    "steward.item.running": "运行中…",
    "steward.item.exit": "退出码 {code}",
    "steward.item.output": "结果",
    "steward.item.noOutput": "没有输出",
    "steward.item.stopped": "它请求了一次授权，而这条会话没有人能回答——已拒绝，所以它停在这里。",
    "steward.item.usage": "这一轮：{usage}",
    "steward.item.cost": "约 ${cost}",
    "steward.item.turnError": "这一轮以错误结束：{error}",

    "steward.empty.title": "这座知识库不是由编码代理编译的",
    "steward.empty.body":
      "管家视图需要一个编码代理。在引擎里把 compile 设成 `agent:codex`（或 `agent:claude-code`），登录好那个 CLI，再回到这里。",
    "steward.empty.detail": "当前：{detail}",
    "steward.empty.engine": "去引擎控制台",

    "steward.exited.title": "会话结束了",
    "steward.exited.body": "进程退出（退出码 {code}）。它不会被悄悄重启——要继续，就开一段新的。",
    "steward.exited.restart": "重新开始",

    "steward.notice.error": "出了点问题",
    "steward.end": "结束会话",
    "steward.moved": "库变了：版次、工序和来源已经刷新。",
  },
  en: {
    "steward.title": "Steward",
    "steward.description":
      "A conversation with the coding agent that compiles this library. Every command it runs is here, with its result.",

    "steward.status.live": "session running",
    "steward.status.idle": "not started",
    "steward.status.exited": "session ended",
    "steward.status.connecting": "connecting…",
    "steward.status.closed": "disconnected",
    "steward.status.backend": "{label} · {protocol}",
    "steward.status.session": "session {id}",

    "steward.compose.placeholder":
      "Tell the Steward something — “what came in this week, and is anything about the tender contradictory?”",
    "steward.compose.send": "Send",
    "steward.compose.busy":
      "It is working. A message sent now is queued and goes in when this turn ends.",
    "steward.compose.hint": "Enter sends, Shift+Enter for a new line",

    "steward.item.owner": "You",
    "steward.item.queued": "queued · waiting for this turn to end",
    "steward.item.running": "running…",
    "steward.item.exit": "exit {code}",
    "steward.item.output": "result",
    "steward.item.noOutput": "no output",
    "steward.item.stopped":
      "It asked for permission, and nobody in this session can answer — declined, so it stopped here.",
    "steward.item.usage": "this turn: {usage}",
    "steward.item.cost": "about ${cost}",
    "steward.item.turnError": "the turn ended with an error: {error}",

    "steward.empty.title": "This library is not compiled by a coding agent",
    "steward.empty.body":
      "The Steward view needs one. Set `compile: agent:codex` (or `agent:claude-code`) in the engine, log that CLI in, and come back.",
    "steward.empty.detail": "Currently: {detail}",
    "steward.empty.engine": "Open the engine console",

    "steward.exited.title": "The session ended",
    "steward.exited.body":
      "The process exited (code {code}). Nothing restarts it silently — start a new one to carry on.",
    "steward.exited.restart": "Start again",

    "steward.notice.error": "Something went wrong",
    "steward.end": "End the session",
    "steward.moved": "The library moved: history, process and sources have refreshed.",
  },
});
