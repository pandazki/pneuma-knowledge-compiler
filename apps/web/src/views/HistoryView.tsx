import { useEffect, useMemo, useState } from "react";
import {
  Cpu,
  Coins,
  GitCommitHorizontal,
  PackageCheck,
  FileText,
  Layers,
} from "lucide-react";
import { useApp } from "@/lib/store";
import type { BundleVersion, PatchRecord, Snapshot } from "@/lib/types";
import { patchChanges, patchNum, type Model } from "@/lib/model";
import { DocEvolution } from "@/components/DocEvolution";
import { Chip, Eyebrow, StatusDot } from "@/components/ui";
import { fmtTime, fmtTokens, shortSha } from "@/lib/format";
import { flagMeta, escalationText } from "@/lib/claim";
import { cn } from "@/lib/cn";

type TimelineItem =
  | { kind: "patch"; ts: string; patch: PatchRecord }
  | { kind: "bundle"; ts: string; bundle: BundleVersion };

export function HistoryView() {
  const { model, selection, select, jump } = useApp();
  const patches = model?.dataset.timeline.patches ?? [];
  const bundles = model?.dataset.timeline.bundle_versions ?? [];

  const items = useMemo<TimelineItem[]>(() => {
    const list: TimelineItem[] = [
      ...patches.map((p) => ({ kind: "patch" as const, ts: p.ts ?? "", patch: p })),
      ...bundles.map((b) => ({ kind: "bundle" as const, ts: b.ts ?? "", bundle: b })),
    ];
    return list.sort((a, b) => {
      const t = (a.ts || "").localeCompare(b.ts || "");
      if (t !== 0) return t;
      return a.kind === "patch" && b.kind === "patch"
        ? patchNum(a.patch.patch_id) - patchNum(b.patch.patch_id)
        : 0;
    });
  }, [patches, bundles]);

  const latestPatch = patches.length
    ? [...patches].sort((a, b) => patchNum(b.patch_id) - patchNum(a.patch_id))[0].patch_id
    : null;

  const selectedPatchId =
    selection?.kind === "patch" ? selection.id : latestPatch;
  const selectedSnapshot =
    selection?.kind === "snapshot" ? model?.snapshotById.get(selection.id) ?? null : null;

  const [evoDocId, setEvoDocId] = useState<string | null>(null);

  // choose an evolution doc from the current selection
  useEffect(() => {
    if (!model) return;
    if (selection?.kind === "claim") {
      setEvoDocId(selection.documentId);
      return;
    }
    if (selection?.kind === "document" || selection?.kind === "node") {
      if (model.docById.has(selection.id)) setEvoDocId(selection.id);
      return;
    }
    if (selection?.kind === "patch") {
      const p = model.patchById.get(selection.id);
      const first = p
        ? patchChanges(model, p)
            .map((ch) => ch.document_id ?? model.docByPath.get(ch.path)?.document_id ?? null)
            .find((id): id is string => !!id)
        : null;
      if (first) setEvoDocId(first);
      return;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, model]);

  // default evolution doc = document with the most patch touches
  useEffect(() => {
    if (evoDocId || !model) return;
    let best: string | null = null;
    let bestN = -1;
    for (const [path, ps] of model.patchesByPath) {
      const doc = model.docByPath.get(path);
      if (doc?.document_id && ps.length > bestN) {
        best = doc.document_id;
        bestN = ps.length;
      }
    }
    if (best) setEvoDocId(best);
  }, [model, evoDocId]);

  if (!model) return null;
  const evoDoc = evoDocId ? model.docById.get(evoDocId) : undefined;
  const selectedPatch = selectedPatchId ? model.patchById.get(selectedPatchId) : undefined;
  const highlightAnchor = selection?.kind === "claim" ? selection.anchor : null;
  const docsWithId = model.dataset.documents.documents.filter((d) => d.document_id);

  return (
    <div className="flex h-full min-h-0">
      {/* timeline rail */}
      <aside className="w-80 flex-none border-r border-border bg-card overflow-y-auto">
        <div className="px-4 py-3 border-b border-border-subtle sticky top-0 bg-card z-10">
          <Eyebrow>Timeline · {patches.length} patches · {bundles.length} bundles</Eyebrow>
        </div>
        <ol className="px-4 py-3">
          {items.map((it, i) =>
            it.kind === "bundle" ? (
              <BundleRow key={`b${i}`} bundle={it.bundle} last={i === items.length - 1} />
            ) : (
              <PatchRow
                key={it.patch.patch_id}
                item={it}
                selected={it.patch.patch_id === selectedPatchId}
                last={i === items.length - 1}
                onSelect={() => select({ kind: "patch", id: it.patch.patch_id })}
              />
            ),
          )}
          {items.length === 0 && (
            <li className="text-sm text-muted-foreground py-6">timeline.json 无 patch / bundle。</li>
          )}
        </ol>
      </aside>

      {/* detail */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-8 py-6 space-y-8">
          {selectedSnapshot ? (
            <SnapshotDetail snap={selectedSnapshot} patches={patches} onPatch={(id) => select({ kind: "patch", id })} />
          ) : selectedPatch ? (
            <PatchDetail
              patch={selectedPatch}
              model={model}
              onOpenDoc={(id) => select({ kind: "document", id })}
              onOpenSource={(id) => jump({ kind: "source", id }, "sources")}
            />
          ) : null}

          {/* single-document evolution */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <Eyebrow>单文档演化</Eyebrow>
              <div className="flex-1" />
              <label htmlFor="evo-doc-select" className="sr-only">
                选择文档
              </label>
              <select
                id="evo-doc-select"
                name="evo-doc"
                value={evoDocId ?? ""}
                onChange={(e) => setEvoDocId(e.target.value)}
                className="h-8 text-[length:var(--text-sm)] bg-card border border-border rounded-sm px-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {docsWithId.map((d) => (
                  <option key={d.document_id!} value={d.document_id!}>
                    {d.title}
                  </option>
                ))}
              </select>
            </div>
            {evoDoc ? (
              <DocEvolution
                doc={evoDoc}
                model={model}
                selectedPatch={selectedPatchId}
                highlightAnchor={highlightAnchor}
              />
            ) : (
              <div className="text-sm text-muted-foreground">选择一个文档查看演化。</div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function PatchRow({
  item,
  selected,
  last,
  onSelect,
}: {
  item: Extract<TimelineItem, { kind: "patch" }>;
  selected: boolean;
  last: boolean;
  onSelect: () => void;
}) {
  const p = item.patch;
  const flagKeys = Object.keys(p.flag_counts ?? {});
  return (
    <li className="relative flex gap-3 pb-4">
      <div className="relative flex flex-col items-center">
        <span
          className="z-10 flex items-center justify-center rounded-full"
          style={{
            width: 20,
            height: 20,
            border: `1px solid ${selected ? "var(--color-accent)" : "var(--color-border-strong)"}`,
            background: "var(--color-card)",
          }}
        >
          <GitCommitHorizontal size={11} className="text-muted-foreground" />
        </span>
        {!last && <span className="absolute top-[20px] bottom-0 w-px" style={{ background: "var(--color-border)" }} />}
      </div>
      <button
        onClick={onSelect}
        className={cn(
          "text-left flex-1 min-w-0 rounded-sm px-2 py-1 -mt-0.5",
          selected ? "bg-accent" : "hover:bg-accent",
        )}
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-[length:var(--text-sm)]">{p.patch_id}</span>
          <span className="text-[length:var(--text-2xs)] text-muted-foreground">{fmtTime(p.ts)}</span>
        </div>
        <div className="text-[length:var(--text-2xs)] text-muted-foreground mt-0.5">
          {p.changed_paths?.length ?? 0} 文档
          {flagKeys.map((f) => (
            <span key={f} className="ml-1.5 inline-flex items-center gap-1">
              <StatusDot color={flagMeta(f).token} />
              {p.flag_counts[f]}
            </span>
          ))}
        </div>
      </button>
    </li>
  );
}

function BundleRow({ bundle, last }: { bundle: BundleVersion; last: boolean }) {
  return (
    <li className="relative flex gap-3 pb-4">
      <div className="relative flex flex-col items-center">
        <span
          className="z-10 flex items-center justify-center rounded-sm"
          style={{ width: 20, height: 20, background: "var(--color-accent)" }}
        >
          <PackageCheck size={12} style={{ color: "var(--color-text-on-accent)" }} />
        </span>
        {!last && <span className="absolute top-[20px] bottom-0 w-px" style={{ background: "var(--color-border)" }} />}
      </div>
      <div className="flex-1 min-w-0 px-2 py-1">
        <div className="flex items-center gap-2">
          <span className="text-[length:var(--text-sm)] font-medium">Bundle v{bundle.version}</span>
          <span className="text-[length:var(--text-2xs)] text-muted-foreground">{fmtTime(bundle.ts)}</span>
        </div>
        <div className="text-[length:var(--text-2xs)] text-muted-foreground font-mono mt-0.5 truncate">{bundle.tag}</div>
      </div>
    </li>
  );
}

function PatchDetail({
  patch,
  model,
  onOpenDoc,
  onOpenSource,
}: {
  patch: PatchRecord;
  model: Model;
  onOpenDoc: (id: string) => void;
  onOpenSource: (id: string) => void;
}) {
  return (
    <section>
      <Eyebrow>Patch 详情</Eyebrow>
      <h2 className="mt-2 text-[length:var(--text-2xl)] font-light flex items-center gap-3">
        <span className="font-mono">{patch.patch_id}</span>
        <span className="text-[length:var(--text-2xs)] text-muted-foreground font-sans">{fmtTime(patch.ts)}</span>
      </h2>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
        <span className="inline-flex items-center gap-1"><Cpu size={12} /> {patch.lineage?.model || patch.lineage?.driver || "—"}</span>
        <span className="inline-flex items-center gap-1"><Coins size={12} /> {fmtTokens(patch.lineage?.tokens)} tok</span>
        <span>effort {patch.effort ?? "—"}</span>
        <span>skill v{patch.skill_version ?? "—"}</span>
        <span className="font-mono">base {shortSha(patch.base_commit)}</span>
        {patch.job_id && <span className="font-mono">{patch.job_id}</span>}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground mb-1.5 flex items-center gap-1">
            <FileText size={12} /> 变更文档
          </div>
          <div className="flex flex-col gap-1">
            {patchChanges(model, patch).map((ch) => {
              const docId =
                ch.document_id ?? model.docByPath.get(ch.path)?.document_id ?? null;
              return (
                <button
                  key={ch.path}
                  onClick={() => docId && onOpenDoc(docId)}
                  disabled={!docId}
                  className="text-left flex items-center gap-2 text-[length:var(--text-sm)] font-mono px-2 py-1 border border-border rounded-sm hover:bg-accent disabled:opacity-60"
                >
                  <span
                    className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] flex-none"
                    style={{
                      color:
                        ch.change_type === "created"
                          ? "var(--color-verified)"
                          : "var(--color-info)",
                    }}
                  >
                    {ch.change_type}
                  </span>
                  <span className="truncate">{ch.path}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground mb-1.5 flex items-center gap-1">
            <Layers size={12} /> 消化来源
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(patch.sources_consumed ?? []).map((s) => (
              <Chip
                key={s}
                className="font-mono"
                title={`打开原文 ${s}`}
                onClick={() => onOpenSource(s)}
              >
                {s}
              </Chip>
            ))}
            {(patch.sources_consumed ?? []).length === 0 && (
              <span className="text-[length:var(--text-2xs)] text-muted-foreground">—</span>
            )}
          </div>
        </div>
      </div>

      {patch.escalations?.length > 0 && (
        <div className="mt-4">
          <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">Escalations</div>
          {patch.escalations.map((e, i) => {
            const { label, body } = escalationText(e);
            return (
              <div
                key={i}
                className="text-[length:var(--text-sm)] pl-2.5 py-1.5 mb-1"
                style={{ borderLeft: "2px solid var(--color-open-question)", background: "var(--color-surface-muted)" }}
              >
                <span className="font-medium">{label}</span>
                {body && <div className="text-muted-foreground mt-0.5">{body}</div>}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function SnapshotDetail({
  snap,
  patches,
  onPatch,
}: {
  snap: Snapshot;
  patches: PatchRecord[];
  onPatch: (id: string) => void;
}) {
  const consumers = patches.filter((p) => p.sources_consumed?.includes(snap.source_id));
  return (
    <section>
      <Eyebrow>来源快照</Eyebrow>
      <h2 className="mt-2 text-[length:var(--text-2xl)] font-light font-mono">{snap.source_id}</h2>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
        <span>type {snap.source_type}</span>
        <span>captured {fmtTime(snap.captured_at)}</span>
        <span className="font-mono truncate">{snap.checksum}</span>
      </div>
      <div className="mt-3">
        <div className="text-[length:var(--text-2xs)] uppercase tracking-[0.08em] text-muted-foreground mb-1.5">被以下 patch 消化</div>
        <div className="flex flex-wrap gap-1.5">
          {consumers.map((p) => (
            <button
              key={p.patch_id}
              onClick={() => onPatch(p.patch_id)}
              className="font-mono text-[length:var(--text-2xs)] px-2 py-[3px] border border-border rounded-sm hover:bg-accent"
            >
              {p.patch_id}
            </button>
          ))}
          {consumers.length === 0 && <span className="text-[length:var(--text-2xs)] text-muted-foreground">—</span>}
        </div>
      </div>
    </section>
  );
}
