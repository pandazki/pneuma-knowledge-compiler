import type { RefCallback } from "react";
import {
  AtSign,
  CalendarDays,
  ChevronRight,
  Clock3,
  FileText,
  Folder,
  Hash,
  Link2,
  Mail,
  MessageSquare,
  Paperclip,
  Tag,
  Users,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { SourceDetail } from "@/lib/api";
import { fmtDate, fmtTime } from "@/lib/format";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { cn } from "@/ui/cn";

import {
  buildSourcePresentation,
  sourceKindLabel,
  type AttachmentPresentation,
  type EmailMessagePresentation,
  type ParticipantPresentation,
  type PersonAddress,
  type SourcePresentation,
} from "./sourcePresentation";

export interface SourceReaderProps {
  detail: SourceDetail;
  inRange: (index: number) => boolean;
  onFetchBlock: (index: number) => void;
  blockRef: (index: number) => RefCallback<HTMLElement>;
  fetching: boolean;
}

function clockTime(ts: string | null): string {
  if (!ts) return "—";
  const value = new Date(ts);
  if (Number.isNaN(value.getTime())) return ts;
  return value.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function metadataValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}

function initialOf(name: string): string {
  return Array.from(name.trim())[0] ?? "?";
}

function addressLabel(address: PersonAddress): string {
  return address.displayName
    ? `${address.displayName} <${address.address}>`
    : address.address;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function BlockLocator({
  index,
  fetching,
  onFetch,
}: {
  index: number;
  fetching: boolean;
  onFetch: (index: number) => void;
}) {
  return (
    <button
      type="button"
      disabled={fetching}
      onClick={() => onFetch(index)}
      aria-label={`取 block ${index} 精确段`}
      title="取精确原文段"
      className="shrink-0 rounded-1 px-1 py-0.5 text-ink-3 hover:bg-hover hover:text-accent disabled:opacity-45"
    >
      <Mono className="text-12">b{index}</Mono>
    </button>
  );
}

function ParticipantList({ participants }: { participants: ParticipantPresentation[] }) {
  if (participants.length === 0) return <span className="text-ink-3">未提供参与者元信息</span>;
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {participants.map((participant) => (
        <Badge key={participant.id} tone={participant.owner ? "accent" : "neutral"}>
          {participant.displayName}
          {participant.owner ? " · 本人" : ""}
        </Badge>
      ))}
    </span>
  );
}

function MeetingReader({
  presentation,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: Omit<SourceReaderProps, "detail"> & {
  presentation: Extract<SourcePresentation, { kind: "meeting" }>;
}) {
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title="会议概览" />
        <dl className="grid border-y border-line sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex gap-3 border-b border-line py-3 sm:border-r sm:pr-4 lg:border-b-0">
            <CalendarDays size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">日期</dt>
              <dd className="mt-0.5 text-14 text-ink">{fmtDate(presentation.startedAt)}</dd>
            </div>
          </div>
          <div className="flex gap-3 border-b border-line py-3 sm:pl-4 lg:border-r lg:pr-4">
            <Clock3 size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">时段</dt>
              <dd className="mt-0.5 text-13 text-ink">
                <span className="whitespace-nowrap">
                  {clockTime(presentation.startedAt)}–{clockTime(presentation.endedAt)}
                </span>
                {presentation.durationMinutes != null && (
                  <span className="ml-1.5 whitespace-nowrap text-ink-3">
                    · {presentation.durationMinutes} 分钟
                  </span>
                )}
              </dd>
            </div>
          </div>
          <div className="flex gap-3 border-b border-line py-3 sm:border-b-0 sm:border-r sm:pr-4 lg:pl-4">
            <Users size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">参与者</dt>
              <dd className="mt-0.5 text-14 text-ink">{presentation.participants.length} 人</dd>
            </div>
          </div>
          <div className="flex gap-3 py-3 sm:pl-4">
            <MessageSquare size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">转写</dt>
              <dd className="mt-0.5 text-14 text-ink">{presentation.segments.length} 段</dd>
            </div>
          </div>
        </dl>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.7fr)]">
          <div>
            <p className="mb-2 text-13 font-medium text-ink">与会者</p>
            <ParticipantList participants={presentation.participants} />
          </div>
          <div>
            <p className="mb-2 text-13 font-medium text-ink">议程</p>
            {presentation.agenda.length > 0 ? (
              <ol className="flex flex-col gap-1 text-13 leading-[1.65] text-ink-2">
                {presentation.agenda.map((item, index) => (
                  <li key={item} className="flex gap-2">
                    <Mono className="text-ink-3">{index + 1}.</Mono>
                    <span>{item}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-13 text-ink-3">未提供会议议程</p>
            )}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule
          no="02"
          title="逐字稿"
          actions={<span className="text-12 text-ink-3">点击 block 编号取精确段</span>}
        />
        <ol className="border-y border-line">
          {presentation.segments.map((segment) => (
            <li
              key={segment.segmentId}
              ref={blockRef(segment.blockIndex) as RefCallback<HTMLLIElement>}
              className={cn(
                "grid grid-cols-[4.5rem_minmax(0,1fr)_auto] gap-x-3 border-b border-line px-2 py-3 last:border-b-0",
                "sm:grid-cols-[5rem_6.5rem_minmax(0,1fr)_auto]",
                inRange(segment.blockIndex) && "bg-accent-soft",
              )}
            >
              <Mono className="pt-0.5 text-12 text-ink-3">{clockTime(segment.startedAt)}</Mono>
              <span
                className={cn(
                  "col-start-2 min-w-0 text-13 font-medium sm:col-start-auto",
                  segment.owner ? "text-accent" : "text-ink",
                )}
              >
                {segment.speaker}
              </span>
              <p className="prose col-span-2 col-start-2 mt-1 min-w-0 text-14 sm:col-span-1 sm:col-start-auto sm:mt-0">
                {segment.text}
              </p>
              <BlockLocator
                index={segment.blockIndex}
                fetching={fetching}
                onFetch={onFetchBlock}
              />
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function DocumentReader({
  presentation,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: Omit<SourceReaderProps, "detail"> & {
  presentation: Extract<SourcePresentation, { kind: "document_library" }>;
}) {
  const frontmatter = Object.entries(presentation.frontmatter);
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title="Vault 定位" />
        <div className="border-y border-line py-3">
          <p className="flex flex-wrap items-center gap-1.5 text-13 text-ink-2">
            <Folder size={15} aria-hidden className="mr-0.5 text-ink-3" />
            <span>{presentation.libraryTitle ?? presentation.libraryId ?? "文档库"}</span>
            {presentation.pathParts.map((part) => (
              <span key={part} className="contents">
                <ChevronRight size={13} aria-hidden className="text-ink-3" />
                <Mono className="text-12 text-ink">{part}</Mono>
              </span>
            ))}
          </p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-12 text-ink-3">
            {presentation.createdAt && <span>创建 {fmtTime(presentation.createdAt)}</span>}
            {presentation.modifiedAt && <span>更新 {fmtTime(presentation.modifiedAt)}</span>}
          </p>
        </div>

        <div className="grid gap-x-8 gap-y-5 lg:grid-cols-2">
          <div>
            <p className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
              <FileText size={14} aria-hidden className="text-ink-3" />
              Frontmatter
            </p>
            {frontmatter.length > 0 ? (
              <dl className="border-y border-line">
                {frontmatter.map(([key, value]) => (
                  <div
                    key={key}
                    className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3 border-b border-line py-2 last:border-b-0"
                  >
                    <dt>
                      <Mono className="text-12 text-ink-3">{key}</Mono>
                    </dt>
                    <dd className="min-w-0 whitespace-pre-wrap text-13 text-ink-2">
                      {metadataValue(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-13 text-ink-3">这篇文档没有 frontmatter</p>
            )}
          </div>
          <div className="flex flex-col gap-4">
            <div>
              <p className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
                <Tag size={14} aria-hidden className="text-ink-3" />
                标签
              </p>
              <p className="flex flex-wrap gap-1.5">
                {presentation.tags.length > 0 ? (
                  presentation.tags.map((tag) => <Badge key={tag}>#{tag}</Badge>)
                ) : (
                  <span className="text-13 text-ink-3">无标签</span>
                )}
              </p>
            </div>
            <div>
              <p className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
                <Link2 size={14} aria-hidden className="text-ink-3" />
                双链
              </p>
              {presentation.links.length > 0 ? (
                <ul className="flex flex-col gap-1.5">
                  {presentation.links.map((link) => (
                    <li key={`${link.target}-${link.label ?? ""}`} className="text-13 text-ink-2">
                      <Mono className="text-accent">
                        {link.embedded ? "![[" : "[["}
                        {link.target}
                        {link.label ? `|${link.label}` : ""}
                        {"]]"}
                      </Mono>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="text-13 text-ink-3">无出链</span>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule
          no="02"
          title="文档正文"
          actions={<span className="text-12 text-ink-3">{presentation.blocks.length} blocks</span>}
        />
        <ol className="border-y border-line">
          {presentation.blocks.map((block) => (
            <li
              key={block.index}
              ref={blockRef(block.index) as RefCallback<HTMLLIElement>}
              className={cn(
                "grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-b border-line px-2 py-4 last:border-b-0",
                inRange(block.index) && "bg-accent-soft",
              )}
            >
              <div className="min-w-0">
                {block.section_path.length > 0 && (
                  <p className="mb-2 flex flex-wrap items-center gap-1 text-12 text-ink-3">
                    {block.section_path.map((part, index) => (
                      <span key={`${part}-${index}`} className="contents">
                        {index > 0 && <ChevronRight size={12} aria-hidden />}
                        <span>{part}</span>
                      </span>
                    ))}
                  </p>
                )}
                <div className="prose text-14">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{block.text}</ReactMarkdown>
                </div>
              </div>
              <BlockLocator index={block.index} fetching={fetching} onFetch={onFetchBlock} />
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function ImReader({
  detail,
  presentation,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: SourceReaderProps & {
  presentation: Extract<SourcePresentation, { kind: "im" }>;
}) {
  let lastDate: string | null = null;
  const typeLabel =
    presentation.conversationType === "channel"
      ? "频道"
      : presentation.conversationType === "dm"
        ? "私聊"
        : presentation.conversationType === "group_dm"
          ? "多人私聊"
          : "会话";
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title="会话语境" />
        <div className="flex flex-col gap-3 border-y border-line py-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-16 font-medium text-ink">
              {presentation.conversationType === "channel" ? (
                <Hash size={17} aria-hidden className="text-ink-3" />
              ) : (
                <AtSign size={17} aria-hidden className="text-ink-3" />
              )}
              {detail.title}
            </p>
            <p className="mt-1 text-13 text-ink-2">
              {presentation.purpose ?? `${typeLabel} · ${presentation.messages.length} 条消息`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge>{typeLabel}</Badge>
            <ParticipantList participants={presentation.members} />
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule
          no="02"
          title="消息记录"
          actions={<span className="text-12 text-ink-3">线程回复保留缩进</span>}
        />
        <ol className="border-y border-line">
          {presentation.messages.map((message) => {
            const showDate = message.date !== lastDate;
            lastDate = message.date;
            return (
              <li
                key={message.messageId}
                className="border-b border-line last:border-b-0"
              >
                {showDate && (
                  <div className="flex items-center gap-3 border-b border-line py-2">
                    <span className="text-12 text-ink-3">{message.date ?? "日期未知"}</span>
                    <hr aria-hidden className="flex-1 border-0 border-t border-line" />
                  </div>
                )}
                <article
                  ref={blockRef(message.blockIndex) as RefCallback<HTMLElement>}
                  className={cn(
                    "grid grid-cols-[2rem_minmax(0,1fr)_auto] gap-x-3 px-2 py-3",
                    message.isReply && "ml-8 border-l border-l-line pl-3",
                    inRange(message.blockIndex) && "bg-accent-soft",
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      "flex size-8 items-center justify-center rounded-2 border text-13 font-medium",
                      message.owner
                        ? "border-accent-line bg-accent-soft text-accent"
                        : "border-line-2 bg-surface text-ink-2",
                    )}
                  >
                    {initialOf(message.speaker)}
                  </span>
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span
                        className={cn(
                          "text-13 font-medium",
                          message.owner ? "text-accent" : "text-ink",
                        )}
                      >
                        {message.speaker}
                      </span>
                      <Mono className="text-12 text-ink-3">{clockTime(message.sentAt)}</Mono>
                      {message.editedAt && <span className="text-12 text-ink-3">已编辑</span>}
                      {message.isReply && <span className="text-12 text-ink-3">线程回复</span>}
                    </p>
                    <p className="prose mt-1 text-14">{message.text}</p>
                    {message.reactions.length > 0 && (
                      <p className="mt-2 flex flex-wrap gap-1">
                        {message.reactions.map((reaction) => (
                          <Badge key={reaction.name}>
                            :{reaction.name}: {reaction.count}
                          </Badge>
                        ))}
                      </p>
                    )}
                  </div>
                  <BlockLocator
                    index={message.blockIndex}
                    fetching={fetching}
                    onFetch={onFetchBlock}
                  />
                </article>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

function AttachmentList({ attachments }: { attachments: AttachmentPresentation[] }) {
  if (attachments.length === 0) return null;
  return (
    <ul className="mt-4 flex flex-col gap-1.5">
      {attachments.map((attachment) => (
        <li
          key={`${attachment.filename}-${attachment.sizeBytes}`}
          className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-2 border border-line px-2.5 py-2 text-12"
        >
          <Paperclip size={13} aria-hidden className="text-ink-3" />
          <span className="font-medium text-ink">{attachment.filename}</span>
          <span className="text-ink-3">
            {attachment.contentType} · {formatBytes(attachment.sizeBytes)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function EmailHeader({ message }: { message: EmailMessagePresentation }) {
  return (
    <dl className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-12 leading-[1.55]">
      <dt className="text-ink-3">发件人</dt>
      <dd className={message.owner ? "text-accent" : "text-ink"}>
        {addressLabel(message.from)}
        {message.owner && " · 本人"}
      </dd>
      <dt className="text-ink-3">收件人</dt>
      <dd className="text-ink-2">{message.to.map(addressLabel).join("，") || "—"}</dd>
      {message.cc.length > 0 && (
        <>
          <dt className="text-ink-3">抄送</dt>
          <dd className="text-ink-2">{message.cc.map(addressLabel).join("，")}</dd>
        </>
      )}
      <dt className="text-ink-3">时间</dt>
      <dd className="text-ink-2">{fmtTime(message.sentAt)}</dd>
    </dl>
  );
}

function EmailReader({
  presentation,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: Omit<SourceReaderProps, "detail"> & {
  presentation: Extract<SourcePresentation, { kind: "email" }>;
}) {
  const correspondents = new Set(
    presentation.messages.flatMap((message) => [
      addressLabel(message.from),
      ...message.to.map(addressLabel),
      ...message.cc.map(addressLabel),
    ]),
  );
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title="邮件线程" />
        <div className="grid gap-4 border-y border-line py-3 sm:grid-cols-3">
          <div className="flex gap-2">
            <Mail size={15} aria-hidden className="mt-0.5 text-ink-3" />
            <div>
              <p className="text-12 text-ink-3">邮件</p>
              <p className="mt-0.5 text-14 text-ink">{presentation.messages.length} 封</p>
            </div>
          </div>
          <div className="flex gap-2">
            <Users size={15} aria-hidden className="mt-0.5 text-ink-3" />
            <div>
              <p className="text-12 text-ink-3">通信方</p>
              <p className="mt-0.5 text-14 text-ink">{correspondents.size} 个地址</p>
            </div>
          </div>
          <div className="min-w-0">
            <p className="text-12 text-ink-3">Thread-ID</p>
            <Mono className="mt-0.5 block truncate text-12 text-ink-2">
              {presentation.threadId ?? "—"}
            </Mono>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule no="02" title="往来邮件" />
        <ol className="border-y border-line">
          {presentation.messages.map((message, index) => (
            <li
              key={message.messageId}
              ref={blockRef(message.blockIndex) as RefCallback<HTMLLIElement>}
              className={cn(
                "border-b border-line px-2 py-5 last:border-b-0",
                inRange(message.blockIndex) && "bg-accent-soft",
              )}
            >
              <article>
                <header className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="mb-1 text-12 text-ink-3">第 {index + 1} 封</p>
                    <h3 className="font-serif text-16 text-balance text-ink">{message.subject}</h3>
                  </div>
                  <BlockLocator
                    index={message.blockIndex}
                    fetching={fetching}
                    onFetch={onFetchBlock}
                  />
                </header>
                <div className="mt-3 border-y border-line py-3">
                  <EmailHeader message={message} />
                </div>
                <p className="prose mt-4 max-w-measure whitespace-pre-wrap text-14">
                  {message.body}
                </p>
                <AttachmentList attachments={message.attachments} />
              </article>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function GenericReader({
  presentation,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: Omit<SourceReaderProps, "detail"> & {
  presentation: Extract<SourcePresentation, { kind: "generic" }>;
}) {
  return (
    <section className="flex flex-col gap-3">
      <SectionRule
        no="01"
        title="原文"
        actions={<span className="text-12 text-ink-3">{presentation.blocks.length} blocks</span>}
      />
      <ol className="border-y border-line">
        {presentation.blocks.map((block) => (
          <li
            key={block.index}
            ref={blockRef(block.index) as RefCallback<HTMLLIElement>}
            className={cn(
              "flex gap-3 border-b border-line px-2 py-3 last:border-b-0",
              inRange(block.index) && "bg-accent-soft",
            )}
          >
            <BlockLocator index={block.index} fetching={fetching} onFetch={onFetchBlock} />
            <p className="prose min-w-0 whitespace-pre-wrap text-14">{block.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function SourceReader(props: SourceReaderProps) {
  const presentation = buildSourcePresentation(props.detail);
  switch (presentation.kind) {
    case "meeting":
      return <MeetingReader {...props} presentation={presentation} />;
    case "document_library":
      return <DocumentReader {...props} presentation={presentation} />;
    case "im":
      return <ImReader {...props} presentation={presentation} />;
    case "email":
      return <EmailReader {...props} presentation={presentation} />;
    case "generic":
      return <GenericReader {...props} presentation={presentation} />;
  }
}

export function SourceKindSummary({ detail }: { detail: SourceDetail }) {
  const presentation = buildSourcePresentation(detail);
  switch (presentation.kind) {
    case "meeting":
      return `${presentation.participants.length} 位参与者 · ${presentation.segments.length} 段转写`;
    case "document_library":
      return presentation.path ?? `${presentation.blocks.length} 个正文块`;
    case "im":
      return `${presentation.messages.length} 条消息 · ${presentation.members.length} 位成员`;
    case "email":
      return `${presentation.messages.length} 封邮件`;
    case "generic":
      return `${presentation.blocks.length} 个原文块`;
  }
}

export function SourceKindName({ kind }: { kind: string }) {
  return <>{sourceKindLabel(kind)}</>;
}
