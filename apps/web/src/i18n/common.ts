import { defineMessages } from "./define";

/**
 * Shared vocabulary: the ui/ primitives' own defaults plus the words that recur across
 * views (retry / close / pagination / flags / gate ledger). A view-specific phrase belongs
 * in that view's bundle, not here — this file is for text that would otherwise be written
 * twice.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
 */
export const common = defineMessages({
  zh: {
    "common.retry": "重试",
    "common.close": "关闭",
    "common.dismissNotice": "关闭提示",
    "common.clear": "清空",
    "common.filterPlaceholder": "过滤…",
    "common.noMatches": "没有匹配项",
    "common.selectPlaceholder": "请选择",
    "common.loading": "加载中",
    "common.decrease": "减少",
    "common.increase": "增加",
    "common.removeFile": "移除文件",
    "common.filePicker.drop": "松开以选择文件",
    "common.filePicker.idle": "点击选择或拖入文件",
    "common.drawer.title": "抽屉面板",
    "common.errorTitle": "出错了",
    "common.unknownError": "未知错误",
    "common.bootFailed": "启动失败",

    "common.footnote.aria": "脚注 {index}",
    "common.footnote.block": "块 {range}",
    "common.footnote.jumpHint": "点击编号跳到原文",
    "common.footnote.untitledSource": "未命名来源",

    "common.citation.sourceNoun": "来源",
    "common.citation.capturedTitle": "{capturedAt} 的{kind}",
    "common.citation.untitled": "未命名{kind}",
    "common.citation.missingTitle": "原始标题缺失",
    "common.citation.listAria": "引用列表",

    "common.escalation.fallback": "升级",
    "common.unknownSpeaker": "未知发言人",
    "common.untitledAttachment": "未命名附件",
    "common.noSubject": "（无主题）",

    "common.pagination.aria": "分页",
    "common.pagination.noun": "条",
    "common.pagination.page": "第 {current} / {total} 页",
    "common.pagination.previous": "上一页",
    "common.pagination.next": "下一页",

    "common.heatmap.legendAria": "密度图例",
    "common.heatmap.less": "少",
    "common.heatmap.more": "多",
    "common.heatmap.empty": "还没有可绘制的活动。",
    "common.heatmap.dayCount": "{count} 条",
    "common.heatmap.mon": "一",
    "common.heatmap.wed": "三",
    "common.heatmap.fri": "五",
    "common.heatmap.sun": "日",

    "common.flag.disputed": "有争议",
    "common.flag.open_question": "待决问题",
    "common.flag.inferred": "推断",

    "common.gate.aria": "门禁计数",
    "common.gate.unparsed": "无法解析",
    "common.gate.repeat": "重复",
    "common.gate.uncited": "无引用",
    "common.gate.low_confidence": "低置信",
    "common.gate.capped": "超限",

    "common.sourceSpan.title": "原文",
    "common.sourceSpan.fetchExact": "fetch 精确段",
    "common.sourceSpan.fetchFailed": "fetch 失败：{detail}",

    "common.placeholder.title": "本篇正在排版",
    "common.placeholder.description":
      "地基阶段已铺好设计系统与应用外壳，本视图将在下一阶段实现。",
  },
  en: {
    "common.retry": "Retry",
    "common.close": "Close",
    "common.dismissNotice": "Dismiss notice",
    "common.clear": "Clear",
    "common.filterPlaceholder": "Filter…",
    "common.noMatches": "No matches",
    "common.selectPlaceholder": "Select…",
    "common.loading": "Loading",
    "common.decrease": "Decrease",
    "common.increase": "Increase",
    "common.removeFile": "Remove file",
    "common.filePicker.drop": "Release to choose this file",
    "common.filePicker.idle": "Click to choose, or drop a file here",
    "common.drawer.title": "Drawer panel",
    "common.errorTitle": "Something went wrong",
    "common.unknownError": "Unknown error",
    "common.bootFailed": "Startup failed",

    "common.footnote.aria": "Footnote {index}",
    "common.footnote.block": "Block {range}",
    "common.footnote.jumpHint": "Click the number to open the original",
    "common.footnote.untitledSource": "Untitled source",

    "common.citation.sourceNoun": "source",
    "common.citation.capturedTitle": "{kind} captured {capturedAt}",
    "common.citation.untitled": "Untitled {kind}",
    "common.citation.missingTitle": "Original title missing",
    "common.citation.listAria": "Citations",

    "common.escalation.fallback": "Escalation",
    "common.unknownSpeaker": "Unknown speaker",
    "common.untitledAttachment": "Untitled attachment",
    "common.noSubject": "(no subject)",

    "common.pagination.aria": "Pagination",
    "common.pagination.noun": "items",
    "common.pagination.page": "Page {current} of {total}",
    "common.pagination.previous": "Previous",
    "common.pagination.next": "Next",

    "common.heatmap.legendAria": "Density legend",
    "common.heatmap.less": "Less",
    "common.heatmap.more": "More",
    "common.heatmap.empty": "No activity to plot yet.",
    "common.heatmap.dayCount": "{count} item{count||s}",
    "common.heatmap.mon": "M",
    "common.heatmap.wed": "W",
    "common.heatmap.fri": "F",
    "common.heatmap.sun": "S",

    "common.flag.disputed": "Disputed",
    "common.flag.open_question": "Open question",
    "common.flag.inferred": "Inferred",

    "common.gate.aria": "Gate counts",
    "common.gate.unparsed": "Unparsed",
    "common.gate.repeat": "Repeat",
    "common.gate.uncited": "Uncited",
    "common.gate.low_confidence": "Low confidence",
    "common.gate.capped": "Capped",

    "common.sourceSpan.title": "Original text",
    "common.sourceSpan.fetchExact": "Fetch exact span",
    "common.sourceSpan.fetchFailed": "Fetch failed: {detail}",

    "common.placeholder.title": "This chapter is still being typeset",
    "common.placeholder.description":
      "The design system and app shell are in place; this view lands in the next stage.",
  },
});
