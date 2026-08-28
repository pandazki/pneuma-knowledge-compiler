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
