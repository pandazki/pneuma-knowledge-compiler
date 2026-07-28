export type OfficialSourceKind = "meeting" | "document_library" | "im" | "email";

export interface OfficialSourceOption {
  kind: OfficialSourceKind;
  schema: string;
  label: string;
  provider: string;
  description: string;
  citationUnit: string;
}

export const OFFICIAL_SOURCE_OPTIONS: OfficialSourceOption[] = [
  {
    kind: "meeting",
    schema: "pneuma.source.meeting/v1",
    label: "会议",
    provider: "Zoom / canonical JSON",
    description: "带参与者、议程和逐段时间戳的会议记录。",
    citationUnit: "整场会议",
  },
  {
    kind: "document_library",
    schema: "pneuma.source.document-library/v1",
    label: "文档库",
    provider: "Obsidian / canonical JSON",
    description: "保留目录层级、frontmatter、标签与双向链接的文档集合。",
    citationUnit: "单篇文档",
  },
  {
    kind: "im",
    schema: "pneuma.source.im/v1",
    label: "即时消息",
    provider: "Slack / canonical JSON",
    description: "频道、私聊及线程消息，保留成员、编辑与 reaction。",
    citationUnit: "单个会话",
  },
  {
    kind: "email",
    schema: "pneuma.source.email/v1",
    label: "电子邮件",
    provider: "RFC 5322 / canonical JSON",
    description: "按 thread 组织的邮件，保留收发件人、回复链和附件描述。",
    citationUnit: "单个邮件线程",
  },
];

const OPTION_BY_SCHEMA = new Map(
  OFFICIAL_SOURCE_OPTIONS.map((option) => [option.schema, option] as const),
);
const OPTION_BY_KIND = new Map(
  OFFICIAL_SOURCE_OPTIONS.map((option) => [option.kind, option] as const),
);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

export function detectOfficialSourceKind(payload: unknown): OfficialSourceKind | null {
  if (!isRecord(payload) || typeof payload.schema !== "string") return null;
  return OPTION_BY_SCHEMA.get(payload.schema)?.kind ?? null;
}

export function parseOfficialSourcePayload(
  source: string,
  expectedKind: OfficialSourceKind,
): Record<string, unknown> {
  let payload: unknown;
  try {
    payload = JSON.parse(source);
  } catch (error) {
    throw new Error(`JSON 解析失败：${(error as Error).message}`);
  }
  if (!isRecord(payload)) {
    throw new Error("source contract 顶层必须是 JSON object。");
  }
  const actualKind = detectOfficialSourceKind(payload);
  const expected = OPTION_BY_KIND.get(expectedKind);
  if (actualKind !== expectedKind) {
    const actual =
      typeof payload.schema === "string" ? payload.schema : "缺少 schema";
    throw new Error(
      `当前选择的是 ${expectedKind}，需要 ${expected?.schema ?? expectedKind}；收到 ${actual}。`,
    );
  }
  return payload;
}

export interface OfficialSourceSummary {
  title: string;
  provider: string;
  itemLabel: string;
  itemCount: number;
}

export function summarizeOfficialSourcePayload(
  payload: Record<string, unknown>,
  kind: OfficialSourceKind,
): OfficialSourceSummary {
  const provider = typeof payload.provider === "string" ? payload.provider : "unknown";
  if (kind === "meeting") {
    return {
      title: typeof payload.title === "string" ? payload.title : "未命名会议",
      provider,
      itemLabel: "segments",
      itemCount: Array.isArray(payload.segments) ? payload.segments.length : 0,
    };
  }
  if (kind === "document_library") {
    return {
      title: typeof payload.title === "string" ? payload.title : "未命名文档库",
      provider,
      itemLabel: "documents",
      itemCount: Array.isArray(payload.documents) ? payload.documents.length : 0,
    };
  }
  if (kind === "im") {
    return {
      title: typeof payload.archive_id === "string" ? payload.archive_id : "未命名 IM archive",
      provider,
      itemLabel: "conversations",
      itemCount: Array.isArray(payload.conversations) ? payload.conversations.length : 0,
    };
  }
  return {
    title: typeof payload.archive_id === "string" ? payload.archive_id : "未命名邮件 archive",
    provider,
    itemLabel: "threads",
    itemCount: Array.isArray(payload.threads) ? payload.threads.length : 0,
  };
}

const TEMPLATES: Record<OfficialSourceKind, Record<string, unknown>> = {
  meeting: {
    schema: "pneuma.source.meeting/v1",
    provider: "mock",
    meeting_id: "meeting-synthetic-001",
    title: "项目协作周会（示例）",
    started_at: "2026-07-28T09:00:00+08:00",
    ended_at: "2026-07-28T09:30:00+08:00",
    timezone: "Asia/Shanghai",
    owner_participant_ids: ["owner"],
    participants: [
      {
        participant_id: "owner",
        display_name: "本人",
        email: "owner@example.dev",
      },
      {
        participant_id: "collaborator",
        display_name: "协作者",
        email: "collaborator@example.dev",
      },
    ],
    agenda: ["确认本周范围", "同步外部依赖"],
    segments: [
      {
        segment_id: "segment-001",
        speaker_id: "owner",
        started_at: "2026-07-28T09:00:05+08:00",
        ended_at: "2026-07-28T09:00:25+08:00",
        text: "先确认本周必须交付的范围，以及需要外部协作者确认的依赖。",
      },
    ],
    metadata: { synthetic: true },
  },
  document_library: {
    schema: "pneuma.source.document-library/v1",
    provider: "mock",
    library_id: "vault-synthetic-001",
    title: "个人工作库（示例）",
    documents: [
      {
        document_id: "doc-project-overview",
        path: "01-Projects/Demo/项目总览.md",
        title: "项目总览",
        content: "# 项目总览\n\n首期目标是让每一条知识都能回到原始来源。",
        frontmatter: { status: "active", synthetic: true },
        tags: ["project/demo"],
        links: [{ target: "02-Areas/独立开发", label: "独立开发", embedded: false }],
        created_at: "2026-07-28T09:00:00+08:00",
        modified_at: "2026-07-28T09:10:00+08:00",
        metadata: {},
      },
    ],
    metadata: { synthetic: true },
  },
  im: {
    schema: "pneuma.source.im/v1",
    provider: "mock",
    archive_id: "im-synthetic-001",
    owner_user_ids: ["U_OWNER"],
    users: [
      {
        user_id: "U_OWNER",
        display_name: "本人",
        email: "owner@example.dev",
        is_bot: false,
      },
      {
        user_id: "U_COLLAB",
        display_name: "协作者",
        email: "collaborator@example.dev",
        is_bot: false,
      },
    ],
    conversations: [
      {
        conversation_id: "C_PROJECT",
        conversation_type: "channel",
        title: "项目协作",
        member_ids: ["U_OWNER", "U_COLLAB"],
        messages: [
          {
            message_id: "M001",
            sender_id: "U_COLLAB",
            sent_at: "2026-07-28T10:00:00+08:00",
            text: "接口字段表已经更新，今天可以开始联调。",
            thread_id: null,
            edited_at: null,
            reactions: [{ name: "eyes", count: 1 }],
            metadata: {},
          },
        ],
        metadata: {},
      },
    ],
    metadata: { synthetic: true },
  },
  email: {
    schema: "pneuma.source.email/v1",
    provider: "mock",
    archive_id: "mail-synthetic-001",
    owner_addresses: ["owner@example.dev"],
    threads: [
      {
        thread_id: "thread-project-scope",
        subject: "项目范围确认",
        messages: [
          {
            message_id: "<message-001@example.dev>",
            sent_at: "2026-07-28T11:00:00+08:00",
            from: {
              address: "collaborator@example.dev",
              display_name: "协作者",
            },
            to: [{ address: "owner@example.dev", display_name: "本人" }],
            cc: [],
            subject: "项目范围确认",
            text: "附件中的范围已经确认，下一步可以按两周试点推进。",
            in_reply_to: null,
            references: [],
            attachments: [
              {
                filename: "scope.pdf",
                content_type: "application/pdf",
                size_bytes: 1024,
                content_id: null,
              },
            ],
            metadata: {},
          },
        ],
        metadata: {},
      },
    ],
    metadata: { synthetic: true },
  },
};

export function officialSourceTemplate(kind: OfficialSourceKind): string {
  return JSON.stringify(TEMPLATES[kind], null, 2);
}
