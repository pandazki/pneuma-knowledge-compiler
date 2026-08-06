/**
 * The ink-toned line diff, same idiom as EvolveTaskDetail's DiffBlock: the LCS diff from
 * lib/evolve rendered in plain ink tones — no colourful diff.
 */
import { useMemo } from "react";
import { diffStat, lineDiff } from "@/lib/evolve";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

export function DiffBlock({ oldBody, newBody }: { oldBody: string; newBody: string }) {
  const rows = useMemo(() => lineDiff(oldBody, newBody), [oldBody, newBody]);
  const { adds, dels } = diffStat(rows);
  return (
    <div>
      <p className="mb-1.5 text-12 text-ink-3">
        <Mono>
          +{adds} / −{dels}
        </Mono>
      </p>
      <div className="overflow-x-auto rounded-2 border border-line">
        <pre className="min-w-max px-3 py-2 font-mono text-12 leading-5">
          {rows.map((r, k) => (
            <div key={k} className="flex">
              <span className="mr-2 w-3 shrink-0 text-center text-ink-3 select-none">
                {r.type === "add" ? "+" : r.type === "del" ? "−" : " "}
              </span>
              <span
                className={cn(
                  "break-words whitespace-pre-wrap",
                  r.type === "add" && "text-ink",
                  r.type === "del" && "text-ink-3 line-through",
                  r.type === "same" && "text-ink-3",
                )}
              >
                {r.text || " "}
              </span>
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}
