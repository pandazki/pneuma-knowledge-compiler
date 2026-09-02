import { defineMessages } from "./define";

/**
 * The backend's closed vocabularies, keyed by the STABLE key the API already ships
 * (`domain/intake.py::INTAKE_ARCHETYPES`, `domain/suggestion.py::CONTEXT_FOCUSES` /
 * `SUGGESTION_KINDS`). The service keeps serving its English `label` / `summary` — that is
 * the wire contract and it does not move — and the client renders this dictionary instead,
 * falling back to the served text for any key it does not know (`tOr`). A value added to a
 * vocabulary therefore degrades to English rather than to a blank.
 *
 * The `en` column deliberately repeats the server's own wording, so the dictionary path and
 * the fallback path read identically.
 *
 * Source kinds carry TWO key families on purpose: `citationKind.*` is the terse form used in
 * citation chips, `sourceKind.*` the fuller form used in the Sources readers. Both were
 * already distinct in the original copy and both are still needed.
 *
 * `sourceClass.*` and `sourceOrigin.*` complete the trio a catalogue row is filtered by
 * (`domain/source.py`). Provider origins are proper nouns and read the same in both columns —
 * translating "Slack" would name a different thing.
 */
export const enums = defineMessages({
  zh: {
    "enum.intakeArchetype.digest.label": "研读入库",
    "enum.intakeArchetype.digest.summary": "全文编译进知识库",
    "enum.intakeArchetype.digest.examples": "手写笔记、工作产出、短但重要的来源",
    "enum.intakeArchetype.distill.label": "提炼要点",
    "enum.intakeArchetype.distill.summary": "要点进正本，正文留在外部可检索",
    "enum.intakeArchetype.distill.examples": "合同、报告、规格说明",
    "enum.intakeArchetype.archive.label": "仅编目",
    "enum.intakeArchetype.archive.summary": "只留卡片与元数据，正文仍可回溯",
    "enum.intakeArchetype.archive.examples": "书籍、长篇来源",
    "enum.intakeArchetype.searchable.label": "仅可搜索",
    "enum.intakeArchetype.searchable.summary": "不编译、不做语义索引，只保底全文检索",
    "enum.intakeArchetype.searchable.examples": "只想存下来、能找到就行的来源",

    "enum.claimLabel.current": "当前",
    "enum.claimLabel.superseded": "已被取代",

    "enum.contextFocus.general.label": "全部",
    "enum.contextFocus.general.summary": "工作流里任何值得补充的概念或事实，不论出自谁口",
    "enum.contextFocus.owner.label": "只看本人",
    "enum.contextFocus.owner.summary": "只为本人提出的内容出卡；参与者的内容只作理解上下文",
    "enum.contextFocus.other.label": "只看协作者",
    "enum.contextFocus.other.summary": "只为参与者提出的内容出卡；本人的内容只作理解上下文",

    "enum.suggestionKind.concept.label": "概念",
    "enum.suggestionKind.concept.summary":
      "工作流里出现了知识库已有的概念、人物或事项；卡片解释它是什么",
    "enum.suggestionKind.fact.label": "事实",
    "enum.suggestionKind.fact.summary":
      "工作流里出现了知识库能直接回答的问题；卡片给出答案",

    "enum.citationKind.meeting": "会议",
    "enum.citationKind.document_library": "文档",
    "enum.citationKind.im": "即时消息",
    "enum.citationKind.email": "邮件",
    "enum.citationKind.conversation": "对话",
    "enum.citationKind.document": "文档",
    "enum.citationKind.structured": "结构化数据",

    "enum.sourceKind.meeting": "会议",
    "enum.sourceKind.document_library": "文档库",
    "enum.sourceKind.im": "即时消息",
    "enum.sourceKind.email": "电子邮件",
    "enum.sourceKind.owner_dialogue": "所有者陈述",
    "enum.sourceKind.conversation": "对话",
    "enum.sourceKind.document": "文档",
    "enum.sourceKind.structured": "结构化数据",

    "enum.sourceClass.workstream": "工作流",
    "enum.sourceClass.reference": "参考",

    "enum.sourceOrigin.upload": "上传",
    "enum.sourceOrigin.context_stream": "上下文流",
    "enum.sourceOrigin.zoom": "Zoom",
    "enum.sourceOrigin.obsidian": "Obsidian",
    "enum.sourceOrigin.slack": "Slack",
    "enum.sourceOrigin.rfc822": "RFC822",
    "enum.sourceOrigin.mock": "模拟",
  },
  en: {
    "enum.intakeArchetype.digest.label": "Study and file",
    "enum.intakeArchetype.digest.summary": "compiled into the knowledge base in full",
    "enum.intakeArchetype.digest.examples":
      "handwritten notes, work products, short but important pieces",
    "enum.intakeArchetype.distill.label": "Distil key points",
    "enum.intakeArchetype.distill.summary":
      "key information enters canonical, the body stays external and searchable",
    "enum.intakeArchetype.distill.examples": "contracts, reports, specifications",
    "enum.intakeArchetype.archive.label": "Catalogue only",
    "enum.intakeArchetype.archive.summary":
      "a card plus metadata only, the body remains reachable",
    "enum.intakeArchetype.archive.examples": "books, long-form sources",
    "enum.intakeArchetype.searchable.label": "Searchable only",
    "enum.intakeArchetype.searchable.summary":
      "no compile, no semantic indexing, just baseline full-text search",
    "enum.intakeArchetype.searchable.examples":
      "anything you only want stored and findable",

    "enum.claimLabel.current": "current",
    "enum.claimLabel.superseded": "superseded",

    "enum.contextFocus.general.label": "General",
    "enum.contextFocus.general.summary":
      "any concept or fact in the whole workstream worth adding, whoever said it",
    "enum.contextFocus.owner.label": "Owner only",
    "enum.contextFocus.owner.summary":
      "cards only for what the owner put in; participants' content is context for understanding only",
    "enum.contextFocus.other.label": "Collaborators only",
    "enum.contextFocus.other.summary":
      "cards only for what participants put in; the owner's content is context for understanding only",

    "enum.suggestionKind.concept.label": "Concept",
    "enum.suggestionKind.concept.summary":
      "a concept, person or matter the knowledge base already holds appeared in the stream; the card explains what it is",
    "enum.suggestionKind.fact.label": "Fact",
    "enum.suggestionKind.fact.summary":
      "a question the knowledge base can answer directly appeared in the stream; the card gives the answer",

    "enum.citationKind.meeting": "Meeting",
    "enum.citationKind.document_library": "Document",
    "enum.citationKind.im": "Message",
    "enum.citationKind.email": "Email",
    "enum.citationKind.conversation": "Conversation",
    "enum.citationKind.document": "Document",
    "enum.citationKind.structured": "Structured data",

    "enum.sourceKind.meeting": "Meeting",
    "enum.sourceKind.document_library": "Document library",
    "enum.sourceKind.im": "Instant messages",
    "enum.sourceKind.email": "Email",
    "enum.sourceKind.owner_dialogue": "Owner statement",
    "enum.sourceKind.conversation": "Conversation",
    "enum.sourceKind.document": "Document",
    "enum.sourceKind.structured": "Structured data",

    "enum.sourceClass.workstream": "Workstream",
    "enum.sourceClass.reference": "Reference",

    "enum.sourceOrigin.upload": "Upload",
    "enum.sourceOrigin.context_stream": "Context stream",
    "enum.sourceOrigin.zoom": "Zoom",
    "enum.sourceOrigin.obsidian": "Obsidian",
    "enum.sourceOrigin.slack": "Slack",
    "enum.sourceOrigin.rfc822": "RFC822",
    "enum.sourceOrigin.mock": "Mock",
  },
});
