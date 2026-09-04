import { useEffect, useMemo, useState } from "react";
import { Archive, BookMarked, ChevronRight, FileText, Inbox } from "lucide-react";
import { useApp } from "@/lib/store";
import type { Claim, DocumentRecord } from "@/lib/types";
import { claimKey, documentDisplayTitle, type DirNode, type Model } from "@/lib/model";
import { defaultCollapsedDirs, dirFileCount, isDirOpen } from "@/lib/documentTree";
import {
  archiveRecordFullTarget,
  documentAddress,
  documentByPath,
  foldArchive,
  isArchiveRecord,
  isArchivedPath,
  splitArchived,
} from "@/lib/archive";
import { displayClaim, extractClaimLabel } from "@/lib/claim";
import {
  DOC_ID_KEY,
  frontmatterFields,
  frontmatterInline,
  frontmatterValue,
  type FrontmatterField,
} from "@/lib/frontmatter";
import {
  buildSupersessionIndex,
  currentClaims,
  documentHasSupersession,
  emptySupersessionIndex,
  isSuperseded,
  supersededBy,
  supersededCount,
  type SupersessionIndex,
} from "@/lib/supersession";
import {
  hasOverviewContent,
  ledgerClaims,
  parseOverview,
  resolveHref,
  type DocumentOverview,
} from "@/lib/overview";
import { isExternalHref, splitInlineMarkdown } from "@/lib/inlineMarkdown";
import {
  buildCitationNumbers,
  citationKey,
  presentCitationSource,
} from "@/lib/citations";
import { fmtTime } from "@/lib/format";
import { intlTag } from "@/lib/i18n";
import {
  buildLinkIndex,
  lensDocuments,
  volumeFamily,
  type LinkIndex,
} from "@/lib/structureLens";
import { useLocale, useT, useTOr } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { ArchiveInventoryDrawer } from "@/views/archive/ArchiveInventoryDrawer";
import { ArchiveProposalDialog } from "@/views/archive/ArchiveProposalDialog";
import { AccessCard } from "./AccessCard";
import { NeighborhoodCard } from "./NeighborhoodCard";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { SegmentedControl } from "@/ui/SegmentedControl";
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
  const lens = useApp((s) => s.lens);

  const currentUser = useApp((s) => s.currentUser);
  const docs = model?.dataset.documents.documents ?? [];

  /**
   * The archive is folded OUT of the contents, not hidden from them: an archived page is
   * still cited, still anchored, still addressable — it has simply stopped being the answer.
   * It gets its own collapsed section at the foot of the rail, the way a rollover volume gets
   * folded onto its owner (`lib/structureLens`), and the count line above the tree counts the
   * live library so that "95 documents" does not quietly include what the owner retired.
   */
  const fold = useMemo(() => (model ? foldArchive(model.tree) : null), [model]);
  const liveDocs = useMemo(() => splitArchived(docs).live, [docs]);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [inventoryOpen, setInventoryOpen] = useState(false);

  // The base's two-way link index, built once per projection: the neighbourhood card is an
  // index over ALL documents' claims, not over the one on screen, so it cannot be derived
  // inside the proof.
  const linkIndex = useMemo(
    () => (model ? buildLinkIndex(lensDocuments(model.dataset.documents.documents)) : null),
    [model],
  );

  // Supersession is a repository-level fact — a successor may live in another document — so
  // the index is built over every document, once per projection, and read per page.
  const supersession = useMemo(
    () =>
      model
        ? buildSupersessionIndex(model.dataset.documents.documents)
        : emptySupersessionIndex(),
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
    // `docById` is keyed by document_id; a jump from outside canonical (a consultation's
    // manifest, a document's access card) knows the PATH, which is the address the rest
    // of the system uses. Falling back to it makes one selection kind serve both.
    const byId = id ? model.docById.get(id) ?? model.docByPath.get(id) : undefined;
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
          // Importing a source is the owner's act; a visitor offered the button would be
          // offered a page their lens does not have.
          action={
            lens === "owner" ? (
              <Button size="sm" onClick={() => setView("ingest")}>
                {t("library.empty.action")}
              </Button>
            ) : undefined
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
        description={t("library.description", { count: liveDocs.length })}
        // The archive is the owner's judgement about attention, so its inventory is the
        // owner's page. A visitor never sees the door, and never needs to.
        actions={
          lens === "owner" && currentUser ? (
            <Button
              size="sm"
              variant="ghost"
              aria-label={t("archive.inventory.openAria")}
              onClick={() => setInventoryOpen(true)}
            >
              <Archive size={14} aria-hidden />
              {t("archive.inventory.open")}
            </Button>
          ) : undefined
        }
      />
      {currentUser && (
        // Keyed by the owner: an inventory, like a proposal, belongs to ONE library, so a
        // switch REMOUNTS the drawer rather than letting the previous owner's listing (or a
        // restore dialog opened over it) survive into the next one's (I1 at the UI).
        <ArchiveInventoryDrawer
          key={currentUser}
          open={inventoryOpen}
          onOpenChange={setInventoryOpen}
          userId={currentUser}
        />
      )}
      {/* Two panes, each scrolling on its own: the contents and the proof (scroll charter). */}
      <div className="flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:items-stretch">
        {/* Left: the document tree, its count line pinned above it */}
        <div className="flex min-h-0 w-full shrink-0 flex-col border-b border-line pb-3 md:w-64 md:border-b-0 md:pb-0">
          <p className="mb-2 shrink-0 text-12 text-ink-3">
            {t("library.toc.count", { count: liveDocs.length })}
          </p>
          <ScrollRegion
            as="nav"
            aria-label={t("library.toc.aria")}
            className="max-h-64 min-h-0 md:max-h-[70vh] lg:max-h-none lg:flex-1"
          >
            <ul className="flex flex-col">
              {(fold?.live ?? model.tree).children.map((node) => (
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
                  // A record stands among the live pages, and it shares its subject with
                  // the copy under `archive/`: the two are addressed by path, everything
                  // else by the id that survives a rename (`lib/archive.ts`).
                  onSelect={(doc) =>
                    select({
                      kind: "document",
                      id: documentAddress(doc.path, doc.document_id, doc),
                    })
                  }
                />
              ))}
            </ul>
            {/* The archive: below the contents, under its own rule, collapsed. A library
                that has archived nothing renders exactly as it did before the archive
                existed — no empty heading, no extra rule. */}
            {fold && fold.archived.length > 0 && (
              <div className="mt-2 border-t border-line pt-2">
                <button
                  type="button"
                  onClick={() => setArchiveOpen((open) => !open)}
                  aria-expanded={archiveOpen}
                  aria-label={t(
                    archiveOpen ? "archive.library.collapse" : "archive.library.expand",
                    { count: fold.archivedFiles },
                  )}
                  className="flex w-full items-center gap-1.5 py-1 pr-2 text-left text-13 text-ink-3 transition-colors duration-120 hover:bg-hover"
                >
                  <ChevronRight
                    size={12}
                    aria-hidden
                    className={cn(
                      "shrink-0 transition-transform duration-120",
                      archiveOpen && "rotate-90",
                    )}
                  />
                  <Archive size={12} aria-hidden className="shrink-0" />
                  <span className="truncate">{t("archive.library.section")}</span>
                  <span className="ml-auto shrink-0 text-12">({fold.archivedFiles})</span>
                </button>
                {archiveOpen && (
                  <ul className="flex flex-col">
                    {fold.archived.map((node) => (
                      <TreeRow
                        key={node.path || node.name}
                        node={node}
                        depth={1}
                        selectedPath={activeDoc?.path ?? null}
                        collapsedDefaults={collapsedDefaults}
                        openOverrides={openOverrides}
                        onToggle={(path, open) =>
                          setOpenOverrides((prev) => ({ ...prev, [path]: open }))
                        }
                        // Every row here is an archived path — the half of a move whose
                        // other half stands live under the same subject. Selecting by path
                        // is what keeps the two apart.
                        onSelect={(doc) => select({ kind: "document", id: doc.path })}
                      />
                    ))}
                  </ul>
                )}
              </div>
            )}
          </ScrollRegion>
        </div>

        {/* Right: the selected document, set as a proof */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {activeDoc ? (
            <DocumentProof
              key={activeDoc.document_id ?? activeDoc.path}
              doc={activeDoc}
              model={model}
              linkIndex={linkIndex}
              supersession={supersession}
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

/* ------------------------------------------------------------- inline claim prose */

/**
 * One claim's prose with its inline markdown laid out: a `[Title](../x.md)` cross-link
 * becomes a jump to that document when the library holds it (the compile writes links
 * against paths, and a link into a document this snapshot lacks stays as its label), an
 * absolute URL opens in a new tab, a code span is set in mono. Anything else is text.
 */
function InlineClaimText({
  md,
  fromPath,
  resolve,
  onOpen,
}: {
  md: string;
  fromPath: string;
  resolve: (path: string) => DocumentRecord | undefined;
  onOpen: (target: DocumentRecord) => void;
}) {
  return (
    <>
      {splitInlineMarkdown(md).map((seg, i) => {
        if (seg.kind === "code") return <Mono key={i}>{seg.text}</Mono>;
        if (seg.kind === "strong") return <strong key={i}>{seg.text}</strong>;
        if (seg.kind === "link") {
          if (isExternalHref(seg.href)) {
            return (
              <a
                key={i}
                href={seg.href}
                target="_blank"
                rel="noreferrer"
                className="text-accent underline-offset-2 hover:underline"
              >
                {seg.label}
              </a>
            );
          }
          const target = resolve(resolveHref(fromPath, seg.href));
          if (!target) return <span key={i}>{seg.label}</span>;
          return (
            <button
              key={i}
              type="button"
              title={target.path}
              onClick={(e) => {
                e.stopPropagation();
                onOpen(target);
              }}
              className="rounded-1 text-accent underline-offset-2 hover:underline"
            >
              {seg.label}
            </button>
          );
        }
        return <span key={i}>{seg.text}</span>;
      })}
    </>
  );
}

/* ---------------------------------------------------------------- the overview */

/**
 * The document's structured facts as the overview card's header strip: list-valued keys as
 * chips, everything else as a compact `key value` pair, and `doc_id` last and quietest — it
 * is an address, not a fact about the subject.
 *
 * Keys and values are the document's own bytes and render verbatim; the two exceptions a
 * CLOSED VOLUME carries — the legacy `archived_from` key and its `type: archive` fallback —
 * are resolved by `lib/frontmatter`, which is where the reason is written down. A key naming
 * another document is a door when this projection carries it, and its bare path when it does
 * not: naming where something is says more than silence, and less than a link to nowhere.
 */
function MetaStrip({
  entries,
  onOpen,
  titleOf,
}: {
  entries: [string, unknown][];
  onOpen: (path: string) => void;
  titleOf: (path: string) => string | null;
}) {
  const t = useT();
  const fields = frontmatterFields(entries);
  // Chips first, as before: a set of values reads as a group, and interleaving it with the
  // one-line pairs turns the strip into a list of unlike things.
  const ordered = [
    ...fields.filter((f) => f.kind === "chips"),
    ...fields.filter((f) => f.kind !== "chips"),
  ];
  const docId = entries.find(([k]) => k === DOC_ID_KEY);
  const label = (field: FrontmatterField) => (field.labelKey ? t(field.labelKey) : field.key);
  return (
    <div
      role="group"
      aria-label={t("library.frontmatter.title")}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3"
    >
      {ordered.map((field) =>
        field.kind === "chips" ? (
          <div key={field.key} className="flex flex-wrap items-center gap-1.5">
            <span className="text-12 uppercase tracking-wide text-ink-3">{label(field)}</span>
            {field.chips.map((chip) => (
              <Badge key={chip}>
                <Mono className="text-12">{chip}</Mono>
              </Badge>
            ))}
          </div>
        ) : (
          <div key={field.key} className="flex min-w-0 items-baseline gap-1.5">
            <span className="shrink-0 text-12 uppercase tracking-wide text-ink-3">
              {label(field)}
            </span>
            {field.kind === "path" && titleOf(field.text) ? (
              <button
                type="button"
                title={field.text}
                onClick={() => onOpen(field.text)}
                className="min-w-0 rounded-1 text-left text-accent underline-offset-2 hover:underline"
              >
                <Mono className="break-all text-12">{field.text}</Mono>
              </button>
            ) : (
              <Mono className="min-w-0 break-all text-12 text-ink-2">
                {field.textKey ? t(field.textKey) : field.text}
              </Mono>
            )}
          </div>
        ),
      )}
      {docId && (
        <Mono className="min-w-0 break-all text-12 text-ink-3">
          doc_id · {frontmatterValue(docId[1])}
        </Mono>
      )}
    </div>
  );
}

/**
 * What this document IS, at the top of the page: the structured facts as a header strip, then
 * the overview region's four slots with their headings, connections as links into the library.
 * The region markers and the grounding references never reach the page — `lib/overview` strips
 * them with the rest of the machinery, exactly as `lib/claim` does for a claim. A document with
 * no overview region still gets the card: it then carries the facts alone.
 */
function OverviewCard({
  overview,
  fromPath,
  frontmatter,
  onOpen,
  titleOf,
}: {
  overview: DocumentOverview | null;
  /** The document this card belongs to — a connection's href is written relative to it. */
  fromPath: string;
  frontmatter: [string, unknown][];
  onOpen: (path: string) => void;
  /** The target's title, or null when this projection carries no such document. */
  titleOf: (path: string) => string | null;
}) {
  const t = useT();
  const slots = (
    [
      ["definition", overview?.definition],
      ["summary", overview?.summary],
      ["introduction", overview?.introduction],
    ] as const
  ).filter(([, text]) => !!text);
  const connections = overview?.connections ?? [];
  const hasRegion = slots.length > 0 || connections.length > 0;
  return (
    <section className="mt-5">
      <SectionRule no={1} title={t("library.overview.title")} />
      {/* The note speaks for the overview region. A card carrying only the facts must not
          claim a picture the document never wrote. */}
      {hasRegion && <p className="mt-2 text-12 text-ink-3">{t("library.overview.note")}</p>}
      <div className="mt-3 rounded-1 border border-line">
        {frontmatter.length > 0 && (
          <MetaStrip entries={frontmatter} onOpen={onOpen} titleOf={titleOf} />
        )}
        {hasRegion && (
          <dl className="flex flex-col gap-3 p-4">
            {slots.map(([slot, text]) => (
              <div key={slot} className="flex flex-col gap-1">
                <dt className="text-12 uppercase tracking-wide text-ink-3">
                  {t(`library.overview.${slot}`)}
                </dt>
                <dd className="prose max-w-measure text-ink">{text}</dd>
              </div>
            ))}
            {connections.length > 0 && (
              <div className="flex flex-col gap-1">
                <dt className="text-12 uppercase tracking-wide text-ink-3">
                  {t("library.overview.connections")}
                </dt>
                <dd>
                  <ul className="flex flex-col gap-1">
                    {/* A relation names the SUBJECT it points at, not the file it lives in:
                        the body's cross-links already read as titles, and a slot printing
                        `../projects/x.md` beside them was the one address the reader had to
                        decode. The path stays, as the link's title attribute. */}
                    {connections.map((c) => {
                      // The HREF is the address; the label may be anything the compile wrote
                      // — including, as here, the relative path itself. Resolving it against
                      // this document is what the gate does, and what the body's cross-links
                      // already do.
                      const target = resolveHref(fromPath, c.href) || c.path;
                      const title = titleOf(target);
                      return (
                        <li key={c.path} className="flex flex-wrap items-baseline gap-2">
                          {title != null ? (
                            <button
                              type="button"
                              title={target}
                              onClick={() => onOpen(target)}
                              className="text-13 text-accent underline-offset-2 hover:underline"
                            >
                              {title}
                            </button>
                          ) : (
                            <Mono className="text-12 text-ink-3">{c.path}</Mono>
                          )}
                          <span className="min-w-0 text-13 text-ink-2">{c.relation}</span>
                        </li>
                      );
                    })}
                  </ul>
                </dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------- the proof */

function DocumentProof({
  doc,
  model,
  linkIndex,
  supersession,
  highlightAnchor,
  selectedAnchor,
}: {
  doc: DocumentRecord;
  model: Model;
  linkIndex: LinkIndex | null;
  supersession: SupersessionIndex;
  highlightAnchor: string | null;
  selectedAnchor: string | null;
}) {
  const t = useT();
  const tOr = useTOr();
  const locale = useLocale();
  const select = useApp((s) => s.select);
  const jump = useApp((s) => s.jump);
  const focusSource = useApp((s) => s.focusSource);
  const currentUser = useApp((s) => s.currentUser);
  const lens = useApp((s) => s.lens);
  const labels = model.dataset.claimLabels;

  // The wording lib/citations needs, injected: that module is transpiled standalone by its
  // test, so it cannot import the dictionary itself.
  const citationI18n = useMemo(() => ({ tOr, intlTag: intlTag(locale) }), [tOr, locale]);

  const fm = doc.frontmatter ?? {};
  const fmEntries = Object.entries(fm);
  // One line of frontmatter for the pinned masthead, which stays legible once §01's meta strip
  // has scrolled away. doc_id is already spelled out beside it, so it does not get said twice.
  const fmSummary = useMemo(
    () =>
      frontmatterFields(fmEntries)
        .slice(0, 4)
        .map((f) => {
          const key = f.labelKey ? t(f.labelKey) : f.key;
          const value =
            f.kind === "chips"
              ? f.chips.join(", ")
              : f.textKey
                ? t(f.textKey)
                : frontmatterInline(f.value);
          return `${key} ${value}`;
        })
        .join("  ·  "),
    // fmEntries is derived from doc; recomputing per document is the whole point. `t` is in
    // because the masthead line now carries words, and words follow the locale toggle.
    [doc, t],
  );
  const patches = doc.document_id
    ? model.patchesByDocId.get(doc.document_id) ?? []
    : model.patchesByPath.get(doc.path) ?? [];

  /* ------------------------------------------------------- current vs history */

  // A page whose claims take part in a supersession chain opens on CURRENT — the states that
  // hold now — and the reader switches to HISTORY to read what they replaced. A page with no
  // chain never shows the switch and never hides a claim.
  // The document's head, read off the body the exporter already ships. The Current/History
  // switch below is about the LEDGER — the overview is neither current nor history, it is the
  // reading of both — so it sits above the switch and its own blocks are taken out of the
  // claim list rather than shown twice.
  const overview = useMemo(() => parseOverview(doc), [doc]);
  const family = useMemo(
    () => (linkIndex ? volumeFamily(linkIndex, doc.path) : null),
    [linkIndex, doc.path],
  );
  const showOverview = hasOverviewContent(overview);
  const ledger = useMemo(
    () => ({ ...doc, claims: ledgerClaims(doc.claims, overview) }),
    [doc, overview],
  );

  const hasChain = useMemo(
    () => documentHasSupersession(ledger, supersession),
    [ledger, supersession],
  );
  const hiddenCount = useMemo(
    () => supersededCount(ledger, supersession),
    [ledger, supersession],
  );
  const [bodyView, setBodyView] = useState<"current" | "history">("current");
  /**
   * The archive mark, read off the PATH and off nothing else (docs/design/archive.md §2.1) —
   * the same rule the service, the gate and `rebuild_derived` read it by. A page here says so
   * in one badge; the action beside it opens the proposal, which is where the closure — the
   * sources this page cites, the pages that depend on them — is computed and confirmed.
   */
  const archived = isArchivedPath(doc.path);
  /**
   * The other half of the same move: archiving leaves a short RECORD standing at the live
   * path, so the subject does not simply vanish from the pages that link to it. The record
   * is live knowledge — `archived: false`, read by the glance and by recall — which is why
   * the path rule above says nothing about it and the frontmatter the archive job stamped
   * says everything (`lib/archive.ts::isArchiveRecord`).
   *
   * A reader who lands here should learn three things at once: that this is a record, where
   * the full page went, and that the way back is Restore.
   */
  const record = isArchiveRecord(doc);
  /**
   * The door, resolved by PATH and never by `document_id`: `archive_of` names the copy by
   * path because the record and the copy are the one pair in a library that speaks for a
   * single subject, and a jump that went through identity could land back on the record it
   * started from (`lib/archive.ts::documentByPath`).
   */
  const fullTarget = archiveRecordFullTarget(model.dataset.documents.documents, doc);
  /** Both spellings of "the subject has left", and both are restored the same way. */
  const restores = archived || record;
  const [archiveOpen, setArchiveOpen] = useState(false);
  const archiveSeeds = useMemo(
    // A RECORD is seeded by the copy it stands for, never by its own path. The record is a
    // live page AT that path, so an unarchive planned from it reads back `already_live` and
    // selects nothing — the button would open a dialog that can do nothing. `archive_of`
    // names the thing that actually has to move, which is what the reader means by Restore.
    () => ({
      documents: [record && fullTarget ? fullTarget.path : doc.path],
      sources: [] as string[],
    }),
    [doc.path, record, fullTarget],
  );
  const focusAnchor = highlightAnchor ?? selectedAnchor;
  // A deep link (History → “State changed” → the claim) can land ON a superseded claim. The
  // page must not open in the one view that hides its own target.
  useEffect(() => {
    if (focusAnchor && isSuperseded(supersession, focusAnchor)) setBodyView("history");
  }, [focusAnchor, supersession]);
  const showingHistory = !hasChain || bodyView === "history";
  const visibleClaims = useMemo(
    () => (showingHistory ? ledger.claims : currentClaims(ledger, supersession)),
    [ledger, showingHistory, supersession],
  );
  // Switching view re-renders the body, so the scroll has to follow the claim into it.
  useEffect(() => {
    if (!focusAnchor) return;
    document.getElementById(`claim-${focusAnchor}`)?.scrollIntoView({ block: "center" });
  }, [focusAnchor, showingHistory]);

  const jumpToClaim = (site: { documentId: string | null; anchor: string }) => {
    if (site.documentId) select({ kind: "claim", documentId: site.documentId, anchor: site.anchor });
    else
      document.getElementById(`claim-${site.anchor}`)?.scrollIntoView({ block: "center" });
  };

  // Consecutive list_items merge into one list; paragraphs each stand alone.
  const groups = useMemo(() => {
    const out: { kind: "list" | "prose"; claims: Claim[] }[] = [];
    for (const c of visibleClaims) {
      const kind = c.kind === "list_item" ? ("list" as const) : ("prose" as const);
      const last = out[out.length - 1];
      if (last && last.kind === "list" && kind === "list") last.claims.push(c);
      else out.push({ kind, claims: [c] });
    }
    return out;
  }, [visibleClaims]);

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
    // Chain markers, derived from the body the exporter already ships: what replaced this
    // claim, and what this claim replaced. The raw <!-- supersedes … --> comment itself never
    // reaches the page — lib/claim strips it with the rest of the machinery.
    const successor = c.anchor ? supersession.successorOf.get(c.anchor.toLowerCase()) : undefined;
    const superseded = !!successor;
    const replaced = supersededBy(supersession, c.anchor);
    const replacedSite = replaced ? supersession.siteOf.get(replaced) : undefined;
    const chainChips = (superseded || replaced) && (
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        {successor && (
          <button
            type="button"
            title={t("library.supersession.jump", { anchor: successor.anchor })}
            onClick={(e) => {
              e.stopPropagation();
              jumpToClaim(successor);
            }}
            className="rounded-1 transition-opacity duration-120 hover:opacity-80"
          >
            <Badge tone="warn">
              {t("library.supersession.supersededBy", { anchor: successor.anchor })}
            </Badge>
          </button>
        )}
        {replaced && (
          <button
            type="button"
            title={t("library.supersession.jump", { anchor: replaced })}
            onClick={(e) => {
              e.stopPropagation();
              jumpToClaim(replacedSite ?? { documentId: doc.document_id, anchor: replaced });
            }}
            className="rounded-1 transition-opacity duration-120 hover:opacity-80"
          >
            <Badge>{t("library.supersession.supersedes", { anchor: replaced })}</Badge>
          </button>
        )}
        {successor && successor.path !== doc.path && (
          <span className="text-12 text-ink-3">
            {t("library.supersession.elsewhere", { path: successor.path })}
          </span>
        )}
      </div>
    );
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
        {chainChips}
        <p className={cn("prose", superseded && "text-ink-3")}>
          {labeled && (
            <>
              <Badge tone="neutral" className={cn("mr-1.5 align-[1px]", labelBadgeClass(labeled.label.tier))}>
                {labeled.label.label}
              </Badge>
            </>
          )}
          <InlineClaimText
            md={labeled ? labeled.rest : md}
            fromPath={doc.path}
            resolve={(path) => model.docByPath.get(path)}
            onOpen={(target) =>
              select({
                kind: "document",
                id: documentAddress(target.path, target.document_id, target),
              })
            }
          />
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
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Mono className="min-w-0 flex-1 break-all text-12 text-ink-3">{doc.path}</Mono>
          {archived && (
            <Badge tone="warn" className="shrink-0">
              {t("archive.badge")}
            </Badge>
          )}
          {record && (
            <Badge tone="warn" className="shrink-0">
              {t("archive.record.badge")}
            </Badge>
          )}
          {lens === "owner" && currentUser && (
            <Button
              size="sm"
              variant="ghost"
              className="shrink-0"
              onClick={() => setArchiveOpen(true)}
            >
              {t(restores ? "archive.action.restore" : "archive.action.archive")}
            </Button>
          )}
        </div>
        {/* The door the record owes its reader: the full page is not gone, it is one click
            away in the archive section. A copy the projection does not carry stays a path
            rather than becoming a link to nowhere. */}
        {fullTarget && (
          <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-12 text-ink-3">
            <span>{t("archive.record.fullPage")}</span>
            {fullTarget.doc ? (
              <button
                type="button"
                title={fullTarget.path}
                onClick={() => select({ kind: "document", id: fullTarget.path })}
                className="rounded-1 text-accent transition-colors duration-120 hover:bg-hover hover:underline"
              >
                <Mono className="break-all text-12">{fullTarget.path}</Mono>
              </button>
            ) : (
              <Mono className="break-all text-12">{fullTarget.path}</Mono>
            )}
          </p>
        )}
        {currentUser && (
          // Keyed by the owner, so a library switch throws the whole dialog away — plan,
          // overrides, note and any confirm still on the wire (I1 at the UI).
          <ArchiveProposalDialog
            key={currentUser}
            open={archiveOpen}
            onOpenChange={setArchiveOpen}
            userId={currentUser}
            action={restores ? "unarchive" : "archive"}
            seeds={archiveSeeds}
          />
        )}
        {/* A rolled-over subject is several files; the reader means the subject. A closed
            volume used to say `archived_from … rollover_volume 01` in words and offer no way
            back to the page it was cut from. */}
        {family && (
          <nav aria-label={t("library.volumes.aria")} className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-12 text-ink-3">{t("library.volumes.label")}</span>
            {family.map((page) => (
              <button
                key={page.path}
                type="button"
                title={page.path}
                disabled={page.current}
                // By path, like every other lens row: the family is keyed by path, and a
                // page of it may be a record's subject rather than an id of its own.
                onClick={() => select({ kind: "document", id: page.path })}
                className={cn(
                  "rounded-1 px-1 text-12 transition-colors duration-120",
                  page.current
                    ? "cursor-default font-medium text-ink"
                    : "text-accent hover:bg-hover hover:underline",
                )}
              >
                {page.main ? t("library.volumes.main") : page.label}
              </button>
            ))}
          </nav>
        )}
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
      {/* §01 answers "what is this" in one place: the document's structured facts as the card's
          header strip, the compiled picture below them. It is the one part of the page a compile
          rewrites whole, so it reads as a card rather than as a run of claims — and a document
          with neither facts nor picture is numbered from §02, the honest statement that it has
          said nothing about itself. */}
      {(showOverview || fmEntries.length > 0) && (
        <OverviewCard
          overview={showOverview ? overview : null}
          fromPath={doc.path}
          frontmatter={fmEntries}
          onOpen={(path) => {
            const target = documentByPath(model.dataset.documents.documents, path);
            if (target)
              select({
                kind: "document",
                id: documentAddress(target.path, target.document_id, target),
              });
          }}
          titleOf={(path) => {
            const target = model.docByPath.get(path);
            return target ? documentDisplayTitle(target) : null;
          }}
        />
      )}

      <section className="mt-6">
        <SectionRule
          no={2}
          title={t("library.body.title")}
          actions={
            hasChain ? (
              <SegmentedControl
                size="sm"
                aria-label={t("library.supersession.aria")}
                value={bodyView}
                onChange={(v) => setBodyView(v as "current" | "history")}
                options={[
                  { value: "current", label: t("library.supersession.current") },
                  { value: "history", label: t("library.supersession.history") },
                ]}
              />
            ) : undefined
          }
        />
        {/* The note only says something when there IS something to say: a page holding only a
            successor hides nothing, and "0 hidden" is noise. */}
        {hasChain && (showingHistory || hiddenCount > 0) && (
          <p className="mt-2 text-12 text-ink-3">
            {showingHistory
              ? t("library.supersession.historyNote")
              : t("library.supersession.currentNote", { count: hiddenCount })}
          </p>
        )}
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
          {ledger.claims.length === 0 && (
            <p className="py-6 text-13 text-ink-3">{t("library.body.empty")}</p>
          )}
        </div>
      </section>

      {citations.length > 0 && (
        <section className="mt-6">
          <SectionRule no={3} title={t("library.citations.title")} />
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

      {/* Which editions wrote this page — a compile record that opens in History, and so
          the owner's. The reading room reads the page, not the process that produced it. */}
      {patches.length > 0 && lens === "owner" && (
        <section className="mt-6">
          <SectionRule no={4} title={t("library.patches.title")} />
          <ul className="mt-3 flex flex-col">
            {patches.map((p) => (
              <li key={p.patch_id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  onClick={() => jump({ kind: "patch", id: p.patch_id }, "history")}
                  className="flex w-full items-baseline gap-3 py-1.5 text-left transition-colors duration-120 hover:bg-hover"
                >
                  <Mono className="text-12 text-accent">{p.patch_id}</Mono>
                  <span
                    className="min-w-0 flex-1 truncate text-12 text-ink-3"
                    title={p.ts ?? undefined}
                  >
                    {p.ts ? fmtTime(p.ts) : ""}
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

      {/* Last: the way OUT of this page. The exits come after the document has been read —
          first what this is, then what it says and on whose authority, and only then where the
          thread leads next. The pinned masthead keeps the reader's place while they scroll. */}
      {linkIndex && (
        <section className="mt-6">
          <SectionRule no={5} title={t("library.neighborhood.title")} />
          <p className="mt-2 text-12 text-ink-3">{t("library.neighborhood.note")}</p>
          <NeighborhoodCard
            index={linkIndex}
            path={doc.path}
            titleOf={(path) => {
              const target = model.docByPath.get(path);
              return target ? documentDisplayTitle(target) : null;
            }}
          />
        </section>
      )}

      {/* Who has read this page, and which questions did. Last, and derived: it is the one
          thing on the page that is not the page — joined at read time, out of the ledger,
          and never written back into the document it is about. Owner-only, like the usage
          panel it is the per-page face of: how often a library is read is the owner's
          measurement of their own library, not part of reading it. */}
      {currentUser && lens === "owner" && (
        <section className="mt-6">
          <SectionRule no={6} title={t("access.title")} />
          <AccessCard userId={currentUser} path={doc.path} />
        </section>
      )}
      </div>
      </ScrollRegion>
    </article>
  );
}
