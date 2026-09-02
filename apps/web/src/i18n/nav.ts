import { defineMessages } from "./define";

/**
 * The app shell: the table of contents and the identity lens at its foot, the top bar's
 * pickers and toggles, and the store-issued notices. The TOC's § numbers stay in code —
 * they are structure, not copy.
 *
 * The lens options are labelled by CONSEQUENCE, the same way the visitor classes were: the
 * name says who you are, the line beside it says what that costs the library. 「无痕访客」is
 * the one that opts out of being counted, and it says so on the badge, in the menu and on
 * the page — a stance nobody can see is not an honest one.
 */
export const nav = defineMessages({
  zh: {
    "nav.toc.aria": "目录",
    "nav.toc.open": "打开目录",

    "nav.group.front": "卷首",
    "nav.group.materials": "来源篇",
    "nav.group.process": "工序篇",
    "nav.group.retrieval": "取用篇",
    "nav.group.canon": "正本篇",
    "nav.group.evolution": "演化篇",
    "nav.group.back": "卷末",

    "nav.view.overview": "卷首 · 这是一个编译器",
    "nav.view.sources": "来源 Sources",
    "nav.view.ingest": "导入 Ingest",
    "nav.view.process": "工序 Process",
    "nav.view.recall": "检索 Recall",
    "nav.view.ask": "问答 Ask",
    "nav.view.live_context": "即时上下文 Live Context",
    "nav.view.consultations": "咨询 Consultations",
    "nav.view.library": "正本 Canonical",
    "nav.view.graph": "图谱 Graph",
    "nav.view.history": "版次 History",
    "nav.view.evolve": "演化 Evolve",
    "nav.view.engine_console": "引擎控制台 Engine Console",
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
    "nav.snapshot.loadMore": "加载更早的快照 · {loaded} / {total}",
    "nav.snapshot.retryList": "重试快照列表",
    "nav.snapshot.switchAria": "切换到历史快照",
    "nav.snapshot.filterPlaceholder": "输入 ref 或标签…",
    "nav.snapshot.empty": "没有匹配的快照",
    "nav.snapshot.loadingNote": "加载快照…",
    "nav.snapshot.noneNote": "尚无快照",

    "nav.snapshot.groupLive": "当前",
    "nav.snapshot.groupFrozen": "冻结快照 · 可问答",
    "nav.snapshot.groupCommits": "正本快照 · 仅浏览",
    "nav.snapshot.kbScale": "{sources} 份来源 · {claims} 条断言（claim）",
    "nav.snapshot.kbCreating": "复制中…",
    "nav.snapshot.kbFailed": "创建失败",
    "nav.snapshot.kbCreateHint": "输入名称以冻结当前知识库",
    "nav.snapshot.kbCreateNamed": "冻结当前知识库为「{label}」",
    "nav.snapshot.kbDelete": "删除快照「{label}」",
    "nav.snapshot.kbBanner": "冻结快照 · 只读",

    "nav.lens.aria": "切换身份",
    "nav.lens.label": "身份",
    "nav.lens.owner": "所有者",
    "nav.lens.visitor": "访客",
    "nav.lens.silent": "无痕访客",
    "nav.lens.owner.consequence": "整台控制台 · 留记录并计入热度",
    "nav.lens.visitor.consequence": "只读阅览室 · 留记录并计入热度",
    "nav.lens.silent.consequence": "只读阅览室 · 不留任何痕迹",
    "nav.lens.silentBanner": "本次浏览不留任何记录",

    "nav.notice.lensGuard": "这一页只对所有者开放，已回到阅览室。",
    "nav.notice.newProfile": "新画像 · 可以用 AI 生成草稿，也可以直接填写",
    "nav.notice.profileSaved": "画像已保存 · 去 Ingest 导入第一条数据",
    "nav.notice.profileSkipped": "已跳过画像设置 · 去 Ingest 导入第一条数据",
  },
  en: {
    "nav.toc.aria": "Contents",
    "nav.toc.open": "Open contents",

    "nav.group.front": "Front matter",
    "nav.group.materials": "Sources",
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
    "nav.view.consultations": "Consultations",
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
    "nav.snapshot.loadMore": "Load earlier snapshots · {loaded} / {total}",
    "nav.snapshot.retryList": "Retry the snapshot list",
    "nav.snapshot.switchAria": "Switch to a historical snapshot",
    "nav.snapshot.filterPlaceholder": "Type a ref or label…",
    "nav.snapshot.empty": "No matching snapshot",
    "nav.snapshot.loadingNote": "Loading snapshots…",
    "nav.snapshot.noneNote": "No snapshots yet",

    "nav.snapshot.groupLive": "Live",
    "nav.snapshot.groupFrozen": "Frozen · answerable",
    "nav.snapshot.groupCommits": "Canonical · browse only",
    "nav.snapshot.kbScale": "{sources} source{sources||s} · {claims} claim{claims||s}",
    "nav.snapshot.kbCreating": "copying…",
    "nav.snapshot.kbFailed": "failed",
    "nav.snapshot.kbCreateHint": "Type a name to freeze the base as it stands",
    "nav.snapshot.kbCreateNamed": "Freeze the base as “{label}”",
    "nav.snapshot.kbDelete": "Delete snapshot “{label}”",
    "nav.snapshot.kbBanner": "Frozen snapshot · read-only",

    "nav.lens.aria": "Switch identity",
    "nav.lens.label": "Identity",
    "nav.lens.owner": "Owner",
    "nav.lens.visitor": "Visitor",
    "nav.lens.silent": "Silent visitor",
    "nav.lens.owner.consequence": "The whole console · recorded, counts as use",
    "nav.lens.visitor.consequence": "The reading room · recorded, counts as use",
    "nav.lens.silent.consequence": "The reading room · no trace at all",
    "nav.lens.silentBanner": "This visit leaves no trace.",

    "nav.notice.lensGuard": "That page is the owner's; you are back in the reading room.",
    "nav.notice.newProfile":
      "New profile · let the AI draft one, or just fill it in yourself",
    "nav.notice.profileSaved": "Profile saved · head to Ingest for your first source",
    "nav.notice.profileSkipped":
      "Profile setup skipped · head to Ingest for your first source",
  },
});
