import { useMemo, useState } from "react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { claimOneLine } from "@/lib/claim";
import { neighborhoodOf, type LinkIndex, type NeighborRow } from "@/lib/structureLens";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { cn } from "@/ui/cn";

/** Rows past this many go behind the column's own scroll rather than down the proof. */
const ROWS_VISIBLE = 12;

/**
 * The neighbourhood of one document: who it links to, who links to it, and — on every single
 * row — THE SENTENCE THAT MADE THE LINK.
 *
 * This is where following a thread actually happens, and it is here rather than on a canvas
 * for one reason: an edge's whole information content is the claim that wrote it. A dot joined
 * to another dot answers nothing; "on the 21st, so-and-so adjusted the wording of X" answers
 * the question the reader came with. The card and the body are complementary — the body is the
 * ledger of what this subject is, the card is the index of what it is attached to.
 *
 * Archive volumes are folded into their owner, so a reader never has to learn that `a01`
 * exists; a sentence that physically lives in one says so on its row.
 */
export function NeighborhoodCard({ index, path }: { index: LinkIndex; path: string }) {
  const t = useT();
  const { outgoing, incoming } = useMemo(() => neighborhoodOf(index, path), [index, path]);
  return (
    <div className="mt-3 flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-10">
      <Direction
        title={t("library.neighborhood.out", { count: outgoing.length })}
        rows={outgoing}
        empty={t("library.neighborhood.emptyOut")}
      />
      <Direction
        title={t("library.neighborhood.in", { count: incoming.length })}
        rows={incoming}
        empty={t("library.neighborhood.emptyIn")}
      />
    </div>
  );
}

function Direction({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: NeighborRow[];
  empty: string;
}) {
  const t = useT();
  const select = useApp((s) => s.select);
  const [expanded, setExpanded] = useState(false);
  const overflowing = rows.length > ROWS_VISIBLE;
  return (
    <section className="min-w-0 flex-1">
      <p className="text-12 text-ink-3">{title}</p>
      {rows.length === 0 ? (
        <p className="mt-1 text-13 text-ink-3">{empty}</p>
      ) : (
        <>
          <ScrollRegion
            className={cn("mt-1", overflowing && !expanded && "max-h-80")}
            aria-label={title}
          >
            <ul className="flex flex-col">
              {rows.map((row) => (
                <li key={row.path} className="border-b border-line last:border-b-0">
                  <button
                    type="button"
                    onClick={() => select({ kind: "document", id: row.documentId ?? row.path })}
                    className="flex w-full min-w-0 flex-col gap-0.5 py-2 text-left transition-colors duration-120 hover:bg-hover"
                  >
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-13 text-ink">{row.title}</span>
                      {row.more > 0 && (
                        <Mono className="shrink-0 text-12 text-ink-3">
                          {t("library.neighborhood.more", { count: row.more })}
                        </Mono>
                      )}
                    </span>
                    {/* The edge, in words. Never truncated to a single line: the date and the
                        name are usually at the end of the sentence. */}
                    <span className="text-12 leading-relaxed text-ink-2">
                      {claimOneLine(row.sentence)}
                    </span>
                    {row.volume && (
                      <Mono className="truncate text-12 text-ink-3">
                        {t("library.neighborhood.volume", {
                          name: row.volume.slice(row.volume.lastIndexOf("/") + 1),
                        })}
                      </Mono>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          </ScrollRegion>
          {overflowing && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 text-12 text-accent transition-colors duration-120 hover:underline"
            >
              {expanded ? t("common.list.collapse") : t("common.list.showAll", { count: rows.length })}
            </button>
          )}
        </>
      )}
    </section>
  );
}
