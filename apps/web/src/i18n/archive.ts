import { defineMessages } from "./define";

/**
 * The archive: where the owner moves knowledge that is no longer worth an answer slot.
 *
 * The copy has one job the design gave it — never let the archive read as a deletion. Every
 * sentence here says MOVED, and the dialog's own vocabulary ("still cited by", "will also be
 * archived", "related, not selected") states what the planner computed rather than what the
 * console guessed. Document paths, source ids and titles are data and render untranslated.
 *
 * The `archive.record.*` half says the same thing from the other side: a page that leaves
 * leaves a RECORD standing at its live path, and those words describe live knowledge — what
 * the subject was, how much it held, where the full page went — never a tombstone.
 */
export const archive = defineMessages({
  zh: {
    "archive.label": "归档",
    "archive.badge": "已归档",
    "archive.badge.aria": "这一条已归档",

    "archive.action.archive": "归档…",
    "archive.action.restore": "恢复…",

    "archive.dialog.archive.title": "归档",
    "archive.dialog.unarchive.title": "从归档恢复",
    "archive.dialog.archive.description":
      "归档是「移动」，不是删除：文档连同它的历史一起移到 archive/ 下，来源保留全部原文块，引用仍然可以精确定位。默认之后的检索不再读到它们。",
    "archive.dialog.unarchive.description":
      "把它们移回正本：文档回到原路径，来源清掉归档时间，检索重新读到它们。",
    "archive.dialog.planning": "正在计算这一步会牵连到什么…",
    "archive.dialog.planFailed": "无法计算归档方案",

    "archive.group.seeds": "你指定的",
    "archive.group.cascade.archive": "将一并归档",
    "archive.group.cascade.unarchive": "将一并恢复",
    "archive.group.related": "相关，但不动",
    // 这一组两个方向都会用到：从文档出发时是「还被别的在用文档引用的来源」，从来源出发时
    // 是「只有部分断言依赖它的文档」。所以这句只说共同的那件事，具体依据写在每条旁边。
    "archive.group.related.note":
      "这些都还牵着你指定范围以外的东西，各自的依据写在下面；勾选会把它们也作为起点重新计算。",
    "archive.group.empty": "没有牵连到别的东西。",

    "archive.item.document": "文档",
    "archive.item.source": "来源",
    "archive.item.volumes": "含 {count} 个已结卷",
    "archive.item.aria": "选择 {title}",

    "archive.reason.seed": "你指定的对象",
    "archive.reason.orphaned": "没有别的在用文档引用它",
    "archive.reason.stillCited": "仍被引用：{documents}",
    "archive.reason.citedByArchived": "仍被归档页引用：{documents}",
    "archive.reason.restoredWithPage": "随页面一并恢复",
    "archive.reason.fullyDependent": "全部 {total} 条断言都引用了选中的来源（{cited}/{total}）",
    "archive.reason.partiallyDependent": "{total} 条断言里有 {cited} 条引用了选中的来源",
    "archive.reason.alreadyArchived": "已经在归档里",
    "archive.reason.alreadyLive": "已经在正本里",
    "archive.reason.andMore": "{shown} 等 {count} 篇",

    "archive.note.label": "备注",
    // 两个动作留下的是两种痕迹：归档写进留痕页，恢复只是把页面移回来。同一句提示会让恢复
    // 对话框问一个它不会记下的问题。
    "archive.note.placeholder.archive": "为什么归档——留给以后翻到这一条的人。",
    "archive.note.placeholder.unarchive": "为什么把它移回正本——留给以后翻到这一步的人。",

    "archive.record.badge": "归档记录",
    "archive.record.preview": "原路径上会留下",
    "archive.record.fullPage": "完整页面",
    "archive.record.at": "记录在",
    "archive.record.span": "覆盖 {from}–{to}",
    "archive.record.claims": "账本 claim {count} 条",
    "archive.record.sources": "源 {count} 个",
    "archive.record.volumes": "已结卷 {count} 卷",
    "archive.record.inbound": "被活页链接 {count} 处",
    // 与留痕页逐字对齐（prompt catalog 的 `archive.record.reason`：「拥有者于 {date} 归档：
    // 「{note}」」）。日期要到执行那天才定，所以预览里只省掉日期，其余一字不改。
    "archive.record.reason": "拥有者归档：「{note}」",

    "archive.summary.archive.none": "当前没有勾选任何条目。",
    "archive.summary.archive.documents": "将归档 {documents} 篇文档。",
    "archive.summary.archive.sources": "将归档 {sources} 个来源。",
    "archive.summary.archive.both": "将归档 {documents} 篇文档、{sources} 个来源。",
    "archive.summary.unarchive.none": "当前没有勾选任何条目。",
    "archive.summary.unarchive.documents": "将恢复 {documents} 篇文档。",
    "archive.summary.unarchive.sources": "将恢复 {sources} 个来源。",
    "archive.summary.unarchive.both": "将恢复 {documents} 篇文档、{sources} 个来源。",

    "archive.confirm.archive": "确认归档",
    "archive.confirm.unarchive": "确认恢复",
    "archive.cancel": "取消",
    "archive.queued": "已排队：{job}。执行在编译队列上排队进行，完成后正本会更新。",
    // 这串哈希就是「过期」的判据：方案是对着这一版正本算的。不标出来，下面那条过期提示
    // 说的「正本又变了」便无处可指。
    "archive.plan.libraryRef": "基于正本",
    "archive.stale.title": "这份方案已经过期",
    "archive.stale.body":
      "自这份方案计算之后，正本又发生了变化——它预览的是另一个知识库的状态。重新计算一次再确认。",
    "archive.stale.replan": "重新计算",
    "archive.confirmFailed": "确认失败",

    "archive.inventory.title": "归档",
    "archive.inventory.description": "已经移出应答范围的文档与来源。它们仍然完整，仍可被精确引用。",
    "archive.inventory.open": "归档",
    "archive.inventory.openAria": "查看归档里有什么",
    "archive.inventory.documents": "文档 · {count}",
    "archive.inventory.sources": "来源 · {count}",
    "archive.inventory.archivedOn": "归档于 {date}",
    "archive.inventory.volumes": "{count} 个已结卷",
    "archive.inventory.empty.title": "归档是空的",
    "archive.inventory.empty.description": "还没有任何文档或来源被移入归档。",
    "archive.inventory.error": "读不到归档",

    "archive.library.section": "归档",
    "archive.library.sectionCount": "归档 · {count} 篇",
    "archive.library.expand": "展开归档 · {count} 篇",
    "archive.library.collapse": "折叠归档 · {count} 篇",

    "archive.sources.show": "显示已归档",
    "archive.sources.showHint": "把已归档的来源也列出来，并标注。",
    "archive.sources.archivedAt": "归档于 {date}",

    "archive.recall.include": "包含已归档",
    "archive.recall.includeHint": "让答案也读到归档里的内容，读到的每一条都会标注。",
    "archive.recall.hidden": "有 {count} 条已归档证据未显示 · 打开「包含已归档」可查看",
  },
  en: {
    "archive.label": "Archive",
    "archive.badge": "Archived",
    "archive.badge.aria": "This one is archived",

    "archive.action.archive": "Archive…",
    "archive.action.restore": "Restore…",

    "archive.dialog.archive.title": "Archive",
    "archive.dialog.unarchive.title": "Restore from the archive",
    "archive.dialog.archive.description":
      "Archiving MOVES: a document goes under archive/ with its history, a source keeps every block, and every citation still resolves. What changes is that retrieval stops reading them by default.",
    "archive.dialog.unarchive.description":
      "Move them back: documents return to their live paths, sources lose their archive timestamp, and retrieval reads them again.",
    "archive.dialog.planning": "Working out what this pulls with it…",
    "archive.dialog.planFailed": "Could not work out what to archive",

    "archive.group.seeds": "You named",
    "archive.group.cascade.archive": "Will also be archived",
    "archive.group.cascade.unarchive": "Will also be restored",
    "archive.group.related": "Related, not selected",
    "archive.group.related.note":
      "Each of these is still tied to something outside what you named — the reason beside it says what. Ticking one re-plans with it as another starting point.",
    "archive.group.empty": "Nothing else follows from this.",

    "archive.item.document": "Document",
    "archive.item.source": "Source",
    "archive.item.volumes": "with {count} closed volume{count||s}",
    "archive.item.aria": "Select {title}",

    "archive.reason.seed": "you named this",
    "archive.reason.orphaned": "cited by no other live document",
    "archive.reason.stillCited": "still cited by: {documents}",
    "archive.reason.citedByArchived": "still cited by archived: {documents}",
    "archive.reason.restoredWithPage": "restored with its page",
    "archive.reason.fullyDependent": "all {total} claims cite the selected sources ({cited}/{total})",
    "archive.reason.partiallyDependent": "{cited} of {total} claims cite the selected sources",
    "archive.reason.alreadyArchived": "already in the archive",
    "archive.reason.alreadyLive": "already live",
    "archive.reason.andMore": "{shown} and {count} more",

    "archive.note.label": "Note",
    // The two actions leave two different traces — an archive writes its reason onto the
    // record, a restore only moves the page back — so one placeholder would have the
    // restore dialog ask a question it does not keep an answer for.
    "archive.note.placeholder.archive": "Why this is going in — for whoever finds it later.",
    "archive.note.placeholder.unarchive": "Why it is coming back — for whoever finds this later.",

    "archive.record.badge": "Archived record",
    "archive.record.preview": "What stays at the live path",
    "archive.record.fullPage": "Full page",
    "archive.record.at": "Record at",
    "archive.record.span": "Covered {from}–{to}",
    // Labelled numbers, the figure last — word for word what the record page itself will
    // say (`archive.record.facts` in the prompt catalog), so a reader who confirms this
    // preview and then opens the live path finds the same line. Nothing is inflected here
    // either: the page cannot inflect, and a console that said `1 source` over a page
    // saying `sources 1` would be two spellings of one fact.
    "archive.record.claims": "ledger claims {count}",
    "archive.record.sources": "sources {count}",
    "archive.record.volumes": "closed volumes {count}",
    "archive.record.inbound": "linked from live pages {count}",
    "archive.record.reason": "Archived by the owner: «{note}»",

    "archive.summary.archive.none": "Nothing is selected.",
    "archive.summary.archive.documents": "{documents} document{documents||s} will be archived.",
    "archive.summary.archive.sources": "{sources} source{sources||s} will be archived.",
    "archive.summary.archive.both":
      "{documents} document{documents||s} and {sources} source{sources||s} will be archived.",
    "archive.summary.unarchive.none": "Nothing is selected.",
    "archive.summary.unarchive.documents": "{documents} document{documents||s} will be restored.",
    "archive.summary.unarchive.sources": "{sources} source{sources||s} will be restored.",
    "archive.summary.unarchive.both":
      "{documents} document{documents||s} and {sources} source{sources||s} will be restored.",

    "archive.confirm.archive": "Archive",
    "archive.confirm.unarchive": "Restore",
    "archive.cancel": "Cancel",
    "archive.queued": "Queued as {job}. It runs on the compile queue; canonical updates when it lands.",
    // The hash IS the staleness test: the plan was computed against this canonical
    // HEAD. Unlabelled, the warning below has nothing to point at.
    "archive.plan.libraryRef": "Planned against",
    "archive.stale.title": "This plan is out of date",
    "archive.stale.body":
      "Canonical has moved since this plan was computed, so it previews a library state that no longer exists. Plan it again before confirming.",
    "archive.stale.replan": "Re-plan",
    "archive.confirmFailed": "Confirm failed",

    "archive.inventory.title": "Archive",
    "archive.inventory.description":
      "The documents and sources moved out of the answering set. They are whole, and they still answer when addressed.",
    "archive.inventory.open": "Archive",
    "archive.inventory.openAria": "See what is in the archive",
    "archive.inventory.documents": "Documents · {count}",
    "archive.inventory.sources": "Sources · {count}",
    "archive.inventory.archivedOn": "Archived {date}",
    "archive.inventory.volumes": "{count} closed volume{count||s}",
    "archive.inventory.empty.title": "The archive is empty",
    "archive.inventory.empty.description": "Nothing has been moved into the archive yet.",
    "archive.inventory.error": "Could not read the archive",

    "archive.library.section": "Archive",
    "archive.library.sectionCount": "Archive · {count}",
    "archive.library.expand": "Expand the archive · {count} document{count||s}",
    "archive.library.collapse": "Collapse the archive · {count} document{count||s}",

    "archive.sources.show": "Show archived",
    "archive.sources.showHint": "List archived sources too, marked as archived.",
    "archive.sources.archivedAt": "Archived {date}",

    "archive.recall.include": "Include archived",
    "archive.recall.includeHint":
      "Let the answer read the archive too; everything it takes from there is labelled.",
    "archive.recall.hidden":
      "{count} archived item{count||s} {count|was|were} not shown · include archived to see them",
  },
});
