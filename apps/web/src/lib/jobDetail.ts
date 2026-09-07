/**
 * A job's `detail`, prepared for reading.
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
