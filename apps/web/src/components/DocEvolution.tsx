import { useMemo } from "react";
import { BookOpen, Info } from "lucide-react";
import type { DocumentRecord } from "@/lib/types";
import type { Model } from "@/lib/model";
import { patchNum } from "@/lib/model";
import { displayClaim, extractClaimLabel, flagMeta, toPlainText } from "@/lib/claim";
import { useApp } from "@/lib/store";
import { CitationBadge, ClaimLabelBadge } from "./ClaimView";
import { Button, Chip, Eyebrow } from "./ui";
import { cn } from "@/lib/cn";

interface AnchorTrace {
  patch_id: string;
  flags: string[];
  note?: string;
}

export function DocEvolution({
  doc,
  model,
  selectedPatch,
  highlightAnchor,
}: {
  doc: DocumentRecord;
  model: Model;
  selectedPatch: string | null;
  highlightAnchor?: string | null;
}) {
  const { jump, select } = useApp();
  const trail = model.patchesByPath.get(doc.path) ?? [];
  const trailIds = new Set(trail.map((p) => p.patch_id));

  // anchor -> ordered sidecar traces recorded across patches
  const traceByAnchor = useMemo(() => {
    const m = new Map<string, AnchorTrace[]>();
    for (const p of [...model.dataset.timeline.patches].sort((a, b) => patchNum(a.patch_id) - patchNum(b.patch_id))) {
      for (const c of p.claims ?? []) {
        if (c.anchor?.document_id !== doc.document_id) continue;
        const a = c.anchor?.anchor;
        if (!a) continue;
        const arr = m.get(a) ?? [];
        arr.push({ patch_id: p.patch_id, flags: c.flags ?? [], note: c.note });
        m.set(a, arr);
      }
    }
    return m;
  }, [model, doc.document_id]);

  const allPatches = [...model.dataset.timeline.patches].sort(
    (a, b) => patchNum(a.patch_id) - patchNum(b.patch_id),
  );

  return (
    <div>
      <div className="flex items-center gap-2">
        <BookOpen size={15} className="text-muted-foreground" />
        <span className="text-[length:var(--text-lg)] font-light">{doc.title}</span>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => doc.document_id && jump({ kind: "document", id: doc.document_id }, "library")}
        >
          在 Library 打开
        </Button>
      </div>
      <div className="text-[length:var(--text-2xs)] text-muted-foreground font-mono mt-1">{doc.path}</div>

      {/* patch trail */}
      <Eyebrow className="mt-5 mb-2">Patch 轨迹</Eyebrow>
      <div className="flex flex-wrap items-center gap-1.5">
        {allPatches.map((p) => {
          const inTrail = trailIds.has(p.patch_id);
          const isSel = p.patch_id === selectedPatch;
          return (
            <button
              key={p.patch_id}
              onClick={() => select({ kind: "patch", id: p.patch_id })}
              className={cn(
                "font-mono text-[length:var(--text-2xs)] px-2 py-[3px] border rounded-sm transition-colors",
                inTrail
                  ? "text-foreground border-[var(--color-border-strong)]"
                  : "text-muted-foreground border-border opacity-50",
                isSel && "bg-accent",
              )}
              style={isSel ? { boxShadow: "inset 0 -2px 0 var(--color-accent)" } : undefined}
              title={inTrail ? "该 patch 触及本文档" : "未触及本文档"}
            >
              {p.patch_id}
            </button>
          );
        })}
      </div>

      {/* claim-level trace */}
      <Eyebrow className="mt-5 mb-2">Claim 级 trace</Eyebrow>
      <div className="border border-border rounded-sm overflow-hidden">
        <table className="w-full text-[length:var(--text-sm)]">
          <thead>
            <tr className="bg-[var(--color-surface-muted)] text-muted-foreground">
              <th className="text-left font-medium px-3 py-1.5 w-24">anchor</th>
              <th className="text-left font-medium px-3 py-1.5">claim</th>
              <th className="text-left font-medium px-3 py-1.5 w-40">过程记录</th>
            </tr>
          </thead>
          <tbody>
            {doc.claims.map((c, i) => {
              const cleaned = displayClaim(c);
              const labeled = extractClaimLabel(cleaned.md, model.dataset.claimLabels);
              const traces = c.anchor ? traceByAnchor.get(c.anchor) ?? [] : [];
              const hi = highlightAnchor && c.anchor === highlightAnchor;
              return (
                <tr
                  key={i}
                  className="border-t border-border-subtle align-top"
                  style={{
                    borderTopColor: "var(--color-border-subtle)",
                    background: hi ? "var(--color-surface-hover)" : undefined,
                    boxShadow: hi ? "inset 3px 0 0 var(--color-accent)" : undefined,
                  }}
                >
                  <td className="px-3 py-2 font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                    {c.anchor ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span className="line-clamp-2">
                      {labeled && (
                        <>
                          <ClaimLabelBadge label={labeled.label} />{" "}
                        </>
                      )}
                      {toPlainText(labeled ? labeled.rest : cleaned.md)}
                    </span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {c.flags.map((f) => {
                        const meta = flagMeta(f);
                        return (
                          <Chip key={f} dotColor={meta.token}>
                            {meta.label}
                          </Chip>
                        );
                      })}
                      {c.citations.map((cite, ci) => (
                        <CitationBadge key={`cite-${ci}`} cite={cite} />
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {traces.length === 0 ? (
                      <span className="text-muted-foreground text-[length:var(--text-2xs)]">—</span>
                    ) : (
                      <div className="space-y-1">
                        {traces.map((t, j) => (
                          <div key={j} className="text-[length:var(--text-2xs)]" title={t.note}>
                            <button
                              onClick={() => select({ kind: "patch", id: t.patch_id })}
                              className="font-mono underline underline-offset-2 hover:text-foreground"
                            >
                              {t.patch_id}
                            </button>
                            {t.flags.length > 0 && (
                              <span className="text-muted-foreground">
                                {" "}
                                · {t.flags.map((f) => flagMeta(f).label).join(", ")}
                              </span>
                            )}
                            {t.note && (
                              <div className="text-muted-foreground mt-0.5">{t.note}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-start gap-2 text-[length:var(--text-2xs)] text-muted-foreground">
        <Info size={12} className="mt-0.5 flex-none" />
        <span>
          inspection projection 仅携带当前正文，不含历史版本正文，故演化以 patch 级 claim
          元数据（保锚改写、flag、note）呈现，而非逐行 diff。
        </span>
      </div>
    </div>
  );
}
