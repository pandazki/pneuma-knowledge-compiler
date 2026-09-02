/**
 * The owner's own words, as an ordinary source (`pneuma.source.owner-dialogue/v1`).
 *
 * The owner acts on the library only by SPEAKING to the steward, so a correction, an
 * instruction or an addition arrives here as evidence like any other evidence: L0 verbatim,
 * one block per turn, cited `[cite: <sid> ¶n]` exactly as a chat message is, and reaching
 * canonical only through an ordinary compile and the citation gate. There is no owner write
 * path, and this form is not one.
 *
 * ORDER IS MEANING, so it is validated here rather than repaired. Every other contract sorts
 * what it is handed, because a provider archive's order is an artefact of the export. A
 * dialogue's order IS its content: a sentence that qualifies the one before it stops
 * qualifying it once the two are swapped. The service rejects a payload whose `said_at` goes
 * backwards, and the form says so before the round trip rather than after it.
 *
 * Wording never comes from a runtime import: the tests transpile this file on its own into a
 * data: URL module, so an `import { tx }` would not resolve. Composed messages take an
 * injected lookup, exactly as `officialSources.ts` does.
 */
import type { MessageKey } from "@/i18n";

export const OWNER_DIALOGUE_SCHEMA = "pneuma.source.owner-dialogue/v1";

/** The translator a caller supplies; `t` is the view's `useT()`. */
export interface OwnerStatementI18n {
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
}

export type OwnerRole = "owner" | "steward";

/** One turn as the editor holds it: a local `datetime-local` string, not an instant. */
export interface OwnerTurnDraft {
  role: OwnerRole;
  /** `YYYY-MM-DDTHH:mm`, the browser's own local-time spelling. */
  saidAt: string;
  text: string;
}

/**
 * A `Date` in the `datetime-local` spelling — LOCAL time, because that is what the person
 * typing remembers speaking. It becomes an aware instant at submit, where the browser's zone
 * does the conversion; the contract requires an aware timestamp and gets one.
 */
export function localInputValue(at: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    `T${pad(at.getHours())}:${pad(at.getMinutes())}`
  );
}

/** A fresh turn, spoken by the owner, now. */
export function emptyOwnerTurn(now: Date = new Date()): OwnerTurnDraft {
  return { role: "owner", saidAt: localInputValue(now), text: "" };
}

/**
 * A dialogue id from the first turn's instant, plus a short random tail.
 *
 * The id is the application's own and the framework mints the stored title from it, so it is
 * built to be readable in a source list rather than to be unique in the abstract. The tail
 * exists because two statements made in the same minute are two statements.
 */
export function mintDialogueId(now: Date = new Date()): string {
  const stamp = localInputValue(now).replace(/[-:T]/g, "");
  const tail = Math.random().toString(36).slice(2, 8);
  return `owner-${stamp}-${tail}`;
}

/**
 * Does this draft carry a written turn spoken by the OWNER?
 *
 * The contract requires one, because the whole standing of an owner dialogue is that the
 * subject the library is about spoke for themselves — a payload of steward turns alone is
 * a document the steward wrote about the owner, compiled as though the owner had said it.
 * The form asks the same question the service asks, so the button is dead before the round
 * trip rather than after it; the service's refusal remains the one that decides.
 */
export function hasOwnerTurn(turns: OwnerTurnDraft[]): boolean {
  return turns.some((turn) => turn.role === "owner" && turn.text.trim().length > 0);
}

export interface OwnerStatementBuild {
  ownerId: string;
  dialogueId: string;
  stewardId?: string | null;
}

/**
 * The draft turns → one contract payload, or a thrown `Error` naming the first thing wrong.
 *
 * Throws rather than returning a result object because the caller is a form with one error
 * slot and the shipped `parseOfficialSourcePayload` beside it already behaves this way — two
 * failure protocols on one screen is one too many.
 */
export function buildOwnerStatementPayload(
  turns: OwnerTurnDraft[],
  { ownerId, dialogueId, stewardId }: OwnerStatementBuild,
  { t }: OwnerStatementI18n,
): Record<string, unknown> {
  const kept = turns.filter((turn) => turn.text.trim().length > 0);
  if (kept.length === 0) throw new Error(t("ingest.owner.error.empty"));
  if (!hasOwnerTurn(turns)) throw new Error(t("ingest.owner.error.noOwnerTurn"));

  const built = kept.map((turn, index) => {
    const at = new Date(turn.saidAt);
    if (Number.isNaN(at.getTime())) {
      throw new Error(t("ingest.owner.error.badTime", { turn: index + 1 }));
    }
    return {
      turn_id: `t${index + 1}`,
      role: turn.role,
      said_at: at.toISOString(),
      text: turn.text.trim(),
    };
  });

  for (let i = 1; i < built.length; i += 1) {
    if (built[i]!.said_at < built[i - 1]!.said_at) {
      throw new Error(t("ingest.owner.error.outOfOrder", { turn: i + 1 }));
    }
  }

  const payload: Record<string, unknown> = {
    schema: OWNER_DIALOGUE_SCHEMA,
    provider: "console",
    dialogue_id: dialogueId,
    owner_id: ownerId,
    turns: built,
    metadata: {},
  };
  if (stewardId) payload.steward_id = stewardId;
  return payload;
}
