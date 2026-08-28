import { Info } from "lucide-react";
import {
  asFlow,
  formatStageMs,
  previewRows,
  slowestStage,
  stageFlow,
  type FlowNode,
  type FlowStage,
  type StageTiming,
} from "@/lib/stages";
import { useT } from "@/lib/useT";
import { Mono } from "@/ui/Mono";
import { Popover } from "@/ui/Popover";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/**
 * What a lane cost, drawn as the lane's own SHAPE — a flow of nodes joined by arrows, with
 * the concurrent children of a gather fanning out from the node they ran inside.
 *
 * It is a diagram rather than a list because the two facts a reader needs are structural, and
 * a list can state neither: which step follows which, and which steps ran at the same time.
 * The retrieval children sum to MORE than their parent — that is not an error to correct but
 * the whole point of the fan; a bar chart that scaled them to fit would hide which lane was
 * slow. And `total` is not a step at all: it wraps every other one, so it sits apart as a
 * badge instead of pretending to be the last node in the chain.
 *
 * LIVE OR FINISHED, ONE COMPONENT. Pass `stages` (a finished answer) or `live` (the rows a
 * stream is folding, `lib/stages.ts`) — both arrive here as `FlowStage[]`, and a node that has
 * begun and not yet settled simply pulses with a counter ticking from the server's own
 * elapsed offset. So the diagram GROWS IN PLACE while the lane runs and needs no second
 * rendering when it lands.
 *
 * The two SHAPES a lane can have are both handled, and neither is named in code:
 *
 * - A mechanical lane (fast recall, the briefing build) sends a FIXED vocabulary every time.
 *   A stage that did not run arrives marked, and is drawn dashed and labelled "not run"
 *   rather than `0ms`, because "never happened" and "was free" are different facts and
 *   keeping them apart is the whole point.
 * - An agentic lane (deep recall, a briefing ask) sends the run's own sequence instead —
 *   turns, the tools they reached for, an optional forced finalize — because there the order
 *   IS the finding, and nothing is ever "skipped": there was no list it could have run.
 *
 * `description` is the caller's, not this component's: only the caller knows which shape its
 * lane has and what caveat is true of it (the concurrency note under a fast diagram would be
 * a lie under a sequential build). It rides the ⓘ rather than sitting under the diagram —
 * the explanation is worth one hover, not four permanent lines beside every answer.
 *
 * Renders NOTHING when there are no stages — a result restored from a session cache, or a
 * briefing built before the service measured builds — so no caller needs a guard of its own.
 */

function StageNode({ node, child }: { node: FlowNode; child?: boolean }) {
  const t = useT();
  const skipped = node.status === "skipped";
  const degraded = node.status === "degraded";
  // Only a node with something to show is clickable. A stage that reported no preview — an
  // older service, a stage with nothing worth a glance — renders exactly as it always did,
  // so the affordance is never a promise of an empty panel.
  const body = (
    <span
      className={cn(
        "inline-flex flex-col items-start gap-0.5 rounded-1 border px-2 py-1 leading-none",
        child ? "text-[0.95em]" : "",
        skipped
          ? "border-dashed border-line text-ink-3 opacity-60"
          : degraded
            ? "border-danger/50 bg-surface"
            : "border-line bg-surface",
        node.running && "border-accent",
        node.preview &&
          "cursor-pointer transition-colors duration-120 hover:border-accent hover:bg-hover",
      )}
      title={degraded ? t("recall.stages.degraded", { reason: node.detail ?? "" }) : undefined}
    >
      <span className={cn("whitespace-nowrap", skipped ? "text-ink-3" : "text-ink-2")}>
        {node.leaf}
      </span>
      <Mono
        className={cn(
          "text-12 whitespace-nowrap",
          degraded ? "text-danger" : node.running ? "text-accent" : "text-ink-3",
        )}
      >
        {skipped ? (
          t("recall.stages.skipped")
        ) : (
          <>
            {formatStageMs(node.ms)}
            {/* A running node's number is a counter, not a measurement — the ellipsis is
                what says so, and it stops the moment the `end` event lands. */}
            {node.running && <span className="animate-pulse">…</span>}
          </>
        )}
      </Mono>
      {degraded && <span className="text-12 text-danger">!{node.detail}</span>}
    </span>
  );
  if (!node.preview) return body;
  return (
    <Popover
      trigger={
        <button
          type="button"
          aria-label={t("recall.stages.previewOpen", { stage: node.leaf })}
          className="inline-flex text-left"
        >
          {body}
        </button>
      }
    >
      <StagePreviewPanel node={node} />
    </Popover>
  );
}

/**
 * What the stage was handed and what came out.
 *
 * Two shapes, because a preview holds two kinds of fact. A scalar — a count, a cap, a line
 * about the faces — prints as one key and one value. A LIST OF ENTRIES prints one entry per
 * line, and the line is laid out in the order a person reads it: what the item says, in
 * normal type; where it is, dim behind it; the id last, as a small mono tag. That order is
 * the whole point — a panel of ids named every result and described none of them, which is
 * what the owner saw and said was not a preview at all.
 *
 * Still deliberately dumb about the KEYS: `previewRows` flattens whatever the lane sent and
 * this prints it. A viewer that translated the key names would go stale the day a lane added
 * a stage — and would be lying about the ones it did not know, which is worse than a mono key.
 */
function StagePreviewPanel({ node }: { node: FlowNode }) {
  const t = useT();
  const rows = previewRows(node.preview);
  return (
    <div className="max-w-[26rem] min-w-[14rem]">
      <p className="text-12 text-ink-3">
        {t("recall.stages.previewTitle", { stage: node.leaf })}
      </p>
      <dl className="mt-2 flex flex-col gap-2">
        {rows.map((row) =>
          row.items ? (
            <div key={row.key} className="flex flex-col gap-1">
              <Mono className="text-12 text-ink-3">{row.key}</Mono>
              <ul className="flex flex-col gap-1">
                {row.items.map((item, index) => (
                  <li key={index} className="flex flex-col gap-0.5">
                    {item.text && (
                      <span className="text-12 break-words text-ink-2">{item.text}</span>
                    )}
                    <span className="flex items-baseline gap-1.5">
                      {item.where && (
                        <span className="text-12 break-words text-ink-3">{item.where}</span>
                      )}
                      {item.id && (
                        <Mono className="rounded-1 bg-hover px-1 text-[0.9em] text-ink-3">
                          {item.id}
                        </Mono>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div key={row.key} className="flex items-baseline gap-2">
              <Mono className="text-12 shrink-0 text-ink-3">{row.key}</Mono>
              <span className="text-12 break-words text-ink-2">{row.value}</span>
            </div>
          ),
        )}
      </dl>
    </div>
  );
}

/** The joint between two sequential nodes. Decorative — the order is already in the DOM. */
function Arrow() {
  return (
    <span aria-hidden className="shrink-0 select-none px-0.5 text-ink-3">
      →
    </span>
  );
}

/**
 * One node plus the lanes that ran INSIDE it. The children are stacked and bracketed rather
 * than laid end to end, because laying them in a row would draw concurrency as sequence.
 */
function StageGroup({ node }: { node: FlowNode }) {
  if (node.children.length === 0) return <StageNode node={node} />;
  return (
    <span className="inline-flex items-center gap-1">
      <StageNode node={node} />
      {/* Stacked behind one rule, not laid end to end: a row would draw concurrency as
          sequence, which is the one thing the fan exists to deny. */}
      <span className="ml-1 inline-flex flex-col items-start gap-1 border-l-2 border-line-2 pl-2">
        {node.children.map((child) => (
          <StageNode key={child.key} node={child} child />
        ))}
      </span>
    </span>
  );
}

export function StageStrip({
  stages,
  live,
  description,
  className,
}: {
  /** A finished answer's breakdown. Ignored when `live` is given. */
  stages?: StageTiming[] | null;
  /** The rows a stream is folding right now (`liveStages`), while the lane runs. */
  live?: FlowStage[] | null;
  /** The sentence behind the ⓘ, already translated — see the note above on why. */
  description: string;
  className?: string;
}) {
  const t = useT();
  const rows = live && live.length > 0 ? live : asFlow(stages);
  const { nodes, total } = stageFlow(rows);
  if (nodes.length === 0 && total == null) return null;
  const slowest = slowestStage(rows);
  return (
    <div className={cn("mt-2 text-12 text-ink-3", className)}>
      <p className="flex flex-wrap items-center gap-x-2">
        <span>{t("recall.stages.title")}</span>
        <Tooltip content={description}>
          <button
            type="button"
            aria-label={t("recall.stages.explain")}
            className="inline-flex items-center rounded-1 p-0.5 text-ink-3 transition-colors duration-120 hover:bg-hover hover:text-ink"
          >
            <Info aria-hidden className="size-3.5" />
          </button>
        </Tooltip>
        {slowest && (
          <Mono className="text-12">
            {t("recall.stages.slowest", {
              stage: slowest.leaf,
              ms: formatStageMs(slowest.ms),
            })}
          </Mono>
        )}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-y-2 overflow-x-auto">
        {nodes.map((node, index) => (
          <span key={node.key} className="inline-flex items-center">
            {index > 0 && <Arrow />}
            <StageGroup node={node} />
          </span>
        ))}
        {total && (
          <span className="ml-3 inline-flex items-baseline gap-1 rounded-1 border border-line-2 px-2 py-1">
            <span className="text-ink-2">{total.leaf}</span>
            <Mono className={cn("text-12", total.running ? "text-accent" : "text-ink")}>
              {formatStageMs(total.ms)}
              {total.running && <span className="animate-pulse">…</span>}
            </Mono>
          </span>
        )}
      </div>
    </div>
  );
}
