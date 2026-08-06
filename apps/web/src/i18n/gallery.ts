import { defineMessages } from "./define";

/**
 * The hidden `#/components` state matrix — the UI's own sample book. Almost everything on
 * that page is chrome, and the few bits that look like content (a fake citation, a fake
 * error detail, the L0–L3 gloss) are hard-coded demo material, so they live here too.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
 */
export const gallery = defineMessages({
  zh: {
    "gallery.title": "组件状态矩阵",
    "gallery.description":
      "全部 primitives 的默认 / focus 说明 / disabled / error / loading / empty。此页不进目录，仅供验收与回归。",

    "gallery.section.buttons": "按钮 Button / IconButton",
    "gallery.section.text": "文本输入 TextField / SearchField / TextArea",
    "gallery.section.choice": "选择 Select / Combobox / SegmentedControl",
    "gallery.section.numbers": "数值 NumberField / Slider",
    "gallery.section.toggles": "Switch / Checkbox / RadioGroup",
    "gallery.section.overlays": "浮层 Dialog / Drawer / Popover / Tooltip / Menu / Tabs",
    "gallery.section.feedback": "反馈 Callout / Empty / Error / Loading / Badge / Stamp",
    "gallery.section.typography": "排版 Footnote / Mono / DefinitionList",

    "gallery.demo.focusNote": "focus 说明",
    "gallery.demo.textDefault": "默认 / 前后缀",
    "gallery.demo.textArea": "TextArea（autoRows）/ error",
    "gallery.demo.select": "Select 默认 / error / disabled",
    "gallery.demo.combobox": "Combobox（过滤 + 分组）/ disabled",
    "gallery.demo.numberField": "NumberField 默认 / error / disabled",
    "gallery.demo.slider": "Slider 默认 / disabled",
    "gallery.demo.radioGroup": "RadioGroup 默认 / error",
    "gallery.demo.filePicker": "FilePicker 空 / 已选 / error",
    "gallery.demo.tabs": "Tabs（下划线式）",
    "gallery.demo.callout": "Callout 四阶",
    "gallery.demo.footnote": "Footnote（hover 出卡片，点击跳源）",
    "gallery.demo.icons": "图标基线（lucide 中性用法）",

    "gallery.state.disabled": "禁用",
    "gallery.state.disabledLabel": "禁用态",
    "gallery.state.error": "错误态",
    "gallery.state.off": "关闭态",
    "gallery.state.required": "不能为空",

    "gallery.button.compile": "编译",
    "gallery.button.default": "默认",
    "gallery.button.ghost": "幽灵",
    "gallery.button.danger": "放弃",
    "gallery.button.small": "小号",
    "gallery.button.medium": "中号",
    "gallery.button.withIcon": "带图标",
    "gallery.button.settings": "设置",
    "gallery.button.compiling": "编译中",
    "gallery.button.focusHint": "Tab 聚焦任意按钮：accent 2px outline + 2px offset。",

    "gallery.text.value": "校样文字",
    "gallery.text.titleLabel": "标题",
    "gallery.text.titleHint": "输入即受控更新",
    "gallery.text.pathLabel": "路径",
    "gallery.text.userIdError": "只能包含字母、数字与连字符",
    "gallery.text.disabledValue": "不可编辑",

    "gallery.search.value": "脚注",
    "gallery.search.placeholder": "检索正本…",
    "gallery.search.emptyPlaceholder": "空值占位",

    "gallery.textArea.value": "纸、墨、发丝线、脚注。",
    "gallery.textArea.label": "正文",
    "gallery.textArea.hint": "随内容增高，至多 5 行",

    "gallery.select.contract": "合同 Contract",
    "gallery.select.novel": "长文 Novel",
    "gallery.select.note": "笔记 Note",
    "gallery.select.requiredPlaceholder": "必选一项",
    "gallery.select.focusHint":
      "Select / Combobox 触发器与列表项均键盘可达：↑↓ 移动，Enter 选中，Esc 关闭。",

    "gallery.combobox.group": "版本",
    "gallery.combobox.first": "初版",
    "gallery.combobox.second": "二校",
    "gallery.combobox.demoAria": "演示 combobox",
    "gallery.combobox.emptyTrigger": "空数据",
    "gallery.combobox.disabledAria": "禁用 combobox",
    "gallery.combobox.noneNote": "尚无版本",

    "gallery.segmented.modeAria": "检索模式",
    "gallery.segmented.disabledAria": "禁用分段",

    "gallery.number.label": "字符预算",
    "gallery.number.hint": "± 按钮与 ↑↓ 键步进 256",
    "gallery.number.error": "超出预算",

    "gallery.switch.label": "统计帧",
    "gallery.checkbox.all": "全选",
    "gallery.checkbox.checked": "已选",

    "gallery.radio.workstream": "工作流",
    "gallery.radio.workstreamNote": "持续产生的对话与实验",
    "gallery.radio.reference": "参考资料",
    "gallery.radio.referenceNote": "稳定的外部文档",
    "gallery.radio.unselected": "未选",
    "gallery.radio.error": "必选一类",

    "gallery.filePicker.hint": "Markdown / 纯文本",
    "gallery.filePicker.error": "文件过大",

    "gallery.overlay.openDialog": "打开 Dialog",
    "gallery.overlay.openDrawer": "打开 Drawer",
    "gallery.popover.body": "浮层内容：raised 底 + 发丝线 + 浅影。",
    "gallery.tooltip.content": "快捷键提示见 Kbd",
    "gallery.tooltip.trigger": "hover 我",
    "gallery.menu.trigger": "菜单",
    "gallery.menu.rename": "重命名",
    "gallery.menu.delete": "删除",
    "gallery.menu.disabledItem": "禁用项",
    "gallery.tabs.aria": "演示 tabs",
    "gallery.tabs.one": "文档",
    "gallery.tabs.onePanel": "第一页面板。",
    "gallery.tabs.two": "会话",
    "gallery.tabs.twoPanel": "第二页面板。",

    "gallery.callout.noticeTitle": "提示",
    "gallery.callout.noticeBody": "数据集已回退到默认样例。",
    "gallery.callout.infoTitle": "信息",
    "gallery.callout.infoBody": "这是一个中性补充说明。",
    "gallery.callout.warnTitle": "警告",
    "gallery.callout.warnBody": "服务不可达，面板已降级。",
    "gallery.callout.dangerTitle": "错误",
    "gallery.callout.dangerBody": "编译失败，可关闭此提示。",

    "gallery.empty.title": "还没有原料",
    "gallery.empty.description": "去「导入 Ingest」添加第一条 source。",
    "gallery.empty.action": "去导入",
    "gallery.errorState.detail": "502 Bad Gateway：compile queue unreachable",

    "gallery.stamp.snapshot": "历史快照 · 只读",

    "gallery.footnote.lead": "每个断言（claim）都能回到原文精确段",
    "gallery.footnote.tail": "，这是引用门禁成立的前提",
    "gallery.footnote.stop": "。",
    "gallery.footnote.citationTitle": "编译器原理笔记",
    "gallery.footnote.citationSnippet": "溯源不是功能，是这套系统的地基。",

    "gallery.level.l0": "原始材料：对话、文档、实验记录。",
    "gallery.level.l1": "原料块索引：可定位、可取回。",
    "gallery.level.l2": "语义索引：recall 的命中面。",
    "gallery.level.l3": "正本知识：每条断言都带引用。",

    "gallery.dialog.title": "确认编译",
    "gallery.dialog.description": "把当前未消化的原料编译进正本。",
    "gallery.dialog.cancel": "取消",
    "gallery.dialog.body": "正文区：表单或说明文字。",
    "gallery.drawer.title": "侧栏抽屉",
    "gallery.drawer.body": "SourceSpanSheet 等侧栏内容的容器。",
  },
  en: {
    "gallery.title": "Component state matrix",
    "gallery.description":
      "Every primitive in its default / focus / disabled / error / loading / empty state. This page stays out of the contents; it exists for acceptance shots and regressions.",

    "gallery.section.buttons": "Buttons — Button / IconButton",
    "gallery.section.text": "Text input — TextField / SearchField / TextArea",
    "gallery.section.choice": "Choice — Select / Combobox / SegmentedControl",
    "gallery.section.numbers": "Numbers — NumberField / Slider",
    "gallery.section.toggles": "Switch / Checkbox / RadioGroup",
    "gallery.section.overlays": "Overlays — Dialog / Drawer / Popover / Tooltip / Menu / Tabs",
    "gallery.section.feedback": "Feedback — Callout / Empty / Error / Loading / Badge / Stamp",
    "gallery.section.typography": "Typography — Footnote / Mono / DefinitionList",

    "gallery.demo.focusNote": "focus notes",
    "gallery.demo.textDefault": "default / affixes",
    "gallery.demo.textArea": "TextArea (autoRows) / error",
    "gallery.demo.select": "Select default / error / disabled",
    "gallery.demo.combobox": "Combobox (filter + groups) / disabled",
    "gallery.demo.numberField": "NumberField default / error / disabled",
    "gallery.demo.slider": "Slider default / disabled",
    "gallery.demo.radioGroup": "RadioGroup default / error",
    "gallery.demo.filePicker": "FilePicker empty / chosen / error",
    "gallery.demo.tabs": "Tabs (underlined)",
    "gallery.demo.callout": "Callout, four tones",
    "gallery.demo.footnote": "Footnote (hover for the card, click to open the source)",
    "gallery.demo.icons": "Icon baseline (neutral lucide usage)",

    "gallery.state.disabled": "Disabled",
    "gallery.state.disabledLabel": "Disabled state",
    "gallery.state.error": "Error state",
    "gallery.state.off": "Off",
    "gallery.state.required": "Cannot be empty",

    "gallery.button.compile": "Compile",
    "gallery.button.default": "Default",
    "gallery.button.ghost": "Ghost",
    "gallery.button.danger": "Discard",
    "gallery.button.small": "Small",
    "gallery.button.medium": "Medium",
    "gallery.button.withIcon": "With icon",
    "gallery.button.settings": "Settings",
    "gallery.button.compiling": "Compiling",
    "gallery.button.focusHint": "Tab to any button: a 2px accent outline, offset by 2px.",

    "gallery.text.value": "Proof copy",
    "gallery.text.titleLabel": "Title",
    "gallery.text.titleHint": "Controlled — updates as you type",
    "gallery.text.pathLabel": "Path",
    "gallery.text.userIdError": "Letters, digits and hyphens only",
    "gallery.text.disabledValue": "Not editable",

    "gallery.search.value": "footnote",
    "gallery.search.placeholder": "Search canonical…",
    "gallery.search.emptyPlaceholder": "Empty placeholder",

    "gallery.textArea.value": "Paper, ink, hairlines, footnotes.",
    "gallery.textArea.label": "Body",
    "gallery.textArea.hint": "Grows with the content, up to 5 rows",

    "gallery.select.contract": "Contract",
    "gallery.select.novel": "Novel",
    "gallery.select.note": "Note",
    "gallery.select.requiredPlaceholder": "Pick one",
    "gallery.select.focusHint":
      "Select and Combobox triggers and rows are all keyboard-reachable: ↑↓ to move, Enter to choose, Esc to close.",

    "gallery.combobox.group": "Versions",
    "gallery.combobox.first": "First cut",
    "gallery.combobox.second": "Second proof",
    "gallery.combobox.demoAria": "Demo combobox",
    "gallery.combobox.emptyTrigger": "No data",
    "gallery.combobox.disabledAria": "Disabled combobox",
    "gallery.combobox.noneNote": "No versions yet",

    "gallery.segmented.modeAria": "Retrieval mode",
    "gallery.segmented.disabledAria": "Disabled segmented control",

    "gallery.number.label": "Character budget",
    "gallery.number.hint": "The ± buttons and the ↑↓ keys step by 256",
    "gallery.number.error": "Over budget",

    "gallery.switch.label": "Stats frame",
    "gallery.checkbox.all": "Select all",
    "gallery.checkbox.checked": "Selected",

    "gallery.radio.workstream": "Workstream",
    "gallery.radio.workstreamNote": "Conversations and experiments that keep arriving",
    "gallery.radio.reference": "Reference material",
    "gallery.radio.referenceNote": "Stable external documents",
    "gallery.radio.unselected": "Unselected",
    "gallery.radio.error": "Choose one class",

    "gallery.filePicker.hint": "Markdown / plain text",
    "gallery.filePicker.error": "File too large",

    "gallery.overlay.openDialog": "Open Dialog",
    "gallery.overlay.openDrawer": "Open Drawer",
    "gallery.popover.body": "Overlay content: raised ground, a hairline, a shallow shadow.",
    "gallery.tooltip.content": "See Kbd for the shortcut hint",
    "gallery.tooltip.trigger": "Hover me",
    "gallery.menu.trigger": "Menu",
    "gallery.menu.rename": "Rename",
    "gallery.menu.delete": "Delete",
    "gallery.menu.disabledItem": "Disabled item",
    "gallery.tabs.aria": "Demo tabs",
    "gallery.tabs.one": "Documents",
    "gallery.tabs.onePanel": "First panel.",
    "gallery.tabs.two": "Sessions",
    "gallery.tabs.twoPanel": "Second panel.",

    "gallery.callout.noticeTitle": "Notice",
    "gallery.callout.noticeBody": "The dataset has fallen back to the default sample.",
    "gallery.callout.infoTitle": "Info",
    "gallery.callout.infoBody": "A neutral aside.",
    "gallery.callout.warnTitle": "Warning",
    "gallery.callout.warnBody": "The service is unreachable; the panel is degraded.",
    "gallery.callout.dangerTitle": "Error",
    "gallery.callout.dangerBody": "The compile failed. This notice can be dismissed.",

    "gallery.empty.title": "No material yet",
    "gallery.empty.description": "Head to Ingest to add the first source.",
    "gallery.empty.action": "Go to Ingest",
    "gallery.errorState.detail": "502 Bad Gateway: compile queue unreachable",

    "gallery.stamp.snapshot": "Historical snapshot · read-only",

    "gallery.footnote.lead": "Every claim can be traced back to an exact source span",
    "gallery.footnote.tail": ", which is what makes the citation gate possible",
    "gallery.footnote.stop": ".",
    "gallery.footnote.citationTitle": "Notes on compiler construction",
    "gallery.footnote.citationSnippet":
      "Provenance is not a feature; it is the ground this system stands on.",

    "gallery.level.l0": "Raw material: conversations, documents, experiment logs.",
    "gallery.level.l1": "Source block index: locatable, fetchable.",
    "gallery.level.l2": "Semantic index: the surface recall hits.",
    "gallery.level.l3": "Canonical knowledge, with citations.",

    "gallery.dialog.title": "Confirm compile",
    "gallery.dialog.description": "Compile the undigested sources into canonical knowledge.",
    "gallery.dialog.cancel": "Cancel",
    "gallery.dialog.body": "Body area: a form, or explanatory copy.",
    "gallery.drawer.title": "Side drawer",
    "gallery.drawer.body": "The container for side content such as SourceSpanSheet.",
  },
});
