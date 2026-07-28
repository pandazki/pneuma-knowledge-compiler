export interface PresentableBlock {
  index: number;
  text: string;
  section_path: string[];
}

export interface PresentableSource {
  kind: string;
  created_at: string;
  meta: Record<string, unknown>;
  blocks: PresentableBlock[];
}

export interface PersonAddress {
  address: string;
  displayName: string | null;
}

export interface AttachmentPresentation {
  filename: string;
  contentType: string;
  sizeBytes: number;
}

export interface ParticipantPresentation {
  id: string;
  displayName: string;
  email: string | null;
  owner: boolean;
}

export interface TimelineItemPresentation {
  blockIndex: number;
  segmentId: string;
  speakerId: string;
  speaker: string;
  owner: boolean;
  startedAt: string | null;
  endedAt: string | null;
  text: string;
}

export interface MessagePresentation {
  blockIndex: number;
  messageId: string;
  speakerId: string;
  speaker: string;
  owner: boolean;
  sentAt: string | null;
  editedAt: string | null;
  threadId: string | null;
  isReply: boolean;
  reactions: { name: string; count: number }[];
  text: string;
  date: string | null;
}

export interface EmailMessagePresentation {
  blockIndex: number;
  messageId: string;
  sentAt: string | null;
  from: PersonAddress;
  to: PersonAddress[];
  cc: PersonAddress[];
  subject: string;
  owner: boolean;
  inReplyTo: string | null;
  attachments: AttachmentPresentation[];
  body: string;
}

export type SourcePresentation =
  | {
      kind: "meeting";
      startedAt: string;
      endedAt: string | null;
      timezone: string | null;
      durationMinutes: number | null;
      participants: ParticipantPresentation[];
      agenda: string[];
      segments: TimelineItemPresentation[];
    }
  | {
      kind: "document_library";
      libraryId: string | null;
      libraryTitle: string | null;
      path: string | null;
      pathParts: string[];
      frontmatter: Record<string, unknown>;
      tags: string[];
      links: { target: string; label: string | null; embedded: boolean }[];
      createdAt: string | null;
      modifiedAt: string | null;
      blocks: PresentableBlock[];
    }
  | {
      kind: "im";
      conversationType: string;
      purpose: string | null;
      members: ParticipantPresentation[];
      messages: MessagePresentation[];
    }
  | {
      kind: "email";
      threadId: string | null;
      ownerAddresses: string[];
      messages: EmailMessagePresentation[];
    }
  | {
      kind: "generic";
      blocks: PresentableBlock[];
    };

const SOURCE_KIND_LABELS: Record<string, string> = {
  meeting: "会议",
  document_library: "文档库",
  im: "即时消息",
  email: "电子邮件",
  conversation: "对话",
  document: "文档",
  structured: "结构化数据",
};

export function sourceKindLabel(kind: string): string {
  return SOURCE_KIND_LABELS[kind] ?? kind;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function objectArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(objectValue) : [];
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function booleanValue(value: unknown): boolean {
  return value === true;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function durationMinutes(startedAt: string, endedAt: string | null): number | null {
  if (!endedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = new Date(endedAt).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return Math.round((end - start) / 60_000);
}

function splitSpeakerText(text: string): {
  speaker: string;
  owner: boolean;
  body: string;
} {
  const separator = text.indexOf("：");
  if (separator < 0) return { speaker: "未知发言人", owner: false, body: text };
  const rawSpeaker = text.slice(0, separator);
  const owner = rawSpeaker.startsWith("本人（") && rawSpeaker.endsWith("）");
  return {
    speaker: owner ? rawSpeaker.slice(3, -1) : rawSpeaker,
    owner,
    body: text.slice(separator + 1),
  };
}

function addressValue(value: unknown): PersonAddress {
  const record = objectValue(value);
  return {
    address: stringValue(record.address) ?? "—",
    displayName: stringValue(record.display_name),
  };
}

function attachmentValue(value: unknown): AttachmentPresentation {
  const record = objectValue(value);
  return {
    filename: stringValue(record.filename) ?? "未命名附件",
    contentType: stringValue(record.content_type) ?? "application/octet-stream",
    sizeBytes: numberValue(record.size_bytes),
  };
}

function emailBody(text: string, hasAttachments: boolean): string {
  const lines = text.split("\n");
  const body = lines.slice(2);
  if (hasAttachments && body[body.length - 1]?.startsWith("附件：")) body.pop();
  return body.join("\n").trim();
}

function buildMeeting(source: PresentableSource): SourcePresentation {
  const meta = source.meta;
  const ownerIds = new Set(stringArray(meta.owner_participant_ids));
  const participants = objectArray(meta.participants).map((item) => {
    const id = stringValue(item.participant_id) ?? "unknown";
    return {
      id,
      displayName: stringValue(item.display_name) ?? id,
      email: stringValue(item.email),
      owner: ownerIds.has(id),
    };
  });
  const people = new Map(participants.map((person) => [person.id, person]));
  const segmentMeta = objectArray(meta.segments);
  const segments = source.blocks.map((block, index) => {
    const envelope = segmentMeta[index] ?? {};
    const fallback = splitSpeakerText(block.text);
    const speakerId = stringValue(envelope.speaker_id) ?? "";
    const participant = people.get(speakerId);
    return {
      blockIndex: block.index,
      segmentId: stringValue(envelope.segment_id) ?? `block-${block.index}`,
      speakerId,
      speaker: participant?.displayName ?? fallback.speaker,
      owner: participant?.owner ?? fallback.owner,
      startedAt: stringValue(envelope.started_at),
      endedAt: stringValue(envelope.ended_at),
      text: fallback.body,
    };
  });
  const startedAt = stringValue(meta.started_at) ?? source.created_at;
  const endedAt = stringValue(meta.ended_at);
  return {
    kind: "meeting",
    startedAt,
    endedAt,
    timezone: stringValue(meta.timezone),
    durationMinutes: durationMinutes(startedAt, endedAt),
    participants,
    agenda: stringArray(meta.agenda),
    segments,
  };
}

function buildDocument(source: PresentableSource): SourcePresentation {
  const meta = source.meta;
  const path = stringValue(meta.path);
  return {
    kind: "document_library",
    libraryId: stringValue(meta.library_id),
    libraryTitle: stringValue(meta.library_title),
    path,
    pathParts: path?.split("/").filter(Boolean) ?? [],
    frontmatter: objectValue(meta.frontmatter),
    tags: stringArray(meta.tags),
    links: objectArray(meta.links).map((link) => ({
      target: stringValue(link.target) ?? "—",
      label: stringValue(link.label),
      embedded: booleanValue(link.embedded),
    })),
    createdAt: stringValue(meta.created_at),
    modifiedAt: stringValue(meta.modified_at),
    blocks: source.blocks,
  };
}

function buildIm(source: PresentableSource): SourcePresentation {
  const meta = source.meta;
  const ownerIds = new Set(stringArray(meta.owner_user_ids));
  const members = objectArray(meta.users).map((item) => {
    const id = stringValue(item.user_id) ?? "unknown";
    return {
      id,
      displayName: stringValue(item.display_name) ?? id,
      email: stringValue(item.email),
      owner: ownerIds.has(id),
    };
  });
  const people = new Map(members.map((person) => [person.id, person]));
  const messageMeta = objectArray(meta.messages);
  const messages = source.blocks.map((block, index) => {
    const envelope = messageMeta[index] ?? {};
    const fallback = splitSpeakerText(block.text);
    const speakerId = stringValue(envelope.sender_id) ?? "";
    const person = people.get(speakerId);
    const threadId = stringValue(envelope.thread_id);
    const messageId = stringValue(envelope.message_id) ?? `block-${block.index}`;
    return {
      blockIndex: block.index,
      messageId,
      speakerId,
      speaker: person?.displayName ?? fallback.speaker,
      owner: person?.owner ?? fallback.owner,
      sentAt: stringValue(envelope.sent_at),
      editedAt: stringValue(envelope.edited_at),
      threadId,
      isReply: threadId != null && threadId !== messageId,
      reactions: objectArray(envelope.reactions).map((reaction) => ({
        name: stringValue(reaction.name) ?? "reaction",
        count: numberValue(reaction.count),
      })),
      text: fallback.body,
      date: block.section_path[0] ?? null,
    };
  });
  return {
    kind: "im",
    conversationType: stringValue(meta.conversation_type) ?? "conversation",
    purpose: stringValue(objectValue(meta.metadata).purpose),
    members,
    messages,
  };
}

function buildEmail(source: PresentableSource): SourcePresentation {
  const meta = source.meta;
  const ownerAddresses = stringArray(meta.owner_addresses);
  const owners = new Set(ownerAddresses.map((address) => address.toLocaleLowerCase()));
  const messageMeta = objectArray(meta.messages);
  const messages = source.blocks.map((block, index) => {
    const envelope = messageMeta[index] ?? {};
    const attachments = objectArray(envelope.attachments).map(attachmentValue);
    const from = addressValue(envelope.from);
    return {
      blockIndex: block.index,
      messageId: stringValue(envelope.message_id) ?? `block-${block.index}`,
      sentAt: stringValue(envelope.sent_at),
      from,
      to: objectArray(envelope.to).map(addressValue),
      cc: objectArray(envelope.cc).map(addressValue),
      subject: stringValue(envelope.subject) ?? "（无主题）",
      owner: owners.has(from.address.toLocaleLowerCase()),
      inReplyTo: stringValue(envelope.in_reply_to),
      attachments,
      body: emailBody(block.text, attachments.length > 0),
    };
  });
  return {
    kind: "email",
    threadId: stringValue(meta.thread_id),
    ownerAddresses,
    messages,
  };
}

export function buildSourcePresentation(source: PresentableSource): SourcePresentation {
  switch (source.kind) {
    case "meeting":
      return buildMeeting(source);
    case "document_library":
      return buildDocument(source);
    case "im":
      return buildIm(source);
    case "email":
      return buildEmail(source);
    default:
      return { kind: "generic", blocks: source.blocks };
  }
}
