import { defineMessages } from "./define";

/**
 * The app shell: table of contents, top bar, the two pickers, the two toggles, and the
 * store-issued notices. The TOC's § numbers stay in code — they are structure, not copy.
 */
export const nav = defineMessages({
  zh: {
    "nav.toc.aria": "目录",
    "nav.toc.open": "打开目录",

    "nav.group.front": "卷首",
    "nav.group.materials": "原料篇",
    "nav.group.process": "工序篇",
    "nav.group.retrieval": "取用篇",
    "nav.group.canon": "正本篇",
    "nav.group.evolution": "演化篇",
    "nav.group.back": "卷末",

    "nav.view.overview": "卷首 · 这是一个编译器",
    "nav.view.sources": "原料 Sources",
    "nav.view.ingest": "导入 Ingest",
    "nav.view.process": "工序 Process",
    "nav.view.recall": "检索 Recall",
    "nav.view.ask": "问答 Ask",
    "nav.view.live_context": "即时上下文 Live Context",
    "nav.view.library": "正本",
    "nav.view.graph": "图谱 Graph",
    "nav.view.history": "版本 History",
    "nav.view.evolve": "演化 Evolve",
    "nav.view.engine_console": "引擎控制台 Engine",
    "nav.view.profile": "画像 Profile",

    "nav.offline": "无法连接 pneuma-knowledge 服务，面板已降级。",
    "nav.snapshotBanner": "历史快照 · 只读",
    "nav.backToHead": "回到 HEAD",

    "nav.theme.label": "切换主题",
    "nav.theme.toLight": "切到日间「纸」",
    "nav.theme.toDark": "切到夜间「灯箱」",

    "nav.locale.label": "切换界面语言",
    "nav.locale.toZh": "切换到中文界面",
    "nav.locale.toEn": "切换到英文界面",

    "nav.user.recent": "最近",
    "nav.user.all": "全部",
    "nav.user.choose": "选择画像",
    "nav.user.switchAria": "切换用户画像",
    "nav.user.filterPlaceholder": "输入名字或 user_id…",
    "nav.user.empty": "没有匹配的画像",
    "nav.user.create": "新建画像",

    "nav.snapshot.headKeywords": "head 当前",
    "nav.snapshot.headNote": "当前 · 可写",
    "nav.snapshot.readOnly": "只读",
    "nav.snapshot.loadMore": "加载更早版本 · {loaded} / {total}",
    "nav.snapshot.retryList": "重试版本列表",
    "nav.snapshot.switchAria": "切换到历史快照",
    "nav.snapshot.filterPlaceholder": "输入 ref 或标签…",
    "nav.snapshot.empty": "没有匹配的快照",
    "nav.snapshot.loadingNote": "加载版本…",
    "nav.snapshot.noneNote": "尚无版本",

    "nav.snapshot.groupLive": "当前",
    "nav.snapshot.groupFrozen": "冻结快照 · 可问答",
    "nav.snapshot.groupCommits": "正本提交 · 仅浏览",
    "nav.snapshot.kbScale": "{sources} 份原料 · {claims} 条断言（claim）",
    "nav.snapshot.kbCreating": "复制中…",
    "nav.snapshot.kbFailed": "创建失败",
    "nav.snapshot.kbCreateHint": "输入名称以冻结当前知识库",
    "nav.snapshot.kbCreateNamed": "冻结当前知识库为「{label}」",
    "nav.snapshot.kbDelete": "删除快照「{label}」",
    "nav.snapshot.kbBanner": "冻结快照 · 只读",

    "nav.notice.newProfile": "新画像 · 可以用 AI 生成草稿，也可以直接填写",
    "nav.notice.profileSaved": "画像已保存 · 去 Ingest 导入第一条数据",
    "nav.notice.profileSkipped": "已跳过画像设置 · 去 Ingest 导入第一条数据",
  },
  en: {
    "nav.toc.aria": "Contents",
    "nav.toc.open": "Open contents",

    "nav.group.front": "Front matter",
    "nav.group.materials": "Materials",
    "nav.group.process": "Process",
    "nav.group.retrieval": "Retrieval",
    "nav.group.canon": "Canonical",
    "nav.group.evolution": "Evolution",
    "nav.group.back": "Back matter",

    // Kept short on purpose: the contents rail is 232px and truncates. The group heading
    // above it already says "Front matter", so the item carries the editorial line instead.
    "nav.view.overview": "This is a compiler",
    "nav.view.sources": "Sources",
    "nav.view.ingest": "Ingest",
    "nav.view.process": "Process",
    "nav.view.recall": "Recall",
    "nav.view.ask": "Ask",
    "nav.view.live_context": "Live Context",
    "nav.view.library": "Canonical",
    "nav.view.graph": "Graph",
    "nav.view.history": "History",
    "nav.view.evolve": "Evolve",
    "nav.view.engine_console": "Engine Console",
    "nav.view.profile": "Profile",

    "nav.offline": "Cannot reach the pneuma-knowledge service; the panels are degraded.",
    "nav.snapshotBanner": "Historical snapshot · read-only",
    "nav.backToHead": "Back to HEAD",

    "nav.theme.label": "Toggle theme",
    "nav.theme.toLight": "Switch to daylight “paper”",
    "nav.theme.toDark": "Switch to night “lightbox”",

    "nav.locale.label": "Switch interface language",
    "nav.locale.toZh": "Switch the interface to Chinese",
    "nav.locale.toEn": "Switch the interface to English",

    "nav.user.recent": "Recent",
    "nav.user.all": "All",
    "nav.user.choose": "Choose a profile",
    "nav.user.switchAria": "Switch user profile",
    "nav.user.filterPlaceholder": "Type a name or user_id…",
    "nav.user.empty": "No matching profile",
    "nav.user.create": "New profile",

    "nav.snapshot.headKeywords": "head current",
    "nav.snapshot.headNote": "current · writable",
    "nav.snapshot.readOnly": "read-only",
    "nav.snapshot.loadMore": "Load earlier versions · {loaded} / {total}",
    "nav.snapshot.retryList": "Retry the version list",
    "nav.snapshot.switchAria": "Switch to a historical snapshot",
    "nav.snapshot.filterPlaceholder": "Type a ref or label…",
    "nav.snapshot.empty": "No matching snapshot",
    "nav.snapshot.loadingNote": "Loading versions…",
    "nav.snapshot.noneNote": "No versions yet",

    "nav.snapshot.groupLive": "Live",
    "nav.snapshot.groupFrozen": "Frozen snapshots · answerable",
    "nav.snapshot.groupCommits": "Canonical commits · browse only",
    "nav.snapshot.kbScale": "{sources} source{sources||s} · {claims} claim{claims||s}",
    "nav.snapshot.kbCreating": "copying…",
    "nav.snapshot.kbFailed": "failed",
    "nav.snapshot.kbCreateHint": "Type a name to freeze the base as it stands",
    "nav.snapshot.kbCreateNamed": "Freeze the base as “{label}”",
    "nav.snapshot.kbDelete": "Delete snapshot “{label}”",
    "nav.snapshot.kbBanner": "Frozen snapshot · read-only",

    "nav.notice.newProfile":
      "New profile · let the AI draft one, or just fill it in yourself",
    "nav.notice.profileSaved": "Profile saved · head to Ingest for your first material",
    "nav.notice.profileSkipped":
      "Profile setup skipped · head to Ingest for your first material",
  },
});
