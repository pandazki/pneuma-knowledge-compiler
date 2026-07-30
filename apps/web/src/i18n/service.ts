import { defineMessages } from "./define";

/**
 * Transport-level messages raised by `lib/api.ts`. These are framework text (the client's
 * own account of a failed call), not server payload — a server `detail` string rides in as
 * `{detail}` and is never translated.
 */
export const service = defineMessages({
  zh: {
    "service.unreachable": "无法连接 API：{detail}",
    "service.duplicateCursor": "来源分页返回了重复游标",
    "service.ws.closed": "已关闭",
    "service.ws.disconnected": "已断开",
    "service.ws.error": "WebSocket 连接错误",
    "service.ws.badFrame": "无法解析服务端帧：{detail}",
  },
  en: {
    "service.unreachable": "Cannot reach the API: {detail}",
    "service.duplicateCursor": "Source pagination returned a repeated cursor",
    "service.ws.closed": "Closed",
    "service.ws.disconnected": "Disconnected",
    "service.ws.error": "WebSocket connection error",
    "service.ws.badFrame": "Could not parse the server frame: {detail}",
  },
});
