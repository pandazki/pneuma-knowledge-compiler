/**
 * Claim-text helpers.
 *
 * schema_version 2 exporters deliver a CLEAN `claim.text` (machinery + list marker
 * already stripped) plus structured `claim.notes`. Components should prefer those via
 * `displayClaim(claim)`.
 *
 * `cleanClaimText` remains as a tolerant FALLBACK for schema_version 1 exports, whose
 * `text` still carries inline machinery: [cite: …], [inferred], anchor comments
 * <!-- c:xxxx -->, and flag comments <!-- disputed: … --> / <!-- open-question: … -->.
 */

import { tx } from "./i18n";
import type { Claim, ClaimLabel, Escalation } from "./types";

const CITE_RE = /\[cite:[^\]]*\]/g;
const INFERRED_RE = /\[inferred\]/gi;
const ANCHOR_COMMENT_RE = /<!--\s*c:[0-9a-f]+\s*-->/gi;
const FLAG_COMMENT_RE = /<!--\s*(disputed|open-question)\s*:?\s*([^>]*?)\s*-->/gi;
const LIST_MARKER_RE = /^\s*[-*+]\s+/;

export interface CleanedClaim {
  /** prose with all machinery removed, ready for inline markdown rendering */
  md: string;
  /** rationale captured from a <!-- disputed: … --> comment, if any */
  disputedNote?: string;
  /** rationale captured from a <!-- open-question: … --> comment, if any */
  openQuestionNote?: string;
}

export function cleanClaimText(text: string, kind: string): CleanedClaim {
  let disputedNote: string | undefined;
  let openQuestionNote: string | undefined;

  let out = text.replace(FLAG_COMMENT_RE, (_m, kindStr: string, note: string) => {
    const trimmed = (note || "").trim();
    if (kindStr === "disputed") disputedNote = trimmed || disputedNote;
    else openQuestionNote = trimmed || openQuestionNote;
    return "";
  });

  out = out
    .replace(ANCHOR_COMMENT_RE, "")
    .replace(CITE_RE, "")
    .replace(INFERRED_RE, "");

  if (kind === "list_item") out = out.replace(LIST_MARKER_RE, "");

  out = out.replace(/[ \t]+/g, " ").trim();
  return { md: out, disputedNote, openQuestionNote };
}

/** True when a claim still carries inline machinery — i.e. an older schema v1 export. */
function looksRaw(claim: Claim): boolean {
  const t = claim.text;
  if (/<!--|\[cite:|\[inferred\]/i.test(t)) return true;
  if (claim.kind === "list_item" && LIST_MARKER_RE.test(t)) return true;
  return false;
}

/**
 * Resolve a claim to its display form. Prefers the schema v2 clean `text` +
 * structured `notes`; falls back to cleanClaimText only when the claim still looks
 * like it carries machinery (schema v1). Structured notes always win when present.
 */
export function displayClaim(claim: Claim): CleanedClaim {
  if (looksRaw(claim)) {
    const cleaned = cleanClaimText(claim.text, claim.kind);
    return {
      md: cleaned.md,
      disputedNote: claim.notes?.disputed ?? cleaned.disputedNote,
      openQuestionNote: claim.notes?.open_question ?? cleaned.openQuestionNote,
    };
  }
  return {
    md: claim.text,
    disputedNote: claim.notes?.disputed,
    openQuestionNote: claim.notes?.open_question,
  };
}

export interface ExtractedClaimLabel {
  /** the matched declared label (drives the badge + tooltip) */
  label: ClaimLabel;
  /** the claim prose with the【label】prefix stripped off */
  rest: string;
}

const CLAIM_LABEL_PREFIX_RE = /^\s*【([^【】]+)】\s*/;

/**
 * Lift a skill-declared claim-prefix label off the head of a claim's text.
 *
 * Generic mechanism, no hardcoded vocabulary: matches a leading `【…】` (leading
 * whitespace tolerated) and returns `{label, rest}` ONLY when the bracketed text matches one
 * of the DECLARED labels character for character. An undeclared `【…】` prefix — or an empty
 * / absent label list — is left untouched so it stays part of the prose. Both the schema v2
 * clean-text path and the v1 fallback funnel their display text through here.
 */
export function extractClaimLabel(
  text: string,
  labels: ClaimLabel[] | undefined | null,
): ExtractedClaimLabel | null {
  if (!labels || labels.length === 0) return null;
  const m = CLAIM_LABEL_PREFIX_RE.exec(text);
  if (!m) return null;
  const found = labels.find((l) => l.label === m[1]);
  if (!found) return null;
  return { label: found, rest: text.slice(m[0].length) };
}

/** A citation's block range as `¶a` / `¶a-b` (empty when `from` is absent). */
export function citationRange(from?: number | null, to?: number | null): string {
  if (from == null) return "";
  return to != null && to !== from ? `¶${from}-${to}` : `¶${from}`;
}

/**
 * Short human label for a citation's source. The canonical (five-file) projection
 * carries no per-source title — only the raw source_id — so we surface its first 8
 * chars once the id is long enough to be worth shortening, and the whole id otherwise.
 */
export function citationShortLabel(sourceId: string): string {
  return sourceId.length > 12 ? sourceId.slice(0, 8) : sourceId;
}

/** Flatten inline markdown (links, bold, code) to plain text for dense contexts. */
export function toPlainText(md: string): string {
  return md
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

/** Human labels + which domain-state token drives the color, keyed by flag id. */
export const FLAG_META: Record<
  string,
  { label: string; token: string; tone: "disputed" | "open-question" | "inferred" }
> = {
  disputed: { label: "Disputed", token: "var(--color-disputed)", tone: "disputed" },
  open_question: {
    label: "Open question",
    token: "var(--color-open-question)",
    tone: "open-question",
  },
  inferred: { label: "Inferred", token: "var(--color-inferred)", tone: "inferred" },
};

export function flagMeta(flag: string) {
  return (
    FLAG_META[flag] ?? {
      label: flag,
      token: "var(--color-text-tertiary)",
      tone: "inferred" as const,
    }
  );
}

/**
 * Escalation display text, tolerant of the producer-varying schema (fable F14).
 * Label falls through reason → trigger → category → policy; body through
 * note → detail → question. Used by History (detail) and Process (job card).
 */
export function escalationText(e: Escalation): { label: string; body: string | null } {
  return {
    label: e.reason ?? e.trigger ?? e.category ?? e.policy ?? tx("common.escalation.fallback"),
    body: e.note ?? e.detail ?? e.question ?? null,
  };
}
