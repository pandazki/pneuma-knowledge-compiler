import { useMemo, useState } from "react";
import {
  Crosshair,
  Network,
  BookOpen,
  History as HistoryIcon,
  Search,
  FileText,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { GraphCanvas } from "@/components/GraphCanvas";
import { typeGlyph } from "@/lib/model";
import { GlyphSwatch } from "@/components/Glyph";
import { Button, Chip, EmptyState, Eyebrow, SegmentedControl } from "@/components/ui";
import { flagMeta } from "@/lib/claim";
import { cn } from "@/lib/cn";

const DEGREES = [1, 2, 3, 4];

export function GraphView() {
  const { model, selection, select, jump } = useApp();
  const [degree, setDegree] = useState(2);
  // interactive legend filter: empty set = all types active.
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  // tree-first default: only the ego spanning tree is drawn. `showAll` restores the
  // full edge set (sibling cross-edges included) for the rare deep-audit case.
  const [showAll, setShowAll] = useState(false);

  const nodes = model?.dataset.graph.nodes ?? [];

  // The center is derived purely from the current selection (a node, or a document
  // that maps to a node). No auto-pick: with nothing selected we show the empty
  // state so the graph is always ABOUT something the user chose.
  const center = useMemo(() => {
    if (!model) return null;
    if (selection?.kind === "node" && model.nodeById.has(selection.id)) return selection.id;
    if (selection?.kind === "document" && model.nodeById.has(selection.id)) return selection.id;
    if (selection?.kind === "claim" && model.nodeById.has(selection.documentId))
      return selection.documentId;
    return null;
  }, [model, selection]);

  if (!model) return null;
  if (nodes.length === 0)
    return (
      <EmptyState
        icon={<Network size={28} className="text-muted-foreground" />}
        title="图为空"
        hint="graph.json 没有节点——该 workspace 还没有文档，或文档间没有链接。"
      />
    );

  const usedTypes = [...new Set(nodes.map((n) => n.type).filter(Boolean))] as string[];
  const activeTypes = typeFilter.size === 0 ? null : typeFilter;
  const toggleType = (t: string) =>
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  const selNode = center ? model.nodeById.get(center) : undefined;
  const selDoc = selNode ? model.docById.get(selNode.id) : undefined;
  const flagTally = new Map<string, number>();
  if (selDoc)
    for (const c of selDoc.claims)
      for (const f of c.flags) flagTally.set(f, (flagTally.get(f) ?? 0) + 1);

  const neighborCount = center ? model.neighbors.get(center)?.size ?? 0 : 0;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
      <div className="flex min-h-[25rem] min-w-0 flex-none flex-col md:min-h-0 md:flex-1">
        {/* controls */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card px-3 py-2.5 md:gap-3 md:px-4">
          <Eyebrow className="flex-none">Graph</Eyebrow>
          <div className="flex flex-none items-center gap-2">
            <span className="whitespace-nowrap text-[length:var(--text-2xs)] text-muted-foreground">前后 n 度</span>
            <SegmentedControl
              segments={DEGREES.map((d) => ({ value: String(d), label: String(d) }))}
              value={String(degree)}
              onChange={(v) => setDegree(Number(v))}
            />
          </div>
          <button
            onClick={() => setShowAll((v) => !v)}
            aria-pressed={showAll}
            className={cn(
              "flex-none rounded-sm border px-2 py-[3px] text-[length:var(--text-2xs)] transition-colors",
              showAll
                ? "border-[var(--color-accent)] text-foreground"
                : "border-border text-muted-foreground hover:bg-accent",
            )}
            title={showAll ? "只看生成树（默认）" : "画出全部关联边（含兄弟横边）"}
          >
            {showAll ? "关联：全部" : "关联：树"}
          </button>
          {center && (
            <span className="min-w-0 flex-1 truncate text-[length:var(--text-2xs)] text-muted-foreground">
              以 <span className="text-foreground">{selNode?.title}</span> 为中心
            </span>
          )}
          {!center && <div className="flex-1" />}
          {/* interactive legend: click a type to filter, shape + shade match nodes */}
          <div className="hidden max-w-[46%] flex-none flex-wrap items-center justify-end gap-1.5 lg:flex">
            <button
              onClick={() => setTypeFilter(new Set())}
              className={cn(
                "rounded-sm border px-1.5 py-[3px] text-[length:var(--text-2xs)] transition-colors",
                activeTypes === null
                  ? "border-[var(--color-border-strong)] text-foreground"
                  : "border-border text-muted-foreground hover:bg-accent",
              )}
              title="显示全部类型"
            >
              全部
            </button>
            {usedTypes.map((t) => {
              const g = typeGlyph(model, t);
              const on = activeTypes === null || activeTypes.has(t);
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-sm border px-1.5 py-[3px] text-[length:var(--text-2xs)] transition-colors",
                    activeTypes !== null && on
                      ? "border-[var(--color-border-strong)] text-foreground"
                      : "border-border text-muted-foreground hover:bg-accent",
                    !on && "opacity-45",
                  )}
                  title={on ? `隐藏 ${t}` : `只看 ${t}`}
                >
                  <GlyphSwatch shape={g.shape} shade={g.shade} size={11} />
                  {t}
                </button>
              );
            })}
          </div>
        </div>

        {/* canvas / empty state */}
        <div className="relative min-h-0 flex-1">
          {center ? (
            <>
              <GraphCanvas
                model={model}
                center={center}
                degree={degree}
                activeTypes={activeTypes}
                showAll={showAll}
                onRecenter={(id) => select({ kind: "node", id })}
              />
              <div className="pointer-events-none absolute bottom-3 left-3 right-3 flex flex-col gap-1 rounded-sm border border-border-subtle bg-card/90 px-2 py-1 text-[length:var(--text-2xs)] text-muted-foreground md:right-auto">
                <span>默认只画生成树（左：入链 → 右：出链）· 悬停节点显示其余关联 · +N 徽标点击固定 · 单击节点切换中心 · 拖拽平移 · 滚轮缩放</span>
                <span className="flex items-center gap-2.5">
                  <EdgeLegend dash="" label="link" />
                  <EdgeLegend dash="4 3" label="relationship" />
                  <EdgeLegend dash="1.5 3" label="merge" />
                </span>
              </div>
            </>
          ) : (
            <GraphEmptyState query={query} setQuery={setQuery} />
          )}
        </div>
      </div>

      {/* node detail */}
      <aside className="w-full flex-none border-t border-border bg-card md:w-80 md:overflow-y-auto md:border-l md:border-t-0">
        {selNode ? (
          <div className="p-5">
            <Eyebrow>Node</Eyebrow>
            <h2 className="mt-2 text-[length:var(--text-xl)] font-light leading-tight">{selNode.title}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Chip>
                <GlyphSwatch
                  shape={typeGlyph(model, selNode.type).shape}
                  shade={typeGlyph(model, selNode.type).shade}
                  size={11}
                />
                {selNode.type ?? "—"}
              </Chip>
              <Chip className="font-mono text-muted-foreground">{selNode.id}</Chip>
            </div>
            <div className="mt-1 font-mono text-[length:var(--text-2xs)] text-muted-foreground">{selNode.path}</div>

            {flagTally.size > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {[...flagTally.entries()].map(([f, n]) => {
                  const meta = flagMeta(f);
                  return (
                    <Chip key={f} dotColor={meta.token}>
                      {meta.label} · {n}
                    </Chip>
                  );
                })}
              </div>
            )}

            {/* neighbors */}
            <Eyebrow className="mb-2 mt-5">直接关联 ({neighborCount})</Eyebrow>
            <div className="flex flex-col gap-1">
              {[...(model.neighbors.get(selNode.id) ?? [])].map((nb) => {
                const nn = model.nodeById.get(nb);
                if (!nn) return null;
                return (
                  <button
                    key={nb}
                    onClick={() => select({ kind: "node", id: nb })}
                    className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-left hover:bg-accent"
                  >
                    <GlyphSwatch
                      shape={typeGlyph(model, nn.type).shape}
                      shade={typeGlyph(model, nn.type).shade}
                      size={11}
                    />
                    <span className="truncate text-[length:var(--text-sm)]">{nn.title}</span>
                    <span className="ml-auto text-[length:var(--text-2xs)] text-muted-foreground">{nn.type}</span>
                  </button>
                );
              })}
              {neighborCount === 0 && (
                <span className="text-[length:var(--text-2xs)] text-muted-foreground">无出入链接</span>
              )}
            </div>

            {/* actions */}
            <div className="mt-5 flex flex-col gap-2">
              <Button variant="outline" onClick={() => jump({ kind: "document", id: selNode.id }, "library")}>
                <BookOpen size={14} /> 在 Library 打开
              </Button>
              <Button variant="outline" onClick={() => jump({ kind: "document", id: selNode.id }, "history")}>
                <HistoryIcon size={14} /> 查看演化
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-5 text-center text-sm text-muted-foreground">
            <Crosshair size={22} />
            <div>选中一个知识点后，这里显示它的类型、标记与直接关联。</div>
          </div>
        )}
      </aside>
    </div>
  );
}

/** Tiny inline SVG stroke sample for the edge-type legend (fable F9). */
function EdgeLegend({ dash, label }: { dash: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <svg width="18" height="6" aria-hidden>
        <line
          x1="0"
          y1="3"
          x2="18"
          y2="3"
          stroke="var(--color-text-tertiary)"
          strokeWidth="1.5"
          strokeDasharray={dash || undefined}
        />
      </svg>
      {label}
    </span>
  );
}

/** Empty state: guide + a compact, filterable, clickable document list. */
function GraphEmptyState({
  query,
  setQuery,
}: {
  query: string;
  setQuery: (v: string) => void;
}) {
  const { model, select } = useApp();
  const items = useMemo(() => {
    if (!model) return [];
    const q = query.trim().toLowerCase();
    return model.dataset.graph.nodes
      .filter((n) => !q || n.title.toLowerCase().includes(q) || (n.path ?? "").toLowerCase().includes(q))
      .sort((a, b) => a.title.localeCompare(b.title));
  }, [model, query]);

  if (!model) return null;

  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center p-8">
      <div className="flex w-full max-w-md flex-col items-center gap-4">
        <Network size={30} className="text-muted-foreground" />
        <div className="text-center">
          <div className="text-[length:var(--text-lg)] font-light text-foreground">选择一个知识点</div>
          <div className="mt-1 text-sm text-muted-foreground">
            从 Library 或下面的列表选中一个知识点，图会以它为中心分层展开前后 n 度关联。
          </div>
        </div>

        <div className="relative w-full">
          <Search
            size={14}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索知识点…"
            className="h-8 w-full rounded-sm border border-border bg-card pl-8 pr-3 text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        <div className="max-h-72 w-full overflow-y-auto rounded-sm border border-border-subtle">
          {items.length === 0 && (
            <div className="px-3 py-6 text-center text-[length:var(--text-sm)] text-muted-foreground">
              没有匹配的知识点。
            </div>
          )}
          {items.map((n) => {
            const g = typeGlyph(model, n.type);
            return (
              <button
                key={n.id}
                onClick={() => select({ kind: "node", id: n.id })}
                className="flex w-full items-center gap-2 border-b border-border-subtle px-3 py-2 text-left last:border-b-0 hover:bg-accent"
              >
                <GlyphSwatch shape={g.shape} shade={g.shade} size={12} />
                <span className="min-w-0 flex-1 truncate text-[length:var(--text-sm)] text-foreground">{n.title}</span>
                <span className="flex items-center gap-1 text-[length:var(--text-2xs)] text-muted-foreground">
                  <FileText size={10} /> {n.type ?? "—"}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
