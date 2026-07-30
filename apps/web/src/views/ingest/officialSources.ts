/**
 * The four official source contracts the Web import surface publishes, plus canonical-JSON
 * preflight and the synthetic samples.
 *
 * Wording never comes from a runtime import here: the tests transpile this file on its own
 * into a data: URL module, so an `import { tx }` would not resolve. Enumerated labels are
 * therefore returned as message KEYS for the view to translate, and anything that has to be
 * composed takes an injected lookup (`OfficialSourceI18n`, see lib/useT: `useT`).
 */
import type { MessageKey } from "@/i18n";

export type OfficialSourceKind = "meeting" | "document_library" | "im" | "email";

/** The translator a caller supplies; `t` is the view's `useT()`. */
export interface OfficialSourceI18n {
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

export interface OfficialSourceOption {
  kind: OfficialSourceKind;
  schema: string;
  /** The shared source-kind vocabulary — the same word the Sources readers use. */
  labelKey: MessageKey;
  provider: string;
  descriptionKey: MessageKey;
  citationUnitKey: MessageKey;
}

export const OFFICIAL_SOURCE_OPTIONS: OfficialSourceOption[] = [
  {
    kind: "meeting",
    schema: "pneuma.source.meeting/v1",
    labelKey: "enum.sourceKind.meeting",
    provider: "Zoom / canonical JSON",
    descriptionKey: "ingest.official.meeting.description",
    citationUnitKey: "ingest.official.meeting.citationUnit",
  },
  {
    kind: "document_library",
    schema: "pneuma.source.document-library/v1",
    labelKey: "enum.sourceKind.document_library",
    provider: "Obsidian / canonical JSON",
    descriptionKey: "ingest.official.document_library.description",
    citationUnitKey: "ingest.official.document_library.citationUnit",
  },
  {
    kind: "im",
    schema: "pneuma.source.im/v1",
    labelKey: "enum.sourceKind.im",
    provider: "Slack / canonical JSON",
    descriptionKey: "ingest.official.im.description",
    citationUnitKey: "ingest.official.im.citationUnit",
  },
  {
    kind: "email",
    schema: "pneuma.source.email/v1",
    labelKey: "enum.sourceKind.email",
    provider: "RFC 5322 / canonical JSON",
    descriptionKey: "ingest.official.email.description",
    citationUnitKey: "ingest.official.email.citationUnit",
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
  i18n: OfficialSourceI18n,
): Record<string, unknown> {
  let payload: unknown;
  try {
    payload = JSON.parse(source);
  } catch (error) {
    throw new Error(
      i18n.t("ingest.official.error.jsonParse", { detail: (error as Error).message }),
    );
  }
  if (!isRecord(payload)) {
    throw new Error(i18n.t("ingest.official.error.notObject"));
  }
  const actualKind = detectOfficialSourceKind(payload);
  const expected = OPTION_BY_KIND.get(expectedKind);
  if (actualKind !== expectedKind) {
    const actual =
      typeof payload.schema === "string"
        ? payload.schema
        : i18n.t("ingest.official.error.missingSchema");
    throw new Error(
      i18n.t("ingest.official.error.kindMismatch", {
        expectedKind,
        expectedSchema: expected?.schema ?? expectedKind,
        actual,
      }),
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

/** The fallback title per contract, for a payload that carries no readable one. */
const UNTITLED_KEY: Record<OfficialSourceKind, MessageKey> = {
  meeting: "ingest.official.untitled.meeting",
  document_library: "ingest.official.untitled.document_library",
  im: "ingest.official.untitled.im",
  email: "ingest.official.untitled.email",
};

export function summarizeOfficialSourcePayload(
  payload: Record<string, unknown>,
  kind: OfficialSourceKind,
  i18n: OfficialSourceI18n,
): OfficialSourceSummary {
  const provider = typeof payload.provider === "string" ? payload.provider : "unknown";
  // `itemLabel` names a contract array (segments / documents / …), so it stays untranslated.
  const untitled = i18n.t(UNTITLED_KEY[kind]);
  if (kind === "meeting") {
    return {
      title: typeof payload.title === "string" ? payload.title : untitled,
      provider,
      itemLabel: "segments",
      itemCount: Array.isArray(payload.segments) ? payload.segments.length : 0,
    };
  }
  if (kind === "document_library") {
    return {
      title: typeof payload.title === "string" ? payload.title : untitled,
      provider,
      itemLabel: "documents",
      itemCount: Array.isArray(payload.documents) ? payload.documents.length : 0,
    };
  }
  if (kind === "im") {
    return {
      title: typeof payload.archive_id === "string" ? payload.archive_id : untitled,
      provider,
      itemLabel: "conversations",
      itemCount: Array.isArray(payload.conversations) ? payload.conversations.length : 0,
    };
  }
  return {
    title: typeof payload.archive_id === "string" ? payload.archive_id : untitled,
    provider,
    itemLabel: "threads",
    itemCount: Array.isArray(payload.threads) ? payload.threads.length : 0,
  };
}

/**
 * The synthetic sample payloads. Ids, timestamps and addresses are fixed contract data; the
 * prose around them is demo copy and follows the reader's language.
 */
function officialSourceTemplatePayload(
  kind: OfficialSourceKind,
  i18n: OfficialSourceI18n,
): Record<string, unknown> {
  const owner = i18n.t("ingest.sample.owner");
  const collaborator = i18n.t("ingest.sample.collaborator");
  if (kind === "meeting") {
    return {
      schema: "pneuma.source.meeting/v1",
      provider: "mock",
      meeting_id: "meeting-synthetic-001",
      title: i18n.t("ingest.sample.meeting.title"),
      started_at: "2026-07-28T09:00:00+08:00",
      ended_at: "2026-07-28T09:30:00+08:00",
      timezone: "Asia/Shanghai",
      owner_participant_ids: ["owner"],
      participants: [
        {
          participant_id: "owner",
          display_name: owner,
          email: "owner@example.dev",
        },
        {
          participant_id: "collaborator",
          display_name: collaborator,
          email: "collaborator@example.dev",
        },
      ],
      agenda: [
        i18n.t("ingest.sample.meeting.agendaScope"),
        i18n.t("ingest.sample.meeting.agendaDependencies"),
      ],
      segments: [
        {
          segment_id: "segment-001",
          speaker_id: "owner",
          started_at: "2026-07-28T09:00:05+08:00",
          ended_at: "2026-07-28T09:00:25+08:00",
          text: i18n.t("ingest.sample.meeting.segment"),
        },
      ],
      metadata: { synthetic: true },
    };
  }
  if (kind === "document_library") {
    return {
      schema: "pneuma.source.document-library/v1",
      provider: "mock",
      library_id: "vault-synthetic-001",
      title: i18n.t("ingest.sample.library.title"),
      documents: [
        {
          document_id: "doc-project-overview",
          path: i18n.t("ingest.sample.library.docPath"),
          title: i18n.t("ingest.sample.library.docTitle"),
          content: i18n.t("ingest.sample.library.docContent"),
          frontmatter: { status: "active", synthetic: true },
          tags: ["project/demo"],
          links: [
            {
              target: i18n.t("ingest.sample.library.linkTarget"),
              label: i18n.t("ingest.sample.library.linkLabel"),
              embedded: false,
            },
          ],
          created_at: "2026-07-28T09:00:00+08:00",
          modified_at: "2026-07-28T09:10:00+08:00",
          metadata: {},
        },
      ],
      metadata: { synthetic: true },
    };
  }
  if (kind === "im") {
    return {
      schema: "pneuma.source.im/v1",
      provider: "mock",
      archive_id: "im-synthetic-001",
      owner_user_ids: ["U_OWNER"],
      users: [
        {
          user_id: "U_OWNER",
          display_name: owner,
          email: "owner@example.dev",
          is_bot: false,
        },
        {
          user_id: "U_COLLAB",
          display_name: collaborator,
          email: "collaborator@example.dev",
          is_bot: false,
        },
      ],
      conversations: [
        {
          conversation_id: "C_PROJECT",
          conversation_type: "channel",
          title: i18n.t("ingest.sample.im.conversationTitle"),
          member_ids: ["U_OWNER", "U_COLLAB"],
          messages: [
            {
              message_id: "M001",
              sender_id: "U_COLLAB",
              sent_at: "2026-07-28T10:00:00+08:00",
              text: i18n.t("ingest.sample.im.message"),
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
    };
  }
  const subject = i18n.t("ingest.sample.email.subject");
  return {
    schema: "pneuma.source.email/v1",
    provider: "mock",
    archive_id: "mail-synthetic-001",
    owner_addresses: ["owner@example.dev"],
    threads: [
      {
        thread_id: "thread-project-scope",
        subject,
        messages: [
          {
            message_id: "<message-001@example.dev>",
            sent_at: "2026-07-28T11:00:00+08:00",
            from: {
              address: "collaborator@example.dev",
              display_name: collaborator,
            },
            to: [{ address: "owner@example.dev", display_name: owner }],
            cc: [],
            subject,
            text: i18n.t("ingest.sample.email.body"),
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
  };
}

export function officialSourceTemplate(
  kind: OfficialSourceKind,
  i18n: OfficialSourceI18n,
): string {
  return JSON.stringify(officialSourceTemplatePayload(kind, i18n), null, 2);
}
