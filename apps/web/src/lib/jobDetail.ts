/**
 * The job ledger, prepared for reading: a job's `detail`, and the queue summary above it.
 *
 * A gate rejection is not one sentence: the gate collects every reason it refused and joins
 * them with `; `, so a failed compile arrives as a single paragraph holding four or five
 * separate findings — which is exactly the shape a reader cannot count. Splitting it back
 * into the lines it was built from costs nothing and makes "how many things went wrong"
 * answerable at a glance.
 *
 * The separator is the gate's own (`compile/gate.py` joins on `"; "`), and a detail that
 * does not carry it — a one-line worker error, a message with a semicolon inside a sentence
 * — comes back as the single line it is. Import-free, so it is transpiled and tested alone.
 */
export function splitGateDetail(detail: string | null | undefined): string[] {
  if (!detail) return [];
  const parts = detail
    .split(/;\s+/)
    .map((part) => part.trim())
    .filter((part) => part !== "");
  return parts.length > 0 ? parts : [detail.trim()];
}

/**
 * How many of these jobs are waiting for the Steward — a queued compile job under an agent
 * executor, which does not drain itself (docs/design/coding-agent-mode.md story 2.24).
 *
 * The API answers this per job (`waiting_for`), because the deployment's executor is the
 * server's fact and not the browser's; the page only counts. A job whose `waiting_for` is
 * absent — an older API, a finished job — is not waiting for anybody.
 */
export function countWaitingForSteward(
  jobs: { waiting_for?: string | null }[] | null | undefined,
): number {
  if (!jobs) return 0;
  return jobs.filter((job) => job.waiting_for === "steward").length;
}

/* ------------------------------------------------------------------ waiting jobs */

/**
 * A job the worker parked rather than failed.
 *
 * Unavailability is not the job's fault: a provider refusing the connection, a harness that
 * died before its first turn. The worker puts such a job back on the queue with a
 * `not_before`, and writes its row's `detail` as
 * `waiting: <reason>; retry at <iso> (attempt n)`. The prefix is the whole contract — the
 * reason text is the server's and this page never parses inside it.
 */
const WAITING_PREFIX = "waiting:";

/**
 * And when the schedule runs out, the job PAUSES and waits for a person:
 * `paused: <reason>; <n> attempts over <span>; resume with pkc jobs resume`. Its own status,
 * not a failure — nothing about it was judged wrong, and a person can put it back.
 */
const PAUSED_PREFIX = "paused:";

export function isWaitingDetail(detail: string | null | undefined): boolean {
  return (detail ?? "").trimStart().startsWith(WAITING_PREFIX);
}

export function isPausedDetail(detail: string | null | undefined): boolean {
  return (detail ?? "").trimStart().startsWith(PAUSED_PREFIX);
}

/**
 * A job's `detail`, as the lines it should be read as.
 *
 * A gate rejection is several findings and is split; a parked note is ONE sentence that
 * happens to carry a `; ` inside it, and splitting it would print a parked job as two or
 * three findings — which is the error shape these states exist not to be.
 */
export function detailLines(detail: string | null | undefined): string[] {
  if (!detail) return [];
  if (isWaitingDetail(detail) || isPausedDetail(detail)) return [detail.trim()];
  return splitGateDetail(detail);
}

/** One reason jobs are parked, and when the earliest of them comes back. */
export interface JobWaitingReason {
  reason: string;
  count: number;
  /** ISO stamp; null when the server did not say. */
  next_retry_at: string | null;
}

/** One reason jobs are paused, and since when the oldest of them has been. */
export interface JobPausedReason {
  reason: string;
  count: number;
  /** ISO stamp; null when the server did not say. */
  since: string | null;
}

/** `GET /v1/users/{uid}/jobs/summary` — the queue's state in counts. */
export interface JobsSummary {
  queued: number;
  waiting: { count: number; reasons: JobWaitingReason[] };
  paused: { count: number; reasons: JobPausedReason[] };
  claimed: number;
  failed: number;
  succeeded: number;
}

/**
 * One `{count, reasons: [{reason, count, <stamp>}]}` group. Waiting and paused are the same
 * shape under two names — the stamp is `next_retry_at` for one and `since` for the other —
 * so they are read once, and a group the server has not grown yet reads as zero.
 */
function parseReasonGroup(
  value: unknown,
  stampKey: string,
): { count: number; rows: { reason: string; count: number; stamp: string | null }[] } {
  const raw =
    typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  const rows: { reason: string; count: number; stamp: string | null }[] = [];
  if (Array.isArray(raw.reasons)) {
    for (const entry of raw.reasons) {
      if (typeof entry !== "object" || entry === null) continue;
      const row = entry as Record<string, unknown>;
      const reason = typeof row.reason === "string" ? row.reason.trim() : "";
      const count = summaryCount(row.count);
      if (reason === "" || count === 0) continue;
      const stamp = row[stampKey];
      rows.push({ reason, count, stamp: typeof stamp === "string" ? stamp : null });
    }
  }
  return { count: summaryCount(raw.count), rows };
}

function summaryCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/**
 * The summary document, or null for anything that is not one.
 *
 * Tolerant in the same way `parseHomeStatus` is, and for the same reason: this endpoint is
 * newer than the consoles that will call it, so an older engine's 404 body and a shape the
 * queue grows later must both degrade to "nothing to say" rather than to a broken ledger.
 * A reason with no name or a count of zero is dropped — a waiting line that lists a reason
 * nothing is waiting for is worse than no line.
 */
export function parseJobsSummary(input: unknown): JobsSummary | null {
  if (typeof input !== "object" || input === null || Array.isArray(input)) return null;
  const raw = input as Record<string, unknown>;
  const waiting = parseReasonGroup(raw.waiting, "next_retry_at");
  const paused = parseReasonGroup(raw.paused, "since");
  return {
    queued: summaryCount(raw.queued),
    waiting: {
      count: waiting.count,
      reasons: waiting.rows.map(({ reason, count, stamp }) => ({
        reason,
        count,
        next_retry_at: stamp,
      })),
    },
    paused: {
      count: paused.count,
      reasons: paused.rows.map(({ reason, count, stamp }) => ({
        reason,
        count,
        since: stamp,
      })),
    },
    claimed: summaryCount(raw.claimed),
    failed: summaryCount(raw.failed),
    succeeded: summaryCount(raw.succeeded),
  };
}
