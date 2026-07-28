import { Fragment, useEffect, useMemo } from "react";
import { Network, History as HistoryIcon, FileWarning } from "lucide-react";
import type { DocumentRecord } from "@/lib/types";
import type { Model } from "@/lib/model";
import { useApp } from "@/lib/store";
import { resolveLink } from "@/lib/paths";
import { Button, Chip, Eyebrow, StatusDot } from "./ui";
import { ClaimView } from "./ClaimView";
import { flagMeta } from "@/lib/claim";

export function DocumentReader({
  doc,
  model,
  highlightAnchor,
}: {
  doc: DocumentRecord;
  model: Model;
  highlightAnchor?: string | null;
}) {
  const { jump, select } = useApp();

  useEffect(() => {
    if (!highlightAnchor) return;
    const el = document.getElementById(`claim-${highlightAnchor}`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightAnchor, doc.document_id]);

  const onLink = (href: string) => {
    const target = resolveLink(doc.path, href);
    const t = model.docByPath.get(target);
    if (t?.document_id) select({ kind: "document", id: t.document_id });
  };

  // group consecutive list_item claims into lists; paragraphs stand alone.
  const groups = useMemo(() => groupClaims(doc), [doc]);

  // aggregate flags present in the document for the header summary.
  const flagTally = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of doc.claims)
      for (const f of c.flags) m.set(f, (m.get(f) ?? 0) + 1);
    return [...m.entries()];
  }, [doc]);

  const fm = doc.frontmatter ?? {};
  const type = (fm.type as string) ?? null;
  const inGraph = doc.document_id && model.nodeById.has(doc.document_id);
  const patches = model.patchesByPath.get(doc.path) ?? [];

  return (
    <article className="mx-auto max-w-3xl px-4 py-5 sm:px-8 sm:py-6">
      <header className="border-b border-border pb-4 mb-5">
        <Eyebrow>{doc.path}</Eyebrow>
        <h1
          className="mt-2 font-light leading-[1.03]"
          style={{
            fontSize: "var(--text-4xl)",
            letterSpacing: 0,
          }}
        >
          {doc.title}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {type && <Chip>{type}</Chip>}
          {doc.document_id && (
            <Chip className="font-mono text-muted-foreground">{doc.document_id}</Chip>
          )}
          {flagTally.map(([f, n]) => {
            const meta = flagMeta(f);
            return (
              <Chip key={f} dotColor={meta.token} title={`${n} 处 ${meta.label}`}>
                {meta.label} · {n}
              </Chip>
            );
          })}
          <div className="flex-1" />
          {inGraph && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => jump({ kind: "node", id: doc.document_id! }, "graph")}
            >
              <Network size={14} /> 图中查看
            </Button>
          )}
          {patches.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => jump({ kind: "patch", id: patches[patches.length - 1].patch_id }, "history")}
            >
              <HistoryIcon size={14} /> 演化 ({patches.length})
            </Button>
          )}
        </div>
      </header>

      {/* frontmatter panel */}
      {Object.keys(fm).length > 0 && (
        <section className="mb-6">
          <Eyebrow className="mb-2">Frontmatter</Eyebrow>
          <div className="border border-border rounded-sm overflow-hidden">
            <table className="w-full text-[length:var(--text-sm)]">
              <tbody>
                {Object.entries(fm).map(([k, v], i) => (
                  <tr
                    key={k}
                    className={i > 0 ? "border-t border-border-subtle" : ""}
                    style={{ borderTopColor: "var(--color-border-subtle)" }}
                  >
                    <td className="py-1.5 px-3 w-32 text-muted-foreground align-top font-medium bg-[var(--color-surface-muted)]">
                      {k}
                    </td>
                    <td className="py-1.5 px-3 font-mono break-all">
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* body */}
      <section className="space-y-1">
        {groups.map((g, gi) =>
          g.kind === "list" ? (
            <ul key={gi} className="list-disc pl-5 marker:text-[var(--color-text-tertiary)]">
              {g.claims.map((c, i) => (
                <li key={i}>
                  <ClaimView
                    claim={c}
                    documentId={doc.document_id}
                    onLink={onLink}
                    highlight={!!highlightAnchor && c.anchor === highlightAnchor}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <Fragment key={gi}>
              {g.claims.map((c, i) => (
                <ClaimView
                  key={i}
                  claim={c}
                  documentId={doc.document_id}
                  onLink={onLink}
                  highlight={!!highlightAnchor && c.anchor === highlightAnchor}
                />
              ))}
            </Fragment>
          ),
        )}
        {doc.claims.length === 0 && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm py-6">
            <FileWarning size={16} /> 该文档没有可追溯 claim 块。
          </div>
        )}
      </section>

      {/* document-id echo */}
      {doc.document_id && (
        <footer className="mt-8 pt-3 border-t border-border-subtle flex items-center gap-2 text-[length:var(--text-2xs)] text-muted-foreground">
          <StatusDot color="var(--color-verified)" />
          {doc.claims.length} claim 块 · {patches.length} 次 patch 触及
        </footer>
      )}
    </article>
  );
}

type ClaimGroup = { kind: "list" | "prose"; claims: DocumentRecord["claims"] };

function groupClaims(doc: DocumentRecord): ClaimGroup[] {
  const groups: ClaimGroup[] = [];
  for (const c of doc.claims) {
    const kind = c.kind === "list_item" ? "list" : "prose";
    const last = groups[groups.length - 1];
    if (last && last.kind === kind && kind === "list") last.claims.push(c);
    else groups.push({ kind, claims: [c] });
  }
  return groups;
}
