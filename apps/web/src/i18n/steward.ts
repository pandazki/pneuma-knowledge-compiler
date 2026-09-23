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
    "steward.item.succeeded": "已完成",
    "steward.item.failed": "执行失败",
    "steward.item.stoppedShort": "已停止",
    "steward.item.finished": "执行结束",
    "steward.item.usageDetails": "本轮用量",
    "steward.item.costLabel": "费用",
    "steward.item.duration": "耗时",
    "steward.usage.input": "输入 token",
    "steward.usage.output": "输出 token",
    "steward.usage.cached": "缓存命中",
    "steward.usage.cacheWrite": "缓存写入",
    "steward.usage.reasoning": "推理 token",
    "steward.usage.total": "总 token",
    "steward.title": "管家 Steward",
    "steward.description": "与知识库管家对话。",

    "steward.status.live": "会话进行中",
    "steward.status.idle": "尚未开始",
    "steward.status.exited": "会话已结束",
    "steward.status.connecting": "连接中…",
    "steward.status.closed": "连接已断开",
    "steward.status.backend": "{label} · {protocol}",
    "steward.status.session": "会话 {id}",

    "steward.compose.placeholder": "跟管家说点什么，比如「这周进来了什么，招标那块有没有互相矛盾的地方？」",
    "steward.compose.label": "给管家的消息",
    "steward.compose.send": "发送",
    "steward.compose.hint": "Enter 发送，Shift+Enter 换行",
    "steward.compose.working": "管家正在处理…",
    "steward.compose.queueing": "将排队，这一轮结束后发送",
    "steward.compose.attach": "附上图片",
    "steward.compose.removeImage": "移除 {name}",
    "steward.compose.pastedImage": "粘贴的图片",
    "steward.compose.refused.type": "{name} 不是 PNG / JPEG / WebP / GIF，没有附上。",
    "steward.compose.refused.size": "{name} 超过 {size} MiB，没有附上。",
    "steward.compose.refused.count": "一条消息最多 {max} 张图片，{name} 没有附上。",

    "steward.item.owner": "你",
    "steward.item.openImage": "查看 {name} 原图",
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
    "steward.item.succeeded": "Completed",
    "steward.item.failed": "Command failed",
    "steward.item.stoppedShort": "Stopped",
    "steward.item.finished": "Finished",
    "steward.item.usageDetails": "Turn usage",
    "steward.item.costLabel": "Cost",
    "steward.item.duration": "Duration",
    "steward.usage.input": "Input tokens",
    "steward.usage.output": "Output tokens",
    "steward.usage.cached": "Cache read",
    "steward.usage.cacheWrite": "Cache write",
    "steward.usage.reasoning": "Reasoning tokens",
    "steward.usage.total": "Total tokens",
    "steward.title": "Steward",
    "steward.description":
      "Talk with your library’s Steward.",

    "steward.status.live": "session running",
    "steward.status.idle": "not started",
    "steward.status.exited": "session ended",
    "steward.status.connecting": "connecting…",
    "steward.status.closed": "disconnected",
    "steward.status.backend": "{label} · {protocol}",
    "steward.status.session": "session {id}",

    "steward.compose.placeholder":
      "Tell the Steward something — “what came in this week, and is anything about the tender contradictory?”",
    "steward.compose.label": "Message to the Steward",
    "steward.compose.send": "Send",
    "steward.compose.hint": "Enter sends, Shift+Enter for a new line",
    "steward.compose.working": "Steward is working…",
    "steward.compose.queueing": "Queued until this turn ends",
    "steward.compose.attach": "Attach images",
    "steward.compose.removeImage": "Remove {name}",
    "steward.compose.pastedImage": "pasted image",
    "steward.compose.refused.type": "{name} is not a PNG, JPEG, WebP or GIF — not attached.",
    "steward.compose.refused.size": "{name} is over {size} MiB — not attached.",
    "steward.compose.refused.count":
      "At most {max} images per message — {name} was not attached.",

    "steward.item.owner": "You",
    "steward.item.openImage": "Open {name} full size",
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
