import { Quote, ShieldOff, Anchor as AnchorIcon } from "lucide-react";
import type { Citation, Claim, ClaimLabel } from "@/lib/types";
import {
  citationRange,
  citationShortLabel,
  displayClaim,
  extractClaimLabel,
  flagMeta,
} from "@/lib/claim";
import { claimKey } from "@/lib/model";
import { cn } from "@/lib/cn";
import { InlineMarkdown } from "./InlineMarkdown";
import { Chip, Hover, StatusDot } from "./ui";
import { useApp } from "@/lib/store";

/**
 * A structured claim-prefix badge (§5强/中/弱). The skill DECLARES the vocabulary; this
 * renders it generically by `tier` — solid = filled high-contrast, outline = 描边,
 * muted = 弱化灰. Semantics ride the shared Hover card (immediate on hover, click pins) —
 * the native `title` was falsified live: its ~1s delay makes the affordance unguessable.
 * The badge replaces the字面【label】prefix; no specific word is hardcoded.
 */
export function ClaimLabelBadge({ label }: { label: ClaimLabel }) {
  const base =
    "inline-flex items-center rounded-sm px-1.5 py-[2px] text-[length:var(--text-2xs)] leading-none " +
    "font-medium select-none cursor-help align-middle";
  const chip =
    label.tier === "solid" ? (
      <span
        className={cn(base)}
        style={{
          background: "var(--color-surface-inverse)",
          color: "var(--color-text-inverse)",
        }}
      >
        {label.label}
      </span>
    ) : label.tier === "outline" ? (
      <span
        className={cn(base, "border text-foreground")}
        style={{ borderColor: "var(--color-border-strong)" }}
      >
        {label.label}
      </span>
    ) : (
      // muted (and any unknown tier) → weakened gray, hairline border.
      <span className={cn(base, "border border-border text-muted-foreground")}>
        {label.label}
      </span>
    );
  return (
    <Hover width={300} trigger={chip}>
      <div className="flex flex-col gap-1.5">
        <div className="pneuma-eyebrow">
          {label.label} · {label.name}
        </div>
        <div className="text-[length:var(--text-sm)] leading-relaxed text-foreground">
          {label.description}
        </div>
      </div>
    </Hover>
  );
}

/**
 * A flag chip. When `basis` is provided (the disputed / open-question rationale,
 * inline or joined from the process sidecar) it becomes a hover-card so a reviewer
 * can see WHY the claim carries the flag (P1-3).
 */
export function FlagBadge({ flag, basis }: { flag: string; basis?: string }) {
  const meta = flagMeta(flag);
  const chip = (
    <span
      className="inline-flex items-center gap-1.5 border border-border rounded-sm px-1.5 py-[2px] text-[length:var(--text-2xs)] leading-none"
      style={{ color: "var(--color-text)" }}
      title={basis ? undefined : meta.label}
    >
      <StatusDot color={meta.token} />
      {meta.label}
    </span>
  );
  if (!basis) return chip;
  return (
    <Hover width={300} trigger={<span className="cursor-help">{chip}</span>}>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1.5">
          <StatusDot color={meta.token} />
          <span className="pneuma-eyebrow">{meta.label} · 依据</span>
        </div>
        <div className="text-[length:var(--text-sm)] leading-relaxed text-foreground">{basis}</div>
      </div>
    </Hover>
  );
}

/**
 * One citation as a hover-card chip: `source_id ¶from-to` + the snippet + a jump to the
 * source in the timeline. Exported because the AI-cue cards render the same provenance
 * and a second chip would be a second thing to keep in sync (ContextStreamView).
 */
export function CitationChip({ cite }: { cite: Citation }) {
  const { jump } = useApp();
  const withheld =
    cite.redaction_state === "withheld" || (!cite.snippet && cite.redaction_state !== "included");
  const range =
    cite.from != null
      ? cite.to != null && cite.to !== cite.from
        ? `¶${cite.from}-${cite.to}`
        : `¶${cite.from}`
      : "";

  return (
    <Hover
      width={340}
      trigger={
        <Chip dotColor="var(--color-verified)" className="cursor-help">
          <Quote size={11} />
          {cite.source_id} {range}
        </Chip>
      }
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="pneuma-eyebrow">Citation</span>
          <span className="text-[length:var(--text-2xs)] text-muted-foreground font-mono">
            {cite.source_id} {range}
          </span>
        </div>
        {withheld ? (
          <div className="flex items-start gap-2 text-muted-foreground">
            <ShieldOff size={14} className="mt-0.5 flex-none" />
            <div>
              <div className="text-foreground">source withheld</div>
              <div className="text-xs mt-0.5">
                导出策略为 redacted，原文 span 未随产物分发。连接本地服务或
                --include-source-spans 可读取受控原文。
              </div>
            </div>
          </div>
        ) : (
          <blockquote
            className="text-[length:var(--text-sm)] leading-relaxed pl-2.5 text-foreground"
            style={{ borderLeft: "2px solid var(--color-text)" }}
          >
            {cite.snippet}
            {cite.redaction_state === "snippet" && (
              <span className="text-muted-foreground">… </span>
            )}
          </blockquote>
        )}
        <button
          onClick={() => jump({ kind: "snapshot", id: cite.source_id }, "history")}
          className="self-start text-[length:var(--text-2xs)] text-muted-foreground hover:text-foreground underline underline-offset-2"
        >
          在时间轴定位来源 →
        </button>
        <div className="text-[length:var(--text-2xs)] text-muted-foreground">
          redaction: {cite.redaction_state ?? "—"}
        </div>
      </div>
    </Hover>
  );
}

/**
 * A single-click provenance badge: `source-short ¶a-b` → jumps to the source's
 * original text focused on the citation's start block (the 溯源动线 落点). The snippet
 * (or a withheld notice) rides along as a native title tooltip so the compact badge
 * keeps the provenance readable without the pinned hover card. Used inline on Library
 * claims and on History's claim-level trace rows.
 */
export function CitationBadge({ cite }: { cite: Citation }) {
  const { jump } = useApp();
  const range = citationRange(cite.from, cite.to);
  const label = citationShortLabel(cite.source_id);
  const withheld =
    cite.redaction_state === "withheld" ||
    (!cite.snippet && cite.redaction_state !== "included");
  const title = [
    `${cite.source_id} ${range}`.trim(),
    withheld ? "原文受控未随产物分发" : cite.snippet,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <Chip
      dotColor="var(--color-verified)"
      title={title || undefined}
      onClick={() =>
        jump(
          { kind: "source", id: cite.source_id, block: cite.from ?? undefined },
          "sources",
        )
      }
    >
      <Quote size={11} />
      {label} {range}
    </Chip>
  );
}

export function ClaimView({
  claim,
  documentId,
  onLink,
  highlight,
}: {
  claim: Claim;
  documentId: string | null;
  onLink?: (href: string) => void;
  highlight?: boolean;
}) {
  const { jump, model } = useApp();
  const cleaned = displayClaim(claim);
  // Lift a skill-declared【强】/【中】/【弱】prefix into a structured badge; the vocabulary
  // rides the dataset meta. Undeclared / absent → prose is left exactly as-is.
  const labeled = extractClaimLabel(cleaned.md, model?.dataset.claimLabels);
  const bodyMd = labeled ? labeled.rest : cleaned.md;
  const hasCites = claim.citations.length > 0;

  // Join the process sidecar: a disputed / open-question rationale may live only on
  // the patch that touched this (document_id, anchor), not inline in the prose.
  const sidecar =
    documentId && claim.anchor
      ? model?.sidecarNotes.get(claimKey(documentId, claim.anchor))
      : undefined;
  const disputedBasis = cleaned.disputedNote ?? sidecar?.disputed;
  const openQuestionBasis = cleaned.openQuestionNote ?? sidecar?.open_question;
  const basisForFlag = (flag: string): string | undefined =>
    flag === "disputed"
      ? disputedBasis
      : flag === "open_question"
        ? openQuestionBasis
        : undefined;

  return (
    <div
      id={claim.anchor ? `claim-${claim.anchor}` : undefined}
      className="group py-1.5"
      style={
        highlight
          ? { boxShadow: "inset 3px 0 0 var(--color-accent)", paddingLeft: 10 }
          : undefined
      }
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1.5 text-[length:var(--text-md)] leading-relaxed">
        {labeled && <ClaimLabelBadge label={labeled.label} />}
        <span className="text-foreground">
          <InlineMarkdown text={bodyMd} onLink={onLink} />
        </span>
        {claim.flags.map((f) => (
          <FlagBadge key={f} flag={f} basis={basisForFlag(f)} />
        ))}
        {claim.citations.map((c, i) => (
          <CitationBadge key={i} cite={c} />
        ))}
        {claim.anchor && documentId && (
          <button
            title={`claim ${claim.anchor} · 查看历史`}
            onClick={() => jump({ kind: "claim", documentId, anchor: claim.anchor! }, "history")}
            className="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground hover:text-foreground font-mono transition-opacity"
          >
            <AnchorIcon size={10} /> {claim.anchor}
          </button>
        )}
      </div>

      {(disputedBasis || openQuestionBasis) && (
        <div className="mt-1.5 space-y-1">
          {disputedBasis && (
            <Callout tone="var(--color-disputed)" label="Disputed">
              {disputedBasis}
            </Callout>
          )}
          {openQuestionBasis && (
            <Callout tone="var(--color-open-question)" label="Open question">
              {openQuestionBasis}
            </Callout>
          )}
        </div>
      )}
      {!hasCites && !claim.flags.includes("inferred") && (
        <div className="mt-1 text-[length:var(--text-2xs)] text-muted-foreground italic">未标注来源</div>
      )}
    </div>
  );
}

function Callout({
  tone,
  label,
  children,
}: {
  tone: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="text-[length:var(--text-sm)] text-muted-foreground pl-2.5 py-1"
      style={{ borderLeft: `2px solid ${tone}`, background: "var(--color-surface-muted)" }}
    >
      <span className="font-medium" style={{ color: "var(--color-text)" }}>
        {label}：
      </span>
      {children}
    </div>
  );
}
