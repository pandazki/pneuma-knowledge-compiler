import { defineMessages } from "./define";

/**
 * The Ingest view: the two import surfaces (structured source contracts, single document)
 * plus the synthetic sample payloads.
 *
 * Two things deliberately stay out of here:
 *   - the intake archetype vocabulary, which the service owns and ./enums renders
 *     (`enum.intakeArchetype.*`), with the served English label as the fallback;
 *   - contract identifiers — schema strings, `source_class`, `canonical_treatment`,
 *     `segments` / `documents` / `conversations` / `threads` — which are wire names, not copy.
 *
 * The `ingest.sample.*` block IS copy: those payloads are hand-written demo content living
 * in the client, so the sample a reader loads is in the language they are reading in. The
 * synthetic contract fields around them (ids, timestamps, addresses) are not translated.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
 */
export const ingest = defineMessages({
  zh: {
    "ingest.pageTitle": "导入 Ingest",
    "ingest.pageDescription":
      "会议、文档库、即时消息与邮件共用一套可审计入口；标准来源契约预检通过后才进入编译流水线。",
    "ingest.noUser.title": "未选择用户",
    "ingest.noUser.description": "在右上角选择或新建一个 user_id，导入的来源归属于该用户。",
    "ingest.readOnly.title": "历史快照 · 只读",
    "ingest.readOnly.body": "正在查看历史快照，导入已禁用；切回 HEAD 后才能提交新来源。",
    "ingest.tabs.aria": "导入方式",
    "ingest.tabs.official": "结构化来源",
    "ingest.tabs.document": "单篇文档",

    "ingest.official.step1": "选择来源协议",
    "ingest.official.kindAria": "官方 source 类型",
    "ingest.official.optionDescription": "{description} 引用单元：{citationUnit}。",
    "ingest.official.step2": "载入标准化 JSON",
    "ingest.official.file.label": "选择 JSON 文件（可选）",
    "ingest.official.file.hint":
      "上传后按 schema 自动切换来源类型；文件只在本地读取，确认导入时才发送。",
    "ingest.official.contract.hint": "可直接粘贴来源适配器产出的标准化 JSON。",
    "ingest.official.loadSample": "载入合成示例",
    "ingest.official.preflight": "预检结构",
    "ingest.official.step3": "确认导入",
    "ingest.official.confirmNote":
      "服务端会再次执行完整 contract 校验；bundle 将按自然引用单元展开，并分别进入 L0–L3 流水线。",
    "ingest.official.submit": "导入 {kind}",
    "ingest.official.fileFailed": "读取 source contract 失败：{detail}",
    "ingest.official.failed": "导入失败",
    "ingest.official.preflightFailed": "预检失败",

    "ingest.official.meeting.description": "带参与者、议程和逐段时间戳的会议记录。",
    "ingest.official.meeting.citationUnit": "整场会议",
    "ingest.official.document_library.description":
      "保留目录层级、frontmatter、标签与双向链接的文档集合。",
    "ingest.official.document_library.citationUnit": "单篇文档",
    "ingest.official.im.description": "频道、私聊及线程消息，保留成员、编辑与 reaction。",
    "ingest.official.im.citationUnit": "单个会话",
    "ingest.official.email.description":
      "按 thread 组织的邮件，保留收发件人、回复链和附件描述。",
    "ingest.official.email.citationUnit": "单个邮件线程",

    "ingest.official.error.jsonParse": "JSON 解析失败：{detail}",
    "ingest.official.error.notObject": "source contract 顶层必须是 JSON object。",
    "ingest.official.error.kindMismatch":
      "当前选择的是 {expectedKind}，需要 {expectedSchema}；收到 {actual}。",
    "ingest.official.error.missingSchema": "缺少 schema",

    "ingest.official.untitled.meeting": "未命名会议",
    "ingest.official.untitled.document_library": "未命名文档库",
    "ingest.official.untitled.im": "未命名 IM archive",
    "ingest.official.untitled.email": "未命名邮件 archive",

    "ingest.official.result.title": "导入完成 · {count} 条 source",
    "ingest.official.result.dedupHit": "去重命中",
    "ingest.official.result.existing": "已存在",
    "ingest.official.result.view": "查看",

    "ingest.sample.owner": "本人",
    "ingest.sample.collaborator": "协作者",
    "ingest.sample.meeting.title": "项目协作周会（示例）",
    "ingest.sample.meeting.agendaScope": "确认本周范围",
    "ingest.sample.meeting.agendaDependencies": "同步外部依赖",
    "ingest.sample.meeting.segment":
      "先确认本周必须交付的范围，以及需要外部协作者确认的依赖。",
    "ingest.sample.library.title": "个人工作库（示例）",
    "ingest.sample.library.docPath": "01-Projects/Demo/项目总览.md",
    "ingest.sample.library.docTitle": "项目总览",
    "ingest.sample.library.docContent":
      "# 项目总览\n\n首期目标是让每一条知识都能回到原始来源。",
    "ingest.sample.library.linkTarget": "02-Areas/独立开发",
    "ingest.sample.library.linkLabel": "独立开发",
    "ingest.sample.im.conversationTitle": "项目协作",
    "ingest.sample.im.message": "接口字段表已经更新，今天可以开始联调。",
    "ingest.sample.email.subject": "项目范围确认",
    "ingest.sample.email.body": "附件中的范围已经确认，下一步可以按两周试点推进。",

    "ingest.document.step1": "编辑",
    "ingest.document.title.label": "标题",
    "ingest.document.title.placeholder": "发布规范 / 会议记录 …",
    "ingest.document.file.label": "从文件读入（可选）",
    "ingest.document.file.hint": "支持 .md / .txt，读入后可在下方继续编辑",
    "ingest.document.body.label": "正文",
    "ingest.document.body.hint": "markdown / 纯文本；按标题分节，无标题按段落",
    "ingest.document.body.placeholder": "# 标题\n\n正文……",
    "ingest.document.archetype.label": "处理意图 intake_archetype",
    "ingest.document.archetype.auto": "自动（让系统判断）",
    "ingest.document.archetype.autoHint":
      "按类型与体量机械判定处理策略，预览时给出系统建议。",
    "ingest.document.archetype.examples": "例：{examples}",
    "ingest.document.sourceClass.auto": "不指定",
    "ingest.document.sourceClass.autoHint": "由系统按内容判断",
    "ingest.document.sourceClass.workstream": "进行中的工作流来源",
    "ingest.document.sourceClass.reference": "长期参考来源",
    "ingest.document.preview": "机械预览",
    "ingest.document.normalizedPrefix": "归一化结果：",
    "ingest.document.blockNoun": "个原文块",
    "ingest.document.charNoun": "字符",
    "ingest.document.proposedArchetype": "系统建议意图",
    "ingest.document.preamble": "(前言)",
    "ingest.document.proposalPrefix": "提案：",
    "ingest.document.treatmentOverride": "canonical_treatment（覆盖）",
    "ingest.document.semanticOverride": "semantic_indexing（覆盖）",
    "ingest.document.proposedOption": "{value} · 提案",
    "ingest.document.confirm": "确认导入",
    "ingest.document.failed": "文档导入失败",
    "ingest.document.fileFailed": "读取文件失败：{detail}",
    "ingest.document.result.deduplicated": "内容去重命中（append-only）",
    "ingest.document.result.stored": "已入库",
    "ingest.document.result.view": "查看来源",
  },
  en: {
    "ingest.pageTitle": "Ingest",
    "ingest.pageDescription":
      "Meetings, document libraries, instant messages and email share one auditable entrance; a source reaches the compile pipeline only after its canonical contract passes preflight.",
    "ingest.noUser.title": "No user selected",
    "ingest.noUser.description":
      "Choose or create a user_id in the top right — an imported source belongs to that user.",
    "ingest.readOnly.title": "Historical snapshot · read-only",
    "ingest.readOnly.body":
      "You are viewing a historical snapshot, so importing is disabled; switch back to HEAD to submit a new source.",
    "ingest.tabs.aria": "Import method",
    "ingest.tabs.official": "Structured source",
    "ingest.tabs.document": "Single document",

    "ingest.official.step1": "Choose the source protocol",
    "ingest.official.kindAria": "Official source type",
    "ingest.official.optionDescription": "{description} Citation unit: {citationUnit}.",
    "ingest.official.step2": "Load the canonical JSON",
    "ingest.official.file.label": "Choose a JSON file (optional)",
    "ingest.official.file.hint":
      "An upload switches the source type by its schema; the file is read locally and only sent when you confirm the import.",
    "ingest.official.contract.hint":
      "Paste the canonical JSON a provider adapter produced.",
    "ingest.official.loadSample": "Load a synthetic sample",
    "ingest.official.preflight": "Preflight the structure",
    "ingest.official.step3": "Confirm the import",
    "ingest.official.confirmNote":
      "The service validates the whole contract again; the bundle is expanded along its natural citation units, each of which enters the L0–L3 pipeline on its own.",
    "ingest.official.submit": "Import {kind}",
    "ingest.official.fileFailed": "Could not read the source contract: {detail}",
    "ingest.official.failed": "Import failed",
    "ingest.official.preflightFailed": "Preflight failed",

    "ingest.official.meeting.description":
      "A meeting record with participants, an agenda and per-segment timestamps.",
    "ingest.official.meeting.citationUnit": "the whole meeting",
    "ingest.official.document_library.description":
      "A document collection that keeps its folder hierarchy, frontmatter, tags and backlinks.",
    "ingest.official.document_library.citationUnit": "one document",
    "ingest.official.im.description":
      "Channel, direct and threaded messages, with members, edits and reactions kept.",
    "ingest.official.im.citationUnit": "one conversation",
    "ingest.official.email.description":
      "Email organised by thread, keeping senders and recipients, the reply chain and attachment descriptions.",
    "ingest.official.email.citationUnit": "one mail thread",

    "ingest.official.error.jsonParse": "JSON parse failed: {detail}",
    "ingest.official.error.notObject":
      "The top level of a source contract must be a JSON object.",
    "ingest.official.error.kindMismatch":
      "You have selected {expectedKind}, which needs {expectedSchema}; received {actual}.",
    "ingest.official.error.missingSchema": "no schema",

    "ingest.official.untitled.meeting": "Untitled meeting",
    "ingest.official.untitled.document_library": "Untitled document library",
    "ingest.official.untitled.im": "Untitled IM archive",
    "ingest.official.untitled.email": "Untitled mail archive",

    "ingest.official.result.title": "Import complete · {count} source{count||s}",
    "ingest.official.result.dedupHit": "deduplicated",
    "ingest.official.result.existing": "already held",
    "ingest.official.result.view": "View",

    "ingest.sample.owner": "Owner",
    "ingest.sample.collaborator": "Collaborator",
    "ingest.sample.meeting.title": "Weekly project sync (sample)",
    "ingest.sample.meeting.agendaScope": "Confirm this week's scope",
    "ingest.sample.meeting.agendaDependencies": "Sync the external dependencies",
    "ingest.sample.meeting.segment":
      "Let us start with the scope we have to deliver this week, and the dependencies an external collaborator still has to confirm.",
    "ingest.sample.library.title": "Personal working library (sample)",
    "ingest.sample.library.docPath": "01-Projects/Demo/Project overview.md",
    "ingest.sample.library.docTitle": "Project overview",
    "ingest.sample.library.docContent":
      "# Project overview\n\nThe first goal is for every piece of knowledge to lead back to its original source.",
    "ingest.sample.library.linkTarget": "02-Areas/Indie development",
    "ingest.sample.library.linkLabel": "Indie development",
    "ingest.sample.im.conversationTitle": "Project collaboration",
    "ingest.sample.im.message":
      "The interface field table is updated, so we can start integration testing today.",
    "ingest.sample.email.subject": "Project scope confirmation",
    "ingest.sample.email.body":
      "The scope in the attachment is confirmed; the next step can run as a two-week pilot.",

    "ingest.document.step1": "Edit",
    "ingest.document.title.label": "Title",
    "ingest.document.title.placeholder": "Publishing standard / meeting notes …",
    "ingest.document.file.label": "Read from a file (optional)",
    "ingest.document.file.hint":
      ".md / .txt; you can keep editing below once it is loaded",
    "ingest.document.body.label": "Body",
    "ingest.document.body.hint":
      "markdown / plain text; split by heading, or by paragraph when there are none",
    "ingest.document.body.placeholder": "# Title\n\nBody…",
    "ingest.document.archetype.label": "Processing intent intake_archetype",
    "ingest.document.archetype.auto": "Automatic (let the system decide)",
    "ingest.document.archetype.autoHint":
      "The strategy is decided mechanically from kind and size; the preview shows what the system proposes.",
    "ingest.document.archetype.examples": "e.g. {examples}",
    "ingest.document.sourceClass.auto": "Unspecified",
    "ingest.document.sourceClass.autoHint": "decided by the system from the content",
    "ingest.document.sourceClass.workstream": "a source from work in progress",
    "ingest.document.sourceClass.reference": "a long-lived reference source",
    "ingest.document.preview": "Mechanical preview",
    "ingest.document.normalizedPrefix": "Normalised: ",
    "ingest.document.blockNoun": "blocks",
    "ingest.document.charNoun": "chars",
    "ingest.document.proposedArchetype": "the system proposes",
    "ingest.document.preamble": "(preamble)",
    "ingest.document.proposalPrefix": "Proposal: ",
    "ingest.document.treatmentOverride": "canonical_treatment (override)",
    "ingest.document.semanticOverride": "semantic_indexing (override)",
    "ingest.document.proposedOption": "{value} · proposed",
    "ingest.document.confirm": "Confirm the import",
    "ingest.document.failed": "Document import failed",
    "ingest.document.fileFailed": "Could not read the file: {detail}",
    "ingest.document.result.deduplicated": "Content deduplicated (append-only)",
    "ingest.document.result.stored": "Stored",
    "ingest.document.result.view": "View the source",
  },
});
