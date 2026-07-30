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
import { intlTag } from "@/lib/i18n";
import { useLocale, useT, useTOr, type TFunction, type TOrFunction } from "@/lib/useT";
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

function clockTime(ts: string | null, tag: string): string {
  if (!ts) return "—";
  const value = new Date(ts);
  if (Number.isNaN(value.getTime())) return ts;
  return value.toLocaleTimeString(tag, {
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
  const t = useT();
  return (
    <button
      type="button"
      disabled={fetching}
      onClick={() => onFetch(index)}
      aria-label={t("sources.block.fetchAria", { index })}
      title={t("sources.block.fetchTitle")}
      className="shrink-0 rounded-1 px-1 py-0.5 text-ink-3 hover:bg-hover hover:text-accent disabled:opacity-45"
    >
      <Mono className="text-12">b{index}</Mono>
    </button>
  );
}

function ParticipantList({ participants }: { participants: ParticipantPresentation[] }) {
  const t = useT();
  if (participants.length === 0) {
    return <span className="text-ink-3">{t("sources.meeting.noParticipants")}</span>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {participants.map((participant) => (
        <Badge key={participant.id} tone={participant.owner ? "accent" : "neutral"}>
          {participant.displayName}
          {participant.owner ? ` · ${t("sources.owner")}` : ""}
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
  const t = useT();
  const tag = intlTag(useLocale());
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title={t("sources.meeting.overview")} />
        <dl className="grid border-y border-line sm:grid-cols-2 lg:grid-cols-4">
          <div className="flex gap-3 border-b border-line py-3 sm:border-r sm:pr-4 lg:border-b-0">
            <CalendarDays size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">{t("sources.meeting.date")}</dt>
              <dd className="mt-0.5 text-14 text-ink">{fmtDate(presentation.startedAt)}</dd>
            </div>
          </div>
          <div className="flex gap-3 border-b border-line py-3 sm:pl-4 lg:border-r lg:pr-4">
            <Clock3 size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">{t("sources.meeting.window")}</dt>
              <dd className="mt-0.5 text-13 text-ink">
                <span className="whitespace-nowrap">
                  {clockTime(presentation.startedAt, tag)}–{clockTime(presentation.endedAt, tag)}
                </span>
                {presentation.durationMinutes != null && (
                  <span className="ml-1.5 whitespace-nowrap text-ink-3">
                    · {t("sources.meeting.minutes", { count: presentation.durationMinutes })}
                  </span>
                )}
              </dd>
            </div>
          </div>
          <div className="flex gap-3 border-b border-line py-3 sm:border-b-0 sm:border-r sm:pr-4 lg:pl-4">
            <Users size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">{t("sources.meeting.participants")}</dt>
              <dd className="mt-0.5 text-14 text-ink">
                {t("sources.meeting.participantCount", {
                  count: presentation.participants.length,
                })}
              </dd>
            </div>
          </div>
          <div className="flex gap-3 py-3 sm:pl-4">
            <MessageSquare size={16} aria-hidden className="mt-0.5 shrink-0 text-ink-3" />
            <div>
              <dt className="text-12 text-ink-3">{t("sources.meeting.transcript")}</dt>
              <dd className="mt-0.5 text-14 text-ink">
                {t("sources.meeting.segmentCount", { count: presentation.segments.length })}
              </dd>
            </div>
          </div>
        </dl>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.7fr)]">
          <div>
            <p className="mb-2 text-13 font-medium text-ink">{t("sources.meeting.attendees")}</p>
            <ParticipantList participants={presentation.participants} />
          </div>
          <div>
            <p className="mb-2 text-13 font-medium text-ink">{t("sources.meeting.agenda")}</p>
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
              <p className="text-13 text-ink-3">{t("sources.meeting.noAgenda")}</p>
            )}
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule
          no="02"
          title={t("sources.meeting.verbatim")}
          actions={
            <span className="text-12 text-ink-3">{t("sources.meeting.blockHint")}</span>
          }
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
              <Mono className="pt-0.5 text-12 text-ink-3">
                {clockTime(segment.startedAt, tag)}
              </Mono>
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
  const t = useT();
  const frontmatter = Object.entries(presentation.frontmatter);
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title={t("sources.document.location")} />
        <div className="border-y border-line py-3">
          <p className="flex flex-wrap items-center gap-1.5 text-13 text-ink-2">
            <Folder size={15} aria-hidden className="mr-0.5 text-ink-3" />
            <span>
              {presentation.libraryTitle ??
                presentation.libraryId ??
                t("sources.document.libraryFallback")}
            </span>
            {presentation.pathParts.map((part) => (
              <span key={part} className="contents">
                <ChevronRight size={13} aria-hidden className="text-ink-3" />
                <Mono className="text-12 text-ink">{part}</Mono>
              </span>
            ))}
          </p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-12 text-ink-3">
            {presentation.createdAt && (
              <span>
                {t("sources.document.created", { time: fmtTime(presentation.createdAt) })}
              </span>
            )}
            {presentation.modifiedAt && (
              <span>
                {t("sources.document.modified", { time: fmtTime(presentation.modifiedAt) })}
              </span>
            )}
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
              <p className="text-13 text-ink-3">{t("sources.document.noFrontmatter")}</p>
            )}
          </div>
          <div className="flex flex-col gap-4">
            <div>
              <p className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
                <Tag size={14} aria-hidden className="text-ink-3" />
                {t("sources.document.tags")}
              </p>
              <p className="flex flex-wrap gap-1.5">
                {presentation.tags.length > 0 ? (
                  presentation.tags.map((tag) => <Badge key={tag}>#{tag}</Badge>)
                ) : (
                  <span className="text-13 text-ink-3">{t("sources.document.noTags")}</span>
                )}
              </p>
            </div>
            <div>
              <p className="mb-2 flex items-center gap-2 text-13 font-medium text-ink">
                <Link2 size={14} aria-hidden className="text-ink-3" />
                {t("sources.document.links")}
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
                <span className="text-13 text-ink-3">{t("sources.document.noLinks")}</span>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <SectionRule
          no="02"
          title={t("sources.document.body")}
          actions={
            <span className="text-12 text-ink-3">
              {t("sources.blockCount", { count: presentation.blocks.length })}
            </span>
          }
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
  const t = useT();
  const tOr = useTOr();
  const tag = intlTag(useLocale());
  let lastDate: string | null = null;
  // A conversation_type the vocabulary does not carry degrades to the generic word.
  const typeLabel = tOr(
    `sources.im.type.${presentation.conversationType}`,
    t("sources.im.type.other"),
  );
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionRule no="01" title={t("sources.im.context")} />
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
              {presentation.purpose ??
                t("sources.im.summary", {
                  type: typeLabel,
                  count: presentation.messages.length,
                })}
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
          title={t("sources.im.log")}
          actions={<span className="text-12 text-ink-3">{t("sources.im.threadHint")}</span>}
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
                    <span className="text-12 text-ink-3">
                      {message.date ?? t("sources.im.unknownDate")}
                    </span>
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
                      <Mono className="text-12 text-ink-3">
                        {clockTime(message.sentAt, tag)}
                      </Mono>
                      {message.editedAt && (
                        <span className="text-12 text-ink-3">{t("sources.im.edited")}</span>
                      )}
                      {message.isReply && (
                        <span className="text-12 text-ink-3">{t("sources.im.threadReply")}</span>
                      )}
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
  const t = useT();
  const separator = t("sources.email.addressSeparator");
  return (
    <dl className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-12 leading-[1.55]">
      <dt className="text-ink-3">{t("sources.email.from")}</dt>
      <dd className={message.owner ? "text-accent" : "text-ink"}>
        {addressLabel(message.from)}
        {message.owner && ` · ${t("sources.owner")}`}
      </dd>
      <dt className="text-ink-3">{t("sources.email.to")}</dt>
      <dd className="text-ink-2">{message.to.map(addressLabel).join(separator) || "—"}</dd>
      {message.cc.length > 0 && (
        <>
          <dt className="text-ink-3">{t("sources.email.cc")}</dt>
          <dd className="text-ink-2">{message.cc.map(addressLabel).join(separator)}</dd>
        </>
      )}
      <dt className="text-ink-3">{t("sources.email.sentAt")}</dt>
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
  const t = useT();
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
        <SectionRule no="01" title={t("sources.email.thread")} />
        <div className="grid gap-4 border-y border-line py-3 sm:grid-cols-3">
          <div className="flex gap-2">
            <Mail size={15} aria-hidden className="mt-0.5 text-ink-3" />
            <div>
              <p className="text-12 text-ink-3">{t("sources.email.countTerm")}</p>
              <p className="mt-0.5 text-14 text-ink">
                {t("sources.email.count", { count: presentation.messages.length })}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <Users size={15} aria-hidden className="mt-0.5 text-ink-3" />
            <div>
              <p className="text-12 text-ink-3">{t("sources.email.correspondents")}</p>
              <p className="mt-0.5 text-14 text-ink">
                {t("sources.email.addressCount", { count: correspondents.size })}
              </p>
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
        <SectionRule no="02" title={t("sources.email.messages")} />
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
                    <p className="mb-1 text-12 text-ink-3">
                      {t("sources.email.ordinal", { index: index + 1 })}
                    </p>
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
  const t = useT();
  return (
    <section className="flex flex-col gap-3">
      <SectionRule
        no="01"
        title={t("sources.generic.body")}
        actions={
          <span className="text-12 text-ink-3">
            {t("sources.blockCount", { count: presentation.blocks.length })}
          </span>
        }
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
  const tOr = useTOr();
  const presentation = buildSourcePresentation(props.detail, { tOr });
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

/** One-line summary of a source, for the catalogue row. A path is data and wins outright. */
function sourceKindSummary(
  presentation: SourcePresentation,
  t: TFunction,
): string {
  switch (presentation.kind) {
    case "meeting":
      return t("sources.summary.meeting", {
        participants: presentation.participants.length,
        segments: presentation.segments.length,
      });
    case "document_library":
      return (
        presentation.path ??
        t("sources.summary.document", { count: presentation.blocks.length })
      );
    case "im":
      return t("sources.summary.im", {
        messages: presentation.messages.length,
        members: presentation.members.length,
      });
    case "email":
      return t("sources.summary.email", { count: presentation.messages.length });
    case "generic":
      return t("sources.summary.generic", { count: presentation.blocks.length });
  }
}

export function SourceKindSummary({ detail }: { detail: SourceDetail }) {
  const t = useT();
  const tOr = useTOr();
  return <>{sourceKindSummary(buildSourcePresentation(detail, { tOr }), t)}</>;
}

export function SourceKindName({ kind }: { kind: string }) {
  const tOr: TOrFunction = useTOr();
  return <>{sourceKindLabel(kind, { tOr })}</>;
}
