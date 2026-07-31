import { useEffect, useMemo, useState } from "react";
import { BookMarked, ChevronRight, FileText, Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import type { Claim, DocumentRecord } from "@/lib/types";
import { claimKey, type DirNode, type Model } from "@/lib/model";
import { defaultCollapsedDirs, dirFileCount, isDirOpen } from "@/lib/documentTree";
import { displayClaim, extractClaimLabel } from "@/lib/claim";
import {
  buildCitationNumbers,
  citationKey,
  presentCitationSource,
} from "@/lib/citations";
import { intlTag } from "@/lib/i18n";
import { buildLinkIndex, lensDocuments, type LinkIndex } from "@/lib/structureLens";
import { useLocale, useT, useTOr } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { NeighborhoodCard } from "./NeighborhoodCard";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { cn } from "@/ui/cn";

/**
 * claimLabel tier → ink step (solid / outline as the secondary / muted as the quietest;
 * rule 4: no per-module colour).
 */
function labelBadgeClass(tier: string): string {
  switch (tier) {
    case "solid":
      return "border-ink-2 text-ink";
    case "muted":
      return "border-line bg-transparent text-ink-3";
    default: // outline
      return "";
  }
}

export default function LibraryView() {
  const t = useT();
  const dataset = useApp((s) => s.dataset);
  const model = useApp((s) => s.model);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const docs = model?.dataset.documents.documents ?? [];

  // The base's two-way link index, built once per projection: the neighbourhood card is an
  // index over ALL documents' claims, not over the one on screen, so it cannot be derived
  // inside the proof.
  const linkIndex = useMemo(
    () => (model ? buildLinkIndex(lensDocuments(model.dataset.documents.documents)) : null),
    [model],
  );

  // Resolve the selection: document/node → the document; claim → document + highlight anchor;
  // otherwise the first document.
  const { activeDoc, highlightAnchor, askedForPath } = useMemo(() => {
    if (!model)
      return {
        activeDoc: null as DocumentRecord | null,
        highlightAnchor: null as string | null,
        askedForPath: null as string | null,
      };
    let id: string | null = null;
    let anchor: string | null = null;
    if (selection?.kind === "document" || selection?.kind === "node") id = selection.id;
    else if (selection?.kind === "claim") {
      id = selection.documentId;
      anchor = selection.anchor;
    }
    const byId = id ? model.docById.get(id) : undefined;
    return {
      activeDoc: byId ?? docs.find((d) => d.document_id) ?? docs[0] ?? null,
      highlightAnchor: anchor,
      // Only a document someone actually asked for (a click, a deep link) — not the
      // fallback first document, which must not unfold the contents on arrival.
      askedForPath: byId?.path ?? null,
    };
  }, [model, selection, docs]);

  // Arriving by deep link (#/library/claim/…): scroll the claim into view. The body is its
  // own scroll region, so this moves that region and leaves the rest of the view put.
  useEffect(() => {
    if (!highlightAnchor || !activeDoc) return;
    const el = document.getElementById(`claim-${highlightAnchor}`);
    el?.scrollIntoView({ block: "center" });
  }, [highlightAnchor, activeDoc]);

  /* --------------------------------------------------------- contents folding state */

  // Which directories start folded (>10 files, first level exempt) …
  const collapsedDefaults = useMemo(
    () => (model ? defaultCollapsedDirs(model.tree) : new Set<string>()),
    [model],
  );
  // … and what the reader has since decided, remembered for the session.
  const [openOverrides, setOpenOverrides] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setOpenOverrides({});
  }, [model?.tree]);

  // A document someone asked for must be visible in the contents: unfold its ancestors,
  // so a deep link into a folded folder does not land on an invisible row.
  useEffect(() => {
    if (!askedForPath) return;
    const parts = askedForPath.split("/").slice(0, -1);
    if (parts.length === 0) return;
    setOpenOverrides((prev) => {
      let next = prev;
      let dir = "";
      for (const part of parts) {
        dir = dir ? `${dir}/${part}` : part;
        if (next[dir] !== true) next = { ...next, [dir]: true };
      }
      return next;
    });
  }, [askedForPath]);

  if (!dataset || !model) {
    return (
      <>
        <PageHeader title={t("library.title")} description={t("library.descriptionShort")} />
        <EmptyState
          icon={Inbox}
          title={t("library.empty.title")}
          description={t("library.empty.description")}
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              {t("library.empty.action")}
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        className="shrink-0"
        title={t("library.title")}
        description={t("library.description", { count: docs.length })}
      />
      {/* Two panes, each scrolling on its own: the contents and the proof (scroll charter). */}
      <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:items-stretch">
        {/* Left: the document tree, its count line pinned above it */}
        <div className="flex min-h-0 w-full shrink-0 flex-col border-b border-line pb-3 md:w-64 md:border-b-0 md:pb-0">
          <p className="mb-2 shrink-0 text-12 text-ink-3">
            {t("library.toc.count", { count: docs.length })}
          </p>
          <ScrollRegion
            as="nav"
            aria-label={t("library.toc.aria")}
            className="max-h-64 min-h-0 md:max-h-[70vh] lg:max-h-none lg:flex-1"
          >
            <ul className="flex flex-col">
              {model.tree.children.map((node) => (
                <TreeRow
                  key={node.path || node.name}
                  node={node}
                  depth={0}
                  selectedPath={activeDoc?.path ?? null}
                  collapsedDefaults={collapsedDefaults}
                  openOverrides={openOverrides}
                  onToggle={(path, open) =>
                    setOpenOverrides((prev) => ({ ...prev, [path]: open }))
                  }
                  onSelect={(doc) =>
                    select({ kind: "document", id: doc.document_id ?? doc.path })
                  }
                />
              ))}
            </ul>
          </ScrollRegion>
        </div>

        {/* Right: the selected document, set as a proof */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {activeDoc ? (
            <DocumentProof
              doc={activeDoc}
              model={model}
              linkIndex={linkIndex}
              highlightAnchor={highlightAnchor}
              selectedAnchor={selection?.kind === "claim" ? selection.anchor : null}
            />
          ) : (
            <EmptyState
              icon={BookMarked}
              title={t("library.noDoc.title")}
              description={t("library.noDoc.description")}
            />
          )}
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------ the document tree */

function TreeRow({
  node,
  depth,
  selectedPath,
  collapsedDefaults,
  openOverrides,
  onToggle,
  onSelect,
}: {
  node: DirNode;
  depth: number;
  selectedPath: string | null;
  collapsedDefaults: Set<string>;
  openOverrides: Record<string, boolean>;
  onToggle: (path: string, open: boolean) => void;
  onSelect: (doc: DocumentRecord) => void;
}) {
  const t = useT();
  const pad = { paddingLeft: `${depth * 14}px` };
  if (node.isDir) {
    const open = isDirOpen(node.path, collapsedDefaults, openOverrides);
    const count = dirFileCount(node);
    return (
      <li>
        <button
          type="button"
          onClick={() => onToggle(node.path, !open)}
          aria-expanded={open}
          aria-label={t(open ? "library.toc.collapseDir" : "library.toc.expandDir", {
            name: node.name,
            count,
          })}
          style={pad}
          className="flex w-full items-center gap-1.5 border-l-2 border-transparent py-1 pr-2 text-left text-13 text-ink-2 transition-colors duration-120 hover:bg-hover"
        >
          <ChevronRight
            size={12}
            aria-hidden
            className={cn(
              "shrink-0 text-ink-3 transition-transform duration-120",
              open && "rotate-90",
            )}
          />
          <span className="truncate">{node.name}</span>
          {!open && (
            <span className="ml-auto shrink-0 text-12 text-ink-3">({count})</span>
          )}
        </button>
        {open && (
          <ul>
            {node.children.map((c) => (
              <TreeRow
                key={c.path || c.name}
                node={c}
                depth={depth + 1}
                selectedPath={selectedPath}
                collapsedDefaults={collapsedDefaults}
                openOverrides={openOverrides}
                onToggle={onToggle}
                onSelect={onSelect}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }
  const selected = node.path === selectedPath;
  return (
    <li>
      <button
        type="button"
        onClick={() => node.doc && onSelect(node.doc)}
        style={pad}
        aria-current={selected || undefined}
        className={cn(
          "flex w-full items-center gap-1.5 border-l-2 py-1 pr-2 text-left text-13 transition-colors duration-120",
          selected
            ? "border-accent bg-accent-soft font-medium text-ink"
            : "border-transparent text-ink-2 hover:bg-hover",
        )}
      >
        <FileText size={13} aria-hidden className="shrink-0 text-ink-3" />
        <span className="truncate">{node.doc?.title || node.name}</span>
      </button>
    </li>
  );
}

/* ------------------------------------------------------------------- the proof */

function DocumentProof({
  doc,
  model,
  linkIndex,
  highlightAnchor,
  selectedAnchor,
}: {
  doc: DocumentRecord;
  model: Model;
  linkIndex: LinkIndex | null;
  highlightAnchor: string | null;
  selectedAnchor: string | null;
}) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();
  const select = useApp((s) => s.select);
  const jump = useApp((s) => s.jump);
  const focusSource = useApp((s) => s.focusSource);
  const labels = model.dataset.claimLabels;

  // The wording lib/citations needs, injected: that module is transpiled standalone by its
  // test, so it cannot import the dictionary itself.
  const citationI18n = useMemo(() => ({ tOr, intlTag: intlTag(locale) }), [tOr, locale]);

  const fm = doc.frontmatter ?? {};
  const fmEntries = Object.entries(fm);
  // One line of frontmatter for the pinned masthead; §1 below keeps the full table. doc_id
  // is already spelled out beside it, so it does not get said twice.
  const fmSummary = useMemo(
    () =>
      fmEntries
        .filter(([k]) => k !== "doc_id")
        .slice(0, 4)
        .map(([k, v]) => `${k} ${Array.isArray(v) ? v.join(", ") : typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}`)
        .join("  ·  "),
    [doc], // fmEntries is derived from doc; recomputing per document is the whole point
  );
  const patches = doc.document_id
    ? model.patchesByDocId.get(doc.document_id) ?? []
    : model.patchesByPath.get(doc.path) ?? [];

  // Consecutive list_items merge into one list; paragraphs each stand alone.
  const groups = useMemo(() => {
    const out: { kind: "list" | "prose"; claims: Claim[] }[] = [];
    for (const c of doc.claims) {
      const kind = c.kind === "list_item" ? ("list" as const) : ("prose" as const);
      const last = out[out.length - 1];
      if (last && last.kind === "list" && kind === "list") last.claims.push(c);
      else out.push({ kind, claims: [c] });
    }
    return out;
  }, [doc]);

  // The document-level citation list (deduplicated, keeping the number of the first mention).
  const citations = useMemo(() => {
    const seen = new Map<string, CitationEntry>();
    for (const c of doc.claims) {
      for (const ci of c.citations) {
        const entry = {
          sourceId: ci.source_id,
          blockStart: ci.from,
          blockEnd: ci.to,
        };
        const key = citationKey(entry);
        if (!seen.has(key)) {
          const node = model.nodeById.get(`src:${ci.source_id}`);
          const snapshot = model.snapshotById.get(ci.source_id);
          const source = presentCitationSource(
            {
              sourceId: ci.source_id,
              title: node?.title,
              kind: snapshot?.source_type,
              capturedAt: snapshot?.captured_at,
            },
            citationI18n,
          );
          seen.set(key, { ...entry, ...source });
        }
      }
    }
    return [...seen.values()];
  }, [doc, model, citationI18n]);

  // The body and the “Sources” section share one document-level ledger, so the same source
  // span always carries the same number in both.
  const citationNumbers = useMemo(
    () => buildCitationNumbers(citations),
    [citations],
  );
  const citationByKey = useMemo(
    () => new Map(citations.map((citation) => [citationKey(citation), citation])),
    [citations],
  );

  const renderClaim = (c: Claim, renderKey?: string | number) => {
    const { md, disputedNote, openQuestionNote } = displayClaim(c);
    const labeled = extractClaimLabel(md, labels);
    const note = c.anchor
      ? model.sidecarNotes.get(claimKey(doc.document_id, c.anchor))
      : undefined;
    const sideDisputed = note?.disputed ?? disputedNote;
    const sideOpen = note?.open_question ?? openQuestionNote;
    const flags = c.flags ?? [];
    const selected = !!c.anchor && c.anchor === (highlightAnchor ?? selectedAnchor);
    const marginalia = (flags.length > 0 || sideDisputed || sideOpen) && (
      <div className="flex flex-row flex-wrap gap-2 md:flex-col md:flex-nowrap">
        {flags.map((f) => (
          <div key={f} className="flex max-w-52 flex-col gap-1">
            <Badge tone={f === "disputed" || f === "open_question" ? "warn" : "neutral"}>
              {tOr(`common.flag.${f}`, f)}
            </Badge>
            {f === "disputed" && sideDisputed && (
              <p className="text-12 leading-relaxed text-ink-3">{sideDisputed}</p>
            )}
            {f === "open_question" && sideOpen && (
              <p className="text-12 leading-relaxed text-ink-3">{sideOpen}</p>
            )}
          </div>
        ))}
        {!flags.includes("disputed") && sideDisputed && (
          <div className="flex max-w-52 flex-col gap-1">
            <Badge tone="warn">{t("common.flag.disputed")}</Badge>
            <p className="text-12 leading-relaxed text-ink-3">{sideDisputed}</p>
          </div>
        )}
        {!flags.includes("open_question") && sideOpen && (
          <div className="flex max-w-52 flex-col gap-1">
            <Badge tone="warn">{t("common.flag.open_question")}</Badge>
            <p className="text-12 leading-relaxed text-ink-3">{sideOpen}</p>
          </div>
        )}
      </div>
    );

    const body = (
      <>
        <p className="prose">
          {labeled && (
            <>
              <Badge tone="neutral" className={cn("mr-1.5 align-[1px]", labelBadgeClass(labeled.label.tier))}>
                {labeled.label.label}
              </Badge>
            </>
          )}
          {labeled ? labeled.rest : md}
          {c.citations.map((ci, i) => {
            const key = citationKey({
              sourceId: ci.source_id,
              blockStart: ci.from,
              blockEnd: ci.to,
            });
            const entry = citationByKey.get(key);
            return (
              <Footnote
                key={`${key}-${i}`}
                index={citationNumbers.get(key) ?? i + 1}
                citation={{
                  sourceId: ci.source_id,
                  blockStart: ci.from,
                  blockEnd: ci.to,
                  title: typeof entry?.title === "string" ? entry.title : undefined,
                  snippet: ci.redaction_state === "withheld" ? undefined : ci.snippet,
                }}
                onJump={() => focusSource(ci.source_id, { start: ci.from, end: ci.to })}
              />
            );
          })}
        </p>
        {c.anchor && (
          <Mono className="mt-1 block text-12 text-ink-3">⚓ {c.anchor}</Mono>
        )}
      </>
    );

    return (
      <div
        key={renderKey}
        id={c.anchor ? `claim-${c.anchor}` : undefined}
        role={c.anchor && doc.document_id ? "button" : undefined}
        tabIndex={c.anchor && doc.document_id ? 0 : undefined}
        onClick={() =>
          c.anchor && doc.document_id &&
          select({ kind: "claim", documentId: doc.document_id, anchor: c.anchor })
        }
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && c.anchor && doc.document_id) {
            e.preventDefault();
            select({ kind: "claim", documentId: doc.document_id, anchor: c.anchor });
          }
        }}
        className={cn(
          "flex flex-col gap-2 py-3 md:flex-row md:gap-6",
          c.anchor && doc.document_id && "cursor-pointer rounded-1",
          selected && "bg-accent-soft",
        )}
      >
        <div className="min-w-0 flex-1">{body}</div>
        {marginalia && (
          <aside className="shrink-0 md:w-44 md:border-l md:border-line md:pl-4">
            {marginalia}
          </aside>
        )}
      </div>
    );
  };

  return (
    <article className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* The masthead stays put: which document you are reading is never scrolled away. */}
      <header className="sticky top-12 z-10 shrink-0 border-b border-line bg-bg pb-4 lg:static">
        <Mono className="text-12 text-ink-3">{doc.path}</Mono>
        <h2 className="mt-1 max-w-measure font-serif text-30 leading-[1.25] text-balance text-ink">
          {doc.title}
        </h2>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-3 text-12 text-ink-3">
          {doc.document_id && <Mono className="text-12">doc_id · {doc.document_id}</Mono>}
          {fmSummary && (
            <Mono className="min-w-0 flex-1 truncate text-12" title={fmSummary}>
              {fmSummary}
            </Mono>
          )}
        </div>
      </header>

      <ScrollRegion className="min-h-0 lg:flex-1">
      <div className="max-w-measure">
      {/* §01 is the way OUT of this page. It leads because a thread is followed from where you
          landed, and a reader who has to scroll past a 1200-claim ledger to find the exits
          will not find them. */}
      {linkIndex && (
        <section className="mt-5">
          <SectionRule no={1} title={t("library.neighborhood.title")} />
          <p className="mt-2 text-12 text-ink-3">{t("library.neighborhood.note")}</p>
          <NeighborhoodCard index={linkIndex} path={doc.path} />
        </section>
      )}

      {fmEntries.length > 0 && (
        <section className="mt-5">
          <SectionRule no={2} title={t("library.frontmatter.title")} />
          <dl className="mt-3 flex flex-col">
            {fmEntries.map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-3 border-b border-line py-1.5 last:border-b-0">
                <dt className="w-32 shrink-0 text-12 text-ink-3">{k}</dt>
                <dd className="min-w-0 break-all">
                  <Mono className="text-12 text-ink-2">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </Mono>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <section className="mt-6">
        <SectionRule no={3} title={t("library.body.title")} />
        <div className="mt-2 divide-y divide-line">
          {groups.map((g, gi) =>
            g.kind === "list" ? (
              <ul key={gi} className="list-disc pl-5 marker:text-ink-3">
                {g.claims.map((c, i) => (
                  <li key={c.anchor ?? i}>{renderClaim(c)}</li>
                ))}
              </ul>
            ) : (
              <div key={gi}>
                {g.claims.map((c, i) => renderClaim(c, c.anchor ?? i))}
              </div>
            ),
          )}
          {doc.claims.length === 0 && (
            <p className="py-6 text-13 text-ink-3">{t("library.body.empty")}</p>
          )}
        </div>
      </section>

      {citations.length > 0 && (
        <section className="mt-6">
          <SectionRule no={4} title={t("library.citations.title")} />
          <CitationList
            className="mt-3"
            citations={citations}
            onJump={(c) =>
              focusSource(
                c.sourceId,
                c.blockStart != null
                  ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart }
                  : null,
              )
            }
          />
        </section>
      )}

      {patches.length > 0 && (
        <section className="mt-6">
          <SectionRule no={5} title={t("library.patches.title")} />
          <ul className="mt-3 flex flex-col">
            {patches.map((p) => (
              <li key={p.patch_id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  onClick={() => jump({ kind: "patch", id: p.patch_id }, "history")}
                  className="flex w-full items-baseline gap-3 py-1.5 text-left transition-colors duration-120 hover:bg-hover"
                >
                  <Mono className="text-12 text-accent">{p.patch_id}</Mono>
                  <span className="min-w-0 flex-1 truncate text-12 text-ink-3">
                    {p.ts ?? ""}
                  </span>
                  <span className="shrink-0 text-12 text-ink-3">
                    {t("library.patches.changed", {
                      count: (p.changed_paths ?? []).length,
                    })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
      </div>
      </ScrollRegion>
    </article>
  );
}
