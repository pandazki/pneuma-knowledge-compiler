import { Suspense, useMemo, useState } from "react";
import { Waypoints, Inbox, BookOpen } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { expandNeighborhood } from "@/lib/model";
import {
  limitGraphNeighborhood,
  pickGraphHub,
  sliceGraph,
} from "@/lib/graphViewport";
import { GraphCanvas } from "@/components/graph";
import { GlyphSwatch } from "@/components/graph/glyph";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Skeleton } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

export default function GraphView() {
  const model = useApp((s) => s.model);
  const dataset = useApp((s) => s.dataset);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const jump = useApp((s) => s.jump);
  const setView = useApp((s) => s.setView);
  const t = useT();
  const [degree, setDegree] = useState(1);

  const nodes = model?.dataset.graph.nodes ?? [];

  // The selected node: a node selection hits directly; a document selection maps onto the
  // graph node of the same id.
  const selectedId = useMemo(() => {
    if (!model || !selection) return null;
    if (selection.kind === "node" && model.nodeById.has(selection.id)) return selection.id;
    if (selection.kind === "document" && model.nodeById.has(selection.id)) return selection.id;
    if (selection.kind === "claim" && model.nodeById.has(selection.documentId))
      return selection.documentId;
    return null;
  }, [model, selection]);

  const defaultId = useMemo(
    () =>
      model
        ? pickGraphHub(model.dataset.graph.nodes, model.dataset.graph.edges)
        : null,
    [model],
  );
  const activeId = selectedId ?? defaultId;

  const expandedNeighborhood = useMemo(() => {
    if (!model || !activeId) return null;
    return expandNeighborhood(model, activeId, degree).ids;
  }, [model, activeId, degree]);

  const neighborhood = useMemo(() => {
    if (!model || !activeId || !expandedNeighborhood) return null;
    return limitGraphNeighborhood(
      model.dataset.graph.nodes,
      model.dataset.graph.edges,
      activeId,
      expandedNeighborhood,
      24,
    );
  }, [model, activeId, expandedNeighborhood]);

  const visibleGraph = useMemo(
    () =>
      model
        ? sliceGraph(
            model.dataset.graph.nodes,
            model.dataset.graph.edges,
            neighborhood,
          )
        : { nodes: [], edges: [] },
    [model, neighborhood],
  );

  const selNode = activeId && model ? model.nodeById.get(activeId) : undefined;
  const selDoc = selNode && model ? model.docById.get(selNode.id) : undefined;

  const incidentEdges = useMemo(() => {
    if (!model || !activeId || !neighborhood) return [];
    return model.dataset.graph.edges.filter(
      (e) =>
        (e.source === activeId && neighborhood.has(e.target)) ||
        (e.target === activeId && neighborhood.has(e.source)),
    );
  }, [model, activeId, neighborhood]);

  const totalIncidentEdges = useMemo(() => {
    if (!model || !activeId) return 0;
    return model.dataset.graph.edges.filter(
      (e) => e.source === activeId || e.target === activeId,
    ).length;
  }, [model, activeId]);

  const usedTypes = useMemo(() => {
    if (!model) return [];
    const present = new Set(nodes.map((n) => n.type).filter((t): t is string => !!t));
    return model.types.filter((t) => present.has(t));
  }, [model, nodes]);

  if (!dataset || !model) {
    return (
      <>
        <PageHeader title={t("nav.view.graph")} description={t("graph.description")} />
        <EmptyState
          icon={Inbox}
          title={t("graph.empty.title")}
          description={t("graph.empty.description")}
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              {t("graph.empty.action")}
            </Button>
          }
        />
      </>
    );
  }

  if (nodes.length === 0) {
    return (
      <>
        <PageHeader title={t("nav.view.graph")} description={t("graph.description")} />
        <EmptyState
          icon={Waypoints}
          title={t("graph.noNodes.title")}
          description={t("graph.noNodes.description")}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={t("nav.view.graph")}
        description={t("graph.summary", {
          nodes: nodes.length,
          edges: model.dataset.graph.edges.length,
          visibleNodes: visibleGraph.nodes.length,
          visibleEdges: visibleGraph.edges.length,
          trimmed:
            expandedNeighborhood && expandedNeighborhood.size > visibleGraph.nodes.length
              ? t("graph.summary.trimmed", { count: expandedNeighborhood.size })
              : "",
        })}
        actions={
          <SegmentedControl
            aria-label={t("graph.degree.aria")}
            size="sm"
            value={String(degree)}
            onChange={(v) => setDegree(Number(v))}
            options={[
              { value: "1", label: t("graph.degree.one") },
              { value: "2", label: t("graph.degree.two") },
            ]}
          />
        }
      />
      <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
        {/* The canvas (lazy; first on mobile). flex-1 is lg-only, where the main axis is the
            row's width: in a column, flex-basis:0% would defeat h-[420px] and collapse the
            canvas to zero height (React Flow error 004). */}
        <div className="h-[420px] min-w-0 overflow-hidden rounded-2 border border-line bg-surface lg:h-[560px] lg:flex-1">
          <Suspense fallback={<Skeleton className="m-4 h-[calc(100%-32px)]" />}>
            <GraphCanvas
              model={model}
              selectedId={activeId}
              neighborhood={neighborhood}
              onSelectNode={(id) => select({ kind: "node", id })}
            />
          </Suspense>
        </div>

        {/* Right: detail + legend (below on mobile) */}
        <aside className="w-full shrink-0 lg:w-72 lg:overflow-y-auto">
          {selNode ? (
            <section aria-label={t("graph.node.detailAria")}>
              <div className="flex items-center gap-2">
                <GlyphSwatch model={model} type={selNode.type} />
                <Badge tone="neutral">{selNode.type ?? "—"}</Badge>
              </div>
              <h2 className="mt-2 font-serif text-20 text-balance text-ink">{selNode.title}</h2>
              <Mono className="mt-1 block break-all text-12 text-ink-3">{selNode.id}</Mono>
              <Mono className="mt-0.5 block break-all text-12 text-ink-3">{selNode.path}</Mono>
              {selDoc && (
                <div className="mt-3">
                  <Button
                    size="sm"
                    onClick={() => jump({ kind: "document", id: selNode.id }, "library")}
                  >
                    <BookOpen size={13} aria-hidden /> {t("graph.node.openDocument")}
                  </Button>
                </div>
              )}

              <p className="mt-5 border-t border-line pt-3 text-12 text-ink-3">
                {t("graph.node.visibleEdges", { count: incidentEdges.length })}
                {totalIncidentEdges > incidentEdges.length &&
                  t("graph.node.allEdges", { count: totalIncidentEdges })}
              </p>
              <ul className="mt-1 flex flex-col">
                {incidentEdges.map((e, i) => {
                  const otherId = e.source === activeId ? e.target : e.source;
                  const other = model.nodeById.get(otherId);
                  if (!other) return null;
                  return (
                    <li key={`${e.source}-${e.target}-${i}`}>
                      <button
                        type="button"
                        onClick={() => select({ kind: "node", id: otherId })}
                        className="flex w-full items-center gap-2 rounded-1 py-1.5 text-left transition-colors duration-120 hover:bg-hover"
                      >
                        <GlyphSwatch model={model} type={other.type} size={12} />
                        <span className="min-w-0 flex-1 truncate text-13 text-ink">
                          {other.title}
                        </span>
                        <Mono className="shrink-0 text-12 text-ink-3">
                          {e.source === activeId ? "→" : "←"} {e.type}
                        </Mono>
                      </button>
                    </li>
                  );
                })}
                {incidentEdges.length === 0 && (
                  <li className="py-1.5 text-12 text-ink-3">{t("graph.node.noEdges")}</li>
                )}
              </ul>
            </section>
          ) : (
            <p className="text-13 text-ink-3">{t("graph.node.hint")}</p>
          )}

          {/* Legend: typeGlyph shape + ink step + type name */}
          <p className="mt-5 border-t border-line pt-3 text-12 text-ink-3">
            {t("graph.legend.title")}
          </p>
          <ul className="mt-1 flex flex-col">
            {usedTypes.map((t) => (
              <li key={t} className={cn("flex items-center gap-2 py-1")}>
                <GlyphSwatch model={model} type={t} size={13} />
                <span className="text-12 text-ink-2">{t}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </>
  );
}
